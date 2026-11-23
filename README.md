# Waveshare 7.5" E-Ink Weather Dashboard

A Python script that fetches current weather from [Open-Meteo](https://open-meteo.com) (no API key needed), renders it to a **Waveshare 7.5" E-Paper HAT (B)** three-color display (black / white / red), and exits cleanly. Designed for scheduled execution on a Raspberry Pi via `cron` or `systemd` timer.

## Features

- Pure weather dashboard: location and date in a centred header — no clock
- Current conditions: large icon, temperature, feels-like, condition, plus a red notice when rain/snow is falling (until when) or due within 2 hours
- Metrics grid: sunrise, sunset, wind (speed + direction), humidity, pressure, UV index, visibility and air quality (European AQI)
- 24-hour chart: temperature line over rain-probability bars
- 7-day forecast cards with icons and high / low
- Filled vector icons drawn for the black/white/red panel: red for sun and warmth, dithered black for greys; moon variants at night
- Smart refresh: the panel is only redrawn when something on screen would change (weather at displayed precision, the date, or the offline state); otherwise it is left untouched, saving panel wear. "Updated HH:MM" therefore shows when the screen last changed
- Every redraw is a full refresh; after N skipped runs in a row (`full_refresh_interval`, default 24) it redraws anyway to clear ghosting
- Stale-data fallback: if the API is unreachable, redraws last known good data with a red "Offline" note next to the update time
- Debug PNG images saved to cache directory for inspection without physical hardware

## Hardware

| Component | Detail |
|-----------|--------|
| SBC | Raspberry Pi Zero 2 W (or any Pi with SPI) |
| Display | Waveshare 7.5inch E-Paper HAT (B) — **3-color variant** (`epd7in5b_V2`) |
| Resolution | 800 × 480 (landscape) |

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/Timmy110/waveshare_weather_display.git
cd waveshare_weather_display
```

### 2. Install Python dependencies

```bash
pip3 install -r requirements.txt
```

The bundled `lib/waveshare_epd/` directory already contains the panel driver — no pip package needed for it.

### 3. Fonts

The [Jost](https://github.com/indestructible-type/Jost) font family (SIL Open Font
License, see `resources/fonts/OFL.txt`) is bundled in `resources/fonts/`, so nothing
needs installing. To use a different face, set `font_path` in the config; heavier
weights are then simulated.

### 4. Configure location & settings

Edit `config.json`:

```json
{
    "latitude": 48.8566,
    "longitude": 2.3522,
    "timezone": "Europe/Paris",
    "temperature_unit": "celsius",
    "cache_dir": "cache",
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
| `cache_dir` | Where weather cache + debug images are stored. Relative paths (default `"cache"`) are resolved against the project directory, so the cache travels with the repo; absolute paths and `~` are also accepted. |
| `full_refresh_interval` | Redraw anyway after this many skipped runs in a row (default 24 — 6 hours at a 15-minute schedule) |
| `api_timeout_seconds` | HTTP timeout for Open-Meteo requests |
| `font_path` | Optional absolute path to a `.ttf`/`.ttc` file. `null` = bundled Jost. |

## Usage

```bash
python3 weather_dashboard.py
```

The script will:
1. Fetch weather from Open-Meteo
2. Compare with the last rendered data
3. Redraw the display (full refresh) **only** if the screen content changed or the periodic redraw threshold was reached — otherwise leave the panel untouched
4. Put the panel to sleep and exit (code 0 = success, non-zero = error)

### Override config path

```bash
python3 weather_dashboard.py --config /path/to/my_config.json
```

### Testing without the display

The script runs on any machine (no Raspberry Pi or panel required) — handy for
working on the layout. If the e-Paper driver/hardware isn't present it
**automatically** falls back to a headless, image-only mode. You can also force it:

```bash
python3 weather_dashboard.py --no-display              # render only, never touch hardware
python3 weather_dashboard.py -o /tmp/preview.png       # also copy the preview to a chosen path
```

In every run (hardware or headless) the renderer writes inspectable images to the
**cache directory**: `last_black.png`, `last_red.png`, and `preview.png` — a composite
RGB image that mimics how the physical panel looks (white / black / red). So a plain
`--no-display` run already leaves the preview at `cache/preview.png`.

`-o/--output PATH` is only needed to additionally save a copy somewhere else. The path
is relative to your current directory, so prefer an explicit location (e.g. `/tmp/...`)
rather than a bare filename that lands in the project root.

## Scheduling

### Option A: cron

Edit crontab (`crontab -e`) and run the dashboard every 15 minutes. Open-Meteo
updates current conditions every 15 minutes, so running more often only fetches the
same data; runs where nothing changed don't touch the panel:

```cron
*/15 * * * * cd /home/pi/waveshare_weather_display && python3 weather_dashboard.py >> /var/log/weather_dashboard.log 2>&1
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
Description=Run weather dashboard every 15 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=15min

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
├── requirements.txt              # Python dependencies
├── weather_dashboard/
│   ├── __init__.py
│   ├── weather.py                # Open-Meteo fetch + parsing
│   ├── cache.py                  # Local JSON cache management
│   ├── render.py                 # Layout: PIL image rendering (black + red buffers)
│   └── icons.py                  # Vector weather + metric icons, dithering
├── cache/                        # Runtime cache + debug images (git-ignored, auto-created)
├── lib/waveshare_epd/            # Bundled Waveshare panel driver
├── resources/
│   ├── fonts/                    # Bundled Jost font family (OFL)
│   └── pic/                      # Fallback font (Font.ttc)
├── tests/                        # Unit tests (run with pytest)
└── README.md
```

## Development

Install the dev/test dependencies (these are **not** needed on the Pi):

```bash
pip3 install -r requirements-dev.txt
```

The fetch/parse/cache logic is covered by unit tests that need neither network
nor hardware:

```bash
python3 -m pytest tests/ -v
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError: waveshare_epd` | Ensure `lib/` is in the same directory as `weather_dashboard.py` |
| Font rendering looks wrong | Check `resources/fonts/` is present, or set `font_path` in config |
| Display stays blank after first run | Check that SPI is enabled: `sudo raspi-config` → Interface Options → SPI |
| Script hangs during `epd.init()` | Verify GPIO pin access — may need to run as `pi` user with proper permissions, or use `sudo` for testing |
| Debug images not appearing | Check the `cache/` directory inside the project (or your configured `cache_dir`) |

## License

MIT
