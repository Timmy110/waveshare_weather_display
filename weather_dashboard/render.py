#!/usr/bin/env python3
"""Render weather data to two PIL images (black + red buffers) for e-Ink display."""

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

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

from weather_dashboard.icons import dither_mask, draw_icon

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

_HERE = os.path.dirname(os.path.abspath(__file__))
_FONT_DIR = os.path.join(_HERE, "..", "resources", "fonts")
_JOST = {
    "regular": "Jost-Regular.ttf",
    "medium": "Jost-Medium.ttf",
    "semibold": "Jost-SemiBold.ttf",
}


# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------

def _fallback_font_path() -> Optional[str]:
    """Single-face fallback when the bundled Jost family isn't available."""
    candidates = [
        os.path.join(_HERE, "..", "resources", "pic", "Font.ttc"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def _font_loader(font_path: Optional[str]):
    """
    Return font(size, weight="regular") -> ImageFont.

    Uses the bundled Jost family (regular / medium / semibold) unless the user
    configured `font_path`, in which case that single face is used and heavier
    weights are faked with a 1px stroke (see _text).
    """
    jost_ok = all(os.path.isfile(os.path.join(_FONT_DIR, f)) for f in _JOST.values())
    single = font_path if (font_path and os.path.isfile(font_path)) else None
    if not single and not jost_ok:
        single = _fallback_font_path()
        logger.warning("Bundled Jost fonts missing; falling back to %s", single or "bitmap font")
    cache: Dict[Tuple[int, str], Any] = {}

    def font(size: int, weight: str = "regular"):
        key = (size, weight)
        if key in cache:
            return cache[key]
        try:
            if single:
                f = ImageFont.truetype(single, size)
                f.fake_bold = weight != "regular"
            elif jost_ok:
                f = ImageFont.truetype(os.path.join(_FONT_DIR, _JOST[weight]), size)
            else:
                f = ImageFont.load_default()
        except Exception as exc:
            logger.warning("Font load failed (%s, %d): %s", weight, size, exc)
            f = ImageFont.load_default()
        cache[key] = f
        return f

    return font


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _condition_label_and_icon(code: int) -> Tuple[str, str]:
    """Return a human-readable condition label and icon name for a WMO code."""
    text, icon = WMO_CODES.get(code, (f"Unknown ({code})", "cloud"))
    return text, icon


def condition_label(code: Optional[int]) -> str:
    """Public helper: human-readable label for a WMO weather code."""
    if code is None:
        return "?"
    return _condition_label_and_icon(code)[0]


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


# Day icons that have a night variant (precipitation/fog/overcast look the same).
_NIGHT_ICONS = {"sun": "moon", "partly_cloudy": "partly_cloudy_night"}


def _is_night(hhmm: Optional[str], sunrise: Optional[str], sunset: Optional[str]) -> bool:
    """True if local "HH:MM" falls before sunrise or at/after sunset (zero-padded compare)."""
    if not (hhmm and sunrise and sunset):
        return False
    return hhmm < sunrise or hhmm >= sunset


def _icon_for(code: int, night: bool) -> str:
    _, icon = _condition_label_and_icon(code)
    return _NIGHT_ICONS.get(icon, icon) if night else icon


def _num(value) -> str:
    """Whole-number display. round() returns an int, so -0.3 shows "0", not "-0"."""
    return str(round(value or 0))


def _format_date(dt: datetime) -> str:
    """'Monday, 23 November' — day name + day-first date, no leading zero."""
    return f"{dt.strftime('%A')}, {dt.day} {dt.strftime('%B')}"


_COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def _compass(degrees: Optional[float]) -> str:
    if degrees is None:
        return ""
    return _COMPASS[int((degrees % 360) / 45 + 0.5) % 8]


def _visibility(metres: Optional[float]) -> Tuple[str, str]:
    if metres is None:
        return "-", ""
    km = metres / 1000
    if km >= 10:
        return f"{km:.0f}", "km"
    return f"{km:.1f}", "km"


def _bad_weather_text(weather: Dict[str, Any], now_local: datetime) -> Optional[str]:
    """
    Short precipitation notice shown under the temperature, or None. If it's
    already raining/snowing, say until when; otherwise name the next event and
    when it starts. Absolute times (not "in N min") because the panel only
    refreshes periodically.
    """
    from weather_dashboard.weather import get_active_bad_weather, get_upcoming_bad_weather

    active = get_active_bad_weather(weather, now_dt=now_local)
    if active:
        return f"{active['type']} until {active['ends']}" if active["ends"] else active["type"]
    upcoming = get_upcoming_bad_weather(weather, max_hours_ahead=2, now_dt=now_local)
    if upcoming:
        when = "now" if upcoming["minutes"] <= 0 else f"from {upcoming['time']}"
        text = f"{upcoming['type']} {when}"
        if upcoming.get("probability") is not None:
            text += f" · {upcoming['probability']}%"
        return text
    return None


# ---------------------------------------------------------------------------
# Text drawing — positioned by INK bounds rather than the font's line box.
# PIL draws text with an internal top bearing, so `draw.text((x, y))` puts the
# glyphs a few pixels below `y`, by a different amount per size. Aligning by
# ink lets mixed sizes (e.g. "21" + "°C") share a clean top or baseline.
# ---------------------------------------------------------------------------

def _ink_box(font, text) -> Tuple[int, int, int, int]:
    """(left, top, right, bottom) ink box of `text` relative to the draw origin."""
    try:
        return font.getbbox(text)
    except AttributeError:  # very old Pillow
        w, h = font.getsize(text)
        return 0, 0, w, h


def _width(font, text) -> int:
    l, _, r, _ = _ink_box(font, text)
    return r - l


def _cap_height(font) -> int:
    _, t, _, b = _ink_box(font, "H")
    return b - t


def _text(draw, text, font, x, y, fill, align="left") -> Tuple[int, int]:
    """
    Draw `text` with its ink top at `y`; `x` is the left edge, centre or right
    edge per `align`. Returns ink (width, height).
    """
    l, t, r, b = _ink_box(font, text)
    w, h = r - l, b - t
    ox = x - w // 2 if align == "center" else x - w if align == "right" else x
    kwargs = {"stroke_width": 1, "stroke_fill": fill} if getattr(font, "fake_bold", False) else {}
    try:
        draw.text((ox - l, y - t), text, font=font, fill=fill, **kwargs)
    except TypeError:  # Pillow < 6.2 has no stroke support
        draw.text((ox - l, y - t), text, font=font, fill=fill)
    return w, h


def _text_baseline(draw, text, font, x, baseline, fill) -> int:
    """Draw `text` left-aligned on a shared baseline (for value + small unit). Returns advance."""
    asc, _ = font.getmetrics()
    l, _, r, _ = _ink_box(font, text)
    kwargs = {"stroke_width": 1, "stroke_fill": fill} if getattr(font, "fake_bold", False) else {}
    try:
        draw.text((x - l, baseline - asc), text, font=font, fill=fill, **kwargs)
    except TypeError:
        draw.text((x - l, baseline - asc), text, font=font, fill=fill)
    return r - l


def _fit_font(make_font, text, max_width, size, min_size):
    """Largest font from `size` down to `min_size` whose ink width fits."""
    f = make_font(size)
    while size > min_size and _width(f, text) > max_width:
        size -= 1
        f = make_font(size)
    return f


def _rounded_rect(draw, box, radius, fill=None, outline=None):
    try:
        draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=1)
    except AttributeError:  # Pillow < 8.2
        draw.rectangle(box, fill=fill, outline=outline)


# ---------------------------------------------------------------------------
# Layout grid (800 x 480)
# ---------------------------------------------------------------------------
MARGIN = 20

HERO_ICON = (112, 172, 150)          # cx, cy, size
TEMP_CX = 300                         # centre of temperature block
GRID_TOP = 100                        # centre of first metrics row
GRID_ROW = 47                         # metrics row pitch
GRID_COLS = ((436, 522), (626, 716))  # (icon cx, text centre x) per column

CHART = (48, 280, 744, 330)           # plot area x0, y0, x1, y1
CARDS_TOP = 356
CARD_H = 116
CARD_GAP = 10


def render_weather(
    weather: Dict[str, Any],
    font_path: Optional[str] = None,
    stale: bool = False,
    timezone_str: str = "Europe/Paris",
    city_name: Optional[str] = None,
) -> Tuple[Image.Image, Image.Image]:
    """
    Render the weather dashboard as an image pair (black_buffer, red_buffer).

    Layout (landscape 800x480):
      - Header:  location (large, centred) with the day + date beneath
      - Now:     big condition icon | temperature, feels-like, rain notice |
                 2x4 metrics grid (sun times, wind, humidity, pressure, UV,
                 visibility, air quality)
      - Chart:   next 24 h — temperature line (red) over rain-probability bars
      - Cards:   next 7 days — day, icon, high / low

    Red marks the sun and warmth (sun icons, the temperature line, UV) and
    alerts; greys are rendered as ordered dither.

    Small text uses Medium or heavier: on a 1-bit panel a Regular weight at
    12-19px gets 1px stems that rasterise unevenly and look soft.

    Returns two PIL images in mode '1' (1-bit), ready for epd.getbuffer().
    """
    font = _font_loader(font_path)

    black_img = Image.new("1", (WIDTH, HEIGHT), COLOR_BG)
    red_img = Image.new("1", (WIDTH, HEIGHT), COLOR_BG)
    draw_b = ImageDraw.Draw(black_img)
    draw_r = ImageDraw.Draw(red_img)

    cur = weather["current"]
    unit_letter = "F" if weather.get("unit") == "fahrenheit" else "C"
    now_local = _get_local_time(timezone_str)
    sunrise, sunset = weather.get("sunrise"), weather.get("sunset")

    # ========================================================================
    # HEADER
    # ========================================================================
    title = city_name or ""
    if title:
        f_title = _fit_font(lambda s: font(s, "semibold"), title, WIDTH - 200, 32, 22)
        _text(draw_b, title, f_title, WIDTH // 2, 14, COLOR_BLACK, align="center")
    _text(draw_b, _format_date(now_local), font(19, "medium"), WIDTH // 2, 54 if title else 22,
          COLOR_BLACK, align="center")

    # Freshness stamp, tucked in the corner
    f_stamp = font(12, "medium")
    stamp = f"Updated {now_local.strftime('%H:%M')}"
    sw, _ = _text(draw_b, stamp, f_stamp, WIDTH - 12, 10, COLOR_BLACK, align="right")
    if stale:
        _text(draw_r, "Offline", font(12, "semibold"), WIDTH - 12 - sw - 8, 10, COLOR_RED, align="right")

    # ========================================================================
    # NOW: icon | temperature | metrics grid
    # ========================================================================
    hero_night = _is_night(now_local.strftime("%H:%M"), sunrise, sunset)
    cx, cy, size = HERO_ICON
    draw_icon(black_img, red_img, _icon_for(cur["weather_code"], hero_night), cx, cy, size)

    f_temp = font(96)
    f_unit = font(30)
    temp_s = _num(cur["temperature"])
    unit_s = f"°{unit_letter}"
    tw, uw = _width(f_temp, temp_s), _width(f_unit, unit_s)
    t_left = TEMP_CX - (tw + 4 + uw) // 2
    temp_top = 122
    _, th = _text(draw_b, temp_s, f_temp, t_left, temp_top, COLOR_BLACK)
    _text(draw_b, unit_s, f_unit, t_left + tw + 4, temp_top, COLOR_BLACK)

    condition, _ = _condition_label_and_icon(cur["weather_code"])
    y = temp_top + th + 16
    f_sub = font(18, "medium")
    _, h = _text(draw_b, f"Feels like {_num(cur['feels_like'])}°", f_sub, TEMP_CX, y,
                 COLOR_BLACK, align="center")
    y += h + 10
    f_cond = _fit_font(lambda s: font(s, "semibold"), condition, 200, 17, 13)
    _, h = _text(draw_b, condition, f_cond, TEMP_CX, y, COLOR_BLACK, align="center")

    alert = _bad_weather_text(weather, now_local)
    if alert:
        f_alert = _fit_font(lambda s: font(s, "medium"), alert, 210, 16, 12)
        _text(draw_r, alert, f_alert, TEMP_CX, y + h + 9, COLOR_RED, align="center")

    aqi = weather.get("air_quality")
    from weather_dashboard.weather import aqi_label
    vis_v, vis_u = _visibility(cur.get("visibility"))
    uv = cur.get("uv_index")
    metrics = [
        ("sunrise", "Sunrise", sunrise or "-", "", {}),
        ("sunset", "Sunset", sunset or "-", "", {}),
        ("wind", "Wind", _num(cur.get("wind_speed")), f"km/h {_compass(cur.get('wind_direction'))}".strip(), {}),
        ("humidity", "Humidity", _num(cur.get("humidity")) if cur.get("humidity") is not None else "-", "%", {}),
        ("pressure", "Pressure", _num(cur.get("pressure")) if cur.get("pressure") is not None else "-", "hPa", {}),
        ("uv", "UV Index", f"{uv:.1f}" if uv is not None else "-", "", {}),
        ("visibility", "Visibility", vis_v, vis_u, {}),
        ("air_quality", "Air Quality", str(aqi) if aqi is not None else "-", aqi_label(aqi), {"value": aqi}),
    ]
    f_label, f_value, f_vunit = font(14, "medium"), font(21, "semibold"), font(12, "medium")
    for i, (icon, label, value, unit, kw) in enumerate(metrics):
        icon_cx, text_cx = GRID_COLS[i % 2]
        row_cy = GRID_TOP + (i // 2) * GRID_ROW
        draw_icon(black_img, red_img, icon, icon_cx, row_cy + 2, 32, **kw)
        _text(draw_b, label, f_label, text_cx, row_cy - 16, COLOR_BLACK, align="center")
        # value + small unit share a baseline, centred as a pair
        vw = _width(f_value, value)
        uw = _width(f_vunit, unit) + 4 if unit else 0
        x = text_cx - (vw + uw) // 2
        baseline = row_cy + 20
        x += _text_baseline(draw_b, value, f_value, x, baseline, COLOR_BLACK) + 4
        if unit:
            _text_baseline(draw_b, unit, f_vunit, x, baseline, COLOR_BLACK)

    # ========================================================================
    # CHART: next 24 h
    # ========================================================================
    _draw_chart(black_img, red_img, draw_b, draw_r, weather.get("hourly_chart") or [], font)

    # ========================================================================
    # CARDS: next 7 days
    # ========================================================================
    days = (weather.get("forecast") or [])[:7]
    if days:
        n = len(days)
        card_w = (WIDTH - 2 * MARGIN - (n - 1) * CARD_GAP) / n
        f_day, f_range = font(18, "medium"), font(15, "medium")
        for i, d in enumerate(days):
            x0 = int(MARGIN + i * (card_w + CARD_GAP))
            x1 = int(x0 + card_w)
            mid = (x0 + x1) // 2
            _rounded_rect(draw_b, [x0, CARDS_TOP, x1, CARDS_TOP + CARD_H], 9, outline=COLOR_BLACK)
            _text(draw_b, d.get("weekday", "?"), f_day, mid, CARDS_TOP + 10, COLOR_BLACK, align="center")
            draw_icon(black_img, red_img, _icon_for(d.get("weather_code", 0), night=False),
                      mid, CARDS_TOP + 60, 56)
            _text(draw_b, f"{_num(d.get('high'))}° / {_num(d.get('low'))}°", f_range, mid,
                  CARDS_TOP + CARD_H - 23, COLOR_BLACK, align="center")

    return black_img, red_img


def _draw_chart(black_img, red_img, draw_b, draw_r, series: List[Dict[str, Any]], font) -> None:
    """24 h chart: rain-probability bars (grey) under a red temperature line."""
    if len(series) < 2:
        return
    x0, y0, x1, y1 = CHART
    h = y1 - y0
    n = len(series) - 1
    step = (x1 - x0) / n

    temps = [p.get("temperature") or 0 for p in series]
    t_min, t_max = min(temps), max(temps)
    lo, hi = round(t_min) - 1, round(t_max) + 1   # 1° headroom so the line never touches the edges

    def ty(t):
        return y1 - (t - lo) / (hi - lo) * h

    pts = [(x0 + i * step, ty(t)) for i, t in enumerate(temps)]

    # Light red wash under the temperature line
    area = Image.new("L", (WIDTH, HEIGHT), 0)
    ImageDraw.Draw(area).polygon([(x0, y1)] + pts + [(x1, y1)], fill=255)
    wash = Image.composite(dither_mask(0.125, 0, 0, WIDTH, HEIGHT), Image.new("L", (WIDTH, HEIGHT), 0), area)
    red_img.paste(0, (0, 0), wash)

    # Rain-probability bars, one per hour, occluding the wash
    for i in range(n):
        p = series[i].get("probability") or 0
        if p <= 0:
            continue
        bx0, bx1 = int(x0 + i * step) + 1, int(x0 + (i + 1) * step) - 1
        by0 = int(y1 - p / 100 * h)
        bw, bh = bx1 - bx0, y1 - by0
        if bw <= 0 or bh <= 0:
            continue
        red_img.paste(255, (bx0, by0, bx1, y1))
        black_img.paste(0, (bx0, by0), dither_mask(0.5, bx0, by0, bw, bh))
        draw_b.line([(bx0, by0), (bx1 - 1, by0)], fill=COLOR_BLACK)

    # Temperature line on top (clear black underneath so red stays clean)
    draw_b.line(pts, fill=COLOR_BG, width=4)
    draw_r.line(pts, fill=COLOR_RED, width=2)

    # Axes labels: temperature range left, probability range right
    f_axis = font(12, "medium")
    _text(draw_b, f"{hi}°", f_axis, x0 - 8, y0 - 2, COLOR_BLACK, align="right")
    _text(draw_b, f"{lo}°", f_axis, x0 - 8, y1 - 9, COLOR_BLACK, align="right")
    _text(draw_b, "100%", f_axis, x1 + 8, y0 - 2, COLOR_BLACK)
    _text(draw_b, "0%", f_axis, x1 + 8, y1 - 9, COLOR_BLACK)
    draw_b.line([(x0, y1 + 1), (x1, y1 + 1)], fill=COLOR_BLACK)

    # Hour labels every 3 h
    for i in range(0, n + 1, 3):
        t = series[i].get("time", "")
        label = t[11:13] + "h" if len(t) >= 13 else ""
        _text(draw_b, label, f_axis, int(x0 + i * step), y1 + 7, COLOR_BLACK, align="center")


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
