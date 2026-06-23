#!/usr/bin/env python3
"""
E-Ink Weather Dashboard — Main Entry Point

Fetches weather from Open-Meteo, renders to a Waveshare 7.5" e-Paper HAT (B),
and exits cleanly. Designed to be triggered by cron / systemd timer on a Raspberry Pi.

Usage:
    python weather_dashboard.py [--config config.json]
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
    read_last_weather,
    should_full_refresh,
    update_meta_after_run,
    write_last_weather,
)
from weather_dashboard.render import render_blank, render_weather  # noqa: E402
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
    "cache_dir": "~/.weather_dashboard",
    "full_refresh_interval": 24,
    "api_timeout_seconds": 10,
    "font_path": None,
}


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
    """Save last-rendered images to cache for debugging (optional)."""
    import datetime
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bpath = os.path.join(os.path.expanduser(cache_dir), f"last_black_{ts}.png")
    rpath = os.path.join(os.path.expanduser(cache_dir), f"last_red_{ts}.png")
    black_img.save(bpath)
    red_img.save(rpath)
    logger.info("Debug images saved: %s, %s", bpath, rpath)


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
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    logger.info("=" * 60)
    logger.info("Weather dashboard run started")

    cfg = load_config(args.config)

    # Resolve cache dir early so it exists for all subsequent calls
    cache_dir = os.path.expanduser(cfg["cache_dir"])
    os.makedirs(cache_dir, exist_ok=True)

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
            # Fetch failed — try to redraw last known good data with stale flag
            logger.warning("Fetch failed; attempting stale-data fallback")
            weather = read_last_weather(cache_dir)
            if weather is None:
                logger.error(
                    "No cached weather available and fetch failed. "
                    "Rendering blank display."
                )
                # Draw a blank screen with error message
                from PIL import Image, ImageDraw
                black_img = Image.new("1", (800, 480), 255)
                red_img = Image.new("1", (800, 480), 255)
                draw_r = ImageDraw.Draw(red_img)
                draw_r.text((200, 200), "FETCH FAILED — NO DATA", fill=0)
                # We still need to display this, so init + display
                from waveshare_epd import epd7in5b_V2
                epd = epd7in5b_V2.EPD()
                epd.init()
                init_called = True
                epd.display(epd.getbuffer(black_img), epd.getbuffer(red_img))
                exit_code = 1
                return exit_code
            stale_mode = True

        # Step 2 — Determine if full refresh is needed
        do_refresh, reason = should_full_refresh(
            cache_dir=cache_dir,
            weather=weather,
            threshold=cfg["full_refresh_interval"],
        )
        logger.info("Refresh decision: %s (%s)", "FULL" if do_refresh else "SKIP", reason)

        if not do_refresh:
            # Skip — just update the run counter/timestamp and exit
            update_meta_after_run(cache_dir, weather, did_refresh=False)
            logger.info("Skipping display update (no change)")
            return 0

        # Step 3 — Render images
        font_path = cfg.get("font_path") or os.path.join(
            os.path.dirname(__file__), "resources", "pic", "Font.ttc"
        )
        black_img, red_img = render_weather(weather, font_path=font_path, stale=stale_mode)

        # Step 4 — Display on e-Paper
        from waveshare_epd import epd7in5b_V2
        epd = epd7in5b_V2.EPD()
        logger.info("Initializing e-Paper display ...")
        init_result = epd.init()
        if init_result != 0:
            raise RuntimeError(f"epd.init() failed with return code {init_result}")
        init_called = True

        logger.info("Sending image buffers to display (full refresh ~15-20s) ...")
        epd.display(epd.getbuffer(black_img), epd.getbuffer(red_img))
        logger.info("Display update complete")

        # Step 5 — Update cache
        write_last_weather(cache_dir, weather)
        update_meta_after_run(cache_dir, weather, did_refresh=True)

        # Save debug images (always useful for verifying output)
        _write_debug_images(black_img, red_img, cache_dir)

    except Exception as exc:
        logger.exception("Unhandled exception during run: %s", exc)
        exit_code = 1
    finally:
        # Always put the display to sleep if we initialized it
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
