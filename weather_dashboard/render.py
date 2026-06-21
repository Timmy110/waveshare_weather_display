#!/usr/bin/env python3
"""Render weather data to two PIL images (black + red buffers) for e-Ink display."""

import logging
import math
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont
import io

try:
    import cairosvg
except ImportError:
    cairosvg = None

logger = logging.getLogger(__name__)

# Resolution matches epd7in5b_V2 constants
WIDTH, HEIGHT = 800, 480

# Color constants (PIL mode '1': 0 = active color, 255 = background)
COLOR_BG = 255       # white background
COLOR_BLACK = 0      # black ink (active pixel in black buffer)
COLOR_RED = 0        # red ink (active pixel in red buffer)

# --- Weather code mapping ---------------------------------------------------
# WMO weather interpretation codes -> (text label, icon name)
# https://open-meteo.com/en/docs#weather+codes
WMO_CODES: Dict[int, Tuple[str, str]] = {
    0: ("Clear Sky", "sun"),
    1: ("Mainly Clear", "sun"),
    2: ("Partly Cloudy", "partly_cloudy"),
    3: ("Overcast", "cloud"),
    45: ("Foggy", "fog"),
    48: ("Rime Fog", "fog"),
    51: ("Light Drizzle", "rain"),
    53: ("Moderate Drizzle", "rain"),
    55: ("Dense Drizzle", "rain"),
    56: ("Freezing Drizzle", "rain"),
    57: ("Dense Freez. Drizzle", "rain"),
    61: ("Slight Rain", "rain"),
    63: ("Moderate Rain", "rain"),
    65: ("Heavy Rain", "rain"),
    66: ("Freezing Rain", "rain"),
    67: ("Heavy Freez. Rain", "rain"),
    71: ("Slight Snow", "snow"),
    73: ("Moderate Snow", "snow"),
    75: ("Heavy Snow", "snow"),
    77: ("Snow Grains", "snow"),
    80: ("Slight Showers", "rain"),
    81: ("Moderate Showers", "rain"),
    82: ("Violent Showers", "rain"),
    85: ("Slight Snow Showers", "snow"),
    86: ("Heavy Snow Showers", "snow"),
    95: ("Thunderstorm", "thunder"),
    96: ("Thunderstorm Hail", "thunder"),
    99: ("Severe Thunderstorm", "thunder"),
}

# Icon file mapping (icon name -> SVG filename)
ICON_FILES = {
    "sun": "sun.svg",
    "cloud": "cloud.svg",
    "partly_cloudy": "partly_cloudy.svg",
    "rain": "rain.svg",
    "snow": "snow.svg",
    "fog": "fog.svg",
    "thunder": "thunder.svg",
}

# Pre-rendered icon cache: {icon_name: {size: Image}}
_icon_cache: Dict[str, Dict[int, Image.Image]] = {}


def _default_font_path() -> Optional[str]:
    """Try common locations for a TrueType Collection / font file."""
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "pic", "Font.ttc"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ]
    for p in candidates:
        if os.path.isfile(p):
            logger.info("Using font: %s", p)
            return p
    logger.warning("No suitable font found; will fall back to default bitmap font")
    return None


def _load_font(path: Optional[str], size: int) -> ImageFont.FreeTypeFont:
    """Load a truetype font at the given size, or return the default."""
    if path and os.path.isfile(path):
        try:
            return ImageFont.truetype(path, size)
        except Exception as exc:
            logger.warning("Failed to load font %s at size %d: %s", path, size, exc)
    # Fallback
    return ImageFont.load_default()


def _get_font_height(font, text="Hg"):
    """
    Get the height of a font in pixels.
    Works with both old and new Pillow versions.
    """
    try:
        size = font.getsize(text)
        return size[1]
    except AttributeError:
        # Newer Pillow uses getbbox
        bbox = font.getbbox(text)
        if bbox:
            return (bbox[3] - bbox[1]) + 1
        return 20


def _get_text_width(font, text):
    """Get the width of text in pixels."""
    try:
        size = font.getsize(text)
        return size[0]
    except AttributeError:
        bbox = font.getbbox(text)
        if bbox:
            return (bbox[2] - bbox[0]) + 1
        return len(text) * 6


def _draw_thick_line(draw, xy, fill, thickness=1):
    """
    Draw a line with specified thickness.
    For older Pillow that doesn't support width= in draw.line(),
    we draw multiple adjacent lines.
    """
    if thickness <= 1:
        draw.line(xy, fill=fill)
        return
    # Get the direction and draw parallel lines
    if len(xy) >= 2:
        x0, y0 = xy[0]
        x1, y1 = xy[-1]
        dx = x1 - x0
        dy = y1 - y0
        length = math.sqrt(dx * dx + dy * dy)
        if length > 0:
            nx = -dy / length
            ny = dx / length
            for t in range(-thickness // 2, (thickness // 2) + 1):
                new_x0 = x0 + int(nx * t)
                new_y0 = y0 + int(ny * t)
                new_x1 = x1 + int(nx * t)
                new_y1 = y1 + int(ny * t)
                draw.line([(new_x0, new_y0), (new_x1, new_y1)], fill=fill)


def _load_icon(icon_name: str, size: int) -> Optional[Image.Image]:
    """
    Load an SVG icon, render it at the specified size, and return as a 1-bit PIL image.
    Icons are cached to avoid re-rendering on every call.
    
    Returns None if cairosvg is not available or icon loading fails.
    """
    # Check cache first
    if icon_name in _icon_cache and size in _icon_cache[icon_name]:
        return _icon_cache[icon_name][size]
    
    if cairosvg is None:
        logger.warning("cairosvg not available, cannot render SVG icons")
        return None
    
    # Resolve icon file path
    filename = ICON_FILES.get(icon_name)
    if not filename:
        logger.warning("Unknown icon name: %s", icon_name)
        return None
    
    # Look for the icon in the icons/ directory relative to this module
    here = os.path.dirname(os.path.abspath(__file__))
    icon_dir = os.path.join(here, "..", "icons")
    icon_path = os.path.join(icon_dir, filename)
    
    if not os.path.isfile(icon_path):
        logger.warning("Icon file not found: %s", icon_path)
        return None
    
    try:
        with open(icon_path, "r") as f:
            svg_content = f.read()
        
        # Render SVG to PNG bytes at higher resolution, then scale down
        png_data = cairosvg.svg2png(
            bytestring=svg_content.encode("utf-8"),
            output_width=size * 2,  # Render at 2x for better quality
            output_height=size * 2,
        )
        
        # Load PNG and convert to grayscale then 1-bit
        img = Image.open(io.BytesIO(png_data))
        img = img.resize((size, size), Image.LANCZOS)
        img = img.convert("L")  # Grayscale
        
        # Threshold at 128: pixels darker than threshold become black (0), rest white (255)
        img = img.point(lambda p: 0 if p < 128 else 255)
        
        # Cache the result
        _icon_cache.setdefault(icon_name, {})[size] = img
        return img
        
    except Exception as exc:
        logger.error("Failed to load icon %s: %s", icon_name, exc)
        return None


def _paste_icon(base_img: Image.Image, icon_name: str, cx: int, cy: int, size: int) -> bool:
    """
    Paste an icon centered at (cx, cy) on the base image.
    Returns True if icon was successfully pasted, False otherwise.
    """
    icon = _load_icon(icon_name, size)
    if icon is None:
        return False
    
    # Calculate top-left position for centered placement
    x = cx - size // 2
    y = cy - size // 2
    
    base_img.paste(icon, (x, y))
    return True


def _condition_label_and_icon(code: int) -> Tuple[str, str]:
    """Return a human-readable condition label and icon name for a WMO code."""
    text, icon = WMO_CODES.get(code, (f"Unknown ({code})", "cloud"))
    return text, icon


def render_weather(
    weather: Dict[str, Any],
    font_path: Optional[str] = None,
    stale: bool = False,
) -> Tuple[Image.Image, Image.Image]:
    """
    Render a complete weather dashboard image pair (black_buffer, red_buffer).

    Layout (landscape 800x480):
      - Top half (~0-240):
        Left (~0-390): Clock + Hourly forecast strip
        Right (~400-799): Current weather (icon, temp, details)
      - Bottom half (~250-440): 5-day forecast columns
      - Footer (~440-480): Source attribution + last update time

    Returns two PIL images in mode '1' (1-bit), ready for epd.getbuffer().
    """
    # Clear icon cache on each render to allow updates
    _icon_cache.clear()
    
    # Font sizes
    if font_path and os.path.isfile(font_path):
        font_clock = _load_font(font_path, 64)          # clock display
        font_temp_large = _load_font(font_path, 72)     # current temperature
        font_icon_label = _load_font(font_path, 32)     # condition text
        font_detail = _load_font(font_path, 24)         # wind, feels like, etc
        font_hourly_temp = _load_font(font_path, 22)    # hourly temps
        font_hourly_time = _load_font(font_path, 18)    # hourly time labels
        font_forecast_day = _load_font(font_path, 24)   # day names in forecast
        font_forecast_temp = _load_font(font_path, 22)  # forecast temps
        font_footer = _load_font(font_path, 16)         # footer text
    else:
        font_clock = _load_font(None, 36)
        font_temp_large = _load_font(None, 48)
        font_icon_label = _load_font(None, 24)
        font_detail = _load_font(None, 20)
        font_hourly_temp = _load_font(None, 16)
        font_hourly_time = _load_font(None, 14)
        font_forecast_day = _load_font(None, 16)
        font_forecast_temp = _load_font(None, 16)
        font_footer = _load_font(None, 12)

    # Create blank canvases (white background = 255 in mode '1')
    black_img = Image.new("1", (WIDTH, HEIGHT), COLOR_BG)
    red_img = Image.new("1", (WIDTH, HEIGHT), COLOR_BG)

    draw_b = ImageDraw.Draw(black_img)
    draw_r = ImageDraw.Draw(red_img)

    cur = weather["current"]
    unit_sym = "°F" if weather.get("unit") == "fahrenheit" else "°C"
    temp_str = f"{cur['temperature']:.0f}{unit_sym}"
    condition_text, icon_name = _condition_label_and_icon(cur["weather_code"])

    # --- LAYOUT CONSTANTS ---------------------------------------------------
    margin = 15
    left_col_width = 390       # left column width (clock + hourly)
    divider_x = left_col_width + 5  # vertical separator between left/right
    right_col_x = divider_x + 10    # start of right column
    top_section_h = 240        # height of top section
    forecast_top = top_section_h + 20
    forecast_bottom = HEIGHT - 50
    footer_y = HEIGHT - 35

    # ========================================================================
    # TOP LEFT: CLOCK
    # ========================================================================
    y_clock = margin + 5

    # Display local time from API (or fall back to UTC)
    local_time_str = cur.get("local_time")
    if local_time_str:
        try:
            now_dt = datetime.fromisoformat(local_time_str)
            clock_display = now_dt.strftime("%H:%M")
            date_display = now_dt.strftime("%a, %b %d")
        except (ValueError, TypeError):
            now_dt = datetime.now(timezone.utc)
            clock_display = now_dt.strftime("%H:%M")
            date_display = now_dt.strftime("%a, %b %d")
    else:
        now_dt = datetime.now(timezone.utc)
        clock_display = now_dt.strftime("%H:%M")
        date_display = now_dt.strftime("%a, %b %d")

    draw_b.text((margin, y_clock), clock_display, font=font_clock, fill=COLOR_BLACK)
    draw_b.text((margin, y_clock + _get_font_height(font_clock) + 5), date_display,
                font=font_hourly_time, fill=COLOR_BLACK)

    # ========================================================================
    # TOP LEFT (below clock): HOURLY FORECAST STRIP
    # ========================================================================
    hourly_forecast = weather.get("hourly_forecast", [])
    y_hourly_start = y_clock + _get_font_height(font_clock) + _get_font_height(font_hourly_time) + 20

    # Draw "HOURLY" label
    draw_b.text((margin, y_hourly_start), "HOURLY", font=font_hourly_time, fill=COLOR_BLACK)
    y_hourly_start += _get_font_height(font_hourly_time) + 5

    # Calculate spacing for hourly items
    num_hours = len(hourly_forecast) if hourly_forecast else 0
    if num_hours > 0:
        available_width = left_col_width - margin * 2
        hour_block_width = max(available_width // num_hours, 40)
    else:
        hour_block_width = 50

    for i, hour_data in enumerate(hourly_forecast[:num_hours]):
        x_base = margin + i * hour_block_width
        hour_label = hour_data.get("hour", "?")
        hour_temp = f"{hour_data.get('temperature', '?'):.0f}"
        _, hour_icon = _condition_label_and_icon(hour_data.get("weather_code", 0))

        # Time label
        time_text = hour_label
        tw = _get_text_width(font_hourly_time, time_text)
        draw_b.text((x_base + (hour_block_width - tw) // 2, y_hourly_start),
                    time_text, font=font_hourly_time, fill=COLOR_BLACK)

        # Icon (centered in block)
        icon_center_y = y_hourly_start + _get_font_height(font_hourly_time) + 15
        icon_size = 20
        cx = x_base + hour_block_width // 2
        if not _paste_icon(black_img, hour_icon, cx, icon_center_y, icon_size):
            # Fallback: draw a simple dot if icon fails
            black_img.putpixel((cx, icon_center_y), COLOR_BLACK)

        # Temperature below icon
        temp_text = f"{hour_temp}°"
        tpw = _get_text_width(font_hourly_temp, temp_text)
        draw_b.text((x_base + (hour_block_width - tpw) // 2, icon_center_y + icon_size),
                    temp_text, font=font_hourly_temp, fill=COLOR_BLACK)

    # ========================================================================
    # TOP RIGHT: CURRENT WEATHER
    # ========================================================================
    y_right = margin + 5

    # Large weather icon (centered in right column)
    right_col_width = WIDTH - right_col_x - margin
    icon_cx = right_col_x + right_col_width // 2
    icon_cy = y_right + 60
    icon_size_large = 80
    _paste_icon(black_img, icon_name, icon_cx, icon_cy, icon_size_large)

    # Large temperature (RED) below icon
    temp_y = icon_cy + icon_size_large + 15
    temp_width = _get_text_width(font_temp_large, temp_str)
    temp_x = right_col_x + (right_col_width - temp_width) // 2
    draw_r.text((temp_x, temp_y), temp_str, font=font_temp_large, fill=COLOR_RED)

    # Condition text below temperature
    cond_y = temp_y + _get_font_height(font_temp_large) + 5
    cond_width = _get_text_width(font_icon_label, condition_text)
    cond_x = right_col_x + (right_col_width - cond_width) // 2
    draw_b.text((cond_x, cond_y), condition_text, font=font_icon_label, fill=COLOR_BLACK)

    # Hi / Lo for today
    hi_lo_str = f"Hi {weather['today_high']:.0f}{unit_sym}   Lo {weather['today_low']:.0f}{unit_sym}"
    hilo_y = cond_y + _get_font_height(font_icon_label) + 15
    hilo_width = _get_text_width(font_detail, hi_lo_str)
    hilo_x = right_col_x + (right_col_width - hilo_width) // 2
    draw_b.text((hilo_x, hilo_y), hi_lo_str, font=font_detail, fill=COLOR_BLACK)

    # Wind speed
    wind_str = f"Wind: {cur['wind_speed']:.0f} km/h"
    wind_y = hilo_y + _get_font_height(font_detail) + 10
    wind_width = _get_text_width(font_detail, wind_str)
    wind_x = right_col_x + (right_col_width - wind_width) // 2
    draw_b.text((wind_x, wind_y), wind_str, font=font_detail, fill=COLOR_BLACK)

    # Feels like
    feels_str = f"Feels like: {cur['feels_like']:.0f}{unit_sym}"
    feels_y = wind_y + _get_font_height(font_detail) + 10
    feels_width = _get_text_width(font_detail, feels_str)
    feels_x = right_col_x + (right_col_width - feels_width) // 2
    draw_b.text((feels_x, feels_y), feels_str, font=font_detail, fill=COLOR_BLACK)

    # ========================================================================
    # SEPARATORS
    # ========================================================================
    # Vertical divider between left and right columns
    _draw_thick_line(draw_b, [(divider_x, margin), (divider_x, top_section_h)],
                    fill=COLOR_BLACK, thickness=2)

    # Horizontal separator above forecast
    sep_y = top_section_h
    _draw_thick_line(draw_b, [(0, sep_y), (WIDTH, sep_y)], fill=COLOR_BLACK, thickness=2)

    # ========================================================================
    # BOTTOM: 5-DAY FORECAST STRIP
    # ========================================================================
    forecast = weather.get("forecast", [])

    strip_top = sep_y + 15
    num_days = len(forecast) if forecast else 0
    day_width = WIDTH // max(num_days, 1)

    for i, day in enumerate(forecast[:5]):
        x_center = i * day_width + day_width // 2
        y_pos = strip_top + 5
        day_label = day.get("weekday", "?")
        day_high = f"{day.get('high', '?'):.0f}{unit_sym}"
        day_low = f"{day.get('low', '?'):.0f}{unit_sym}"

        # Day abbreviation (centered)
        dw = _get_text_width(font_forecast_day, day_label)
        draw_b.text((x_center - dw // 2, y_pos), day_label, font=font_forecast_day, fill=COLOR_BLACK)

        # Forecast icon
        _, day_icon = _condition_label_and_icon(day.get("weather_code", 0))
        icon_center_y = y_pos + _get_font_height(font_forecast_day) + 30
        icon_size_medium = 40
        
        is_precip = day_icon in ("rain", "snow", "thunder")
        if is_precip:
            # Red icons for precipitation days
            _paste_icon(red_img, day_icon, x_center, icon_center_y, icon_size_medium)
        else:
            _paste_icon(black_img, day_icon, x_center, icon_center_y, icon_size_medium)

        # High temp (red accent) below icon
        hi_y = icon_center_y + icon_size_medium // 2 + 5
        hi_w = _get_text_width(font_forecast_temp, day_high)
        draw_r.text((x_center - hi_w // 2, hi_y), day_high, font=font_forecast_temp, fill=COLOR_RED)

        # Low temp below high
        lo_y = hi_y + _get_font_height(font_forecast_temp) + 5
        lo_w = _get_text_width(font_forecast_temp, day_low)
        draw_b.text((x_center - lo_w // 2, lo_y), day_low, font=font_forecast_temp, fill=COLOR_BLACK)

        # Column divider (not after last column)
        if i < num_days - 1 and i < 4:
            div_x = (i + 1) * day_width
            draw_b.line([(div_x, strip_top), (div_x, forecast_bottom)], fill=COLOR_BLACK)

    # ========================================================================
    # FOOTER: Source + Last Updated
    # ========================================================================
    _draw_thick_line(draw_b, [(0, footer_y - 10), (WIDTH, footer_y - 10)],
                    fill=COLOR_BLACK, thickness=1)

    footer_left = "Source: Open-Meteo"
    flw = _get_text_width(font_footer, footer_left)
    draw_b.text((margin, footer_y), footer_left, font=font_footer, fill=COLOR_BLACK)

    # Timestamp on the right
    now_utc_str = datetime.now(timezone.utc).strftime("Updated: %Y-%m-%d %H:%M UTC")
    ftw = _get_text_width(font_footer, now_utc_str)
    draw_b.text((WIDTH - margin - ftw, footer_y), now_utc_str, font=font_footer, fill=COLOR_BLACK)

    # Stale data indicator (if needed)
    if stale:
        stale_text = "!! STALE DATA !!"
        stw = _get_text_width(font_detail, stale_text)
        draw_r.text((WIDTH // 2 - stw // 2, footer_y), stale_text, font=font_detail, fill=COLOR_RED)

    return black_img, red_img


def render_blank() -> Tuple[Image.Image, Image.Image]:
    """Return a pair of blank (all-white) images."""
    b = Image.new("1", (WIDTH, HEIGHT), COLOR_BG)
    r = Image.new("1", (WIDTH, HEIGHT), COLOR_BG)
    return b, r
