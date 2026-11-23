"""Unit tests for render helpers (no hardware, no network)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from weather_dashboard.render import _icon_for, _is_night, _num  # noqa: E402


def _has_ink(img):
    """True if a mode-'1' panel buffer has any ink (0) pixels."""
    return img.getextrema()[0] == 0


def test_is_night_boundaries():
    assert _is_night("05:00", "08:14", "16:50")
    assert not _is_night("08:14", "08:14", "16:50")
    assert not _is_night("12:00", "08:14", "16:50")
    assert _is_night("16:50", "08:14", "16:50")
    assert _is_night("23:00", "08:14", "16:50")


def test_is_night_missing_sun_times_defaults_to_day():
    assert not _is_night("23:00", None, "16:50")
    assert not _is_night(None, "08:14", "16:50")


def test_night_icon_variants():
    assert _icon_for(0, night=True) == "moon"
    assert _icon_for(2, night=True) == "partly_cloudy_night"
    assert _icon_for(0, night=False) == "sun"
    # Precipitation / overcast have no night variant.
    assert _icon_for(63, night=True) == "rain"
    assert _icon_for(3, night=True) == "cloud"


def test_num_has_no_negative_zero():
    assert _num(-0.3) == "0"
    assert _num(-0.6) == "-1"
    assert _num(None) == "0"


def test_every_icon_draws_without_error():
    from PIL import Image
    from weather_dashboard.icons import _ICONS, draw_icon

    for kind in _ICONS:
        b = Image.new("1", (800, 480), 255)
        r = Image.new("1", (800, 480), 255)
        draw_icon(b, r, kind, 100, 100, 64, value=50)
        assert _has_ink(b) or _has_ink(r), kind


def test_dither_is_aligned_to_panel_grid():
    from weather_dashboard.icons import dither_mask

    whole = dither_mask(0.5, 0, 0, 16, 16)
    part = dither_mask(0.5, 5, 6, 8, 8)
    assert part.tobytes() == whole.crop((5, 6, 13, 14)).tobytes()


def test_compass_and_visibility_formatting():
    from weather_dashboard.render import _compass, _visibility

    assert _compass(0) == "N" and _compass(109) == "E" and _compass(350) == "N"
    assert _compass(None) == ""
    assert _visibility(4760) == ("4.8", "km")
    assert _visibility(24000) == ("24", "km")


def test_full_render_produces_both_planes():
    from weather_dashboard.render import render_weather

    weather = {
        "current": {"temperature": 7.4, "feels_like": 4.1, "wind_speed": 12, "wind_direction": 200,
                    "weather_code": 2, "humidity": 80, "pressure": 1012, "visibility": 20000,
                    "uv_index": 1.2, "local_time": "2024-01-15T14:30:00"},
        "hourly_forecast": [], "minutely_forecast": [],
        "hourly_chart": [{"time": f"2024-01-15T{h % 24:02d}:00:00", "temperature": h % 7,
                          "probability": (h * 13) % 100} for h in range(14, 39)],
        "today_high": 9, "today_low": 2, "sunrise": "08:00", "sunset": "17:30",
        "forecast": [{"weekday": d, "weather_code": c, "high": 9, "low": 2}
                     for d, c in zip(["Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Mon"],
                                     [0, 2, 3, 61, 71, 95, 45])],
        "air_quality": 30, "unit": "celsius",
    }
    black, red = render_weather(weather, city_name="Brussels")
    assert black.size == red.size == (800, 480)
    assert _has_ink(black) and _has_ink(red)
