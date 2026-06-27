#!/usr/bin/env python3
"""Render weather data to two PIL images (black + red buffers) for e-Ink display."""

import logging
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

# zoneinfo is stdlib since Python 3.9
if sys.version_info >= (3, 9):
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    pytz = None
else:
    try:
        import pytz
    except ImportError:
        pytz = None

from PIL import Image, ImageDraw, ImageFont

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

# Icon file mapping (icon name -> PNG filename)
ICON_FILES = {
    "sun": "sun.png",
    "cloud": "cloud.png",
    "partly_cloudy": "partly_cloudy.png",
    "rain": "rain.png",
    "snow": "snow.png",
    "fog": "fog.png",
    "thunder": "thunder.png",
}

# Pre-rendered icon cache: {icon_name: {size: Image}}
_icon_cache: Dict[str, Dict[int, Image.Image]] = {}


def _default_font_path() -> Optional[str]:
    """Try common locations for a TrueType Collection / font file."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "..", "resources", "pic", "Font.ttc"),
        os.path.join(here, "..", "resources", "pic", "Font.ttf"),
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


def _draw_centered_text(draw, text, font, center_x, y, fill):
    """Draw `text` horizontally centered on `center_x` at vertical position `y`."""
    w = _get_text_width(font, text)
    draw.text((center_x - w // 2, y), text, font=font, fill=fill)


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


def _load_icon_mask(icon_name: str, size: int) -> Optional[Image.Image]:
    """
    Load a pre-rendered PNG icon and convert it to a paste mask.
    
    The returned image is in mode '1' where pixels are 255 at the shape of the icon
    and 0 everywhere else (suitable as the mask parameter to Image.paste()).
    
    Icons are cached per name+size. Returns None on failure.
    """
    # Check cache first
    if icon_name in _icon_cache and size in _icon_cache[icon_name]:
        return _icon_cache[icon_name][size]

    # Resolve icon file path
    filename = ICON_FILES.get(icon_name)
    if not filename:
        logger.warning("Unknown icon name: %s", icon_name)
        return None

    here = os.path.dirname(os.path.abspath(__file__))
    icon_dir = os.path.join(here, "..", "resources", "icons")
    icon_path = os.path.join(icon_dir, filename)

    if not os.path.isfile(icon_path):
        logger.warning("Icon file not found: %s", icon_path)
        return None

    try:
        # Load PNG directly
        img = Image.open(icon_path)
        # Scale to requested size with LANCZOS (highest quality downsampling)
        img = img.resize((size, size), Image.LANCZOS)

        # Extract alpha channel to determine opaque pixels (icon shape)
        if img.mode in ("RGBA", "LA"):
            # Directly extract the alpha channel (index 3 for RGBA, index 1 for LA)
            alpha = img.split()[-1]
        elif img.mode == "P" and "transparency" in img.info:
            # Palette mode with transparency — convert to RGBA first, then get alpha
            alpha = img.convert("RGBA").split()[3]
        else:
            # No transparency info — use luminance threshold (dark-on-light icons)
            gray = img.convert("L")
            mask = gray.point(lambda p: 255 if p < 128 else 0).convert("1")
            _icon_cache.setdefault(icon_name, {})[size] = mask
            return mask
        
        # Threshold alpha: opaque pixels (>128) become the icon shape
        mask = alpha.point(lambda p: 255 if p > 128 else 0).convert("1")

        # Cache the result
        _icon_cache.setdefault(icon_name, {})[size] = mask
        return mask

    except Exception as exc:
        logger.error("Failed to load icon %s: %s", icon_name, exc)
        return None


def _draw_fallback_glyph(draw: ImageDraw.ImageDraw, glyph: str, cx: int, cy: int, r: int, fill: int) -> None:
    """
    Fallback geometric weather glyph when SVG icons are unavailable.
    Centered at (cx, cy) with radius r.
    """
    if glyph == "sun":
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)
        for angle in range(0, 360, 45):
            x1 = int(cx + (r * 0.6) * math.cos(math.radians(angle)))
            y1 = int(cy + (r * 0.6) * math.sin(math.radians(angle)))
            x2 = int(cx + (r * 1.3) * math.cos(math.radians(angle)))
            y2 = int(cy + (r * 1.3) * math.sin(math.radians(angle)))
            _draw_thick_line(draw, [(x1, y1), (x2, y2)], fill=fill, thickness=2)

    elif glyph == "cloud":
        draw.ellipse([cx - r, cy - int(r * 0.4), cx + r, cy + int(r * 0.6)], fill=fill)
        draw.ellipse([cx - int(r * 1.3), cy, cx - int(r * 0.2), cy + int(r * 0.9)], fill=fill)
        draw.ellipse([cx + int(r * 0.2), cy - int(r * 0.5), cx + int(r * 1.4), cy + int(r * 0.3)], fill=fill)

    elif glyph == "partly_cloudy":
        draw.ellipse([cx - r, cy - r, cx + r, cy + int(r * 0.2)], fill=fill)
        for angle in range(-60, 30, 45):
            x1 = int(cx + (r * 0.5) * math.cos(math.radians(angle)))
            y1 = int(cy + (r * 0.5) * math.sin(math.radians(angle)) - r * 0.2)
            x2 = int(cx + (r * 1.0) * math.cos(math.radians(angle)))
            y2 = int(cy + (r * 1.0) * math.sin(math.radians(angle)) - r * 0.2)
            _draw_thick_line(draw, [(x1, y1), (x2, y2)], fill=fill, thickness=2)

    elif glyph == "rain":
        draw.ellipse([cx - r, cy - int(r * 1.0), cx + r, cy], fill=fill)
        for dx in [-int(r * 0.6), 0, int(r * 0.6)]:
            _draw_thick_line(
                draw,
                [(cx + dx, cy + int(r * 0.3)), (cx + dx - int(r * 0.2), cy + r)],
                fill=fill, thickness=2,
            )

    elif glyph == "snow":
        draw.ellipse([cx - r, cy - int(r * 1.0), cx + r, cy], fill=fill)
        for dx in [-int(r * 0.6), 0, int(r * 0.6)]:
            s = int(r * 0.15)
            fy = cy + int(r * 0.5)
            draw.ellipse([cx + dx - s, fy - s, cx + dx + s, fy + s], fill=fill)

    elif glyph == "fog":
        for dy in [-int(r * 0.6), 0, int(r * 0.6)]:
            _draw_thick_line(
                draw,
                [(cx - r, cy + dy), (cx + r, cy + dy)],
                fill=fill, thickness=3,
            )

    elif glyph == "thunder":
        draw.ellipse([cx - r, cy - int(r * 1.0), cx + r, cy], fill=fill)
        points = [
            (cx + int(r * 0.2), cy + int(r * 0.2)),
            (cx - int(r * 0.2), cy + int(r * 0.6)),
            (cx + int(r * 0.1), cy + int(r * 0.6)),
            (cx - int(r * 0.1), cy + r),
        ]
        draw.polygon(points, fill=fill)


def _paste_icon(base_img: Image.Image, icon_name: str, cx: int, cy: int, size: int) -> bool:
    """
    Paste an icon centered at (cx, cy) on the base black buffer.
    Uses SVG mask pasting if cairosvg is available, else falls back to geometric glyph.
    Returns True if icon was successfully pasted, False otherwise.
    """
    mask = _load_icon_mask(icon_name, size)
    if mask is not None:
        x = cx - size // 2
        y = cy - size // 2
        # Paste COLOR_BLACK (0) where mask is active (255)
        base_img.paste(COLOR_BLACK, (x, y), mask)
        return True

    # Fallback to geometric glyph
    draw = ImageDraw.Draw(base_img)
    _draw_fallback_glyph(draw, icon_name, cx, cy, size // 2, COLOR_BLACK)
    return True


def _paste_icon_red(red_img: Image.Image, icon_name: str, cx: int, cy: int, size: int) -> bool:
    """
    Paste a RED icon centered at (cx, cy) on the red image buffer.
    Falls back to geometric glyph if cairosvg is unavailable.
    """
    mask = _load_icon_mask(icon_name, size)
    if mask is not None:
        x = cx - size // 2
        y = cy - size // 2
        # Paste COLOR_RED (0 in red buffer) where mask is active (255)
        red_img.paste(COLOR_RED, (x, y), mask)
        return True

    # Fallback to geometric glyph on red buffer
    draw = ImageDraw.Draw(red_img)
    _draw_fallback_glyph(draw, icon_name, cx, cy, size // 2, COLOR_RED)
    return True


def _condition_label_and_icon(code: int) -> Tuple[str, str]:
    """Return a human-readable condition label and icon name for a WMO code."""
    text, icon = WMO_CODES.get(code, (f"Unknown ({code})", "cloud"))
    return text, icon


def _get_local_time(timezone_str: str = "Europe/Paris") -> datetime:
    """Return the current local time in the configured timezone."""
    if sys.version_info >= (3, 9):
        try:
            return datetime.now(ZoneInfo(timezone_str))
        except (ZoneInfoNotFoundError, ValueError) as exc:
            logger.warning("Unknown timezone %r (%s); falling back to UTC", timezone_str, exc)
    elif pytz is not None:
        try:
            return datetime.now(pytz.timezone(timezone_str))
        except pytz.UnknownTimeZoneError as exc:
            logger.warning("Unknown timezone %r (%s); falling back to UTC", timezone_str, exc)
    return datetime.now(timezone.utc)


def _round_up_to_5min(dt: datetime) -> datetime:
    """Round datetime up to the next multiple of 5 minutes."""
    if dt.minute % 5 == 0 and dt.second == 0:
        return dt.replace(second=0, microsecond=0)
    new_minutes = (dt.minute // 5 + 1) * 5
    if new_minutes >= 60:
        return dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return dt.replace(minute=new_minutes % 60, second=0, microsecond=0)


def render_clock_region(
    timezone_str: str = "Europe/Paris",
    font_path: Optional[str] = None,
) -> Tuple[Image.Image, Image.Image, Tuple[int, int, int, int]]:
    """
    Render only the clock + date region for a partial e-paper refresh.

    Returns (black_img, red_img, region) where `region` is the (x0, y0, x1, y1)
    pixel box — matching the full-render clock block — so a caller can blit it
    via display_Partial(). NOTE: the bundled epd7in5b_V2 driver does expose
    init_part()/display_Partial(), but partial refresh on this 3-color panel is
    experimental and prone to red-channel ghosting; the main loop currently uses
    a fast full refresh instead. This helper is kept for that future path.
    """
    if not (font_path and os.path.isfile(font_path)):
        font_path = _default_font_path()
    if font_path and os.path.isfile(font_path):
        font_clock = _load_font(font_path, 96)
        font_hourly_time = _load_font(font_path, 20)
    else:
        font_clock = _load_font(None, 36)
        font_hourly_time = _load_font(None, 14)

    now_dt = _get_local_time(timezone_str)
    clock_display = now_dt.strftime("%H:%M")
    date_display = now_dt.strftime("%a, %b %d")

    # Region bounds matching full render layout
    margin = 15
    left_col_width = 560
    y_clock = margin + 5
    clock_height_region = _get_font_height(font_clock) + 5 + _get_font_height(font_hourly_time)

    region = (margin, y_clock, margin + left_col_width, y_clock + clock_height_region)
    rx, ry, rx2, ry2 = region
    rw = rx2 - rx
    rh = ry2 - ry

    black_img = Image.new("1", (rw, rh), COLOR_BG)
    red_img = Image.new("1", (rw, rh), COLOR_BG)
    draw_b = ImageDraw.Draw(black_img)

    _draw_centered_text(draw_b, clock_display, font_clock, rw // 2, 0, COLOR_BLACK)

    y_date = _get_font_height(font_clock) + 5
    _draw_centered_text(draw_b, date_display, font_hourly_time, rw // 2, y_date, COLOR_BLACK)

    return black_img, red_img, region


def render_weather(
    weather: Dict[str, Any],
    font_path: Optional[str] = None,
    stale: bool = False,
    timezone_str: str = "Europe/Paris",
    city_name: Optional[str] = None,
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

    # Fall back to a system TrueType font (e.g. DejaVu) before the bitmap default
    if not (font_path and os.path.isfile(font_path)):
        font_path = _default_font_path()

    # Font sizes
    if font_path and os.path.isfile(font_path):
        font_clock = _load_font(font_path, 96)          # clock display
        font_temp_large = _load_font(font_path, 72)     # current temperature
        font_icon_label = _load_font(font_path, 30)     # condition text
        font_detail = _load_font(font_path, 24)         # wind, feels like, etc
        font_hourly_temp = _load_font(font_path, 24)    # hourly temps
        font_hourly_time = _load_font(font_path, 20)    # hourly time labels
        font_forecast_day = _load_font(font_path, 24)   # day names in forecast
        font_forecast_temp = _load_font(font_path, 22)  # forecast temps
        font_footer = _load_font(font_path, 14)         # footer text (smaller)
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
    left_col_width = 560       # left column width (clock + hourly)
    divider_x = left_col_width + 5  # vertical separator between left/right
    right_col_x = divider_x + 10    # start of right column
    top_section_h = 320        # height of top section (horizontal divider y)
    forecast_bottom = HEIGHT - 35   # bottom of forecast columns
    footer_y = HEIGHT - 18     # tiny footer at bottom

    # ========================================================================
    # TOP LEFT: CLOCK (top-aligned)
    # ========================================================================
    y_clock = margin + 5

    # Display live local time rounded up to next 5-minute mark (update interval)
    now_dt = _round_up_to_5min(_get_local_time(timezone_str))
    clock_display = now_dt.strftime("%H:%M")
    date_display = now_dt.strftime("%a, %b %d")

    # Center the clock within the left column
    left_center_x = margin + left_col_width // 2
    _draw_centered_text(draw_b, clock_display, font_clock, left_center_x, y_clock, COLOR_BLACK)
    y_after_clock = y_clock + _get_font_height(font_clock) + 5

    # Build date line, optionally with city name
    if city_name:
        date_line = f"{date_display} — {city_name}"
    else:
        date_line = date_display
    _draw_centered_text(draw_b, date_line, font_hourly_time, left_center_x, y_after_clock, COLOR_BLACK)

    # Sunrise / Sunset below date (contextual)
    sunrise_time = weather.get("sunrise")
    sunset_time = weather.get("sunset")
    sun_y = y_after_clock + _get_font_height(font_hourly_time) + 10
    cur_hour_min = None
    if now_dt:
        cur_hour_min = now_dt.hour * 60 + now_dt.minute

    if sunrise_time and sunset_time and cur_hour_min is not None:
        sun_lines = []
        try:
            sr_h, sr_m = map(int, sunrise_time.split(":"))
            sr_minutes = sr_h * 60 + sr_m
            if abs(cur_hour_min - sr_minutes) <= 90:
                sun_lines.append(f"Sunrise {sunrise_time}")
        except (ValueError, AttributeError):
            pass
        try:
            ss_h, ss_m = map(int, sunset_time.split(":"))
            ss_minutes = ss_h * 60 + ss_m
            if 0 <= (ss_minutes - cur_hour_min) <= 90:
                sun_lines.append(f"Sunset {sunset_time}")
        except (ValueError, AttributeError):
            pass
        for line in sun_lines:
            _draw_centered_text(draw_b, line, font_hourly_time, left_center_x, sun_y, COLOR_BLACK)
            sun_y += _get_font_height(font_hourly_time) + 3

    # ========================================================================
    # TOP LEFT (below clock): HOURLY FORECAST STRIP (bottom-anchored)
    # ========================================================================
    hourly_forecast = weather.get("hourly_forecast", [])
    num_hours = len(hourly_forecast) if hourly_forecast else 0

    # Calculate total height of one hourly column (time + icon + temp)
    hourly_column_height = (_get_font_height(font_hourly_time) +   # time label
                            15 +                                   # spacing
                            20 +                                   # icon size
                            15 +                                   # spacing
                            _get_font_height(font_hourly_temp))    # temp

    # Anchor the hourly strip snug against the horizontal divider (only 4px gap)
    hourly_bottom = top_section_h - 4
    y_hourly_top = hourly_bottom - hourly_column_height + 30

    # Draw "HOURLY" label just above the anchored hourly strip items
    y_hourly_label = y_hourly_top - _get_font_height(font_hourly_time) - 30
    draw_b.text((margin, y_hourly_label), "HOURLY", font=font_hourly_time, fill=COLOR_BLACK)

    # Check for upcoming bad weather and display warning in red. Pass the live
    # local time so the countdown matches the on-screen clock (not the API snapshot).
    from weather_dashboard.weather import get_upcoming_bad_weather
    bad_weather = get_upcoming_bad_weather(
        weather, max_hours_ahead=2, now_dt=_get_local_time(timezone_str)
    )
    if bad_weather:
        minutes = bad_weather["minutes"]
        bw_text = f"{bad_weather['type']} in {minutes} min ({bad_weather['time']})"
        draw_r.text((margin + 5, y_hourly_label), bw_text, font=font_hourly_time, fill=COLOR_RED)

    # Calculate spacing for hourly items
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

        cx = x_base + hour_block_width // 2

        # Icon (centered at anchored position)
        icon_center_y = y_hourly_top + (_get_font_height(font_hourly_time) // 2)
        icon_size = 24
        if not _paste_icon(black_img, hour_icon, cx, icon_center_y, icon_size):
            black_img.putpixel((cx, icon_center_y), COLOR_BLACK)

        # Time label above icon
        _draw_centered_text(draw_b, hour_label, font_hourly_time, cx,
                            y_hourly_top - _get_font_height(font_hourly_time) - 4, COLOR_BLACK)

        # Temperature below icon
        temp_text = f"{hour_temp}\u00b0"
        _draw_centered_text(draw_b, temp_text, font_hourly_temp, cx,
                            icon_center_y + icon_size // 2 + 4, COLOR_BLACK)

    # ========================================================================
    # TOP RIGHT: CURRENT WEATHER
    # ========================================================================
    y_right = margin + 5

    # Large weather icon (centered in right column)
    right_col_width = WIDTH - right_col_x - margin
    icon_cx = right_col_x + right_col_width // 2
    icon_cy = y_right + 50
    icon_size_large = 80
    _paste_icon(black_img, icon_name, icon_cx, icon_cy, icon_size_large)

    # Large temperature (RED) below icon
    temp_y = icon_cy + icon_size_large // 2 - 10
    _draw_centered_text(draw_r, temp_str, font_temp_large, icon_cx, temp_y, COLOR_RED)

    # Condition text below temperature
    cond_y = temp_y + _get_font_height(font_temp_large) + 5
    _draw_centered_text(draw_b, condition_text, font_icon_label, icon_cx, cond_y, COLOR_BLACK)

    # Hi / Lo for today
    hi_lo_str = f"Hi {weather['today_high']:.0f}{unit_sym}   Lo {weather['today_low']:.0f}{unit_sym}"
    hilo_y = cond_y + _get_font_height(font_icon_label) + 8
    _draw_centered_text(draw_b, hi_lo_str, font_detail, icon_cx, hilo_y, COLOR_BLACK)

    # Wind speed
    wind_str = f"Wind: {cur['wind_speed']:.0f} km/h"
    wind_y = hilo_y + _get_font_height(font_detail) + 5
    _draw_centered_text(draw_b, wind_str, font_detail, icon_cx, wind_y, COLOR_BLACK)

    # Feels like
    feels_str = f"Feels like: {cur['feels_like']:.0f}{unit_sym}"
    feels_y = wind_y + _get_font_height(font_detail) + 5
    _draw_centered_text(draw_b, feels_str, font_detail, icon_cx, feels_y, COLOR_BLACK)

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

    strip_top = sep_y + 8
    num_days = len(forecast) if forecast else 0
    day_width = WIDTH // max(num_days, 1)

    for i, day in enumerate(forecast[:5]):
        x_center = i * day_width + day_width // 2
        y_pos = strip_top + 2
        day_label = day.get("weekday", "?")
        day_high = f"{day.get('high', '?'):.0f}{unit_sym}"
        day_low = f"{day.get('low', '?'):.0f}{unit_sym}"

        # Day abbreviation (centered)
        _draw_centered_text(draw_b, day_label, font_forecast_day, x_center, y_pos, COLOR_BLACK)

        # Forecast icon (compressed vertically by ~1/3)
        _, day_icon = _condition_label_and_icon(day.get("weather_code", 0))
        icon_center_y = y_pos + _get_font_height(font_forecast_day) + 20
        icon_size_medium = 30

        is_precip = day_icon in ("rain", "snow", "thunder")
        if is_precip:
            # Red icons for precipitation days (uses special red buffer)
            _paste_icon_red(red_img, day_icon, x_center, icon_center_y, icon_size_medium)
        else:
            _paste_icon(black_img, day_icon, x_center, icon_center_y, icon_size_medium)

        # High temp (red accent) below icon
        hi_y = icon_center_y + icon_size_medium // 2 + 2
        _draw_centered_text(draw_r, day_high, font_forecast_temp, x_center, hi_y, COLOR_RED)

        # Low temp below high (tighter gap)
        lo_y = hi_y + _get_font_height(font_forecast_temp) + 1
        _draw_centered_text(draw_b, day_low, font_forecast_temp, x_center, lo_y, COLOR_BLACK)

        # Column divider (not after last column)
        if i < num_days - 1 and i < 5:
            div_x = (i + 1) * day_width
            draw_b.line([(div_x, strip_top), (div_x, forecast_bottom)], fill=COLOR_BLACK)

    # ========================================================================
    # FOOTER: Source + Last Updated
    # ========================================================================
    _draw_thick_line(draw_b, [(0, footer_y - 10), (WIDTH, footer_y - 10)],
                    fill=COLOR_BLACK, thickness=1)

    footer_left = "Source: Open-Meteo"
    draw_b.text((margin, footer_y), footer_left, font=font_footer, fill=COLOR_BLACK)

    # Timestamp on the right
    now_utc_str = datetime.now(timezone.utc).strftime("Updated: %Y-%m-%d %H:%M UTC")
    ftw = _get_text_width(font_footer, now_utc_str)
    draw_b.text((WIDTH - margin - ftw, footer_y), now_utc_str, font=font_footer, fill=COLOR_BLACK)

    # Stale data indicator (if needed)
    if stale:
        _draw_centered_text(draw_r, "!! STALE DATA !!", font_detail, WIDTH // 2, footer_y, COLOR_RED)

    return black_img, red_img


def render_blank() -> Tuple[Image.Image, Image.Image]:
    """Return a pair of blank (all-white) images."""
    b = Image.new("1", (WIDTH, HEIGHT), COLOR_BG)
    r = Image.new("1", (WIDTH, HEIGHT), COLOR_BG)
    return b, r


def compose_rgb(black_img: Image.Image, red_img: Image.Image) -> Image.Image:
    """
    Composite the black + red 1-bit buffers into one RGB image that looks like
    the physical panel (white background, black ink, red ink).

    Useful for previewing output on a machine without the display attached.
    """
    preview = Image.new("RGB", (WIDTH, HEIGHT), (255, 255, 255))
    # In mode '1', ink pixels are 0; build masks that are 255 where ink is present.
    black_mask = black_img.point(lambda p: 255 if p == COLOR_BLACK else 0).convert("1")
    red_mask = red_img.point(lambda p: 255 if p == COLOR_RED else 0).convert("1")
    preview.paste((0, 0, 0), (0, 0), black_mask)
    preview.paste((210, 0, 0), (0, 0), red_mask)  # red drawn on top
    return preview
