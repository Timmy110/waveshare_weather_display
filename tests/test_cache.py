"""Unit tests for cache hashing and refresh-decision logic."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from weather_dashboard.cache import (  # noqa: E402
    should_full_refresh,
    update_meta_after_run,
    weather_data_hash,
)


def _weather(temp=7.0):
    return {
        "current": {"temperature": temp, "weather_code": 3, "feels_like": 4.0, "wind_speed": 12.0},
        "hourly_forecast": [{"hour": "15:00", "temperature": 8.0, "weather_code": 61}],
        "today_high": 8,
        "today_low": 2,
        "sunrise": "08:00",
        "sunset": "17:30",
        "forecast": [{"weekday": "Tue", "high": 9, "low": 3, "weather_code": 61}],
    }


def test_hash_is_stable_for_equal_data():
    assert weather_data_hash(_weather()) == weather_data_hash(_weather())


def test_hash_ignores_sub_degree_changes():
    # Rounded to whole degrees, so 7.0 and 7.4 hash identically.
    assert weather_data_hash(_weather(7.0)) == weather_data_hash(_weather(7.4))


def test_hash_changes_on_meaningful_temp_change():
    assert weather_data_hash(_weather(7.0)) != weather_data_hash(_weather(9.0))


def test_first_run_forces_full_refresh(tmp_path):
    do_refresh, reason = should_full_refresh(str(tmp_path), _weather(), threshold=24)
    assert do_refresh is True
    assert "first run" in reason.lower() or "no previous" in reason.lower()


def test_unchanged_data_skips_until_threshold(tmp_path):
    cache = str(tmp_path)
    w = _weather()
    # Record a full refresh (counter resets to 0).
    update_meta_after_run(cache, w, did_refresh=True)
    do_refresh, _ = should_full_refresh(cache, w, threshold=3)
    assert do_refresh is False
    # Bump the counter to the threshold via skips.
    for _ in range(3):
        update_meta_after_run(cache, w, did_refresh=False)
    do_refresh, reason = should_full_refresh(cache, w, threshold=3)
    assert do_refresh is True
    assert "threshold" in reason.lower()


def test_changed_data_forces_refresh(tmp_path):
    cache = str(tmp_path)
    update_meta_after_run(cache, _weather(7.0), did_refresh=True)
    do_refresh, reason = should_full_refresh(cache, _weather(9.0), threshold=24)
    assert do_refresh is True
    assert "changed" in reason.lower()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
