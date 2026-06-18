#!/usr/bin/env python3
"""
Waveshare E-Ink Weather Dashboard
Main entry point for the weather dashboard application.
"""

import sys
import os
import time
import logging
from datetime import datetime

# Add lib directory to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))

from src.config_loader import load_config
from src.weather_api import fetch_weather
from src.layout import render_dashboard
from src.display import init_display, render_to_display, create_blank_images


def setup_logging(log_dir="logs"):
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "weather_dashboard.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )


def main():
    setup_logging()
    logger = logging.getLogger("main")
    logger.info("Starting Weather Dashboard")

    # Load configuration
    config = load_config()
    name, lat, lon = config["location"]["name"], config["location"]["latitude"], config["location"]["longitude"]
    forecast_days = config["display"]["forecast_days"]
    hourly_slots = config["display"]["hourly_slots"]

    logger.info("Location: %s (%.4f, %.4f)", name, lat, lon)

    # Initialize display
    epd = init_display()
    if not epd:
        logger.critical("Cannot initialize display. Exiting.")
        sys.exit(1)

    while True:
        try:
            # Fetch weather data
            logger.info("Fetching weather data...")
            weather = fetch_weather(lat, lon, forecast_days=forecast_days, hourly_slots=hourly_slots)

            if not weather:
                logger.warning("No weather data available. Waiting before retry...")
                # Display fallback message on screen
                img_black, img_red = create_blank_images()
                from PIL import ImageDraw
                draw = ImageDraw.Draw(img_black)
                draw.text((100, 200), "Unable to fetch weather data", fill=0)
                draw.text((100, 230), "Check network connection", fill=0)
                render_to_display(epd, img_black, img_red)
                time.sleep(config["display"]["refresh_interval_minutes"] * 60)
                continue

            # Render dashboard
            logger.info("Rendering dashboard...")
            img_black, img_red = render_dashboard(weather, config)
            render_to_display(epd, img_black, img_red)
            logger.info("Dashboard updated at %s", datetime.now().strftime("%H:%M:%S"))

        except KeyboardInterrupt:
            logger.info("Interrupted by user. Exiting gracefully.")
            break
        except Exception as e:
            logger.exception("Unexpected error in main loop: %s", e)
        
        # Wait for next refresh cycle
        interval = config["display"]["refresh_interval_minutes"] * 60
        logger.info("Next update in %d minutes", config["display"]["refresh_interval_minutes"])
        time.sleep(interval)

    # Clean up display
    try:
        epd.Clear()
        epd.sleep()
    except Exception as e:
        logger.error("Cleanup error: %s", e)
    
    logger.info("Dashboard stopped.")


if __name__ == "__main__":
    main()
