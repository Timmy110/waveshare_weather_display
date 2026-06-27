#!/usr/bin/env python3
"""Fetch weather data from Open-Meteo API."""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

import requests

logger = logging.getLogger(__name__)


def fetch_weather(
    latitude: float,
    longitude: float,
    timezone: str,
    temperature_unit: str,
    timeout: int = 10,
) -> Optional[Dict[str, Any]]:
    """
    Fetch current weather + 5-day forecast from Open-Meteo.

    Returns a dict with the structure expected by the renderer, or None on failure.
    """
    if temperature_unit == "fahrenheit":
        unit = "fahrenheit"
    else:
        unit = "celsius"

    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "timezone": timezone,
        # Use the documented `temperature_2m` names (bare `temperature` is only a
        # legacy alias and is not guaranteed by the API).
        "current": "temperature_2m,apparent_temperature,wind_speed_10m,weather_code",
        "hourly": "temperature_2m,weather_code",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset",
        "temperature_unit": unit,
        # We want today + 5 more days = 6 days from API (skip today for 5 forecast days)
        "forecast_days": 6,
    }

    try:
        logger.info("Fetching weather from Open-Meteo ...")
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        logger.error("Open-Meteo request failed: %s", exc)
        return None
    except ValueError as exc:
        logger.error("Failed to parse Open-Meteo JSON response: %s", exc)
        return None

    try:
        result = _parse_openmeto_response(data, unit)
    except (KeyError, IndexError, TypeError) as exc:
        logger.error("Malformed Open-Meteo response: %s", exc)
        return None

    logger.info(
        "Weather fetched OK — temp=%.1f°%s, code=%s",
        result["current"]["temperature"],
        "F" if unit == "fahrenheit" else "C",
        result["current"]["weather_code"],
    )
    return result


# WMO weather codes that indicate "bad weather" (precipitation/thunder)
BAD_WEATHER_CODES = {
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight showers",
    81: "Moderate showers",
    82: "Violent showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Severe thunderstorm",
}


def get_upcoming_bad_weather(
    weather: Dict[str, Any],
    max_hours_ahead: int = 2,
    now_dt: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """
    Check hourly forecast for bad weather within the next `max_hours_ahead` hours.

    `now_dt` should be the live local time; pass it from the caller so the
    countdown matches the on-screen clock rather than the (possibly stale) API
    snapshot. Falls back to the cached `current.local_time` if not supplied.

    Returns None if no bad weather expected, otherwise a dict like:
        {
            "type": "Rain",           # human-readable type (title case)
            "minutes": 25,           # minutes until it starts
            "time": "18:35",         # HH:MM when it starts
        }
    """
    hourly = weather.get("hourly_forecast", [])
    if not hourly:
        return None

    if now_dt is None:
        now_str = weather.get("current", {}).get("local_time")
        if not now_str:
            return None
        try:
            now_dt = datetime.fromisoformat(now_str)
        except (ValueError, TypeError):
            return None

    # Compare on naive local wall-clock time (hourly timestamps are naive local).
    now_dt = now_dt.replace(tzinfo=None)

    for hour_data in hourly:
        code = hour_data.get("weather_code", 0)
        if code not in BAD_WEATHER_CODES:
            continue

        # Prefer the full ISO timestamp; fall back to legacy HH:MM entries.
        time_iso = hour_data.get("time")
        try:
            if time_iso:
                hour_full = datetime.fromisoformat(time_iso)
            else:
                hour_dt = datetime.strptime(hour_data.get("hour", ""), "%H:%M")
                hour_full = hour_dt.replace(
                    year=now_dt.year, month=now_dt.month, day=now_dt.day
                )
        except (ValueError, TypeError):
            continue

        # Skip hours already in the past.
        if hour_full < now_dt:
            continue

        total_minutes = int((hour_full - now_dt).total_seconds() / 60)
        if total_minutes <= max_hours_ahead * 60:
            return {
                "type": BAD_WEATHER_CODES[code].capitalize(),
                "minutes": total_minutes,
                "time": hour_full.strftime("%H:%M"),
            }

    return None


def _parse_openmeto_response(data: Dict[str, Any], unit: str) -> Dict[str, Any]:
    """Convert the raw Open-Meteo JSON into our internal weather dict."""

    current = data["current"]
    daily = data["daily"]
    hourly = data.get("hourly", {})

    # Parse local time from current time field (API returns timezone-aware string)
    local_time_str = current.get("time", "")
    local_time = None
    if local_time_str:
        try:
            # Format: "2024-01-15T14:30" or similar
            local_time = datetime.strptime(local_time_str, "%Y-%m-%dT%H:%M")
        except ValueError:
            pass

    # Build hourly forecast — select next ~8 hours starting from current hour
    hourly_forecast = []
    if hourly.get("time") and hourly.get("temperature_2m"):
        now_hour = None
        if local_time:
            now_hour = local_time.hour

        # Find the index of the closest future hour
        start_idx = 0
        for i, t in enumerate(hourly["time"]):
            h_dt = datetime.strptime(t, "%Y-%m-%dT%H:%M")
            if h_dt.hour >= (now_hour or 0):
                start_idx = i
                break

        # Take up to 8 hourly slots starting from next hour (skip current)
        for i in range(start_idx + 1, min(start_idx + 9, len(hourly["time"]))):
            t_str = hourly["time"][i]
            h_dt = datetime.strptime(t_str, "%Y-%m-%dT%H:%M")
            hourly_forecast.append({
                # Full ISO timestamp for correct cross-midnight comparison; `hour`
                # is the display-only HH:MM label.
                "time": h_dt.isoformat(),
                "hour": h_dt.strftime("%H:%M"),
                "temperature": hourly["temperature_2m"][i],
                "weather_code": hourly["weather_code"][i],
            })

    # Build forecast list (5 days, skip today if we already show it in current)
    forecast = []
    time_strs = daily["time"]  # UTC date strings like "2024-01-15"

    for i in range(1, min(6, len(time_strs))):  # Start from index 1 to skip today
        dt = datetime.strptime(time_strs[i], "%Y-%m-%d").date()
        forecast.append({
            "date": dt.isoformat(),
            "weekday": dt.strftime("%a"),  # Mon, Tue, etc.
            "weather_code": daily["weather_code"][i],
            "high": daily["temperature_2m_max"][i],
            "low": daily["temperature_2m_min"][i],
        })

    # Parse today's sunrise/sunset times
    sunrise_str = daily.get("sunrise", [None])[0]
    sunset_str = daily.get("sunset", [None])[0]
    sunrise_dt = None
    sunset_dt = None
    if sunrise_str:
        try:
            sunrise_dt = datetime.strptime(sunrise_str, "%Y-%m-%dT%H:%M")
        except (ValueError, IndexError):
            pass
    if sunset_str:
        try:
            sunset_dt = datetime.strptime(sunset_str, "%Y-%m-%dT%H:%M")
        except (ValueError, IndexError):
            pass

    result = {
        "current": {
            "temperature": current["temperature_2m"],
            "feels_like": current["apparent_temperature"],
            "wind_speed": current["wind_speed_10m"],
            "weather_code": current["weather_code"],
            "local_time": local_time.isoformat() if local_time else None,
        },
        "hourly_forecast": hourly_forecast,
        "today_high": daily["temperature_2m_max"][0],
        "today_low": daily["temperature_2m_min"][0],
        "sunrise": sunrise_dt.strftime("%H:%M") if sunrise_dt else None,
        "sunset": sunset_dt.strftime("%H:%M") if sunset_dt else None,
        "forecast": forecast,
        "unit": unit,
    }
    return result
