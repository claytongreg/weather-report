#!/usr/bin/env python3
"""
Daily Birchdale Weather Email Report
Fetches weather from OpenWeather API, generates HTML email with 24h chart,
and sends via Gmail SMTP.
"""
import os
import requests
from datetime import datetime, timezone
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import io

from utils import LAT, LON, MS_TO_KMH, OPENWEATHER_URL, ICON_BASE, PACIFIC, convert_to_pst, get_cardinal

# Configuration from environment variables
OPENWEATHER_API_KEY = os.environ.get('OPENWEATHER_API_KEY')
EMAIL_FROM = os.environ.get('EMAIL_FROM')
EMAIL_TO = os.environ.get('EMAIL_TO')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD')


# ========================================
# HELPER FUNCTIONS
# ========================================
def get_quote():
    try:
        r = requests.get("https://zenquotes.io/api/random", timeout=5)
        if r.status_code == 200:
            q = r.json()[0]
            return f'"{q["q"]}" \u2014 {q["a"]}'
    except:
        pass
    return '"Every day is a new beginning." \u2014 Unknown'


def create_24hour_chart(hourly_data):
    """Generate 24-hour weather chart with temperature, wind, and precipitation"""

    # Prepare data
    hours = []
    temperatures = []
    wind_speeds = []
    wind_gusts = []
    wind_directions = []
    rain_precip = []
    snow_precip = []
    cloud_cover = []

    for i in range(min(24, len(hourly_data))):
        hour = hourly_data[i]
        dt = convert_to_pst(hour['dt'])
        hours.append(dt.strftime('%I%p').lstrip('0'))

        temperatures.append(hour['temp'])
        wind_speeds.append(hour['wind_speed'] * MS_TO_KMH)
        wind_gusts.append(hour.get('wind_gust', hour['wind_speed']) * MS_TO_KMH)
        wind_directions.append(hour.get('wind_deg', 0))

        rain = hour.get('rain', {})
        snow = hour.get('snow', {})
        rain_precip.append(rain.get('1h', 0) if isinstance(rain, dict) else 0)
        snow_precip.append(snow.get('1h', 0) if isinstance(snow, dict) else 0)

        # Add cloud cover
        cloud_cover.append(hour.get('clouds', 0))

    # Create figure with dual y-axes
    fig, ax1 = plt.subplots(figsize=(14, 6), dpi=100)
    ax2 = ax1.twinx()
    ax3 = ax1.twinx()  # Third axis for cloud cover

    # Offset the third axis
    ax3.spines['right'].set_position(('outward', 60))

    x = range(len(hours))

    # Plot temperature line (left axis)
    ax1.plot(x, temperatures, color='#e74c3c', linewidth=3, label='Temperature (\u00b0C)', zorder=3)
    ax1.set_ylabel('Temperature (\u00b0C)', color='#e74c3c', fontweight='bold', fontsize=12)
    ax1.tick_params(axis='y', labelcolor='#e74c3c', labelsize=10)
    ax1.set_ylim(min(temperatures) - 2, max(temperatures) + 2)

    # Add freezing line at 0°C
    ax1.axhline(y=0, color='#3498db', linestyle='--', linewidth=2,
                label='Freezing (0\u00b0C)', zorder=2, alpha=0.8)

    # Plot cloud cover area (third axis)
    ax3.fill_between(x, 0, cloud_cover, color=(0.741, 0.765, 0.780),
                     alpha=0.4, label='Cloud Cover (%)', zorder=1)
    ax3.plot(x, cloud_cover, color='#95a5a6', linewidth=1, alpha=0.8, zorder=1)
    ax3.set_ylabel('Cloud Cover (%)', color='#95a5a6', fontweight='bold', fontsize=12)
    ax3.tick_params(axis='y', labelcolor='#95a5a6', labelsize=10)
    ax3.set_ylim(0, 100)

    # Plot wind lines (right axis)
    ax2.plot(x, wind_speeds, color='#3498db', linewidth=2, label='Wind Speed', zorder=2)
    ax2.plot(x, wind_gusts, color='#3498db', linewidth=2, linestyle='--', label='Wind Gusts', zorder=2)
    ax2.fill_between(x, wind_speeds, wind_gusts, color='#3498db', alpha=0.3, zorder=1)

    # Plot precipitation bars (right axis)
    bar_width = 0.4
    if any(rain_precip):
        ax2.bar([i - bar_width/2 for i in x], rain_precip, width=bar_width,
                color='#2e7d32', alpha=0.8, label='Rain (mm)', zorder=1)
    if any(snow_precip):
        ax2.bar([i + bar_width/2 for i in x], snow_precip, width=bar_width,
                color='#fff', edgecolor='#2196F3', linewidth=3, label='Snow (mm)', zorder=1)

    # Add wind direction arrows (custom shape to match website)
    for i, (wind_speed, wind_dir) in enumerate(zip(wind_speeds, wind_directions)):
        angle_deg = -wind_dir

        arrow_length = 0.4
        arrow_width = 0.2

        # Arrow shape coordinates (pointing up in matplotlib)
        arrow_points = np.array([
            [0, arrow_length],              # tip
            [-arrow_width, -arrow_length],  # left base corner
            [0, -arrow_length*0.3],         # center notch
            [arrow_width, -arrow_length],   # right base corner
            [0, arrow_length]               # close path
        ])

        # Rotate arrow
        angle_rad = np.radians(angle_deg)
        cos_a = np.cos(angle_rad)
        sin_a = np.sin(angle_rad)
        rotation_matrix = np.array([[cos_a, -sin_a], [sin_a, cos_a]])
        rotated_arrow = arrow_points @ rotation_matrix.T

        # Translate to position
        rotated_arrow[:, 0] += i
        rotated_arrow[:, 1] += wind_speed

        # Draw arrow as polygon
        arrow_patch = plt.Polygon(rotated_arrow, fc='#104911', ec='#104911',
                                 linewidth=1, zorder=4)
        ax2.add_patch(arrow_patch)

    # Add 12 km/h warning line
    ax2.axhline(y=12, color='#ffd449', linestyle='--', linewidth=2,
                label='High Wind (12 km/h)', zorder=2)

    ax2.set_ylabel('Wind (km/h) / Precipitation (mm)', color='#3498db',
                   fontweight='bold', fontsize=12)
    ax2.tick_params(axis='y', labelcolor='#3498db', labelsize=10)

    # Set right axis limits
    max_wind = max(max(wind_gusts), 15)
    max_precip = max(max(rain_precip + snow_precip, default=0), 1)
    ax2.set_ylim(0, max(max_wind, max_precip) * 1.2)

    # Formatting
    ax1.set_xlabel('Time', fontweight='bold', fontsize=12)
    ax1.set_xticks(x)
    ax1.set_xticklabels(hours, rotation=45, ha='right', fontsize=9)
    ax1.grid(True, alpha=0.3, linestyle='-', linewidth=0.5, zorder=0)

    # Title
    plt.title('24-Hour Weather Forecast', fontsize=16, fontweight='bold', pad=20)

    # Legend (combine all three axes)
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    lines3, labels3 = ax3.get_legend_handles_labels()
    ax1.legend(lines1 + lines2 + lines3, labels1 + labels2 + labels3, loc='upper left',
              fontsize=9, framealpha=0.9, ncol=3)

    plt.tight_layout()

    # Save to buffer
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
    buf.seek(0)
    plt.close()

    return buf


# ========================================
# MAIN
# ========================================
def main():
    current_time = datetime.now(PACIFIC)

    # ========================================
    # FETCH DATA
    # ========================================
    print("Fetching weather from OpenWeather One Call 3.0...")
    params = {
        "lat": LAT,
        "lon": LON,
        "appid": OPENWEATHER_API_KEY,
        "units": "metric",
        "exclude": "minutely,alerts"
    }
    resp = requests.get(OPENWEATHER_URL, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    # Current
    current = data['current']
    current_temp = current['temp']
    current_humidity = current['humidity']
    current_pressure = current['pressure']  # hPa
    current_desc = current['weather'][0]['description'].title()
    wind_speed_kmh = current['wind_speed'] * MS_TO_KMH
    wind_deg = current.get('wind_deg')
    wind_gust_kmh = current.get('wind_gust', 0) * MS_TO_KMH
    current_cardinal = get_cardinal(wind_deg)

    # Today
    today = data['daily'][0]
    high_temp = today['temp']['max']
    low_temp = today['temp']['min']
    rain_today = today.get('rain', 0)
    snow_today = today.get('snow', 0)
    total_precip = rain_today + snow_today

    # Sunrise / Sunset
    sunrise_time = convert_to_pst(today['sunrise']).strftime("%I:%M %p")
    sunset_time = convert_to_pst(today['sunset']).strftime("%I:%M %p")

    # 24-Hour Forecast
    hourly_24 = []
    for h in data['hourly']:
        dt = convert_to_pst(h['dt'])
        if (dt - current_time).total_seconds() / 3600 > 24:
            break
        hourly_24.append({
            'time': dt,
            'temp': h['temp'],
            'cond': h['weather'][0]['main'],
            'wind_kmh': h['wind_speed'] * MS_TO_KMH,
            'gust_kmh': h.get('wind_gust', 0) * MS_TO_KMH,
            'dir': get_cardinal(h.get('wind_deg')),
            'icon': h['weather'][0]['icon']
        })

    current_wind = hourly_24[0] if hourly_24 else None
    peak_wind = max(hourly_24, key=lambda x: x['wind_kmh']) if hourly_24 else None

    # Wind changes
    wind_changes = []
    for i in range(1, len(hourly_24)):
        diff = hourly_24[i]['wind_kmh'] - hourly_24[i - 1]['wind_kmh']
        if abs(diff) >= 2.5:
            wind_changes.append({
                'time': hourly_24[i]['time'],
                'change': diff,
                'from': hourly_24[i - 1]['wind_kmh'],
                'to': hourly_24[i]['wind_kmh'],
                'dir': hourly_24[i]['dir']
            })

    # 7-Day Forecast
    seven_day = data['daily'][1:8]

    # Generate 24-hour chart
    print("Generating 24-hour chart...")
    chart_buffer = create_24hour_chart(data['hourly'])

    # ========================================
    # BUILD HTML EMAIL
    # ========================================
    quote = get_quote()

    email_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{font-family: 'Segoe UI', sans-serif; line-height: 1.6; color: #333; max-width: 900px; margin: 0 auto; background: #f5f5f5; padding: 15px;}}
        .container {{background: white; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); overflow: hidden;}}
        .header {{background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px 20px; text-align: center;}}
        .header h1 {{margin: 0; font-size: 28px; font-weight: 700;}}
        .header p {{margin: 8px 0 0; font-size: 14px; opacity: 0.95;}}
        .section {{padding: 20px; border-bottom: 1px solid #eee;}}
        .section:last-child {{border-bottom: none;}}
        .section h2 {{color: #667eea; font-size: 18px; margin: 0 0 15px; font-weight: 600; border-bottom: 2px solid #667eea; padding-bottom: 6px;}}

        /* LIVE BUTTON */
        .live-button {{display: inline-block; background: linear-gradient(135deg, #ff6b6b 0%, #ee5a24 100%); color: white; padding: 12px 24px; border-radius: 25px; text-decoration: none; font-weight: 700; font-size: 16px; margin: 15px 5px; box-shadow: 0 4px 15px rgba(255,107,107,0.4); transition: all 0.3s ease;}}
        .live-button:hover {{transform: translateY(-2px); box-shadow: 0 6px 20px rgba(255,107,107,0.6);}}

        /* METRIC CARDS */
        .current-grid, .forecast-grid {{display: flex; flex-wrap: wrap; gap: 12px; justify-content: space-between;}}
        .metric {{flex: 1; min-width: 120px; background: #f8f9fa; padding: 12px; border-radius: 8px; border-left: 4px solid #667eea; text-align: center;}}
        .metric-label {{font-size: 11px; color: #666; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px;}}
        .metric-value {{font-size: 20px; font-weight: 700; color: #333;}}

        /* 24-HOUR CHART */
        .chart-section {{text-align: center; padding: 20px;}}
        .chart-section img {{max-width: 100%; height: auto; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);}}

        .wind-peak {{background: #fff3cd; border-left: 4px solid #ffc107; padding: 12px; border-radius: 8px; margin: 12px 0; font-weight: 500; font-size: 14px;}}
        .wind-change {{background: #f8f9fa; padding: 10px; border-radius: 6px; margin: 8px 0; border-left: 3px solid #28a745; font-size: 13px;}}
        .wind-change.decrease {{border-left-color: #17a2b8;}}
        .wind-change-time {{font-weight: 600; color: #667eea;}}

        .scroll-table {{max-height: 400px; overflow-y: auto; border: 1px solid #eee; border-radius: 8px; margin: 12px 0;}}
        .combined-hourly {{width: 100%; border-collapse: collapse; font-size: 12px;}}
        .combined-hourly th {{background: #667eea; color: white; padding: 8px; text-align: left; font-weight: 600;}}
        .combined-hourly td {{padding: 6px 8px; border-bottom: 1px solid #eee;}}
        .combined-hourly tr:hover {{background: #f8f9fa;}}
        .hour-time {{font-weight: 600; color: #667eea;}}
        .temp-cell {{font-weight: 600;}}
        .wind-cell {{color: #667eea; font-weight: 500;}}

        /* 7-DAY: HORIZONTAL SCROLL */
        .seven-day-container {{overflow-x: auto; white-space: nowrap; padding: 10px 0;}}
        .seven-day {{display: inline-flex; gap: 12px;}}
        .day-card {{background: #f8f9fa; border-radius: 10px; padding: 12px; min-width: 120px; text-align: center; box-shadow: 0 2px 6px rgba(0,0,0,0.05);}}
        .day-date {{font-weight: 600; color: #667eea; font-size: 13px;}}
        .day-icon {{width: 40px; height: 40px; margin: 6px auto;}}
        .day-temps {{font-size: 16px; font-weight: 600; margin: 6px 0;}}
        .day-high {{color: #d35400;}}
        .day-low {{color: #2980b9;}}
        .day-wind {{font-size: 12px; color: #555;}}
        .day-precip {{font-size: 11px; color: #27ae60; margin-top: 4px;}}

        .footer {{text-align: center; padding: 20px; color: #777; font-size: 13px; background: #f8f9fa;}}
        .quote-box {{background: rgba(255,255,255,0.3); backdrop-filter: blur(10px); border-radius: 10px; padding: 15px 20px; margin-top: 15px; font-style: italic; border-left: 4px solid rgba(255,255,255,0.9);}}
        .source {{font-size: 10px; color: #aaa; margin-top: 10px;}}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>DAILY WEATHER REPORT</h1>
            <h2>BIRCHDALE - MURPHY - SCHROEDER CREEK </h2>
            <p>{current_time.strftime("%A, %B %d, %Y at %I:%M %p %Z")}</p>
            <a href="https://birchdale-weather.netlify.app/" class="live-button">\U0001f324\ufe0f Click for Live Conditions</a>
            <a href="https://birchdale-weather.netlify.app/lake.html" class="live-button">\U0001f30a Lake Level Data</a>
            <p class="source">It's only a forecast, always rely on your own senses! Built by Roy - Powered by OpenWeather API</p>
            <div class="quote-box">{quote}</div>
        </div>

        <!-- CURRENT CONDITIONS -->
        <div class="section">
            <h2>Current Conditions</h2>
            <div class="current-grid">
                <div class="metric"><div class="metric-label">Temperature</div><div class="metric-value">{current_temp:.1f}\u00b0C</div></div>
                <div class="metric"><div class="metric-label">Conditions</div><div class="metric-value">{current_desc}</div></div>
                <div class="metric"><div class="metric-label">Humidity</div><div class="metric-value">{current_humidity}%</div></div>
                <div class="metric"><div class="metric-label">Pressure</div><div class="metric-value">{current_pressure} hPa</div></div>
                <div class="metric"><div class="metric-label">Wind</div><div class="metric-value">{wind_speed_kmh:.1f} km/h</div></div>
                <div class="metric"><div class="metric-label">Wind Gusts</div><div class="metric-value">{wind_gust_kmh:.1f} km/h</div></div>
                <div class="metric"><div class="metric-label">Direction</div><div class="metric-value">{current_cardinal}</div></div>
            </div>
        </div>

        <!-- TODAY'S FORECAST -->
        <div class="section">
            <h2>Today's Forecast</h2>
            <div class="forecast-grid">
                <div class="metric"><div class="metric-label">High</div><div class="metric-value">{high_temp:.1f}\u00b0C</div></div>
                <div class="metric"><div class="metric-label">Low</div><div class="metric-value">{low_temp:.1f}\u00b0C</div></div>
                <div class="metric"><div class="metric-label">Precipitation</div><div class="metric-value">
                    """
    if total_precip > 0:
        email_html += f"{total_precip:.1f} mm"
        if snow_today > 0:
            email_html += f" (incl. {snow_today:.1f} mm snow)"
    else:
        email_html += "None expected"
    email_html += f"""
                </div></div>
                <div class="metric"><div class="metric-label">Sunrise</div><div class="metric-value">{sunrise_time}</div></div>
                <div class="metric"><div class="metric-label">Sunset</div><div class="metric-value">{sunset_time}</div></div>
            </div>
        </div>

        <!-- 24-HOUR CHART -->
        <div class="section chart-section">
            <h2>24-Hour Weather Chart</h2>
            <img src="cid:weather_chart" alt="24-Hour Weather Forecast">
            <p style="font-size: 11px; color: #999; margin-top: 10px;">Temperature, Wind Speed & Gusts, Precipitation, Wind Direction</p>
        </div>

        <!-- WIND -->
        <div class="section">
            <h2>Wind (Next 24 Hours)</h2>
            """
    if peak_wind:
        email_html += f'<div class="wind-peak">Peak: {peak_wind["wind_kmh"]:.1f} km/h {peak_wind["dir"]} at {peak_wind["time"].strftime("%I:%M %p")}</div>'

    if wind_changes:
        email_html += f"<p><strong>{len(wind_changes)} change(s):</strong></p>"
        for c in wind_changes:
            t = c['time'].strftime("%I:%M %p")
            note = " <span style='color:#999;'>(tonight)</span>" if (c[
                                                                         'time'] - current_time).total_seconds() / 3600 > 12 else ""
            sign = "+" if c['change'] > 0 else "-"
            cls = "wind-change" if c['change'] > 0 else "wind-change decrease"
            email_html += f'<div class="{cls}"><span class="wind-change-time">{t}:</span> {sign}{abs(c["change"]):.1f} km/h{note}<br>{c["from"]:.1f} to {c["to"]:.1f} km/h from {c["dir"]}</div>'
    else:
        email_html += '<div style="background:#f8f9fa;padding:14px;border-radius:8px;"><p>No major changes.</p>'
        if current_wind: email_html += f"<p>Steady ~{current_wind['wind_kmh']:.1f} km/h</p>"
        email_html += "</div>"
    email_html += """</div>

        <!-- 24-HOUR TABLE -->
        <div class="section">
            <h2>24-Hour Forecast</h2>
            <div class="scroll-table">
                <table class="combined-hourly">
                    <thead><tr><th>Time</th><th>Temp</th><th>Cond</th><th>Wind km/h</th><th>Gust km/h</th><th>Dir</th></tr></thead>
                    <tbody>"""
    for h in hourly_24:
        email_html += f'<tr><td class="hour-time">{h["time"].strftime("%I:%M %p")}</td><td class="temp-cell">{h["temp"]:.1f}\u00b0C</td><td>{h["cond"]}</td><td class="wind-cell">{h["wind_kmh"]:.1f}</td><td class="wind-cell">{h["gust_kmh"]:.1f}</td><td class="wind-cell">{h["dir"]}</td></tr>'
    email_html += """</tbody></table></div>
        </div>

        <!-- 7-DAY: HORIZONTAL SCROLL -->
        <div class="section">
            <h2>7-Day Forecast</h2>
            <div class="seven-day-container">
                <div class="seven-day">"""
    for day in seven_day:
        dt = convert_to_pst(day['dt'])
        high = day['temp']['max']
        low = day['temp']['min']
        wind = day['wind_speed'] * MS_TO_KMH
        wind_dir = get_cardinal(day.get('wind_deg'))
        icon = day['weather'][0]['icon']
        cond = day['weather'][0]['description'].title()
        precip = day.get('rain', 0) + day.get('snow', 0)
        email_html += f"""
                    <div class="day-card">
                        <div class="day-date">{dt.strftime('%a %b %d')}</div>
                        <img src="{ICON_BASE}/{icon}@2x.png" class="day-icon" alt="{cond}">
                        <div class="day-temps">
                            <span class="day-high">{high:.0f}\u00b0</span> / <span class="day-low">{low:.0f}\u00b0</span>
                        </div>
                        <div class="day-wind">{wind:.0f} km/h {wind_dir}</div>"""
        if precip > 0:
            email_html += f'<div class="day-precip">Precip: {precip:.1f} mm</div>'
        email_html += f"<div style='font-size:10px; color:#777; margin-top:3px;'>{cond}</div></div>"
    email_html += """</div>
            </div>
        </div>

        <!-- FOOTER -->
        <div class="footer">
            <p><strong>Have a great day!</strong></p>
            <p style="font-size:11px;color:#999;margin-top:8px;">Automated 24-hour report for Birchdale</p>
             <p style="font-size:11px;color:#999;margin-top:8px;">Reply to this email to be removed from it</p>
        </div>
    </div>
</body>
</html>"""

    # ========================================
    # SEND EMAIL
    # ========================================
    print("Sending email...")
    msg = MIMEMultipart('related')
    msg['From'] = EMAIL_FROM
    msg['To'] = ', '.join([e.strip() for e in EMAIL_TO.split(',')])
    msg['Subject'] = f"Birchdale Weather \u2022 {current_time.strftime('%B %d, %Y')}"

    # Attach HTML
    msg.attach(MIMEText(email_html, 'html'))

    # Attach chart image
    chart_image = MIMEImage(chart_buffer.read())
    chart_image.add_header('Content-ID', '<weather_chart>')
    msg.attach(chart_image)

    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.send_message(msg)
        print("Email sent successfully!")
    except Exception as e:
        print(f"Email failed: {e}")

    print("Report complete!")


if __name__ == '__main__':
    main()
