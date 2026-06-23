#!/usr/bin/env python3
"""Local cache management for weather data and render metadata."""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def _ensure_cache_dir(cache_dir: str) -> str:
    """Resolve the cache directory (expand ~), create it if missing."""
    resolved = os.path.expanduser(cache_dir)
    os.makedirs(resolved, exist_ok=True)
    return resolved


def read_last_weather(cache_dir: str) -> Optional[Dict[str, Any]]:
    """Read the last successfully fetched weather payload from cache."""
    path = os.path.join(_ensure_cache_dir(cache_dir), "last_weather.json")
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        logger.warning("No valid weather cache at %s: %s", path, exc)
        return None


def write_last_weather(cache_dir: str, weather: Dict[str, Any]) -> None:
    """Persist the current weather payload to cache."""
    path = os.path.join(_ensure_cache_dir(cache_dir), "last_weather.json")
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(weather, f, indent=2)
    os.replace(tmp_path, path)
    logger.info("Wrote weather cache to %s", path)


def read_render_meta(cache_dir: str) -> Optional[Dict[str, Any]]:
    """Read render metadata (timestamp, data hash, refresh counter)."""
    path = os.path.join(_ensure_cache_dir(cache_dir), "last_render_meta.json")
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        logger.warning("No valid render meta cache at %s: %s", path, exc)
        return None


def write_render_meta(cache_dir: str, meta: Dict[str, Any]) -> None:
    """Persist render metadata to cache."""
    path = os.path.join(_ensure_cache_dir(cache_dir), "last_render_meta.json")
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(meta, f, indent=2)
    os.replace(tmp_path, path)


def weather_data_hash(weather: Dict[str, Any]) -> str:
    """
    Compute a stable hash of the weather data fields used for rendering.

    Includes current conditions + forecast (excludes unit which doesn't affect
    visual content beyond labels).
    """
    # Build a deterministic snapshot of the displayable fields
    snapshot = {
        "current": {
            "temperature": weather.get("current", {}).get("temperature"),
            "weather_code": weather.get("current", {}).get("weather_code"),
            "feels_like": weather.get("current", {}).get("feels_like"),
            "wind_speed": weather.get("current", {}).get("wind_speed"),
            "local_time": weather.get("current", {}).get("local_time"),
        },
        "hourly_forecast": weather.get("hourly_forecast", []),
        "today_high": weather.get("today_high"),
        "today_low": weather.get("today_low"),
        "sunrise": weather.get("sunrise"),
        "sunset": weather.get("sunset"),
        "forecast": weather.get("forecast", []),
    }
    raw = json.dumps(snapshot, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def should_full_refresh(
    cache_dir: str,
    weather: Dict[str, Any],
    threshold: int,
) -> Tuple[bool, str]:
    """
    Determine whether a full panel refresh is needed.

    Returns (do_refresh, reason).
    A full refresh is required if:
      - No previous cache exists (first run or corrupt)
      - Weather data has changed since last render
      - The refresh counter has reached the threshold
    """
    current_hash = weather_data_hash(weather)
    meta = read_render_meta(cache_dir)

    if meta is None:
        return True, "No previous render metadata (first run or missing cache)"

    prev_hash = meta.get("data_hash")
    counter = meta.get("refresh_counter", 0)

    if prev_hash != current_hash:
        return True, "Weather data has changed"

    if counter >= threshold:
        return True, f"Refresh counter ({counter}) reached threshold ({threshold})"

    return False, f"Unchanged data, counter {counter}/{threshold} — skip"


def update_meta_after_run(
    cache_dir: str,
    weather: Dict[str, Any],
    did_refresh: bool,
) -> None:
    """Update the render metadata after a run completes."""
    current_hash = weather_data_hash(weather)

    if did_refresh:
        # Reset counter on full refresh
        meta = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data_hash": current_hash,
            "refresh_counter": 0,
        }
    else:
        # Increment counter on skip
        meta = read_render_meta(cache_dir)
        if meta is None:
            meta = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data_hash": current_hash,
                "refresh_counter": 1,
            }
        else:
            meta["timestamp"] = datetime.now(timezone.utc).isoformat()
            meta["refresh_counter"] = meta.get("refresh_counter", 0) + 1

    write_render_meta(cache_dir, meta)
