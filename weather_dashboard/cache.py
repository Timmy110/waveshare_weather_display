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
    except FileNotFoundError:
        # Expected on the first run (callers that care log their own message).
        logger.debug("No weather cache yet at %s", path)
        return None
    except json.JSONDecodeError as exc:
        logger.warning("Corrupt weather cache at %s: %s", path, exc)
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
    except FileNotFoundError:
        # Expected on the first run before any render has happened.
        logger.debug("No render meta cache yet at %s", path)
        return None
    except json.JSONDecodeError as exc:
        logger.warning("Corrupt render meta cache at %s: %s", path, exc)
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

    Includes current conditions + forecast. Excludes local_time (clock is
    rendered from live system time, not the API snapshot) and unit which
    doesn't affect visual content beyond labels.
    """
    # Round to match display precision (: .0f) so minor float changes
    # don't trigger unnecessary full refreshes.
    cur = weather.get("current", {})
    snapshot = {
        "current": {
            "temperature": round(cur.get("temperature") or 0),
            "weather_code": cur.get("weather_code"),
            "feels_like": round(cur.get("feels_like") or 0),
            "wind_speed": round(cur.get("wind_speed") or 0),
        },
        "hourly_forecast": [
            {"hour": h.get("hour"), "temperature": round(h.get("temperature") or 0), "weather_code": h.get("weather_code")}
            for h in weather.get("hourly_forecast", [])
        ],
        "today_high": round(weather.get("today_high") or 0),
        "today_low": round(weather.get("today_low") or 0),
        "sunrise": weather.get("sunrise"),
        "sunset": weather.get("sunset"),
        "forecast": [
            {"weekday": d.get("weekday"), "high": round(d.get("high") or 0), "low": round(d.get("low") or 0), "weather_code": d.get("weather_code")}
            for d in weather.get("forecast", [])
        ],
    }
    raw = json.dumps(snapshot, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def diff_weather(
    prev: Optional[Dict[str, Any]],
    current: Dict[str, Any],
) -> list:
    """
    Return human-readable descriptions of what changed between two weather
    payloads, comparing the same rounded fields used by weather_data_hash().

    Returns an empty list if `prev` is None or nothing material changed.
    """
    if not prev:
        return []

    # Imported lazily to avoid a hard import cycle at module load.
    from weather_dashboard.render import condition_label

    def rnd(value):
        return round(value or 0)

    changes = []
    pc = prev.get("current", {})
    cc = current.get("current", {})

    if rnd(pc.get("temperature")) != rnd(cc.get("temperature")):
        changes.append(f"Temperature: {rnd(pc.get('temperature'))}° → {rnd(cc.get('temperature'))}°")
    if pc.get("weather_code") != cc.get("weather_code"):
        changes.append(
            f"Condition: {condition_label(pc.get('weather_code'))} → {condition_label(cc.get('weather_code'))}"
        )
    if rnd(pc.get("feels_like")) != rnd(cc.get("feels_like")):
        changes.append(f"Feels like: {rnd(pc.get('feels_like'))}° → {rnd(cc.get('feels_like'))}°")
    if rnd(pc.get("wind_speed")) != rnd(cc.get("wind_speed")):
        changes.append(f"Wind: {rnd(pc.get('wind_speed'))} → {rnd(cc.get('wind_speed'))} km/h")

    if rnd(prev.get("today_high")) != rnd(current.get("today_high")):
        changes.append(f"Today's high: {rnd(prev.get('today_high'))}° → {rnd(current.get('today_high'))}°")
    if rnd(prev.get("today_low")) != rnd(current.get("today_low")):
        changes.append(f"Today's low: {rnd(prev.get('today_low'))}° → {rnd(current.get('today_low'))}°")

    if prev.get("sunrise") != current.get("sunrise"):
        changes.append(f"Sunrise: {prev.get('sunrise')} → {current.get('sunrise')}")
    if prev.get("sunset") != current.get("sunset"):
        changes.append(f"Sunset: {prev.get('sunset')} → {current.get('sunset')}")

    # Per-day forecast, matched by weekday label.
    prev_days = {d.get("weekday"): d for d in prev.get("forecast", [])}
    for d in current.get("forecast", []):
        pd = prev_days.get(d.get("weekday"))
        if pd is None:
            continue
        parts = []
        if rnd(pd.get("high")) != rnd(d.get("high")):
            parts.append(f"high {rnd(pd.get('high'))}°→{rnd(d.get('high'))}°")
        if rnd(pd.get("low")) != rnd(d.get("low")):
            parts.append(f"low {rnd(pd.get('low'))}°→{rnd(d.get('low'))}°")
        if pd.get("weather_code") != d.get("weather_code"):
            parts.append(f"{condition_label(pd.get('weather_code'))}→{condition_label(d.get('weather_code'))}")
        if parts:
            changes.append(f"{d.get('weekday')} forecast: " + ", ".join(parts))

    # Hourly strip: report how many of the shown hours differ (the window also
    # slides over time, so this naturally picks up the advancing forecast).
    prev_hours = {h.get("hour"): h for h in prev.get("hourly_forecast", [])}
    hourly_changed = 0
    for h in current.get("hourly_forecast", []):
        ph = prev_hours.get(h.get("hour"))
        if ph is None or rnd(ph.get("temperature")) != rnd(h.get("temperature")) \
                or ph.get("weather_code") != h.get("weather_code"):
            hourly_changed += 1
    if hourly_changed:
        changes.append(f"Hourly forecast: {hourly_changed} hour(s) updated")

    return changes


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
