import requests
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

BASE_URL = "https://api.open-meteo.com/v1/forecast"


WMO_CODES = {
    0: ("Clear sky", "☀"),
    1: ("Mainly clear", "☀"),
    2: ("Partly cloudy", "⛅"),
    3: ("Overcast", "☁"),
    45: ("Fog", "🌫"),
    48: ("Depositing rime fog", "🌫"),
    51: ("Light drizzle", "🌦"),
    53: ("Moderate drizzle", "🌦"),
    55: ("Dense drizzle", "🌧"),
    56: ("Light freezing drizzle", "🌧"),
    57: ("Dense freezing drizzle", "🌧"),
    61: ("Slight rain", "🌧"),
    63: ("Moderate rain", "🌧"),
    65: ("Heavy rain", "🌧"),
    66: ("Light freezing rain", "🌧"),
    67: ("Heavy freezing rain", "🌧"),
    71: ("Slight snowfall", "❄"),
    73: ("Moderate snowfall", "❄"),
    75: ("Heavy snowfall", "❄"),
    77: ("Snow grains", "❄"),
    80: ("Slight rain showers", "🌦"),
    81: ("Moderate rain showers", "🌧"),
    82: ("Violent rain showers", "🌧"),
    85: ("Slight snow showers", "❄"),
    86: ("Heavy snow showers", "❄"),
    95: ("Thunderstorm", "⛈"),
    96: ("Thunderstorm with slight hail", "⛈"),
    99: ("Thunderstorm with heavy hail", "⛈"),
}


def get_weather_code_icon(code):
    """Return (description, icon) for a WMO weather code."""
    return WMO_CODES.get(code, ("Unknown", "?"))


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
        response = requests.get(BASE_URL, params=params, timeout=10)
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
