import yaml
import os
import sys
import logging

logger = logging.getLogger(__name__)

DEFAULTS = {
    "location": {
        "name": "Waregem, Belgium",
        "latitude": 50.8967,
        "longitude": 3.2278,
    },
    "display": {
        "refresh_interval_minutes": 30,
        "forecast_days": 5,
        "hourly_slots": 8,
    },
    "units": {
        "temperature": "C",
    },
    "alerts": {
        "temp_high_threshold": 35.0,
        "temp_low_threshold": -5.0,
        "precip_threshold": 10.0,
    },
}


def _find_config():
    """Find config.yaml by walking up from the entry point or cwd."""
    candidates = [
        # Next to main.py (entry script)
        os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "config.yaml"),
        # Current working directory
        os.path.join(os.getcwd(), "config.yaml"),
        # Two levels up from this module (project root fallback)
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[0]


def load_config(path=None):
    """Load configuration from YAML file, falling back to defaults."""
    cfg_path = path or _find_config()
    
    config = {}
    for section, values in DEFAULTS.items():
        config[section] = dict(values)
    
    if os.path.exists(cfg_path):
        logger.info("Loading config from %s", cfg_path)
        try:
            with open(cfg_path, "r") as f:
                user_cfg = yaml.safe_load(f) or {}
            
            for section in DEFAULTS:
                if section in user_cfg and isinstance(user_cfg[section], dict):
                    config[section].update(user_cfg[section])
        except Exception as e:
            logger.error("Failed to parse config file: %s", e)
    else:
        logger.warning("Config file not found at %s, using defaults", cfg_path)
    
    return config


def get_location(config):
    return (
        config["location"]["name"],
        config["location"]["latitude"],
        config["location"]["longitude"],
    )


def get_display_settings(config):
    return config["display"]


def get_alerts(config):
    return config["alerts"]
