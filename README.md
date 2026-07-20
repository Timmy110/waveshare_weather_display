# Waveshare 7.5" E-Ink Weather Dashboard

A Python script that fetches current weather from [Open-Meteo](https://open-meteo.com) (no API key needed), renders it to a **Waveshare 7.5" E-Paper HAT (B)** three-color display (black / white / red), and exits cleanly. Designed for scheduled execution on a Raspberry Pi via `cron` or `systemd` timer.

## Features

- Current temperature, feels-like, wind speed, weather condition with icon
- Today's high/low temperatures
- 5-day forecast strip with per-day highs/lows and weather icons
- Smart refresh: only updates the display when data actually changes (saves e-ink panel wear)
- Forced full-refresh every N runs (configurable, default: 24) to prevent image ghosting
- Per-minute clock updates via `--time-only` (partial refresh of just the clock digits)
- Stale-data fallback: if the API is unreachable, redraws last known good data with a red warning badge
- Debug PNG images saved to cache directory for inspection without physical hardware

## Hardware

| Component | Detail |
|-----------|--------|
| SBC | Raspberry Pi Zero 2 W (or any Pi with SPI) |
| Display | Waveshare 7.5inch E-Paper HAT (B) — **3-color variant** (`epd7in5b_V2`) |
| Resolution | 800 × 480 (landscape) |

> **Note on partial refresh:** The `--time-only` run uses the bundled driver's `init_part()` / `display_Partial()` to repaint just the clock digits every minute without a full-screen flash. Partial refresh on this 3-color (B/W/Red) panel is **experimental**: `display_Partial()` writes to a single RAM plane (0x13), so the updated digits may render on the red channel and/or leave faint ghosting until the next full refresh clears it. If the result looks bad on your panel, set `"time_update_mode": "fast"` in config to repaint the whole screen with a fast refresh each minute instead (no ghosting, brief flash). The weather portion still uses "smart refresh" — skipping the draw entirely when nothing changed, full refresh otherwise.

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
    "cache_dir": "cache",
    "full_refresh_interval": 24,
    "api_timeout_seconds": 10,
    "font_path": null,
    "time_update_mode": "partial"
}
```

| Key | Description |
|-----|-------------|
| `latitude` / `longitude` | Your location (required) |
| `timezone` | IANA timezone for correct day boundaries |
| `temperature_unit` | `"celsius"` or `"fahrenheit"` |
| `cache_dir` | Where weather cache + debug images are stored. Relative paths (default `"cache"`) are resolved against the project directory, so the cache travels with the repo; absolute paths and `~` are also accepted. |
| `full_refresh_interval` | Force a full panel refresh every N runs (default 24) |
| `api_timeout_seconds` | HTTP timeout for Open-Meteo requests |
| `font_path` | Optional absolute path to a `.ttf`/`.ttc` file. `null` = auto-detect. |
| `time_update_mode` | How `--time-only` repaints the clock: `"partial"` (default, partial refresh of the clock digits, flash-free) or `"fast"` (whole-screen fast refresh from cached weather, no ghosting but flashes). |

## Usage

```bash
python3 weather_dashboard.py
```

The script will:
1. Fetch weather from Open-Meteo
2. Compare with the last rendered data
3. Update the display **only** if data changed or the periodic refresh threshold was reached
4. Put the panel to sleep and exit (code 0 = success, non-zero = error)

### Update only the clock (per-minute)

```bash
python3 weather_dashboard.py --time-only
```

Repaints just the clock — no network fetch, no cache writes. Run this every
minute alongside a normal (full) run every ~15 minutes: the full run handles
weather and repaints the whole screen (clearing any partial-refresh ghosting),
while `--time-only` keeps the minutes ticking cheaply in between. Behaviour is
controlled by `time_update_mode` (see config table). Concurrent runs are
serialized with a lock file (`cache/panel.lock`) so the two schedules never
drive the SPI bus at the same time.

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

Edit crontab (`crontab -e`). To get a **per-minute clock + weather every 15 minutes**,
add two lines — one full run, one `--time-only` run:

```cron
# Weather + full redraw every 15 minutes
*/15 * * * * cd /home/pi/waveshare_weather_display && python3 weather_dashboard.py >> /var/log/weather_dashboard.log 2>&1
# Clock only, every minute
* * * * * cd /home/pi/waveshare_weather_display && python3 weather_dashboard.py --time-only >> /var/log/weather_dashboard.log 2>&1
```

At `:00`, `:15`, `:30`, `:45` both jobs fire; the `cache/panel.lock` file makes the
`--time-only` job wait for the full run to finish (the full run repaints the clock
anyway). For a simpler once-every-30-minutes setup with no per-minute clock, use a
single line:

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

For the per-minute clock, add a second oneshot service that runs with
`--time-only` (`ExecStart=... weather_dashboard.py --time-only`) plus a timer with
`OnCalendar=*:0/1` (every minute). The `cache/panel.lock` file keeps it from
colliding with the 15-minute weather run.

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
│   └── render.py                 # PIL image rendering (black + red buffers)
├── cache/                        # Runtime cache + debug images (git-ignored, auto-created)
├── lib/waveshare_epd/            # Bundled Waveshare panel driver
├── resources/
│   ├── pic/                      # Fonts (Font.ttc/.ttf, optional)
│   └── icons/                    # Weather icon PNGs
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
| Font rendering looks wrong | Place a `.ttf` or `.ttc` file at `pic/Font.ttc` or set `font_path` in config |
| Display stays blank after first run | Check that SPI is enabled: `sudo raspi-config` → Interface Options → SPI |
| Script hangs during `epd.init()` | Verify GPIO pin access — may need to run as `pi` user with proper permissions, or use `sudo` for testing |
| Debug images not appearing | Check the `cache/` directory inside the project (or your configured `cache_dir`) |

## License

MIT
