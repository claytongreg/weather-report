#!/usr/bin/env python3
"""
Birchdale Weather & Lake Monitor
- Weather stays on main page with real-time API calls (dynamic)
- Lake data moves to separate page (static, updated daily)
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
import time

# Configuration
LAT = 50.038417
LON = -116.892033
OPENWEATHER_API_KEY = os.environ.get('OPENWEATHER_API_KEY')

# Google Sheets Configuration
SPREADSHEET_ID = os.environ.get('LAKE_SPREADSHEET_ID', '14U9YwogifuDUPS4qBXke2QN49nm9NGCOV3Cm9uQorHk')
SHEET_NAME = 'Lake Level Data'
CREDENTIALS_FILE = os.environ.get('GOOGLE_CREDENTIALS_FILE', 'credentials.json')


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def safe_date_convert(month_day, year):
    """Safely convert month-day string to date, handling Feb 29"""
    try:
        return pd.to_datetime(f'{month_day}-{year}', format='%m-%d-%Y')
    except:
        # If date is invalid (e.g., Feb 29 in non-leap year), use Feb 28
        if month_day == '02-29':
            return pd.to_datetime(f'02-28-{year}', format='%m-%d-%Y')
        return None


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
            print(f"  ✓ Forecast: {forecast_match.group(2)} ft by {forecast_match.group(4)}")
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
    """Generate Kootenay Lake chart with PDF-style historical range using Google Sheets data"""
    print("\n[CHART] Generating lake level chart...")
    
    # CRITICAL FIX: Delete existing PNG to ensure Git detects changes
    chart_path = 'public/lake_chart.png'
    if os.path.exists(chart_path):
        try:
            old_size = os.path.getsize(chart_path)
            old_time = datetime.fromtimestamp(os.path.getmtime(chart_path)).strftime('%Y-%m-%d %H:%M:%S')
            os.remove(chart_path)
            print(f"  ✓ Removed existing chart (was {old_size:,} bytes from {old_time})")
            time.sleep(0.2)
        except Exception as e:
            print(f"  ⚠ Could not remove existing chart: {e}")
    
    try:
        # Read ALL data from Google Sheets
        print("\n[STEP 1] Reading data from Google Sheets...")
        df = read_from_sheets()
        
        if df is None or len(df) < 1:
            print("  ✗ Could not read data from Google Sheets")
            return False
        
        print(f"  ✓ Read {len(df)} rows from Google Sheets")
        
        # Parse the data
        df['Scrape Time'] = pd.to_datetime(df['Scrape Time'], errors='coerce')
        df['Date'] = df['Scrape Time'].dt.date
        df['Date'] = pd.to_datetime(df['Date'])
        
        # Get lake level data - handle both old column name and new
        if "Queen's Bay (ft)" in df.columns:
            df['level_feet'] = pd.to_numeric(df["Queen's Bay (ft)"], errors='coerce')
        elif 'level_meters' in df.columns:
            # If data has level_meters column (from historical import), it's actually in feet
            df['level_feet'] = pd.to_numeric(df['level_meters'], errors='coerce')
        else:
            print("  ✗ Could not find lake level column in data")
            return False
        
        df['year'] = df['Date'].dt.year
        df['month'] = df['Date'].dt.month
        df['day'] = df['Date'].dt.day
        df['month_day'] = df['Date'].dt.strftime('%m-%d')
        
        # Parse forecast data
        df['Forecast Level'] = pd.to_numeric(df['Forecast Level'], errors='coerce')
        df['Forecast Date'] = df['Forecast Date'].astype(str)
        
        # Remove rows without lake level data
        df = df.dropna(subset=['level_feet'])
        
        if len(df) < 1:
            print("  ✗ No valid lake level data found")
            return False
        
        print(f"  ✓ Processed {len(df)} data points")
        print(f"    Date range: {df['Date'].min()} to {df['Date'].max()}")
        print(f"    Level range: {df['level_feet'].min():.1f} to {df['level_feet'].max():.1f} ft")
        
        # Extract forecast markers
        print("\n[STEP 2] Extracting forecast markers...")
        forecast_markers = []
        forecast_data = df[
            (df['Forecast Level'].notna()) & 
            (df['Forecast Date'].str.len() > 3)
        ][['Forecast Date', 'Forecast Level']].drop_duplicates()
        
        for _, row in forecast_data.iterrows():
            try:
                forecast_date = pd.to_datetime(row['Forecast Date'])
                forecast_level = float(row['Forecast Level'])
                forecast_markers.append({'date': forecast_date, 'level': forecast_level})
            except:
                pass
        
        if forecast_markers:
            print(f"  ✓ Found {len(forecast_markers)} forecast marker(s)")
        else:
            print(f"  → No forecast markers found")
        
        # Create figure
        print("\n[STEP 3] Creating chart...")
        fig, ax = plt.subplots(figsize=(16, 9), dpi=100)
        
        current_year = datetime.now().year
        date_range = pd.date_range(f'{current_year}-01-01', f'{current_year}-12-31', freq='D')
        
        # Define the years to plot
        highest_years = [2012, 2018]
        lowest_years = [2008, 2002]
        recent_years = [2020, 2021, 2022, 2023, 2024]
        
        # Calculate historical range (1991-2024) for shading
        range_df = df[(df['year'] >= 1991) & (df['year'] <= 2024)].copy()
        if len(range_df) > 0:
            historical_range = range_df.groupby('month_day')['level_feet'].agg(['min', 'max']).reset_index()
            
            # Convert to plot dates
            historical_range['plot_date'] = historical_range['month_day'].apply(
                lambda x: safe_date_convert(x, current_year)
            )
            historical_range = historical_range.dropna(subset=['plot_date']).sort_values('plot_date')
            
            # Plot shaded historical range
            ax.fill_between(historical_range['plot_date'], 
                            historical_range['min'], 
                            historical_range['max'],
                            color='#CCCCCC', alpha=0.5, label='Historical Range (1991-2024)', zorder=1)
            print(f"  ✓ Plotted historical range shading")
        
        # Define colors and line widths
        colors = {
            2012: '#00FF00', 2018: '#90EE90',
            2008: '#FFA500', 2002: '#FFD700',
            2020: '#00BFFF', 2021: '#1E90FF', 2022: '#0000FF', 
            2023: '#808080', 2024: '#FF00FF',
            current_year: '#FF0000'
        }
        
        linewidths = {
            2012: 2.5, 2018: 2, 2008: 2, 2002: 2,
            2020: 1.5, 2021: 1.5, 2022: 1.5, 2023: 1.5, 2024: 1.5,
            current_year: 3
        }
        
        # Plot all selected years
        all_years = highest_years + lowest_years + recent_years + [current_year]
        lines_plotted = 0
        
        for year in all_years:
            year_data = df[df['year'] == year].copy()
            if len(year_data) > 0:
                year_data['plot_date'] = year_data['month_day'].apply(
                    lambda x: safe_date_convert(x, current_year)
                )
                year_data = year_data.dropna(subset=['plot_date']).sort_values('plot_date')
                
                if len(year_data) > 0:
                    ax.plot(year_data['plot_date'], year_data['level_feet'],
                           color=colors.get(year, '#000000'),
                           linewidth=linewidths.get(year, 1.5),
                           label=str(year),
                           zorder=3 if year == current_year else 2)
                    lines_plotted += 1
                    print(f"    ✓ Plotted {year}: {len(year_data)} points")
        
        print(f"  ✓ Total lines plotted: {lines_plotted}")
        
        # Add ALL forecast markers (black triangles)
        if forecast_markers:
            print(f"  → Adding {len(forecast_markers)} forecast marker(s)...")
            for i, forecast in enumerate(forecast_markers):
                forecast_month_day = forecast['date'].strftime('%m-%d')
                forecast_plot_date = safe_date_convert(forecast_month_day, current_year)
                
                if forecast_plot_date:
                    label = 'Fortis Forecast' if i == 0 else None
                    ax.scatter([forecast_plot_date], [forecast['level']], 
                              marker='^', s=150, color='black', 
                              label=label, 
                              zorder=4, edgecolors='white', linewidths=1.5)
            print(f"  ✓ Added {len(forecast_markers)} forecast marker(s)")
        
        # Add reference lines
        ax.axhline(y=1752, color='#FF0000', linestyle='--', linewidth=1.5, 
                   alpha=0.7, label='Flood Level (1752 ft)', zorder=1)
        ax.axhline(y=1745, color='#8B0000', linestyle=':', linewidth=1.5,
                   alpha=0.7, label='Treaty Max (Nelson)', zorder=1)
        
        # Add text annotation for record high
        ax.text(0.98, 0.98, 'Record High since Duncan Dam completed 1967 >> 1754.24 ft in 1974',
                transform=ax.transAxes, fontsize=9, ha='right', va='top',
                bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
        
        # Styling
        ax.set_xlabel('', fontsize=13, fontweight='bold')
        ax.set_ylabel('daily elevation (feet) @ Queens Bay', fontsize=12, fontweight='bold')
        ax.set_title('KOOTENAY LAKE LEVELS', fontsize=18, fontweight='bold', pad=20)
        ax.grid(True, alpha=0.3, linestyle='-', linewidth=0.5)
        ax.legend(loc='upper left', fontsize=9, framealpha=0.95, ncol=3)
        
        # Format x-axis
        ax.xaxis.set_major_locator(mdates.MonthLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%d-%b'))
        ax.xaxis.set_minor_locator(mdates.WeekdayLocator(interval=1))
        plt.xticks(rotation=45, ha='right')
        
        # Set axis limits
        ax.set_ylim(1737, 1755)
        ax.set_xlim(date_range[0], date_range[-1])
        
        plt.tight_layout()
        
        # CRITICAL: Ensure directory exists
        os.makedirs('public', exist_ok=True)
        
        # Save with MAXIMUM robustness
        print(f"\n[STEP 4] Saving chart to {chart_path}...")
        plt.savefig(chart_path, dpi=150, bbox_inches='tight', facecolor='white')
        plt.close('all')
        
        # Force matplotlib to flush
        import gc
        gc.collect()
        time.sleep(0.3)
        
        # VERIFY FILE WAS CREATED
        if os.path.exists(chart_path):
            file_size = os.path.getsize(chart_path)
            mod_time = datetime.fromtimestamp(os.path.getmtime(chart_path)).strftime('%Y-%m-%d %H:%M:%S')
            print(f"  ✓ Chart saved successfully!")
            print(f"  ✓ Path: {chart_path}")
            print(f"  ✓ Size: {file_size:,} bytes")
            print(f"  ✓ Modified: {mod_time}")
            
            # Double check it's a valid PNG
            with open(chart_path, 'rb') as f:
                png_header = f.read(8)
                if png_header[:4] == b'\x89PNG':
                    print(f"  ✓ Valid PNG file confirmed")
                else:
                    print(f"  ✗ WARNING: File may be corrupted!")
                    return False
        else:
            print(f"  ✗ ERROR: File not created at {chart_path}!")
            return False
        
        print(f"\n✓ Chart generation complete with {lines_plotted} year lines!")
        return True
        
    except Exception as e:
        print(f"  ✗ Error creating chart: {e}")
        import traceback
        traceback.print_exc()
        return False

def generate_lake_page(lake_data):
    """Generate STATIC lake.html page - NO DUPLICATION!"""
    print("\n[HTML] Generating lake page (static)...")
    
    os.makedirs('public', exist_ok=True)
    
    # Build data cards HTML
    cards_html = ""
    
    if lake_data:
        # Queen's Bay card
        if 'queens_ft' in lake_data:
            cards_html += f"""
        <div class="data-card">
          <div class="data-card-label">QUEEN'S BAY</div>
          <div class="data-card-value">{lake_data['queens_ft']}</div>
          <div class="data-card-unit">feet</div>
          <div class="data-card-subtext">({lake_data.get('queens_m', 'N/A')} m)</div>
          <div class="data-card-subtext">Updated: {lake_data.get('queens_updated', 'N/A')}</div>
        </div>
"""
        
        # Nelson card
        if 'nelson_ft' in lake_data:
            cards_html += f"""
        <div class="data-card">
          <div class="data-card-label">NELSON</div>
          <div class="data-card-value">{lake_data['nelson_ft']}</div>
          <div class="data-card-unit">feet</div>
          <div class="data-card-subtext">({lake_data.get('nelson_m', 'N/A')} m)</div>
          <div class="data-card-subtext">Updated: {lake_data.get('nelson_updated', 'N/A')}</div>
        </div>
"""
        
        # Forecast card
        if 'forecast_level' in lake_data and lake_data.get('forecast_level'):
            cards_html += f"""
        <div class="data-card">
          <div class="data-card-label">FORECAST</div>
          <div class="data-card-value">{lake_data['forecast_level']}</div>
          <div class="data-card-unit">feet</div>
          <div class="data-card-subtext">{lake_data.get('forecast_trend', '').title()} by {lake_data.get('forecast_date', 'N/A')}</div>
        </div>
"""
        
        # Discharge card
        if 'discharge_cfs' in lake_data and lake_data.get('discharge_cfs'):
            cards_html += f"""
        <div class="data-card">
          <div class="data-card-label">DISCHARGE</div>
          <div class="data-card-value">{lake_data['discharge_cfs']}</div>
          <div class="data-card-unit">cfs</div>
          <div class="data-card-subtext">{lake_data.get('discharge_location', 'N/A')}</div>
          <div class="data-card-subtext">{lake_data.get('discharge_date', 'N/A')}</div>
        </div>
"""
    
    # Update time
    pst = pytz.timezone('America/Los_Angeles')
    update_time = datetime.now(pst).strftime('%B %d, %Y at %I:%M %p PST')
    
    # Generate complete HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Kootenay Lake Levels - Birchdale</title>
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
      padding: 20px;
    }}
    .container {{
      max-width: 1200px;
      margin: 0 auto;
      background: white;
      border-radius: 20px;
      box-shadow: 0 20px 60px rgba(0,0,0,0.3);
      overflow: hidden;
    }}
    .header {{
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      color: white;
      padding: 30px;
      text-align: center;
    }}
    .header h1 {{
      font-size: 32px;
      margin-bottom: 10px;
    }}
    .header p {{
      opacity: 0.9;
      font-size: 14px;
    }}
    .back-link {{
      display: inline-block;
      margin-top: 15px;
      padding: 10px 20px;
      background: rgba(255,255,255,0.2);
      border-radius: 8px;
      color: white;
      text-decoration: none;
      transition: all 0.3s;
    }}
    .back-link:hover {{
      background: rgba(255,255,255,0.3);
      transform: translateY(-2px);
    }}
    .lake-content {{
      padding: 30px;
    }}
    .data-cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 20px;
      margin-bottom: 30px;
    }}
    .data-card {{
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      color: white;
      padding: 20px;
      border-radius: 12px;
      text-align: center;
      box-shadow: 0 4px 15px rgba(102, 126, 234, 0.3);
    }}
    .data-card-label {{
      font-size: 12px;
      opacity: 0.9;
      text-transform: uppercase;
      letter-spacing: 1px;
      margin-bottom: 10px;
    }}
    .data-card-value {{
      font-size: 36px;
      font-weight: 700;
      margin: 10px 0;
    }}
    .data-card-unit {{
      font-size: 14px;
      opacity: 0.8;
    }}
    .data-card-subtext {{
      font-size: 11px;
      opacity: 0.7;
      margin-top: 5px;
    }}
    .chart-section {{
      background: #f8f9fa;
      padding: 30px;
      border-radius: 12px;
      margin-bottom: 20px;
    }}
    .chart-section h2 {{
      color: #667eea;
      font-size: 24px;
      margin-bottom: 20px;
      text-align: center;
    }}
    .chart-container {{
      background: white;
      padding: 20px;
      border-radius: 12px;
      box-shadow: 0 2px 10px rgba(0,0,0,0.1);
    }}
    .chart-container img {{
      width: 100%;
      height: auto;
      display: block;
      border-radius: 8px;
    }}
    .update-info {{
      text-align: center;
      padding: 20px;
      color: #666;
      font-size: 14px;
      border-top: 2px solid #eee;
    }}
    @media (max-width: 768px) {{
      .data-cards {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>🌊 Kootenay Lake Levels</h1>
      <p>Historical Data & Forecasts</p>
      <a href="index.html" class="back-link">← Back to Weather</a>
    </div>
    
    <div class="lake-content">
      <div class="data-cards">
{cards_html}
      </div>
      
      <div class="chart-section">
        <h2>Historical Lake Level Trend</h2>
        <div class="chart-container">
          <img src="lake_chart.png" alt="Kootenay Lake Level Chart">
        </div>
      </div>
      
      <div class="update-info">
        <p><strong>Data Source:</strong> FortisBC</p>
        <p><strong>Updated:</strong> {update_time}</p>
        <p>Chart updates daily at 6 AM PST</p>
      </div>
    </div>
  </div>
</body>
</html>"""
    
    # Write the file - THIS REPLACES THE ENTIRE FILE (no duplication!)
    with open('public/lake.html', 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"  ✓ Lake page generated: public/lake.html ({len(html)} characters)")
    print("  ✓ NO duplication - file completely replaced each time!")

# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    print("=" * 70)
    print("BIRCHDALE WEATHER & LAKE MONITOR")
    print("=" * 70)
    
    try:
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
        
        # Generate chart with BLACK TRIANGLE forecast marker
        create_lake_chart()
        
        # Generate SEPARATE lake page (no duplication!)
        generate_lake_page(lake_data)
        
        print("\n" + "=" * 70)
        print("✓ ALL TASKS COMPLETED SUCCESSFULLY")
        print("✓ Lake page (static): public/lake.html")
        print("✓ Lake chart: public/lake_chart.png")
        print("✓ Weather page (dynamic): index.html unchanged")
        print("=" * 70)
        
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        raise

if __name__ == '__main__':
    main()
