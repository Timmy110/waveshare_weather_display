#!/usr/bin/env python3
"""
E-Ink Weather Dashboard — Main Entry Point

Fetches weather from Open-Meteo, renders to a Waveshare 7.5" e-Paper HAT (B),
and exits cleanly. Designed to be triggered by cron / systemd timer on a Raspberry Pi.

Usage:
    python weather_dashboard.py [--config config.json]
    python weather_dashboard.py --no-display          # render only, no hardware
    python weather_dashboard.py -o preview.png        # save a preview image

If the e-Paper driver/hardware isn't present, the script automatically falls
back to headless (image-only) mode instead of failing.
"""

import argparse
import json
import logging
import os
import sys
from typing import Any, Dict

# Add lib/ to path so the bundled waveshare_epd package is importable
_here = os.path.dirname(os.path.abspath(__file__))
_lib_dir = os.path.join(_here, "lib")
if _lib_dir not in sys.path:
    sys.path.insert(0, _lib_dir)

from weather_dashboard.cache import (  # noqa: E402
    diff_weather,
    read_last_weather,
    should_full_refresh,
    update_meta_after_run,
    write_last_weather,
)
from weather_dashboard.render import (  # noqa: E402
    clock_partial_buffer,
    compose_rgb,
    render_blank,
    render_clock_region,
    render_weather,
)
from weather_dashboard.weather import fetch_weather  # noqa: E402

logger = logging.getLogger("weather_dashboard")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEFAULTS = {
    "latitude": 48.8566,
    "longitude": 2.3522,
    "timezone": "Europe/Paris",
    "temperature_unit": "celsius",
    # Relative paths are resolved against the repo (script) directory, so the
    # cache travels with the project and works regardless of the cwd cron uses.
    "cache_dir": "cache",
    "full_refresh_interval": 24,
    "api_timeout_seconds": 10,
    "font_path": None,
    # How the per-minute --time-only run repaints the clock:
    #   "partial" — fast, flash-free partial refresh of just the clock digits
    #               (init_part + display_Partial). Best UX, but partial refresh
    #               on this 3-color panel is experimental (see render_clock_region).
    #   "fast"    — repaint the whole screen from cached weather with a fast
    #               refresh (init_Fast). No ghosting, but a brief flash each minute.
    "time_update_mode": "partial",
}


def resolve_cache_dir(cache_dir: str) -> str:
    """
    Resolve the configured cache_dir to an absolute path.

    - A leading ``~`` is expanded to the user's home directory.
    - Absolute paths are used as-is.
    - Relative paths are resolved against the repo/script directory (``_here``),
      NOT the current working directory — so the cache stays with the project
      even if it's moved or run from a different cwd (e.g. cron).
    """
    expanded = os.path.expanduser(cache_dir)
    if not os.path.isabs(expanded):
        expanded = os.path.join(_here, expanded)
    return os.path.abspath(expanded)


def load_config(path: str) -> Dict[str, Any]:
    """Load config from JSON file, merging with defaults."""
    cfg = dict(_DEFAULTS)
    if os.path.isfile(path):
        with open(path, "r") as f:
            user_cfg = json.load(f)
        cfg.update(user_cfg)
        logger.info("Loaded config from %s", path)
    else:
        logger.warning("Config file %s not found; using all defaults", path)
    return cfg


# ---------------------------------------------------------------------------
# Display helper
# ---------------------------------------------------------------------------

def _write_debug_images(black_img, red_img, cache_dir: str):
    """
    Save inspectable copies of the last render (overwrites previous): the two
    raw 1-bit panel buffers plus `preview.png`, a composite RGB image that
    mimics how the physical panel looks.
    """
    resolved = os.path.expanduser(cache_dir)
    black_img.save(os.path.join(resolved, "last_black.png"))
    red_img.save(os.path.join(resolved, "last_red.png"))
    compose_rgb(black_img, red_img).save(os.path.join(resolved, "preview.png"))
    logger.info("Debug images saved to %s (preview.png is the composite)", resolved)


def _send_to_panel(epd_module, black_img, red_img, full_refresh: bool):
    """
    Push the rendered buffers to the physical e-Paper panel.

    Returns the initialized EPD object so the caller can put it to sleep.
    A full refresh (~15-20s) clears ghosting; a fast refresh (~5-8s) is used
    when only the clock changed.
    """
    epd = epd_module.EPD()
    label = "full refresh" if full_refresh else "fast refresh"
    logger.info("Initializing e-Paper (%s) ...", label)
    init_result = epd.init() if full_refresh else epd.init_Fast()
    if init_result != 0:
        raise RuntimeError(f"e-Paper init failed with code {init_result}")
    logger.info("Sending image buffers to panel ...")
    epd.display(epd.getbuffer(black_img), epd.getbuffer(red_img))
    logger.info("Display update complete")
    return epd


def _send_partial_clock(epd_module, region_img, region):
    """
    Push just the clock digits to the panel via a partial refresh.

    Uses init_part() + display_Partial() so only the clock window is redrawn —
    no whole-screen flash. Assumes a prior full render already put the rest of
    the dashboard on the panel (the 15-minute full-refresh run does that).
    Returns the initialized EPD object so the caller can put it to sleep.
    """
    epd = epd_module.EPD()
    logger.info("Initializing e-Paper (partial clock refresh) ...")
    init_result = epd.init_part()
    if init_result != 0:
        raise RuntimeError(f"e-Paper init_part failed with code {init_result}")
    x0, y0, x1, y1 = region
    logger.info("Partial-refreshing clock region %s ...", region)
    # display_Partial_clear seeds the old plane with the inverse of the new
    # digits so the whole (small) window repaints and the previous time is
    # cleared — a plain display_Partial() leaves the old digits underneath
    # because each per-minute run is an isolated init_part/sleep cycle with no
    # valid old frame on the panel.
    epd.display_Partial_clear(clock_partial_buffer(region_img), x0, y0, x1, y1)
    logger.info("Partial clock update complete")
    return epd


def _drive_and_sleep(send_fn):
    """
    Run a panel-send callable and always put the panel to sleep afterwards,
    even if the send raises. Call inside a _panel_lock so init/display/sleep
    all happen under the same lock (no SPI overlap with a concurrent run).
    """
    epd = None
    try:
        epd = send_fn()
    finally:
        if epd is not None:
            try:
                logger.info("Putting e-Paper to sleep ...")
                epd.sleep()
            except Exception as sleep_exc:
                logger.error("Failed during epd.sleep(): %s", sleep_exc)


class _panel_lock:
    """
    Serialize physical-panel access so the every-minute time job and the
    every-15-minute weather job never drive the SPI bus at the same time.

    Uses an exclusive fcntl lock on POSIX (the Raspberry Pi target). On other
    platforms (e.g. Windows dev boxes, which always run headless) it is a no-op.
    """

    def __init__(self, cache_dir: str):
        self._path = os.path.join(cache_dir, "panel.lock")
        self._fh = None

    def __enter__(self):
        try:
            import fcntl
        except ImportError:
            return self  # non-POSIX: nothing to lock (headless only)
        self._fh = open(self._path, "w")
        logger.info("Waiting for panel lock (%s) ...", self._path)
        fcntl.flock(self._fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        if self._fh is not None:
            try:
                import fcntl
                fcntl.flock(self._fh, fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None
        return False


def _emit_headless(black_img, red_img, cache_dir: str, output_path):
    """Report/save the preview image when running without the display."""
    if output_path:
        compose_rgb(black_img, red_img).save(output_path)
        logger.info("Preview image written to %s", output_path)
    else:
        logger.info(
            "Headless mode — preview image at %s",
            os.path.join(os.path.expanduser(cache_dir), "preview.png"),
        )


# ---------------------------------------------------------------------------
# Time-only (per-minute clock) run
# ---------------------------------------------------------------------------

def _run_time_only(cfg, cache_dir, font_path, timezone_str, city_name,
                   headless, epd_module, output_path) -> int:
    """
    Update only the clock — no network fetch, no cache writes.

    Intended to run every minute alongside a separate full run (every ~15 min)
    that handles weather. Two modes, selected by cfg["time_update_mode"]:
      - "partial": partial-refresh just the clock digits (fast, flash-free).
      - "fast":    re-render the whole screen from cached weather with a fast
                   refresh (no ghosting, brief flash). Falls back to this when
                   partial isn't wanted.
    """
    mode = str(cfg.get("time_update_mode", "partial")).lower()

    # "fast" mode needs the last weather snapshot to redraw the full screen.
    if mode == "fast":
        weather = read_last_weather(cache_dir)
        if weather is None:
            logger.warning(
                "time-only (fast mode): no cached weather yet — skipping. "
                "The next full run will populate the cache."
            )
            return 0
        black_img, red_img = render_weather(
            weather, font_path=font_path, timezone_str=timezone_str, city_name=city_name,
        )
        _write_debug_images(black_img, red_img, cache_dir)
        if headless:
            _emit_headless(black_img, red_img, cache_dir, output_path)
            return 0
        with _panel_lock(cache_dir):
            _drive_and_sleep(lambda: _send_to_panel(
                epd_module, black_img, red_img, full_refresh=False))
        return 0

    # Default: "partial" — draw and blit just the clock region.
    region_img, region = render_clock_region(timezone_str=timezone_str, font_path=font_path)
    if headless:
        preview_path = output_path or os.path.join(
            os.path.expanduser(cache_dir), "preview_clock.png"
        )
        region_img.convert("L").save(preview_path)
        logger.info("Headless — clock region preview written to %s", preview_path)
        return 0
    with _panel_lock(cache_dir):
        _drive_and_sleep(lambda: _send_partial_clock(epd_module, region_img, region))
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    """Run one invocation of the weather dashboard. Returns 0 on success."""

    parser = argparse.ArgumentParser(description="E-Ink Weather Dashboard")
    parser.add_argument(
        "--config",
        default=os.path.join(_here, "config.json"),
        help="Path to config JSON (default: ./config.json)",
    )
    parser.add_argument(
        "--no-display",
        action="store_true",
        help="Don't touch the e-Paper hardware; just render the image "
             "(for testing on a machine without the display).",
    )
    parser.add_argument(
        "-o",
        "--output",
        metavar="PATH",
        default=None,
        help="Save a composite PNG preview of the screen to PATH. Implies --no-display.",
    )
    parser.add_argument(
        "--time-only",
        action="store_true",
        help="Only update the clock (no network fetch). Uses a partial refresh "
             "of just the clock region by default — intended to run every minute "
             "while a separate full run handles weather. See time_update_mode.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    logger.info("=" * 60)
    logger.info("Weather dashboard run started")

    cfg = load_config(args.config)

    # Resolve cache dir early so it exists for all subsequent calls
    cache_dir = resolve_cache_dir(cfg["cache_dir"])
    os.makedirs(cache_dir, exist_ok=True)
    logger.info("Using cache directory: %s", cache_dir)

    font_path = cfg.get("font_path") or os.path.join(
        os.path.dirname(__file__), "resources", "pic", "Font.ttc"
    )
    timezone_str = cfg["timezone"]
    city_name = cfg.get("city_name")

    # Decide where output goes: the physical panel, or an image file (headless).
    # `--output`/`--no-display` force headless; otherwise we try to load the
    # driver and fall back to headless automatically if the hardware/driver is
    # unavailable (e.g. running on a laptop for testing).
    headless = args.no_display or args.output is not None
    epd_module = None
    if not headless:
        try:
            from waveshare_epd import epd7in5b_V2
            epd_module = epd7in5b_V2
        except Exception as exc:
            logger.warning(
                "e-Paper driver unavailable (%s). Falling back to headless "
                "image-only mode; pass --no-display to silence this.", exc
            )
            headless = True
    if headless:
        logger.info("Running headless (no display) — rendering image only, hardware untouched.")

    # --time-only: update just the clock and exit (no fetch, no cache writes).
    if args.time_only:
        logger.info("Time-only run (mode=%s)", cfg.get("time_update_mode", "partial"))
        try:
            return _run_time_only(
                cfg, cache_dir, font_path, timezone_str, city_name,
                headless, epd_module, args.output,
            )
        except Exception as exc:
            logger.exception("Unhandled exception during time-only run: %s", exc)
            return 1

    epd = None
    init_called = False
    exit_code = 0

    try:
        # Step 1 — Fetch weather data
        weather = fetch_weather(
            latitude=cfg["latitude"],
            longitude=cfg["longitude"],
            timezone=cfg["timezone"],
            temperature_unit=cfg["temperature_unit"],
            timeout=cfg["api_timeout_seconds"],
        )

        stale_mode = False
        if weather is None:
            logger.warning("Fetch failed; attempting stale-data fallback")
            weather = read_last_weather(cache_dir)
            if weather is None:
                logger.error(
                    "No cached weather available and fetch failed. "
                    "Rendering error screen."
                )
                from PIL import ImageDraw
                black_img, red_img = render_blank()
                draw_r = ImageDraw.Draw(red_img)
                draw_r.text((200, 200), "FETCH FAILED — NO DATA", fill=0)
                _write_debug_images(black_img, red_img, cache_dir)
                if headless:
                    _emit_headless(black_img, red_img, cache_dir, args.output)
                else:
                    with _panel_lock(cache_dir):
                        epd = _send_to_panel(epd_module, black_img, red_img, full_refresh=True)
                    init_called = True
                return 1
            stale_mode = True

        # Step 2 — Determine if weather data changed (full refresh needed)
        do_full_refresh, reason = should_full_refresh(
            cache_dir=cache_dir,
            weather=weather,
            threshold=cfg["full_refresh_interval"],
        )
        logger.info("%s refresh: %s", "Full" if do_full_refresh else "Fast", reason)

        # List exactly what changed (vs the last cached weather) when a full
        # refresh is driven by new data — empty for first run / counter refresh.
        if do_full_refresh:
            changes = diff_weather(read_last_weather(cache_dir), weather)
            if changes:
                logger.info("Weather changed since last update:")
                for change in changes:
                    logger.info("  • %s", change)

        # Step 3 — Render images (live clock time, not the stale API snapshot)
        black_img, red_img = render_weather(
            weather, font_path=font_path, stale=stale_mode,
            timezone_str=timezone_str, city_name=city_name,
        )
        _write_debug_images(black_img, red_img, cache_dir)

        # Step 4 — Output: physical panel or image file
        if headless:
            _emit_headless(black_img, red_img, cache_dir, args.output)
        else:
            with _panel_lock(cache_dir):
                epd = _send_to_panel(epd_module, black_img, red_img, full_refresh=do_full_refresh)
            init_called = True

        # Step 5 — Update cache + refresh metadata
        write_last_weather(cache_dir, weather)
        update_meta_after_run(cache_dir, weather, did_refresh=do_full_refresh)

    except Exception as exc:
        logger.exception("Unhandled exception during run: %s", exc)
        exit_code = 1
    finally:
        if epd is not None and init_called:
            try:
                logger.info("Putting e-Paper to sleep ...")
                epd.sleep()
            except Exception as sleep_exc:
                logger.error("Failed during epd.sleep(): %s", sleep_exc)

    logger.info("Weather dashboard run finished (exit code %d)", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
