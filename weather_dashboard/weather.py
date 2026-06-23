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
        "current": "temperature,relative_humidity_2m,apparent_temperature,wind_speed_10m,weather_code",
        "hourly": "temperature,weather_code",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min",
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
    if hourly.get("time") and hourly.get("temperature"):
        now_hour = None
        if local_time:
            now_hour = local_time.hour
            now_date = local_time.date()
        
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
                "hour": h_dt.strftime("%H:%M"),
                "temperature": hourly["temperature"][i],
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

    result = {
        "current": {
            "temperature": current["temperature"],
            "feels_like": current["apparent_temperature"],
            "wind_speed": current["wind_speed_10m"],
            "weather_code": current["weather_code"],
            "local_time": local_time.isoformat() if local_time else None,
        },
        "hourly_forecast": hourly_forecast,
        "today_high": daily["temperature_2m_max"][0],
        "today_low": daily["temperature_2m_min"][0],
        "forecast": forecast,
        "unit": unit,
    }
    return result
