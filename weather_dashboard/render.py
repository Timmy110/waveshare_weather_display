#!/usr/bin/env python3
"""Render weather data to two PIL images (black + red buffers) for e-Ink display."""

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# Resolution matches epd7in5b_V2 constants
WIDTH, HEIGHT = 800, 480

# Color constants (PIL mode '1': 0 = active color, 255 = background)
COLOR_BG = 255       # white background
COLOR_BLACK = 0      # black ink (active pixel in black buffer)
COLOR_RED = 0        # red ink (active pixel in red buffer)

# --- Weather code mapping ---------------------------------------------------
# WMO weather interpretation codes -> (text label, glyph type)
# https://open-meteo.com/en/docs#weather+codes
WMO_CODES: Dict[int, Tuple[str, str]] = {
    0: ("Clear Sky", "sun"),
    1: ("Mainly Clear", "sun"),
    2: ("Partly Cloudy", "cloud-sun"),
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


def _default_font_path() -> Optional[str]:
    """Try common locations for a TrueType Collection / font file."""
    # Priority: config override > bundled pic/Font.ttc > system fonts
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "pic", "Font.ttc"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "C:\\Windows\\Fonts\\dejavusans.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
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


def _draw_glyph(draw: ImageDraw.ImageDraw, glyph: str, cx: int, cy: int, r: int, fill: int) -> None:
    """
    Draw a simple geometric weather glyph centered at (cx, cy) with radius r.
    Uses PIL primitive shapes to keep dependencies minimal.
    """
    if glyph == "sun":
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)
        # Rays
        for angle in range(0, 360, 45):
            import math
            x1 = int(cx + (r * 0.6) * math.cos(math.radians(angle)))
            y1 = int(cy + (r * 0.6) * math.sin(math.radians(angle)))
            x2 = int(cx + (r * 1.3) * math.cos(math.radians(angle)))
            y2 = int(cy + (r * 1.3) * math.sin(math.radians(angle)))
            draw.line([(x1, y1), (x2, y2)], fill=fill, width=2)

    elif glyph == "cloud":
        # Cloud: overlapping ellipses
        draw.ellipse([cx - r, cy - int(r * 0.4), cx + r, cy + int(r * 0.6)], fill=fill)
        draw.ellipse([cx - int(r * 1.3), cy, cx - int(r * 0.2), cy + int(r * 0.9)], fill=fill)
        draw.ellipse([cx + int(r * 0.2), cy - int(r * 0.5), cx + int(r * 1.4), cy + int(r * 0.3)], fill=fill)

    elif glyph == "cloud-sun":
        # Sun peeking behind cloud
        draw.ellipse([cx - r, cy - r, cx + r, cy + int(r * 0.2)], fill=fill)
        for angle in range(-60, 30, 45):
            import math
            x1 = int(cx + (r * 0.5) * math.cos(math.radians(angle)))
            y1 = int(cy + (r * 0.5) * math.sin(math.radians(angle)) - r * 0.2)
            x2 = int(cx + (r * 1.0) * math.cos(math.radians(angle)))
            y2 = int(cy + (r * 1.0) * math.sin(math.radians(angle)) - r * 0.2)
            draw.line([(x1, y1), (x2, y2)], fill=fill, width=2)

    elif glyph == "rain":
        # Cloud body + rain lines below
        draw.ellipse([cx - r, cy - int(r * 1.0), cx + r, cy], fill=fill)
        for dx in [-int(r * 0.6), 0, int(r * 0.6)]:
            draw.line(
                [(cx + dx, cy + int(r * 0.3)), (cx + dx - int(r * 0.2), cy + r)],
                fill=fill, width=2,
            )

    elif glyph == "snow":
        # Cloud body + snowflakes below
        draw.ellipse([cx - r, cy - int(r * 1.0), cx + r, cy], fill=fill)
        for dx in [-int(r * 0.6), 0, int(r * 0.6)]:
            s = int(r * 0.15)
            fy = cy + int(r * 0.5)
            draw.ellipse([cx + dx - s, fy - s, cx + dx + s, fy + s], fill=fill)

    elif glyph == "fog":
        # Horizontal bars
        for dy in [-int(r * 0.6), 0, int(r * 0.6)]:
            draw.line(
                [(cx - r, cy + dy), (cx + r, cy + dy)],
                fill=fill, width=3,
            )

    elif glyph == "thunder":
        # Cloud + lightning bolt
        draw.ellipse([cx - r, cy - int(r * 1.0), cx + r, cy], fill=fill)
        # Lightning zigzag
        points = [
            (cx + int(r * 0.2), cy + int(r * 0.2)),
            (cx - int(r * 0.2), cy + int(r * 0.6)),
            (cx + int(r * 0.1), cy + int(r * 0.6)),
            (cx - int(r * 0.1), cy + r),
        ]
        draw.polygon(points, fill=fill)


def _condition_label_and_glyph(code: int) -> Tuple[str, str]:
    """Return a human-readable condition label and glyph key for a WMO code."""
    text, glyph = WMO_CODES.get(code, (f"Unknown ({code})", "cloud"))
    return text, glyph


def render_weather(
    weather: Dict[str, Any],
    font_path: Optional[str] = None,
    stale: bool = False,
) -> Tuple[Image.Image, Image.Image]:
    """
    Render a complete weather dashboard image pair (black_buffer, red_buffer).

    Layout (landscape 800x480):
      Top ~60% : Current conditions (large temp, condition, today's hi/lo, details)
      Bottom ~40%: 5-day forecast strip

    Returns two PIL images in mode '1' (1-bit), ready for epd.getbuffer().
    """
    # Font sizes
    if font_path and os.path.isfile(font_path):
        font_large = _load_font(font_path, 72)       # current temp
        font_medium = _load_font(font_path, 36)      # labels / condition text
        font_small = _load_font(font_path, 24)       # details
        font_tiny = _load_font(font_path, 18)        # timestamps
        font_forecast_temp = _load_font(font_path, 22)  # forecast temps
        font_forecast_day = _load_font(font_path, 20)   # day names
    else:
        font_large = _load_font(None, 48)
        font_medium = _load_font(None, 28)
        font_small = _load_font(None, 20)
        font_tiny = _load_font(None, 14)
        font_forecast_temp = _load_font(None, 16)
        font_forecast_day = _load_font(None, 16)

    # Create blank canvases (white background = 255 in mode '1')
    black_img = Image.new("1", (WIDTH, HEIGHT), COLOR_BG)
    red_img = Image.new("1", (WIDTH, HEIGHT), COLOR_BG)

    draw_b = ImageDraw.Draw(black_img)
    draw_r = ImageDraw.Draw(red_img)

    cur = weather["current"]
    unit_sym = "°F" if weather.get("unit") == "fahrenheit" else "°C"
    temp_str = f"{cur['temperature']:.0f}{unit_sym}"
    condition_text, glyph_type = _condition_label_and_glyph(cur["weather_code"])

    # --- TOP SECTION: Current conditions --------------------------------------
    y_top = 20

    # Large temperature (drawn in red for emphasis)
    draw_r.text((40, y_top), temp_str, font=font_large, fill=COLOR_RED)
    # Move past the large text
    bbox = font_large.getbbox(temp_str)
    temp_height = (bbox[3] - bbox[1]) + 10 if bbox else 80
    y_top += temp_height

    # Condition text + glyph side by side
    glyph_y = y_top + 5
    glyph_r = 25
    draw_glyph(draw_b, glyph_type, 40, glyph_y + glyph_r, glyph_r, COLOR_BLACK)
    draw_b.text((90, y_top), condition_text, font=font_medium, fill=COLOR_BLACK)

    # High / Low for today
    hi_lo_str = f"Hi: {weather['today_high']:.0f}{unit_sym}   Lo: {weather['today_low']:.0f}{unit_sym}"
    y_top += 50
    draw_b.text((40, y_top), hi_lo_str, font=font_small, fill=COLOR_BLACK)

    # Feels like + Wind speed
    details = f"Feels like: {cur['feels_like']:.0f}{unit_sym}   Wind: {cur['wind_speed']:.0f} km/h"
    y_top += 35
    draw_b.text((40, y_top), details, font=font_small, fill=COLOR_BLACK)

    # Last updated timestamp (top-right corner)
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    draw_b.text((WIDTH - 10 - len(now_str) * 8, 10), f"Updated: {now_str}", font=font_tiny, fill=COLOR_BLACK)

    # Stale data indicator (if needed)
    if stale:
        draw_r.text((WIDTH - 220, 10), "!! STALE DATA !!", font=font_small, fill=COLOR_RED)

    # Separator line
    sep_y = int(HEIGHT * 0.6)
    draw_b.line([(0, sep_y), (WIDTH, sep_y)], fill=COLOR_BLACK, width=2)

    # --- BOTTOM SECTION: 5-Day Forecast Strip ---------------------------------
    forecast = weather.get("forecast", [])
    n_days = len(forecast)
    if n_days == 0:
        n_days = 1  # prevent zero-division

    strip_top = sep_y + 20
    day_width = WIDTH // 5

    for i, day in enumerate(forecast[:5]):
        x_base = i * day_width + int(day_width * 0.3)  # left margin within column
        day_label = day.get("weekday", "?")
        day_high = f"{day.get('high', '?'):.0f}"
        day_low = f"{day.get('low', '?'):.0f}"

        # Day abbreviation
        draw_b.text((x_base, strip_top), day_label, font=font_forecast_day, fill=COLOR_BLACK)

        # Forecast glyph (drawn in red if precip/thunder for emphasis)
        _, day_glyph = _condition_label_and_glyph(day.get("weather_code", 0))
        glyph_y_pos = strip_top + 25
        glyph_r_small = 18
        is_precip = day_glyph in ("rain", "snow", "thunder")
        if is_precip:
            draw_glyph(draw_r, day_glyph, x_base + glyph_r_small, glyph_y_pos + glyph_r_small, glyph_r_small, COLOR_RED)
        else:
            draw_glyph(draw_b, day_glyph, x_base + glyph_r_small, glyph_y_pos + glyph_r_small, glyph_r_small, COLOR_BLACK)

        # High / Low temps for forecast day
        hi_lo_forecast = f"{day_high}{unit_sym} / {day_low}{unit_sym}"
        draw_b.text((x_base - 5, strip_top + 70), hi_lo_forecast, font=font_forecast_temp, fill=COLOR_BLACK)

        # Column divider (not after last column)
        if i < 4:
            div_x = (i + 1) * day_width
            draw_b.line([(div_x, strip_top), (div_x, HEIGHT - 5)], fill=COLOR_BLACK, width=1)

    return black_img, red_img


def render_blank() -> Tuple[Image.Image, Image.Image]:
    """Return a pair of blank (all-white) images."""
    b = Image.new("1", (WIDTH, HEIGHT), COLOR_BG)
    r = Image.new("1", (WIDTH, HEIGHT), COLOR_BG)
    return b, r
