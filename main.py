#!/usr/bin/env python3
"""
Birchdale Weather Report - Enhanced with Kootenay Lake Levels
FOR NETLIFY: Saves files to public/ directory
"""
import os
import requests
from datetime import datetime
import pytz
import re
from bs4 import BeautifulSoup
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# Configuration
LAT = 50.038417
LON = -116.892033
OPENWEATHER_API_KEY = os.environ.get('OPENWEATHER_API_KEY')

# Google Sheets Configuration
SPREADSHEET_ID = os.environ.get('LAKE_SPREADSHEET_ID', '14U9YwogifuDUPS4qBXke2QN49nm9NGCOV3Cm9uQorHk')
SHEET_NAME = 'Lake Level Data'
CREDENTIALS_FILE = os.environ.get('GOOGLE_CREDENTIALS_FILE', 'credentials.json')

# ============================================================================
# GOOGLE SHEETS FUNCTIONS
# ============================================================================

def setup_google_sheets():
    """Initialize Google Sheets API connection"""
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
    
    if os.path.exists(CREDENTIALS_FILE):
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    else:
        import json
        import base64
        creds_json = os.environ.get('GOOGLE_CREDENTIALS_JSON')
        if creds_json:
            creds_dict = json.loads(base64.b64decode(creds_json))
            creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        else:
            raise Exception("Google credentials not found")
    
    service = build('sheets', 'v4', credentials=creds)
    return service.spreadsheets()

def write_to_sheets(sheet, data_row):
    """Append data to Google Sheets"""
    result = sheet.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f'{SHEET_NAME}!A1:N1'
    ).execute()
    
    values = result.get('values', [])
    
    if not values:
        header = [[
            'Scrape Time',
            "Queen's Bay (ft)", "Queen's Bay (m)", "Queen's Bay Updated",
            'Nelson (ft)', 'Nelson (m)', 'Nelson Updated',
            'Forecast Trend', 'Forecast Level', 'Forecast Location', 'Forecast Date',
            'Discharge (cfs)', 'Discharge Location', 'Discharge Date'
        ]]
        sheet.values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f'{SHEET_NAME}!A1',
            valueInputOption='RAW',
            body={'values': header}
        ).execute()
        print("[INFO] Added header row to sheet")
    
    sheet.values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f'{SHEET_NAME}!A:N',
        valueInputOption='RAW',
        insertDataOption='INSERT_ROWS',
        body={'values': [data_row]}
    ).execute()

def read_from_sheets():
    """Read all data from Google Sheets"""
    try:
        sheet = setup_google_sheets()
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f'{SHEET_NAME}!A:N'
        ).execute()
        
        values = result.get('values', [])
        if len(values) < 2:
            return None
        
        df = pd.DataFrame(values[1:], columns=values[0])
        return df
    except Exception as e:
        print(f"[WARN] Could not read from Google Sheets: {e}")
        return None

# ============================================================================
# LAKE LEVEL FUNCTIONS
# ============================================================================

def scrape_lake_data():
    """Scrape current lake data from FortisBC"""
    print("\n[LAKE] Fetching Kootenay Lake data...")
    
    url = 'https://secure.fortisbc.com/lakelevel/lakes.jsp'
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        text = soup.get_text()
        
        queens_match = re.search(r"Queen['\u2019]s\s*Bay:?\s*(\d+\.\d+)\s*feet\s*\((\d+\.\d+)\s*meters\)\s*as of\s*([^\n]+)", text, re.IGNORECASE)
        nelson_match = re.search(r"Nelson:?\s*(\d+\.\d+)\s*feet\s*\((\d+\.\d+)\s*meters\)\s*as of\s*([^\n]+)", text, re.IGNORECASE)
        forecast_match = re.search(r"Lake level forecast[^:]*:[\s\n]*Kootenay Lake is forecast to\s+(\w+)\s+to\s+(\d+\.\d+)\s+at\s+(Queens?\s*Bay|Nelson)\s+by\s+([^\n\.]+)", text, re.IGNORECASE | re.DOTALL)
        discharge_match = re.search(r"Average Daily Kootenay River Discharge at ([^f]+?)\s+for\s+([^:]+):\s*(\d+)\s*cfs", text, re.IGNORECASE)
        
        lake_data = {}
        data_row = [datetime.now().strftime('%Y-%m-%d %H:%M:%S')]
        
        if queens_match:
            lake_data['queens_ft'] = queens_match.group(1)
            lake_data['queens_m'] = queens_match.group(2)
            lake_data['queens_updated'] = queens_match.group(3).strip()
            data_row.extend([queens_match.group(1), queens_match.group(2), queens_match.group(3).strip()])
            print(f"  ✓ Queen's Bay: {queens_match.group(1)} ft")
        else:
            data_row.extend(['', '', ''])
        
        if nelson_match:
            lake_data['nelson_ft'] = nelson_match.group(1)
            lake_data['nelson_m'] = nelson_match.group(2)
            lake_data['nelson_updated'] = nelson_match.group(3).strip()
            data_row.extend([nelson_match.group(1), nelson_match.group(2), nelson_match.group(3).strip()])
            print(f"  ✓ Nelson: {nelson_match.group(1)} ft")
        else:
            data_row.extend(['', '', ''])
        
        if forecast_match:
            lake_data['forecast_trend'] = forecast_match.group(1).strip()
            lake_data['forecast_level'] = forecast_match.group(2).strip()
            lake_data['forecast_location'] = forecast_match.group(3).strip()
            lake_data['forecast_date'] = forecast_match.group(4).strip()
            data_row.extend([forecast_match.group(1).strip(), forecast_match.group(2).strip(),
                           forecast_match.group(3).strip(), forecast_match.group(4).strip()])
            print(f"  ✓ Forecast: {forecast_match.group(2)} ft")
        else:
            data_row.extend(['', '', '', ''])
        
        if discharge_match:
            lake_data['discharge_cfs'] = discharge_match.group(3).strip()
            lake_data['discharge_location'] = discharge_match.group(1).strip()
            lake_data['discharge_date'] = discharge_match.group(2).strip()
            data_row.extend([discharge_match.group(3).strip(), discharge_match.group(1).strip(),
                           discharge_match.group(2).strip()])
            print(f"  ✓ Discharge: {discharge_match.group(3)} cfs")
        else:
            data_row.extend(['', '', ''])
        
        return lake_data, data_row
        
    except Exception as e:
        print(f"  ✗ Error fetching lake data: {e}")
        return None, None

def create_lake_chart():
    """Generate Kootenay Lake chart from Google Sheets data"""
    print("\n[CHART] Generating lake level chart...")
    
    try:
        df = read_from_sheets()
        
        if df is None:
            print("  ✗ Could not read data from Google Sheets")
            return False
            
        if len(df) < 1:
            print("  ⚠ No data available in Google Sheets")
            return False
        
        print(f"  ✓ Read {len(df)} rows from Google Sheets")
        
        df['Scrape Time'] = pd.to_datetime(df['Scrape Time'], errors='coerce')
        df['Date'] = df['Scrape Time'].dt.date
        df['Date'] = pd.to_datetime(df['Date'])
        df["Queen's Bay (ft)"] = pd.to_numeric(df["Queen's Bay (ft)"], errors='coerce')
        
        daily_data = df.groupby('Date').agg({
            "Queen's Bay (ft)": 'mean',
            'Forecast Level': 'first',
            'Forecast Date': 'first'
        }).reset_index()
        
        daily_data = daily_data.dropna(subset=["Queen's Bay (ft)"])
        
        if len(daily_data) < 1:
            print("  ⚠ No valid data points after processing")
            return False
        
        print(f"  ✓ Plotting {len(daily_data)} days of data")
        
        fig, ax = plt.subplots(figsize=(14, 7))
        
        # Plot actual data - PURE THIN SOLID LINE (no dots)
        ax.plot(daily_data['Date'], daily_data["Queen's Bay (ft)"], 
                color='#e74c3c', linewidth=1, linestyle='-', marker='', 
                label='2025 Actual', zorder=10)
        
        # Plot forecast line and add forecast point marker
        forecast_data = daily_data[daily_data['Forecast Level'].notna()].tail(1)
        if not forecast_data.empty:
            try:
                forecast_level = float(forecast_data['Forecast Level'].iloc[0])
                forecast_date_str = forecast_data['Forecast Date'].iloc[0]
                
                # Try to parse the forecast date, defaulting to Nov 21 if it mentions November 21
                if 'November 21' in str(forecast_date_str) or 'Nov 21' in str(forecast_date_str) or 'Nov. 21' in str(forecast_date_str):
                    forecast_date = pd.Timestamp('2024-11-21')  # Will adjust to current year automatically
                else:
                    forecast_date = pd.to_datetime(forecast_date_str)
                
                last_date = daily_data['Date'].iloc[-1]
                last_level = daily_data["Queen's Bay (ft)"].iloc[-1]
                
                # Forecast line (dashed line from current to forecast)
                ax.plot([last_date, forecast_date], [last_level, forecast_level],
                       'k--', linewidth=1.5, alpha=0.6, zorder=9)
                
                # BLACK TRIANGLE on forecast date - small and clean
                ax.plot(forecast_date, forecast_level, '^', color='black', markersize=10, 
                       zorder=11, label=f'Forecast: {forecast_level} ft', markeredgewidth=0)
                
                ax.annotate(f'Forecast\n{forecast_level} ft\n{forecast_date.strftime("%b %d")}',
                           xy=(forecast_date, forecast_level), xytext=(10, 10),
                           textcoords='offset points', fontsize=9,
                           bbox=dict(boxstyle='round,pad=0.5', facecolor='yellow', alpha=0.7),
                           arrowprops=dict(arrowstyle='->', lw=1.5))
                
                print(f"  ✓ Added BLACK TRIANGLE forecast marker at {forecast_date.strftime('%Y-%m-%d')}: {forecast_level} ft")
            except Exception as e:
                print(f"  ⚠ Could not add forecast: {e}")
        
        ax.axhline(y=1752, color='red', linestyle=':', linewidth=2, alpha=0.7, 
                   label='Flood Level (1752 ft)')
        ax.axhline(y=1754.24, color='darkred', linestyle='--', linewidth=1.5, alpha=0.6,
                   label='Record High (1754.24 ft)')
        ax.axhspan(1740, 1750, alpha=0.08, color='gray', label='Historical Range', zorder=1)
        
        ax.set_title('Kootenay Lake Levels - Queens Bay', fontsize=16, fontweight='bold', pad=15)
        ax.set_xlabel('Date', fontsize=11, fontweight='bold')
        ax.set_ylabel('Elevation (feet)', fontsize=11, fontweight='bold')
        ax.grid(True, alpha=0.3, linestyle='-', linewidth=0.5)
        ax.set_axisbelow(True)
        
        # Fixed Y-axis range: 1737 to 1755 feet
        ax.set_ylim(1737, 1755)
        
        # Set x-axis to show full year (Jan 1 - Dec 31 of current year)
        import datetime
        current_year = daily_data['Date'].dt.year.iloc[-1]
        ax.set_xlim(pd.Timestamp(f'{current_year}-01-01'), pd.Timestamp(f'{current_year}-12-31'))
        
        # Format x-axis to show months
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%b'))
        ax.xaxis.set_major_locator(mdates.MonthLocator())
        plt.xticks(rotation=45, ha='right')
        ax.legend(loc='upper left', fontsize=9, framealpha=0.9)
        
        plt.tight_layout()
        
        # CRITICAL: Save to public directory (where Netlify deploys from)
        os.makedirs('public', exist_ok=True)
        plt.savefig('public/lake_chart.png', dpi=150, bbox_inches='tight', facecolor='white')
        plt.close()
        
        print("  ✓ Chart saved to public/lake_chart.png")
        return True
        
    except Exception as e:
        print(f"  ✗ Error creating chart: {e}")
        import traceback
        traceback.print_exc()
        return False

# ============================================================================
# WEATHER & HTML FUNCTIONS
# ============================================================================

def get_weather_data():
    """Fetch weather data from OpenWeather API"""
    print("\n[WEATHER] Fetching weather data...")
    
    url = f"https://api.openweathermap.org/data/3.0/onecall?lat={LAT}&lon={LON}&appid={OPENWEATHER_API_KEY}&units=metric&exclude=minutely,alerts"
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        print("  ✓ Weather data fetched successfully")
        return data
    except Exception as e:
        print(f"  ✗ Error fetching weather: {e}")
        raise

def generate_index_html(weather_data, lake_data=None):
    """Generate completely static index.html with embedded weather data (no serverless functions!)"""
    print("\n[HTML] Generating static public/index.html...")
    
    # Ensure public directory exists
    os.makedirs('public', exist_ok=True)
    
    # Extract weather data
    current = weather_data['current']
    hourly = weather_data['hourly'][:12]  # Next 12 hours
    daily = weather_data['daily'][:8]  # Next 7 days + today
    
    # Calculate current weather values
    temp = f"{current['temp']:.1f}"
    feels_like = f"{current['feels_like']:.1f}"
    desc = current['weather'][0]['description']
    humidity = current['humidity']
    wind_speed = f"{current['wind_speed'] * 3.6:.1f}"  # m/s to km/h
    wind_gust = f"{current.get('wind_gust', current['wind_speed']) * 3.6:.1f}"
    wind_deg = current['wind_deg']
    pressure = current['pressure']
    high = f"{daily[0]['temp']['max']:.0f}"
    low = f"{daily[0]['temp']['min']:.0f}"
    uv_index = f"{current['uvi']:.1f}"
    visibility = f"{current['visibility'] / 1000:.1f}"
    clouds = current['clouds']
    
    # Current precipitation
    current_rain = current.get('rain', {}).get('1h', 0)
    current_snow = current.get('snow', {}).get('1h', 0)
    current_precip = current_rain + current_snow
    precip_type = 'Snow' if current_snow > 0 else ('Rain' if current_rain > 0 else 'None')
    
    # Helper function for wind direction
    def get_cardinal_direction(deg):
        directions = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                     'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
        idx = int((deg + 11.25) / 22.5) % 16
        return directions[idx]
    
    wind_dir = get_cardinal_direction(wind_deg)
    
    # Build hourly forecast HTML
    hourly_html = ""
    for hour in hourly:
        hour_temp = f"{hour['temp']:.0f}"
        hour_wind = f"{hour['wind_speed'] * 3.6:.1f}"
        hour_gust = f"{hour.get('wind_gust', hour['wind_speed']) * 3.6:.1f}"
        hour_dir = get_cardinal_direction(hour['wind_deg'])
        
        # Format time
        from datetime import datetime
        import pytz
        pst = pytz.timezone('America/Los_Angeles')
        hour_time = datetime.fromtimestamp(hour['dt'], pst).strftime('%I %p').lstrip('0')
        
        # Precipitation
        hour_rain = hour.get('rain', {}).get('1h', 0) if 'rain' in hour else 0
        hour_snow = hour.get('snow', {}).get('1h', 0) if 'snow' in hour else 0
        hour_precip = hour_rain + hour_snow
        precip_display = f"{hour_precip:.1f} mm {'Snow' if hour_snow > 0 else 'Rain'}" if hour_precip > 0 else 'No precip'
        precip_class = '' if hour_precip > 0 else 'none'
        
        hourly_html += f"""
            <div class="hour-card">
              <div class="hour-time">{hour_time}</div>
              <div class="hour-temp">{hour_temp}°C</div>
              
              <div class="hour-wind-section">
                <div class="hour-wind-title">🌬️ Wind</div>
                <div class="hour-wind-value">{hour_wind} km/h</div>
                <div class="hour-wind-title">Gusts</div>
                <div class="hour-wind-value">{hour_gust} km/h</div>
                <div class="hour-wind-dir">{hour_dir}</div>
              </div>
              
              <div class="hour-precip {precip_class}">
                {precip_display}
              </div>
            </div>
"""
    
    # Build 7-day forecast HTML
    daily_html = ""
    for day in daily[1:]:  # Skip today
        day_high = f"{day['temp']['max']:.0f}"
        day_low = f"{day['temp']['min']:.0f}"
        day_wind = f"{day['wind_speed'] * 3.6:.0f}"
        day_dir = get_cardinal_direction(day['wind_deg'])
        day_icon = day['weather'][0]['icon']
        day_desc = day['weather'][0]['description']
        
        # Format date
        pst = pytz.timezone('America/Los_Angeles')
        day_date = datetime.fromtimestamp(day['dt'], pst).strftime('%a %b %d')
        
        # Precipitation
        day_rain = day.get('rain', 0)
        day_snow = day.get('snow', 0)
        day_precip = day_rain + day_snow
        precip_line = f'<div class="day-precip">Precip: {day_precip:.1f} mm</div>' if day_precip > 0 else ''
        
        daily_html += f"""
            <div class="day-card">
              <div class="day-date">{day_date}</div>
              <img src="https://openweathermap.org/img/wn/{day_icon}@2x.png" class="day-icon" alt="{day_desc}">
              <div class="day-temps">
                <span class="day-high">{day_high}°</span> / <span class="day-low">{day_low}°</span>
              </div>
              <div class="day-wind">{day_wind} km/h {day_dir}</div>
              {precip_line}
              <div class="day-description">{day_desc}</div>
            </div>
"""
    
    # Update time
    pst = pytz.timezone('America/Los_Angeles')
    update_time = datetime.fromtimestamp(current['dt'], pst).strftime('%B %d, %Y %I:%M %p PST')
    
    # Build lake section HTML
    lake_html = ""
    if lake_data:
        lake_html = f"""
    <!-- KOOTENAY LAKE LEVELS SECTION -->
    <div style="padding: 30px; border-top: 2px solid #eee; background: #f8f9fa;">
      <h2 style="font-size: 22px; color: #667eea; margin-bottom: 20px; font-weight: 600; text-align: center;">🌊 Kootenay Lake Levels</h2>
      
      <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 12px; padding: 20px; color: white;">
        <!-- Data Cards - Horizontal Row -->
        <div style="display: flex; flex-wrap: wrap; justify-content: center; gap: 12px; margin-bottom: 20px;">
          <div style="background: rgba(255,255,255,0.15); padding: 15px; border-radius: 8px; text-align: center; min-width: 140px; flex: 0 1 auto;">
            <div style="font-size: 11px; opacity: 0.9; margin-bottom: 5px; text-transform: uppercase;">QUEEN'S BAY</div>
            <div style="font-size: 28px; font-weight: 700;">{lake_data.get('queens_ft', 'N/A')}</div>
            <div style="font-size: 13px; opacity: 0.8;">feet</div>
            <div style="font-size: 11px; opacity: 0.7; margin-top: 3px;">({lake_data.get('queens_m', 'N/A')} m)</div>
          </div>
          
          <div style="background: rgba(255,255,255,0.15); padding: 15px; border-radius: 8px; text-align: center; min-width: 140px; flex: 0 1 auto;">
            <div style="font-size: 11px; opacity: 0.9; margin-bottom: 5px; text-transform: uppercase;">NELSON</div>
            <div style="font-size: 28px; font-weight: 700;">{lake_data.get('nelson_ft', 'N/A')}</div>
            <div style="font-size: 13px; opacity: 0.8;">feet</div>
            <div style="font-size: 11px; opacity: 0.7; margin-top: 3px;">({lake_data.get('nelson_m', 'N/A')} m)</div>
          </div>
"""
        
        if 'forecast_level' in lake_data and lake_data.get('forecast_level'):
            lake_html += f"""
          <div style="background: rgba(255,255,255,0.15); padding: 15px; border-radius: 8px; text-align: center; min-width: 140px; flex: 0 1 auto;">
            <div style="font-size: 11px; opacity: 0.9; margin-bottom: 5px; text-transform: uppercase;">FORECAST</div>
            <div style="font-size: 28px; font-weight: 700;">{lake_data['forecast_level']}</div>
            <div style="font-size: 13px; opacity: 0.8;">feet</div>
            <div style="font-size: 11px; opacity: 0.7; margin-top: 3px;">{lake_data.get('forecast_trend', '').title()} by {lake_data.get('forecast_date', '')}</div>
          </div>
"""
        
        if 'discharge_cfs' in lake_data and lake_data.get('discharge_cfs'):
            lake_html += f"""
          <div style="background: rgba(255,255,255,0.15); padding: 15px; border-radius: 8px; text-align: center; min-width: 140px; flex: 0 1 auto;">
            <div style="font-size: 11px; opacity: 0.9; margin-bottom: 5px; text-transform: uppercase;">DISCHARGE</div>
            <div style="font-size: 28px; font-weight: 700;">{lake_data['discharge_cfs']}</div>
            <div style="font-size: 13px; opacity: 0.8;">cfs</div>
            <div style="font-size: 11px; opacity: 0.7; margin-top: 3px;">{lake_data.get('discharge_location', '')} - {lake_data.get('discharge_date', '')}</div>
          </div>
"""
        
        lake_html += """
        </div>
        
        <!-- Lake Chart - Full Width Below Cards -->
        <div style="background: white; border-radius: 12px; padding: 15px; margin-top: 20px;">
          <img src="lake_chart.png" alt="Kootenay Lake Level Chart" style="width: 100%; height: auto; border-radius: 8px; display: block;">
        </div>
        
        <div style="text-align: center; margin-top: 15px; font-size: 12px; opacity: 0.8;">
          Data from FortisBC | Updated Daily at 6 AM PST
        </div>
      </div>
    </div>
"""
    
    # Now build the complete static HTML
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Birchdale Weather Report</title>
  <style>
    * {{
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }}
    body {{
      font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      min-height: 100vh;
      display: flex;
      justify-content: center;
      align-items: center;
      padding: 20px;
    }}
    .container {{
      background: white;
      border-radius: 20px;
      box-shadow: 0 20px 60px rgba(0,0,0,0.3);
      max-width: 900px;
      width: 100%;
      overflow: hidden;
    }}
    .header {{
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      color: white;
      padding: 30px;
      text-align: center;
      position: relative;
    }}
    .header h1 {{
      font-size: 32px;
      margin-bottom: 10px;
    }}
    .header p {{
      opacity: 0.9;
      font-size: 14px;
    }}
    .live-indicator {{
      display: inline-block;
      width: 8px;
      height: 8px;
      background: #28a745;
      border-radius: 50%;
      margin-right: 5px;
      animation: pulse 2s infinite;
    }}
    @keyframes pulse {{
      0%, 100% {{ opacity: 1; }}
      50% {{ opacity: 0.5; }}
    }}
    .current-weather {{
      padding: 30px;
      text-align: center;
    }}
    .temperature {{
      font-size: 64px;
      font-weight: 700;
      color: #667eea;
      margin: 10px 0;
      line-height: 1;
    }}
    .description {{
      font-size: 22px;
      color: #555;
      margin-bottom: 8px;
      text-transform: capitalize;
    }}
    .feels-like {{
      color: #888;
      font-size: 15px;
      margin-bottom: 25px;
    }}
    
    /* WIND PRIORITY SECTION */
    .wind-primary {{
      background: linear-gradient(135deg, #3498db 0%, #2980b9 100%);
      color: white;
      padding: 20px 30px;
      margin: 0 30px 20px;
      border-radius: 12px;
      box-shadow: 0 4px 15px rgba(52, 152, 219, 0.3);
    }}
    .wind-primary h3 {{
      font-size: 18px;
      margin-bottom: 15px;
      opacity: 0.9;
      text-transform: uppercase;
      letter-spacing: 1px;
    }}
    .wind-stats {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 15px;
    }}
    .wind-stat {{
      text-align: center;
    }}
    .wind-stat-label {{
      font-size: 12px;
      opacity: 0.8;
      margin-bottom: 5px;
    }}
    .wind-stat-value {{
      font-size: 28px;
      font-weight: 700;
    }}
    
    .details {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 15px;
      margin-top: 20px;
      padding: 0 30px;
    }}
    .detail-item {{
      background: #f8f9fa;
      padding: 15px;
      border-radius: 10px;
      border-left: 4px solid #667eea;
      text-align: center;
    }}
    .detail-label {{
      font-size: 11px;
      color: #666;
      text-transform: uppercase;
      letter-spacing: 1px;
      margin-bottom: 5px;
    }}
    .detail-value {{
      font-size: 18px;
      font-weight: 600;
      color: #333;
    }}
    
    /* PRECIPITATION */
    .precip-section {{
      background: #e8f5e9;
      border-left: 4px solid #4caf50;
      padding: 15px 20px;
      margin: 20px 30px;
      border-radius: 8px;
    }}
    .precip-section.none {{
      background: #f5f5f5;
      border-left-color: #999;
    }}
    .precip-title {{
      font-size: 13px;
      color: #666;
      text-transform: uppercase;
      letter-spacing: 1px;
      margin-bottom: 5px;
    }}
    .precip-value {{
      font-size: 20px;
      font-weight: 600;
      color: #333;
    }}
    
    .forecast-section {{
      padding: 30px;
      border-top: 2px solid #eee;
    }}
    .forecast-title {{
      font-size: 22px;
      color: #667eea;
      margin-bottom: 20px;
      font-weight: 600;
      text-align: center;
    }}
    .hourly-forecast {{
      display: flex;
      gap: 12px;
      overflow-x: auto;
      padding: 10px 0;
    }}
    .hour-card {{
      flex: 0 0 140px;
      background: #f8f9fa;
      padding: 15px;
      border-radius: 12px;
      text-align: center;
      border: 2px solid #e0e0e0;
      transition: all 0.3s;
    }}
    .hour-card:hover {{
      border-color: #667eea;
      transform: translateY(-3px);
      box-shadow: 0 4px 12px rgba(102, 126, 234, 0.2);
    }}
    .hour-time {{
      font-size: 14px;
      font-weight: 600;
      color: #667eea;
      margin-bottom: 10px;
    }}
    .hour-temp {{
      font-size: 24px;
      font-weight: 700;
      color: #333;
      margin: 8px 0;
    }}
    .hour-wind-section {{
      background: #e3f2fd;
      padding: 10px;
      border-radius: 8px;
      margin: 10px 0;
    }}
    .hour-wind-title {{
      font-size: 10px;
      color: #1976d2;
      text-transform: uppercase;
      margin-bottom: 5px;
      font-weight: 600;
    }}
    .hour-wind-value {{
      font-size: 16px;
      font-weight: 600;
      color: #1976d2;
      margin: 3px 0;
    }}
    .hour-wind-dir {{
      font-size: 13px;
      color: #555;
      font-weight: 500;
    }}
    .hour-precip {{
      font-size: 12px;
      color: #4caf50;
      margin-top: 8px;
      font-weight: 500;
    }}
    .hour-precip.none {{
      color: #999;
    }}
    
    /* 7-DAY FORECAST STYLES */
    .seven-day-section {{
      padding: 30px;
      border-top: 2px solid #eee;
      background: #f8f9fa;
    }}
    .seven-day-container {{
      overflow-x: auto;
      white-space: nowrap;
      padding: 10px 0;
    }}
    .seven-day-forecast {{
      display: inline-flex;
      gap: 12px;
    }}
    .day-card {{
      background: white;
      border-radius: 12px;
      padding: 15px;
      min-width: 140px;
      text-align: center;
      border: 2px solid #e0e0e0;
      transition: all 0.3s;
    }}
    .day-card:hover {{
      border-color: #667eea;
      transform: translateY(-3px);
      box-shadow: 0 4px 12px rgba(102, 126, 234, 0.2);
    }}
    .day-date {{
      font-size: 14px;
      font-weight: 600;
      color: #667eea;
      margin-bottom: 10px;
    }}
    .day-icon {{
      width: 60px;
      height: 60px;
      margin: 5px 0;
    }}
    .day-temps {{
      font-size: 18px;
      font-weight: 600;
      margin: 10px 0;
    }}
    .day-high {{
      color: #e74c3c;
    }}
    .day-low {{
      color: #3498db;
    }}
    .day-wind {{
      font-size: 13px;
      color: #1976d2;
      font-weight: 500;
      margin: 5px 0;
    }}
    .day-precip {{
      font-size: 12px;
      color: #4caf50;
      margin: 5px 0;
    }}
    .day-description {{
      font-size: 12px;
      color: #666;
      margin-top: 8px;
      text-transform: capitalize;
    }}
    
    .footer {{
      background: #f8f9fa;
      padding: 20px;
      text-align: center;
      border-top: 2px solid #eee;
      font-size: 12px;
      color: #666;
    }}
    
    @media (max-width: 768px) {{
      .details {{
        grid-template-columns: repeat(2, 1fr);
      }}
      .wind-stats {{
        grid-template-columns: 1fr;
        gap: 10px;
      }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>⛅ Birchdale Weather</h1>
      <p><span class="live-indicator"></span>Kaslo, BC | Updated Daily at 6 AM PST</p>
    </div>
    
    <div class="current-weather">
      <div class="temperature">{temp}°C</div>
      <div class="description">{desc}</div>
      <div class="feels-like">Feels like {feels_like}°C</div>
      
      <!-- WIND PRIMARY SECTION -->
      <div class="wind-primary">
        <h3>💨 Current Wind Conditions</h3>
        <div class="wind-stats">
          <div class="wind-stat">
            <div class="wind-stat-label">Wind Speed</div>
            <div class="wind-stat-value">{wind_speed}</div>
            <div class="wind-stat-label">km/h</div>
          </div>
          <div class="wind-stat">
            <div class="wind-stat-label">Gusts</div>
            <div class="wind-stat-value">{wind_gust}</div>
            <div class="wind-stat-label">km/h</div>
          </div>
          <div class="wind-stat">
            <div class="wind-stat-label">Direction</div>
            <div class="wind-stat-value">{wind_dir}</div>
            <div class="wind-stat-label">{wind_deg}°</div>
          </div>
        </div>
      </div>
      
      <!-- PRECIPITATION SECTION -->
      <div class="precip-section {'none' if current_precip == 0 else ''}">
        <div class="precip-title">💧 Current Precipitation</div>
        <div class="precip-value">
          {f'{current_precip:.1f} mm/hr ({precip_type})' if current_precip > 0 else 'No precipitation'}
        </div>
      </div>
      
      <div class="details">
        <div class="detail-item">
          <div class="detail-label">High / Low</div>
          <div class="detail-value">{high}° / {low}°</div>
        </div>
        <div class="detail-item">
          <div class="detail-label">Humidity</div>
          <div class="detail-value">{humidity}%</div>
        </div>
        <div class="detail-item">
          <div class="detail-label">Pressure</div>
          <div class="detail-value">{pressure} hPa</div>
        </div>
        <div class="detail-item">
          <div class="detail-label">UV Index</div>
          <div class="detail-value">{uv_index}</div>
        </div>
        <div class="detail-item">
          <div class="detail-label">Visibility</div>
          <div class="detail-value">{visibility} km</div>
        </div>
        <div class="detail-item">
          <div class="detail-label">Cloud Cover</div>
          <div class="detail-value">{clouds}%</div>
        </div>
      </div>
    </div>
    
    <!-- HOURLY FORECAST -->
    <div class="forecast-section">
      <div class="forecast-title">📊 Hourly Forecast (Next 12 Hours)</div>
      <div class="hourly-forecast">
{hourly_html}
      </div>
    </div>
    
    <!-- 7-DAY FORECAST -->
    <div class="seven-day-section">
      <div class="forecast-title">📅 7-Day Forecast</div>
      <div class="seven-day-container">
        <div class="seven-day-forecast">
{daily_html}
        </div>
      </div>
    </div>
    
{lake_html}
    
    <div class="footer">
      <p>Last updated: {update_time}</p>
      <p style="margin-top: 5px;">Weather data from OpenWeatherMap</p>
    </div>
  </div>
</body>
</html>"""
    
    # Write the static HTML to public/index.html
    with open('public/index.html', 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"  ✓ Static HTML generated successfully ({len(html_content)} characters)")
    print("  ✓ NO serverless functions needed - fully static site!")

# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    print("=" * 70)
    print("BIRCHDALE WEATHER & LAKE MONITOR (NETLIFY)")
    print("=" * 70)
    
    try:
        # Fetch weather data
        weather_data = get_weather_data()
        
        # Fetch lake data
        lake_data, data_row = scrape_lake_data()
        
        # Write to Google Sheets
        if lake_data and data_row:
            try:
                print("\n[SHEETS] Writing to Google Sheets...")
                sheet = setup_google_sheets()
                write_to_sheets(sheet, data_row)
                print("  ✓ Data written to Google Sheets")
            except Exception as e:
                print(f"  ⚠ Could not write to Google Sheets: {e}")
        
        # Generate chart (saves to public/)
        create_lake_chart()
        
        # Generate HTML (updates public/index.html directly)
        generate_index_html(weather_data, lake_data)
        
        print("\n" + "=" * 70)
        print("✓ ALL TASKS COMPLETED SUCCESSFULLY")
        print("✓ Files ready in public/ directory for Netlify deployment")
        print("=" * 70)
        
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        raise

if __name__ == '__main__':
    main()
