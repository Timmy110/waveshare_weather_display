"""Unit tests for weather fetching/parsing logic (no hardware, no network)."""

import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from weather_dashboard.weather import (  # noqa: E402
    _parse_openmeto_response,
    get_upcoming_bad_weather,
)


def _sample_response():
    """A minimal Open-Meteo-shaped payload using the documented `*_2m` names."""
    hourly_times = [f"2024-01-15T{h:02d}:00" for h in range(24)]
    return {
        "current": {
            "time": "2024-01-15T14:30",
            "temperature_2m": 7.4,
            "apparent_temperature": 4.1,
            "wind_speed_10m": 12.0,
            "weather_code": 3,
        },
        "hourly": {
            "time": hourly_times,
            "temperature_2m": [float(i) for i in range(24)],
            "weather_code": [0] * 15 + [61] + [0] * 8,  # rain at 15:00
        },
        "daily": {
            "time": [f"2024-01-{15 + i:02d}" for i in range(6)],
            "weather_code": [3, 61, 0, 2, 80, 75],
            "temperature_2m_max": [8, 9, 10, 11, 12, 6],
            "temperature_2m_min": [2, 3, 1, 4, 5, -1],
            "sunrise": [f"2024-01-{15 + i:02d}T08:00" for i in range(6)],
            "sunset": [f"2024-01-{15 + i:02d}T17:30" for i in range(6)],
        },
    }


def test_parse_uses_temperature_2m_keys():
    w = _parse_openmeto_response(_sample_response(), "celsius")
    assert w["current"]["temperature"] == 7.4
    assert w["current"]["feels_like"] == 4.1
    assert w["current"]["wind_speed"] == 12.0
    assert w["unit"] == "celsius"


def test_parse_builds_five_forecast_days_skipping_today():
    w = _parse_openmeto_response(_sample_response(), "celsius")
    assert len(w["forecast"]) == 5
    # First forecast entry is the day *after* today.
    assert w["forecast"][0]["high"] == 9
    assert w["sunrise"] == "08:00"
    assert w["sunset"] == "17:30"


def test_parse_hourly_keeps_full_iso_timestamp():
    w = _parse_openmeto_response(_sample_response(), "celsius")
    first = w["hourly_forecast"][0]
    assert first["time"] == "2024-01-15T15:00:00"
    assert first["hour"] == "15:00"


def test_bad_weather_uses_supplied_live_time():
    """Countdown is measured from now_dt, not the (possibly stale) API snapshot."""
    w = _parse_openmeto_response(_sample_response(), "celsius")
    bw = get_upcoming_bad_weather(w, max_hours_ahead=2, now_dt=datetime(2024, 1, 15, 14, 30))
    assert bw is not None
    assert bw["minutes"] == 30
    assert bw["time"] == "15:00"
    assert "rain" in bw["type"].lower()


def test_bad_weather_detected_across_midnight():
    """Regression: rain in the early hours of the next day must not be skipped."""
    data = _sample_response()
    data["hourly"] = {
        "time": ["2024-01-15T23:00", "2024-01-16T00:00", "2024-01-16T01:00"],
        "temperature_2m": [5, 4, 3],
        "weather_code": [0, 61, 0],  # rain at 00:00 tomorrow
    }
    data["current"]["time"] = "2024-01-15T23:00"
    w = _parse_openmeto_response(data, "celsius")
    bw = get_upcoming_bad_weather(w, max_hours_ahead=2, now_dt=datetime(2024, 1, 15, 23, 30))
    assert bw is not None
    assert bw["minutes"] == 30
    assert bw["time"] == "00:00"


def test_bad_weather_none_when_clear():
    data = _sample_response()
    data["hourly"]["weather_code"] = [0] * 24  # all clear
    w = _parse_openmeto_response(data, "celsius")
    assert get_upcoming_bad_weather(w, max_hours_ahead=2, now_dt=datetime(2024, 1, 15, 14, 30)) is None


def test_bad_weather_outside_window_ignored():
    """Rain 3h away with a 2h window should not warn."""
    w = _parse_openmeto_response(_sample_response(), "celsius")
    # now=12:00, rain at 15:00 == 180 min > 120 min window
    assert get_upcoming_bad_weather(w, max_hours_ahead=2, now_dt=datetime(2024, 1, 15, 12, 0)) is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
