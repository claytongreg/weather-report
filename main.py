#!/usr/bin/env python3
"""
Birchdale Weather Report - Enhanced with Kootenay Lake Levels
Fetches weather, lake data, updates Google Sheets, generates chart, and updates index.html
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
    
    # Handle both file path and JSON string for credentials
    if os.path.exists(CREDENTIALS_FILE):
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    else:
        # If credentials are provided as environment variable (base64 encoded JSON)
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
        
        # Convert to DataFrame
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
        
        # Parse data
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
        
        if df is None or len(df) < 2:
            print("  ⚠ Not enough data for chart yet (need at least 2 days)")
            return False
        
        # Process data
        df['Scrape Time'] = pd.to_datetime(df['Scrape Time'], errors='coerce')
        df['Date'] = df['Scrape Time'].dt.date
        df['Date'] = pd.to_datetime(df['Date'])
        df["Queen's Bay (ft)"] = pd.to_numeric(df["Queen's Bay (ft)"], errors='coerce')
        
        # Get daily averages
        daily_data = df.groupby('Date').agg({
            "Queen's Bay (ft)": 'mean',
            'Forecast Level': 'first',
            'Forecast Date': 'first'
        }).reset_index()
        
        daily_data = daily_data.dropna(subset=["Queen's Bay (ft)"])
        
        if len(daily_data) < 2:
            print("  ⚠ Not enough valid data points")
            return False
        
        print(f"  ✓ Plotting {len(daily_data)} days of data")
        
        # Create figure
        fig, ax = plt.subplots(figsize=(12, 6))
        
        # Plot data
        ax.plot(daily_data['Date'], daily_data["Queen's Bay (ft)"], 
                color='#e74c3c', linewidth=3, marker='o', markersize=6, 
                label='2025 Actual', zorder=10)
        
        # Add forecast
        forecast_data = daily_data[daily_data['Forecast Level'].notna()].tail(1)
        if not forecast_data.empty:
            try:
                forecast_level = float(forecast_data['Forecast Level'].iloc[0])
                forecast_date = pd.to_datetime(forecast_data['Forecast Date'].iloc[0])
                last_date = daily_data['Date'].iloc[-1]
                last_level = daily_data["Queen's Bay (ft)"].iloc[-1]
                
                ax.plot([last_date, forecast_date], [last_level, forecast_level],
                       'k--', linewidth=2, zorder=9, label='Forecast')
                ax.plot([last_date, forecast_date], [last_level, forecast_level],
                       'k^', markersize=8, zorder=9)
                
                ax.annotate(f'Forecast\n{forecast_level} ft\n{forecast_date.strftime("%b %d")}',
                           xy=(forecast_date, forecast_level), xytext=(10, 10),
                           textcoords='offset points', fontsize=9,
                           bbox=dict(boxstyle='round,pad=0.5', facecolor='yellow', alpha=0.7),
                           arrowprops=dict(arrowstyle='->', lw=1.5))
            except:
                pass
        
        # Reference lines
        ax.axhline(y=1752, color='red', linestyle=':', linewidth=2, alpha=0.7, 
                   label='Flood Level (1752 ft)')
        ax.axhline(y=1754.24, color='darkred', linestyle='--', linewidth=1.5, alpha=0.6,
                   label='Record High (1754.24 ft)')
        ax.axhspan(1740, 1750, alpha=0.08, color='gray', label='Historical Range', zorder=1)
        
        # Formatting
        ax.set_title('Kootenay Lake Levels - Queens Bay', fontsize=16, fontweight='bold', pad=15)
        ax.set_xlabel('Date', fontsize=11, fontweight='bold')
        ax.set_ylabel('Elevation (feet)', fontsize=11, fontweight='bold')
        ax.grid(True, alpha=0.3, linestyle='-', linewidth=0.5)
        ax.set_axisbelow(True)
        
        current_level = daily_data["Queen's Bay (ft)"].iloc[-1]
        ax.set_ylim(max(1737, current_level - 8), min(1755, current_level + 8))
        
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
        if len(daily_data) > 7:
            ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, len(daily_data)//7)))
        plt.xticks(rotation=45, ha='right')
        ax.legend(loc='upper left', fontsize=9, framealpha=0.9)
        
        plt.tight_layout()
        
        # Save to public directory
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
# WEATHER FUNCTIONS
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
    """Generate the index.html file with weather and lake data"""
    print("\n[HTML] Generating index.html...")
    
    # Read the template
    with open('public/index.html', 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    # Add lake level section before </body> tag if lake data exists
    if lake_data:
        lake_section = f"""
    <!-- KOOTENAY LAKE LEVELS SECTION -->
    <div class="seven-day-section" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white;">
      <h2 class="forecast-title" style="color: white;">🌊 Kootenay Lake Levels</h2>
      
      <div style="background: rgba(255,255,255,0.1); border-radius: 12px; padding: 20px; margin-bottom: 20px;">
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px;">
          <div style="background: rgba(255,255,255,0.15); padding: 15px; border-radius: 8px; text-align: center;">
            <div style="font-size: 12px; opacity: 0.9; margin-bottom: 5px;">QUEEN'S BAY</div>
            <div style="font-size: 32px; font-weight: 700;">{lake_data.get('queens_ft', 'N/A')}</div>
            <div style="font-size: 14px; opacity: 0.8;">feet ({lake_data.get('queens_m', 'N/A')} m)</div>
            <div style="font-size: 11px; opacity: 0.7; margin-top: 5px;">{lake_data.get('queens_updated', '')}</div>
          </div>
          
          <div style="background: rgba(255,255,255,0.15); padding: 15px; border-radius: 8px; text-align: center;">
            <div style="font-size: 12px; opacity: 0.9; margin-bottom: 5px;">NELSON</div>
            <div style="font-size: 32px; font-weight: 700;">{lake_data.get('nelson_ft', 'N/A')}</div>
            <div style="font-size: 14px; opacity: 0.8;">feet ({lake_data.get('nelson_m', 'N/A')} m)</div>
            <div style="font-size: 11px; opacity: 0.7; margin-top: 5px;">{lake_data.get('nelson_updated', '')}</div>
          </div>
"""
        
        if 'forecast_level' in lake_data and lake_data.get('forecast_level'):
            lake_section += f"""
          <div style="background: rgba(255,255,255,0.15); padding: 15px; border-radius: 8px; text-align: center;">
            <div style="font-size: 12px; opacity: 0.9; margin-bottom: 5px;">FORECAST</div>
            <div style="font-size: 32px; font-weight: 700;">{lake_data['forecast_level']}</div>
            <div style="font-size: 14px; opacity: 0.8;">feet</div>
            <div style="font-size: 11px; opacity: 0.7; margin-top: 5px;">{lake_data.get('forecast_trend', '').title()} by {lake_data.get('forecast_date', '')}</div>
          </div>
"""
        
        if 'discharge_cfs' in lake_data and lake_data.get('discharge_cfs'):
            lake_section += f"""
          <div style="background: rgba(255,255,255,0.15); padding: 15px; border-radius: 8px; text-align: center;">
            <div style="font-size: 12px; opacity: 0.9; margin-bottom: 5px;">DISCHARGE</div>
            <div style="font-size: 32px; font-weight: 700;">{lake_data['discharge_cfs']}</div>
            <div style="font-size: 14px; opacity: 0.8;">cfs</div>
            <div style="font-size: 11px; opacity: 0.7; margin-top: 5px;">{lake_data.get('discharge_location', '')} - {lake_data.get('discharge_date', '')}</div>
          </div>
"""
        
        lake_section += """
        </div>
        
        <!-- Lake Chart -->
        <div style="background: white; border-radius: 12px; padding: 15px; margin-top: 20px;">
          <img src="lake_chart.png" alt="Kootenay Lake Level Chart" style="width: 100%; height: auto; border-radius: 8px;">
        </div>
        
        <div style="text-align: center; margin-top: 15px; font-size: 12px; opacity: 0.8;">
          Data from FortisBC | Updated Daily at 6 AM PST
        </div>
      </div>
    </div>
"""
        
        # Insert before </body>
        if '</body>' in html_content:
            html_content = html_content.replace('</body>', f'{lake_section}\n</body>')
        else:
            # If no </body> tag, append at end
            html_content += lake_section
    
    # Write the updated HTML
    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print("  ✓ index.html generated successfully")

# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    print("=" * 70)
    print("BIRCHDALE WEATHER & LAKE MONITOR")
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
        
        # Generate chart
        create_lake_chart()
        
        # Generate HTML
        generate_index_html(weather_data, lake_data)
        
        print("\n" + "=" * 70)
        print("✓ ALL TASKS COMPLETED SUCCESSFULLY")
        print("=" * 70)
        
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        raise

if __name__ == '__main__':
    main()
