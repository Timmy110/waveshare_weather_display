#!/usr/bin/env python3
"""
Waveshare E-Ink Weather Dashboard
Calls the Waveshare epd7in5b_V2 library directly (similar to example.py).
"""

import sys
import os
import time
import logging
import yaml
import requests
from datetime import datetime, timezone
from PIL import Image, ImageDraw, ImageFont

# Add lib directory to path for waveshare_epd import
libdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")
if os.path.exists(libdir) and libdir not in sys.path:
    sys.path.insert(0, libdir)

from waveshare_epd import epd7in5b_V2

# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("weather_dashboard")

# ─── Display constants ────────────────────────────────────────────────────────

EPD_WIDTH = 800
EPD_HEIGHT = 480

# ─── Default configuration ────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "location": {
        "name": "Brussels, Belgium",
        "latitude": 50.8503,
        "longitude": 4.3517,
    },
    "display": {
        "refresh_interval_minutes": 30,
        "forecast_days": 5,
        "hourly_slots": 8,
    },
    "units": {
        "temperature": "C",
    },
    "alerts": {
        "temp_high_threshold": 35.0,
        "temp_low_threshold": -5.0,
        "precip_threshold": 10.0,
    },
}

# ─── WMO weather codes ────────────────────────────────────────────────────────

WMO_CODES = {
    0: ("Clear sky", "\u2600"),
    1: ("Mainly clear", "\u2600"),
    2: ("Partly cloudy", "\u26c5"),
    3: ("Overcast", "\u2601"),
    45: ("Fog", "\ud83c\udf2b"),
    48: ("Rime fog", "\ud83c\udf2b"),
    51: ("Light drizzle", "\ud83c\udf26"),
    53: ("Moderate drizzle", "\ud83c\udf26"),
    55: ("Dense drizzle", "\ud83c\udf27"),
    56: ("Freezing drizzle", "\ud83c\udf27"),
    57: ("Dense freezing drizzle", "\ud83c\udf27"),
    61: ("Slight rain", "\ud83c\udf27"),
    63: ("Moderate rain", "\ud83c\udf27"),
    65: ("Heavy rain", "\ud83c\udf27"),
    66: ("Freezing rain", "\ud83c\udf27"),
    67: ("Heavy freezing rain", "\ud83c\udf27"),
    71: ("Light snow", "\u2744"),
    73: ("Moderate snow", "\u2744"),
    75: ("Heavy snow", "\u2744"),
    77: ("Snow grains", "\u2744"),
    80: ("Rain showers", "\ud83c\udf26"),
    81: ("Moderate showers", "\ud83c\udf27"),
    82: ("Violent showers", "\ud83c\udf27"),
    85: ("Snow showers", "\u2744"),
    86: ("Heavy snow showers", "\u2744"),
    95: ("Thunderstorm", "\u26c8"),
    96: ("Thunderstorm + hail", "\u26c8"),
    99: ("Thunderstorm + heavy hail", "\u26c8"),
}


def get_wmo_info(code):
    """Return (description, icon_emoji) for WMO weather code."""
    return WMO_CODES.get(code, ("Unknown", "?"))


# ─── Config loading ───────────────────────────────────────────────────────────

def load_config():
    """Load config from config.yaml, falling back to defaults."""
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml"),
        os.path.join(os.getcwd(), "config.yaml"),
    ]
    cfg_path = None
    for c in candidates:
        if os.path.exists(c):
            cfg_path = c
            break

    config = {}
    for section, values in DEFAULT_CONFIG.items():
        config[section] = dict(values)

    if cfg_path:
        logger.info("Loading config from %s", cfg_path)
        try:
            with open(cfg_path, "r") as f:
                user_cfg = yaml.safe_load(f) or {}
            for section in DEFAULT_CONFIG:
                if section in user_cfg and isinstance(user_cfg[section], dict):
                    config[section].update(user_cfg[section])
        except Exception as e:
            logger.error("Failed to parse config file: %s", e)
    else:
        logger.warning("No config.yaml found, using defaults")

    return config


# ─── Weather API ──────────────────────────────────────────────────────────────

METEO_API_URL = "https://api.open-meteo.com/v1/forecast"


def fetch_weather(lat, lon, forecast_days=5, hourly_slots=8):
    """Fetch current, hourly, and daily weather from Open-Meteo."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,precipitation,weather_code",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum",
        "hourly": "temperature_2m,precipitation_probability,weather_code",
        "forecast_days": forecast_days,
        "timezone": "auto",
    }

    try:
        response = requests.get(METEO_API_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        logger.error("Failed to fetch weather data: %s", e)
        return None

    current = data.get("current", {})
    daily = data.get("daily", {})
    hourly = data.get("hourly", {})

    # Parse hourly forecast for next N slots
    now = datetime.now(timezone.utc)
    hourly_times = [datetime.fromisoformat(t.replace("Z", "+00:00")) for t in hourly["time"]]
    current_hour_idx = 0
    for i, t in enumerate(hourly_times):
        if t <= now:
            current_hour_idx = i

    hour_list = []
    for i in range(current_hour_idx, min(current_hour_idx + hourly_slots, len(hourly_times))):
        hour_list.append({
            "time": hourly_times[i].strftime("%H:%M"),
            "temperature": hourly["temperature_2m"][i],
            "precip_probability": hourly["precipitation_probability"][i],
            "weather_code": hourly["weather_code"][i],
        })

    return {
        "current": {
            "temperature": current.get("temperature_2m"),
            "humidity": current.get("relative_humidity_2m"),
            "precipitation": current.get("precipitation"),
            "weather_code": current.get("weather_code"),
        },
        "today_precip": daily.get("precipitation_sum", [0.0])[0] if daily.get("precipitation_sum") else 0.0,
        "hourly": hour_list,
        "daily": {
            "dates": [d[:8] for d in daily.get("time", [])],
            "weather_codes": daily.get("weather_code"),
            "temp_max": daily.get("temperature_2m_max"),
            "temp_min": daily.get("temperature_2m_min"),
            "precipitation_sum": daily.get("precipitation_sum"),
        },
    }


# ─── Font helpers ─────────────────────────────────────────────────────────────

def get_font(size):
    """Load a TTF font, falling back to PIL default if not found."""
    font_paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts", "DejaVuSans.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu-sans/DejaVuSans.ttf",
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return ImageFont.load_default()


def draw_text_aligned(draw, x, y, text, font, fill=0, align="left"):
    """Draw text with optional center/right alignment."""
    try:
        bbox = draw.textbbox((x, y), text, font=font)
        tw = bbox[2] - bbox[0]
        if align == "center":
            x -= tw // 2
        elif align == "right":
            x -= tw
    except Exception:
        pass
    draw.text((x, y), text, font=font, fill=fill)


# ─── Layout / Rendering ──────────────────────────────────────────────────────

def render_dashboard(weather, config):
    """
    Render the full weather dashboard.
    Returns (black_image, red_image) PIL Images for the epd7in5b_V2 display.
    """
    img_black = Image.new("1", (EPD_WIDTH, EPD_HEIGHT), 1)  # white background
    img_red = Image.new("1", (EPD_WIDTH, EPD_HEIGHT), 1)    # white background

    draw_b = ImageDraw.Draw(img_black)
    draw_r = ImageDraw.Draw(img_red)

    location_name = config["location"]["name"]
    alerts = config["alerts"]
    current = weather.get("current", {})
    today_precip = weather.get("today_precip", 0.0)
    hourly = weather.get("hourly", [])
    daily = weather.get("daily", {})

    # Fonts
    f_header = get_font(26)
    f_temp_large = get_font(72)
    f_sub = get_font(28)
    f_hour_label = get_font(22)
    f_hour_temp = get_font(26)
    f_day_label = get_font(24)
    f_day_temp = get_font(22)
    f_footer = get_font(18)

    # --- HEADER BAR (~40px) ---
    header_h = 40
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    draw_b.rectangle([0, 0, EPD_WIDTH - 1, header_h - 1], fill=0, outline=0)
    draw_b.text((20, 6), location_name, font=f_header, fill=1)
    draw_b.text((EPD_WIDTH - 20, 6), now_str, font=f_header, fill=1, anchor="rt")

    # --- TOP SECTION: Current Weather (left) | Hourly Forecast (right) (~240px) ---
    split_x = EPD_WIDTH // 3 * 1 + 50
    top_y = header_h + 5
    top_h = 240

    draw_b.line([(0, header_h), (EPD_WIDTH - 1, header_h)], fill=0)

    # -- LEFT COLUMN: Current Weather --
    wx_code = current.get("weather_code", 0)
    desc, icon_txt = get_wmo_info(wx_code)

    draw_b.text((split_x // 2, top_y + 10), icon_txt, font=get_font(64), fill=0, anchor="mb")

    temp_val = current.get("temperature", "--")
    if isinstance(temp_val, (int, float)):
        temp_str = f"{temp_val:.1f}\u00b0C"
    else:
        temp_str = "--\u00b0C"

    is_alert = False
    if isinstance(temp_val, (int, float)):
        if temp_val >= alerts.get("temp_high_threshold", 35) or temp_val <= alerts.get("temp_low_threshold", -5):
            is_alert = True

    draw_text_aligned(draw_b, split_x // 2, top_y + 80, temp_str, f_temp_large,
                      fill=0 if not is_alert else 1, align="center")
    if is_alert:
        draw_text_aligned(draw_r, split_x // 2, top_y + 80, temp_str, f_temp_large,
                          fill=0, align="center")

    draw_text_aligned(draw_b, split_x // 2, top_y + 145, desc, f_sub, align="center")

    humidity = current.get("humidity", "--")
    if isinstance(humidity, (int, float)):
        draw_b.text((split_x // 2, top_y + 180), f"Humidity: {humidity}%",
                    font=f_hour_label, fill=0, anchor="mb")

    precip_str = f"Precip today: {today_precip:.1f} mm" if isinstance(today_precip, (int, float)) else "Precip today: -- mm"
    precip_alert = isinstance(today_precip, (int, float)) and today_precip >= alerts.get("precip_threshold", 10)
    draw_b.text((split_x // 2, top_y + 210), precip_str, font=f_hour_label,
                fill=0 if not precip_alert else 1, anchor="mb")
    if precip_alert:
        draw_r.text((split_x // 2, top_y + 210), precip_str, font=f_hour_label, fill=0, anchor="mb")

    # Separator between columns
    draw_b.line([(split_x, top_y), (split_x, top_y + top_h)], fill=0)

    # -- RIGHT COLUMN: Hourly Forecast --
    hx_start = split_x + 15
    hour_count = len(hourly)

    if hour_count > 0:
        draw_b.text((hx_start, top_y + 5), "Hourly Forecast", font=f_sub, fill=0)

        col_w = (EPD_WIDTH - hx_start - 20) // min(hour_count, 8)

        for i, hr in enumerate(hourly[:8]):
            cx = hx_start + i * col_w + col_w // 2
            hour_label = hr.get("time", "??:??")
            hr_code = hr.get("weather_code", 0)
            _, hr_icon = get_wmo_info(hr_code)
            hr_temp = hr.get("temperature", "--")
            hr_precip = hr.get("precip_probability", 0)

            draw_b.text((cx, top_y + 35), hour_label[:2] + "h", font=f_hour_label, fill=0, anchor="mb")
            draw_b.text((cx, top_y + 60), hr_icon, font=get_font(32), fill=0, anchor="mb")

            if isinstance(hr_temp, (int, float)):
                t_str = f"{hr_temp:.0f}\u00b0"
            else:
                t_str = "--\u00b0"
            draw_b.text((cx, top_y + 100), t_str, font=f_hour_temp, fill=0, anchor="mb")

            if isinstance(hr_precip, (int, float)):
                p_str = f"{hr_precip:.0f}%"
            else:
                p_str = ""
            draw_b.text((cx, top_y + 130), p_str, font=f_hour_label, fill=0, anchor="mb")

    # --- MIDDLE SECTION: 5-Day Forecast (~120px) ---
    mid_y = header_h + top_h + 10
    draw_b.line([(0, mid_y - 5), (EPD_WIDTH - 1, mid_y - 5)], fill=0)

    daily_codes = daily.get("weather_codes", [])
    daily_max = daily.get("temp_max", [])
    daily_min = daily.get("temp_min", [])
    daily_dates = daily.get("dates", [])

    day_abbr = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    if len(daily_codes) > 0:
        days_to_show = min(5, len(daily_codes))
        col_w = EPD_WIDTH // days_to_show

        for i in range(days_to_show):
            cx = i * col_w + col_w // 2

            date_str = daily_dates[i] if i < len(daily_dates) else ""
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                day_name = day_abbr[dt.weekday()]
            except Exception:
                day_name = str(i + 1)

            draw_b.text((cx, mid_y + 5), day_name, font=f_day_label, fill=0, anchor="mb")

            d_code = daily_codes[i] if i < len(daily_codes) else 0
            _, d_icon = get_wmo_info(d_code)
            draw_b.text((cx, mid_y + 30), d_icon, font=get_font(36), fill=0, anchor="mb")

            hi = daily_max[i] if i < len(daily_max) else "--"
            lo = daily_min[i] if i < len(daily_min) else "--"

            hi_str = f"{hi:.0f}\u00b0" if isinstance(hi, (int, float)) else "--\u00b0"
            lo_str = f"{lo:.0f}\u00b0" if isinstance(lo, (int, float)) else "--\u00b0"

            draw_b.text((cx - 15, mid_y + 72), hi_str, font=f_day_temp, fill=0, anchor="mb")
            draw_b.text((cx + 15, mid_y + 72), lo_str, font=f_day_temp, fill=0, anchor="mb")

    # --- FOOTER (~40px) ---
    foot_y = EPD_HEIGHT - 35
    draw_b.line([(0, foot_y - 5), (EPD_WIDTH - 1, foot_y - 5)], fill=0)

    footer_text = f"Open-Meteo  |  Last update: {datetime.now().strftime('%H:%M')}"
    draw_b.text((20, foot_y), footer_text, font=f_footer, fill=0)

    return img_black, img_red


def render_error_message(msg1, msg2=""):
    """Create a blank image with an error message."""
    img_black = Image.new("1", (EPD_WIDTH, EPD_HEIGHT), 1)
    img_red = Image.new("1", (EPD_WIDTH, EPD_HEIGHT), 1)
    draw = ImageDraw.Draw(img_black)
    f_sub = get_font(28)
    draw.text((100, 200), msg1, font=f_sub, fill=0)
    if msg2:
        draw.text((100, 240), msg2, font=f_sub, fill=0)
    return img_black, img_red


# ─── Main loop ────────────────────────────────────────────────────────────────

def main():
    logger.info("Starting Weather Dashboard")

    config = load_config()
    loc_name = config["location"]["name"]
    lat = config["location"]["latitude"]
    lon = config["location"]["longitude"]
    forecast_days = config["display"]["forecast_days"]
    hourly_slots = config["display"]["hourly_slots"]
    refresh_minutes = config["display"]["refresh_interval_minutes"]

    logger.info("Location: %s (%.4f, %.4f)", loc_name, lat, lon)

    epd = epd7in5b_V2.EPD()

    try:
        logging.info("Init and Clear display")
        epd.init()
        epd.Clear()

        while True:
            try:
                # Fetch weather data
                logger.info("Fetching weather data...")
                weather = fetch_weather(lat, lon, forecast_days=forecast_days, hourly_slots=hourly_slots)

                if not weather:
                    logger.warning("No weather data available. Displaying error message.")
                    img_black, img_red = render_error_message(
                        "Unable to fetch weather data",
                        "Check network connection"
                    )
                    epd.display(epd.getbuffer(img_black), epd.getbuffer(img_red))
                    time.sleep(refresh_minutes * 60)
                    continue

                # Render dashboard
                logger.info("Rendering dashboard...")
                img_black, img_red = render_dashboard(weather, config)
                epd.display(epd.getbuffer(img_black), epd.getbuffer(img_red))
                logger.info("Dashboard updated at %s", datetime.now().strftime("%H:%M:%S"))

            except KeyboardInterrupt:
                logger.info("Interrupted by user. Exiting gracefully.")
                break
            except Exception as e:
                logger.exception("Unexpected error in main loop: %s", e)

            # Wait for next refresh cycle
            logger.info("Next update in %d minutes", refresh_minutes)
            time.sleep(refresh_minutes * 60)

    except KeyboardInterrupt:
        logger.info("Interrupted by user. Exiting gracefully.")

    # Clean up
    logging.info("Clearing display and going to sleep...")
    try:
        epd.init()
        epd.Clear()
        epd.sleep()
    except Exception as e:
        logger.error("Cleanup error: %s", e)

    epd7in5b_V2.epdconfig.module_exit(cleanup=True)
    logger.info("Dashboard stopped.")


if __name__ == "__main__":
    main()