from PIL import Image, ImageDraw, ImageFont
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

WIDTH, HEIGHT = 800, 480
BLACK, WHITE, RED = 0, 1, 2


def _get_font(size):
    """Load a TTF font, falling back to PIL default if not found."""
    font_paths = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts", "DejaVuSans.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu-sans/DejaVuSans.ttf",
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _draw_text(draw, x, y, text, font, fill=BLACK, align="left"):
    """Helper to draw text with optional center/right alignment."""
    try:
        bbox = draw.textbbox((x, y), text, font=font)
        tw = bbox[2] - bbox[0]
        if align == "center":
            x -= tw // 2
        elif align == "right":
            x -= tw
    except Exception:
        pass
    draw.text((x, y), text, font=font, fill=fill)


def render_dashboard(weather, config):
    """
    Render the full weather dashboard.
    Returns (black_image, red_image) PIL Images for the epd7in5b_V2 display.
    """
    # Create two 1-bit images: black channel (0=white, 1=black) and red channel (0=white, 1=red)
    img_black = Image.new("1", (WIDTH, HEIGHT), 1)  # white background
    img_red = Image.new("1", (WIDTH, HEIGHT), 1)    # white background
    
    draw_b = ImageDraw.Draw(img_black)
    draw_r = ImageDraw.Draw(img_red)
    
    location_name = config["location"]["name"]
    alerts = config["alerts"]
    current = weather.get("current", {})
    today_precip = weather.get("today_precip", 0.0)
    hourly = weather.get("hourly", [])
    daily = weather.get("daily", {})
    
    # Font sizes
    f_header = _get_font(26)
    f_temp_large = _get_font(72)
    f_sub = _get_font(28)
    f_hour_label = _get_font(22)
    f_hour_temp = _get_font(26)
    f_day_label = _get_font(24)
    f_day_temp = _get_font(22)
    f_footer = _get_font(18)
    
    # --- HEADER BAR (~40px) ---
    header_h = 40
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    draw_b.rectangle([0, 0, WIDTH - 1, header_h - 1], fill=BLACK, outline=BLACK)
    draw_b.text((20, 6), location_name, font=f_header, fill=WHITE)
    draw_b.text((WIDTH - 20, 6), now_str, font=f_header, fill=WHITE, anchor="rt")
    
    # --- TOP SECTION: Current Weather (left ~35%) | Hourly Forecast (right ~65%) (~240px) ---
    split_x = WIDTH // 3 * 1 + 50  # ~320px left column
    top_y = header_h + 5
    top_h = 240
    
    # Draw separator line below header
    draw_b.line([(0, header_h), (WIDTH - 1, header_h)], fill=BLACK)
    
    # -- LEFT COLUMN: Current Weather --
    wx_code = current.get("weather_code", 0)
    desc, icon_txt = _get_wmo_info(wx_code)
    
    # Large icon text
    draw_b.text((split_x // 2, top_y + 10), icon_txt, font=_get_font(64), fill=BLACK, anchor="mb")
    
    # Temperature
    temp_val = current.get("temperature", "--")
    if isinstance(temp_val, (int, float)):
        temp_str = f"{temp_val:.1f}\u00b0C"
    else:
        temp_str = "--\u00b0C"
    
    # Color high/low in red if exceeding thresholds
    is_alert = False
    if isinstance(temp_val, (int, float)):
        if temp_val >= alerts.get("temp_high_threshold", 35) or temp_val <= alerts.get("temp_low_threshold", -5):
            is_alert = True
    
    _draw_text(draw_b, split_x // 2, top_y + 80, temp_str, f_temp_large, fill=BLACK if not is_alert else RED, align="center")
    if is_alert:
        _draw_text(draw_r, split_x // 2, top_y + 80, temp_str, f_temp_large, fill=RED, align="center")
    
    # Description
    _draw_text(draw_b, split_x // 2, top_y + 145, desc, f_sub, align="center")
    
    # Humidity
    humidity = current.get("humidity", "--")
    if isinstance(humidity, (int, float)):
        draw_b.text((split_x // 2, top_y + 180), f"Humidity: {humidity}%", font=f_hour_label, fill=BLACK, anchor="mb")
    
    # Today's precipitation
    precip_str = f"Precip today: {today_precip:.1f} mm" if isinstance(today_precip, (int, float)) else "Precip today: -- mm"
    precip_alert = isinstance(today_precip, (int, float)) and today_precip >= alerts.get("precip_threshold", 10)
    draw_b.text((split_x // 2, top_y + 210), precip_str, font=f_hour_label, fill=BLACK if not precip_alert else RED, anchor="mb")
    if precip_alert:
        draw_r.text((split_x // 2, top_y + 210), precip_str, font=f_hour_label, fill=RED, anchor="mb")
    
    # Separator between columns
    draw_b.line([(split_x, top_y), (split_x, top_y + top_h)], fill=BLACK)
    
    # -- RIGHT COLUMN: Hourly Forecast --
    hx_start = split_x + 15
    hour_count = len(hourly)
    
    if hour_count > 0:
        draw_b.text((hx_start, top_y + 5), "Hourly Forecast", font=f_sub, fill=BLACK)
        
        col_w = (WIDTH - hx_start - 20) // min(hour_count, 8)
        
        for i, hr in enumerate(hourly[:8]):
            cx = hx_start + i * col_w + col_w // 2
            hour_label = hr.get("time", "??:??")
            hr_code = hr.get("weather_code", 0)
            _, hr_icon = _get_wmo_info(hr_code)
            hr_temp = hr.get("temperature", "--")
            hr_precip = hr.get("precip_probability", 0)
            
            # Time label
            draw_b.text((cx, top_y + 35), hour_label[:2] + "h", font=f_hour_label, fill=BLACK, anchor="mb")
            
            # Icon
            draw_b.text((cx, top_y + 60), hr_icon, font=_get_font(32), fill=BLACK, anchor="mb")
            
            # Temperature
            if isinstance(hr_temp, (int, float)):
                t_str = f"{hr_temp:.0f}\u00b0"
            else:
                t_str = "--\u00b0"
            draw_b.text((cx, top_y + 100), t_str, font=f_hour_temp, fill=BLACK, anchor="mb")
            
            # Precipitation probability
            if isinstance(hr_precip, (int, float)):
                p_str = f"{hr_precip:.0f}%"
            else:
                p_str = ""
            draw_b.text((cx, top_y + 130), p_str, font=f_hour_label, fill=BLACK, anchor="mb")
    
    # --- MIDDLE SECTION: 5-Day Forecast (~120px) ---
    mid_y = header_h + top_h + 10
    draw_b.line([(0, mid_y - 5), (WIDTH - 1, mid_y - 5)], fill=BLACK)
    
    daily_codes = daily.get("weather_codes", [])
    daily_max = daily.get("temp_max", [])
    daily_min = daily.get("temp_min", [])
    daily_dates = daily.get("dates", [])
    
    # Day names for abbreviations
    day_abbr = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    
    if len(daily_codes) > 0:
        days_to_show = min(5, len(daily_codes))
        col_w = WIDTH // days_to_show
        
        for i in range(days_to_show):
            cx = i * col_w + col_w // 2
            
            # Date / Day abbreviation
            date_str = daily_dates[i] if i < len(daily_dates) else ""
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                day_name = day_abbr[dt.weekday()]
            except Exception:
                day_name = str(i + 1)
            
            draw_b.text((cx, mid_y + 5), day_name, font=f_day_label, fill=BLACK, anchor="mb")
            
            # Icon
            d_code = daily_codes[i] if i < len(daily_codes) else 0
            _, d_icon = _get_wmo_info(d_code)
            draw_b.text((cx, mid_y + 30), d_icon, font=_get_font(36), fill=BLACK, anchor="mb")
            
            # Hi / Lo temperatures
            hi = daily_max[i] if i < len(daily_max) else "--"
            lo = daily_min[i] if i < len(daily_min) else "--"
            
            hi_str = f"{hi:.0f}\u00b0" if isinstance(hi, (int, float)) else "--\u00b0"
            lo_str = f"{lo:.0f}\u00b0" if isinstance(lo, (int, float)) else "--\u00b0"
            
            draw_b.text((cx - 15, mid_y + 72), hi_str, font=f_day_temp, fill=BLACK, anchor="mb")
            draw_b.text((cx + 15, mid_y + 72), lo_str, font=f_day_temp, fill=BLACK, anchor="mb")
    
    # --- FOOTER (~40px) ---
    foot_y = HEIGHT - 35
    draw_b.line([(0, foot_y - 5), (WIDTH - 1, foot_y - 5)], fill=BLACK)
    
    footer_text = f"Open-Meteo  |  Last update: {datetime.now().strftime('%H:%M')}"
    draw_b.text((20, foot_y), footer_text, font=f_footer, fill=BLACK)
    
    return img_black, img_red


def _get_wmo_info(code):
    """Return (description, icon_emoji) for WMO weather code."""
    codes = {
        0: ("Clear sky", "\u2600"),
        1: ("Mainly clear", "\u2600"),
        2: ("Partly cloudy", "\u26c5"),
        3: ("Overcast", "\u2601"),
        45: ("Fog", "\ud83c\udf2b"),
        48: ("Rime fog", "\ud83c\udf2b"),
        51: ("Light drizzle", "\ud83c\udf26"),
        53: ("Moderate drizzle", "\ud83c\udf26"),
        55: ("Dense drizzle", "\ud83c\udf27"),
        56: ("Freezing drizzle", "\ud83c\udf27"),
        57: ("Dense freezing drizzle", "\ud83c\udf27"),
        61: ("Slight rain", "\ud83c\udf27"),
        63: ("Moderate rain", "\ud83c\udf27"),
        65: ("Heavy rain", "\ud83c\udf27"),
        66: ("Freezing rain", "\ud83c\udf27"),
        67: ("Heavy freezing rain", "\ud83c\udf27"),
        71: ("Light snow", "\u2744"),
        73: ("Moderate snow", "\u2744"),
        75: ("Heavy snow", "\u2744"),
        77: ("Snow grains", "\u2744"),
        80: ("Rain showers", "\ud83c\udf26"),
        81: ("Moderate showers", "\ud83c\udf27"),
        82: ("Violent showers", "\ud83c\udf27"),
        85: ("Snow showers", "\u2744"),
        86: ("Heavy snow showers", "\u2744"),
        95: ("Thunderstorm", "\u26c8"),
        96: ("Thunderstorm + hail", "\u26c8"),
        99: ("Thunderstorm + heavy hail", "\u26c8"),
    }
    return codes.get(code, ("Unknown", "?"))
