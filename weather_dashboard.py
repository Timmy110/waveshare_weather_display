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
from weather_dashboard.render import render_weather  # noqa: E402
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
    """Save a single backup copy of the last-rendered images (overwrites previous)."""
    resolved = os.path.expanduser(cache_dir)
    bpath = os.path.join(resolved, "last_black.png")
    rpath = os.path.join(resolved, "last_red.png")
    black_img.save(bpath)
    red_img.save(rpath)
    logger.info("Backup image saved: %s, %s", bpath, rpath)


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

    font_path = cfg.get("font_path") or os.path.join(
        os.path.dirname(__file__), "resources", "pic", "Font.ttc"
    )
    timezone_str = cfg["timezone"]
    city_name = cfg.get("city_name")

    epd = None
    init_called = False
    exit_code = 0

    try:
        from waveshare_epd import epd7in5b_V2

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
                    "Rendering blank display."
                )
                from PIL import Image, ImageDraw
                black_img = Image.new("1", (800, 480), 255)
                red_img = Image.new("1", (800, 480), 255)
                draw_r = ImageDraw.Draw(red_img)
                draw_r.text((200, 200), "FETCH FAILED — NO DATA", fill=0)
                epd = epd7in5b_V2.EPD()
                epd.init()
                init_called = True
                epd.display(epd.getbuffer(black_img), epd.getbuffer(red_img))
                exit_code = 1
                return exit_code
            stale_mode = True

        # Step 2 — Determine if weather data changed (full refresh needed)
        do_full_refresh, reason = should_full_refresh(
            cache_dir=cache_dir,
            weather=weather,
            threshold=cfg["full_refresh_interval"],
        )

        if do_full_refresh:
            logger.info("Full refresh needed: %s", reason)

            # Step 3 — Render full images
            black_img, red_img = render_weather(
                weather, font_path=font_path, stale=stale_mode, timezone_str=timezone_str, city_name=city_name
            )

            # Step 4 — Full display update (~15-20s)
            epd = epd7in5b_V2.EPD()
            logger.info("Initializing e-Paper (full refresh) ...")
            init_result = epd.init()
            if init_result != 0:
                raise RuntimeError(f"epd.init() failed with code {init_result}")
            init_called = True

            logger.info("Sending full image buffers (~15-20s) ...")
            epd.display(epd.getbuffer(black_img), epd.getbuffer(red_img))
            logger.info("Full display update complete")

            # Step 5 — Update cache
            write_last_weather(cache_dir, weather)
            update_meta_after_run(cache_dir, weather, did_refresh=True)
            _write_debug_images(black_img, red_img, cache_dir)

        else:
            # Weather unchanged — fast refresh to update the clock without ghosting
            logger.info("Weather unchanged (%s); doing fast full-screen refresh", reason)

            # Re-render with live clock time (not stale API snapshot)
            black_img, red_img = render_weather(
                weather, font_path=font_path, stale=stale_mode, timezone_str=timezone_str, city_name=city_name
            )

            epd = epd7in5b_V2.EPD()
            logger.info("Initializing e-Paper (fast refresh) ...")
            init_result = epd.init_Fast()
            if init_result != 0:
                raise RuntimeError(f"epd.init_Fast() failed with code {init_result}")
            init_called = True

            logger.info("Sending fast image buffers (~5-8s) ...")
            epd.display(epd.getbuffer(black_img), epd.getbuffer(red_img))
            logger.info("Fast refresh complete")

            # Update cache + re-save backup images (clock changed)
            write_last_weather(cache_dir, weather)
            update_meta_after_run(cache_dir, weather, did_refresh=False)
            _write_debug_images(black_img, red_img, cache_dir)

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
