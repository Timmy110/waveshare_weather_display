# Waveshare 7.5" E-Ink Weather Dashboard

A Python script that fetches current weather from [Open-Meteo](https://open-meteo.com) (no API key needed), renders it to a **Waveshare 7.5" E-Paper HAT (B)** three-color display (black / white / red), and exits cleanly. Designed for scheduled execution on a Raspberry Pi via `cron` or `systemd` timer.

## Features

- Current temperature, feels-like, wind speed, weather condition with icon
- Today's high/low temperatures
- 5-day forecast strip with per-day highs/lows and weather icons
- Smart refresh: only updates the display when data actually changes (saves e-ink panel wear)
- Forced full-refresh every N runs (configurable, default: 24) to prevent image ghosting
- Stale-data fallback: if the API is unreachable, redraws last known good data with a red warning badge
- Debug PNG images saved to cache directory for inspection without physical hardware

## Hardware

| Component | Detail |
|-----------|--------|
| SBC | Raspberry Pi Zero 2 W (or any Pi with SPI) |
| Display | Waveshare 7.5inch E-Paper HAT (B) — **3-color variant** (`epd7in5b_V2`) |
| Resolution | 800 × 480 (landscape) |

> **Note:** This script does **not** use `init_part()` / `display_Partial()`. Those methods exist only on the single-color `epd7in5_V2` variant. "Partial refresh" here means *skipping the draw entirely* when nothing changed.

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/Timmy110/waveshare_weather_display.git
cd waveshare_weather_display
```

### 2. Install Python dependencies

```bash
pip3 install Pillow requests
```

The bundled `lib/waveshare_epd/` directory already contains the panel driver — no pip package needed for it.

### 3. Install a font (if not already present)

The renderer prefers `pic/Font.ttc` (place any `.ttc` or `.ttf` there), then falls back to system fonts like DejaVu Sans or Arial. On Raspberry Pi OS:

```bash
sudo apt install fonts-dejavu-core
```

Or copy your preferred font into the project:

```bash
cp /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf pic/Font.ttc
```

### 4. Configure location & settings

Edit `config.json`:

```json
{
    "latitude": 48.8566,
    "longitude": 2.3522,
    "timezone": "Europe/Paris",
    "temperature_unit": "celsius",
    "cache_dir": "~/.weather_dashboard",
    "full_refresh_interval": 24,
    "api_timeout_seconds": 10,
    "font_path": null
}
```

| Key | Description |
|-----|-------------|
| `latitude` / `longitude` | Your location (required) |
| `timezone` | IANA timezone for correct day boundaries |
| `temperature_unit` | `"celsius"` or `"fahrenheit"` |
| `cache_dir` | Where weather cache + debug images are stored |
| `full_refresh_interval` | Force a full panel refresh every N runs (default 24) |
| `api_timeout_seconds` | HTTP timeout for Open-Meteo requests |
| `font_path` | Optional absolute path to a `.ttf`/`.ttc` file. `null` = auto-detect. |

## Usage

```bash
python3 weather_dashboard.py
```

The script will:
1. Fetch weather from Open-Meteo
2. Compare with the last rendered data
3. Update the display **only** if data changed or the periodic refresh threshold was reached
4. Put the panel to sleep and exit (code 0 = success, non-zero = error)

### Override config path

```bash
python3 weather_dashboard.py --config /path/to/my_config.json
```

## Scheduling

### Option A: cron

Edit crontab (`crontab -e`) and add a line like this to run every 30 minutes:

```cron
*/30 * * * * cd /home/pi/waveshare_weather_display && python3 weather_dashboard.py >> /var/log/weather_dashboard.log 2>&1
```

### Option B: systemd timer (recommended)

Create `/etc/systemd/system/weather-dashboard.service`:

```ini
[Unit]
Description=E-Ink Weather Dashboard

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /home/pi/waveshare_weather_display/weather_dashboard.py
WorkingDirectory=/home/pi/waveshare_weather_display
User=pi
```

Create `/etc/systemd/system/weather-dashboard.timer`:

```ini
[Unit]
Description=Run weather dashboard every 30 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=30min

[Install]
WantedBy=timers.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now weather-dashboard.timer
```

Check status:

```bash
systemctl list-timers weather-dashboard.timer
journalctl -u weather-dashboard.service
```

## Project Structure

```
waveshare_weather_display/
├── weather_dashboard.py          # Main entry point (run this)
├── config.json                   # User settings (lat/lon, timezone, etc.)
├── weather_dashboard/
│   ├── __init__.py
│   ├── weather.py                # Open-Meteo fetch + parsing
│   ├── cache.py                  # Local JSON cache management
│   └── render.py                 # PIL image rendering (black + red buffers)
├── lib/waveshare_epd/            # Bundled Waveshare panel driver
├── pic/                          # Fonts, test images (optional)
└── README.md
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError: waveshare_epd` | Ensure `lib/` is in the same directory as `weather_dashboard.py` |
| Font rendering looks wrong | Place a `.ttf` or `.ttc` file at `pic/Font.ttc` or set `font_path` in config |
| Display stays blank after first run | Check that SPI is enabled: `sudo raspi-config` → Interface Options → SPI |
| Script hangs during `epd.init()` | Verify GPIO pin access — may need to run as `pi` user with proper permissions, or use `sudo` for testing |
| Debug images not appearing | Check `~/.weather_dashboard/` directory (or your configured `cache_dir`) |

## License

MIT
