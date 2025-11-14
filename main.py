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
        
        # Plot actual data - PURE THIN LINE (no dots)
        ax.plot(daily_data['Date'], daily_data["Queen's Bay (ft)"], 
                color='#e74c3c', linewidth=1, 
                label='2025 Actual', zorder=10)
        
        # Plot forecast line and add forecast point marker
        forecast_data = daily_data[daily_data['Forecast Level'].notna()].tail(1)
        if not forecast_data.empty:
            try:
                forecast_level = float(forecast_data['Forecast Level'].iloc[0])
                forecast_date = pd.to_datetime(forecast_data['Forecast Date'].iloc[0])
                last_date = daily_data['Date'].iloc[-1]
                last_level = daily_data["Queen's Bay (ft)"].iloc[-1]
                
                # Forecast line
                ax.plot([last_date, forecast_date], [last_level, forecast_level],
                       'k--', linewidth=1.5, zorder=9)
                ax.plot([last_date, forecast_date], [last_level, forecast_level],
                       'k^', markersize=6, zorder=9, label='Forecast Line')
                
                # BLACK DOT on forecast date - this will persist in data
                ax.plot(forecast_date, forecast_level, 'o', color='black', markersize=8, 
                       zorder=11, label='Forecast Point', markeredgewidth=2, markeredgecolor='yellow')
                
                ax.annotate(f'Forecast\n{forecast_level} ft\n{forecast_date.strftime("%b %d")}',
                           xy=(forecast_date, forecast_level), xytext=(10, 10),
                           textcoords='offset points', fontsize=9,
                           bbox=dict(boxstyle='round,pad=0.5', facecolor='yellow', alpha=0.7),
                           arrowprops=dict(arrowstyle='->', lw=1.5))
                
                print(f"  ✓ Added forecast point at {forecast_date.strftime('%Y-%m-%d')}: {forecast_level} ft")
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
    """Generate index.html in public directory (for Netlify)"""
    print("\n[HTML] Generating public/index.html...")
    
    # Read the template from public/index.html
    template_path = 'public/index.html'
    if not os.path.exists(template_path):
        print(f"  ✗ Template not found at {template_path}")
        return
    
    with open(template_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    print(f"  ✓ Read template ({len(html_content)} characters)")
    
    # CRITICAL: Remove any existing lake sections first (prevents duplicates)
    import re
    
    # Remove any existing lake section (everything from lake comment to its closing div)
    lake_pattern = r'<!-- KOOTENAY LAKE LEVELS SECTION -->.*?</div>\s*</div>\s*</div>'
    html_content = re.sub(lake_pattern, '', html_content, flags=re.DOTALL)
    
    # Also remove any orphaned divs between </script> and </body>
    script_end = html_content.rfind('</script>')
    body_start = html_content.rfind('</body>')
    
    if script_end > 0 and body_start > script_end:
        between_content = html_content[script_end + 9:body_start]
        # Clean up any stray divs, keeping only whitespace
        cleaned_between = re.sub(r'</div>\s*', '', between_content)
        html_content = html_content[:script_end + 9] + cleaned_between + html_content[body_start:]
    
    print("  ✓ Cleaned up any existing lake sections")
    
    # Add lake level section AFTER the seven-day forecast section (not before </body>)
    if lake_data:
        print(f"  ✓ Lake data available: Queen's Bay = {lake_data.get('queens_ft', 'N/A')} ft")
        lake_section = f"""
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
            lake_section += f"""
          <div style="background: rgba(255,255,255,0.15); padding: 15px; border-radius: 8px; text-align: center; min-width: 140px; flex: 0 1 auto;">
            <div style="font-size: 11px; opacity: 0.9; margin-bottom: 5px; text-transform: uppercase;">FORECAST</div>
            <div style="font-size: 28px; font-weight: 700;">{lake_data['forecast_level']}</div>
            <div style="font-size: 13px; opacity: 0.8;">feet</div>
            <div style="font-size: 11px; opacity: 0.7; margin-top: 3px;">{lake_data.get('forecast_trend', '').title()} by {lake_data.get('forecast_date', '')}</div>
          </div>
"""
        
        if 'discharge_cfs' in lake_data and lake_data.get('discharge_cfs'):
            lake_section += f"""
          <div style="background: rgba(255,255,255,0.15); padding: 15px; border-radius: 8px; text-align: center; min-width: 140px; flex: 0 1 auto;">
            <div style="font-size: 11px; opacity: 0.9; margin-bottom: 5px; text-transform: uppercase;">DISCHARGE</div>
            <div style="font-size: 28px; font-weight: 700;">{lake_data['discharge_cfs']}</div>
            <div style="font-size: 13px; opacity: 0.8;">cfs</div>
            <div style="font-size: 11px; opacity: 0.7; margin-top: 3px;">{lake_data.get('discharge_location', '')} - {lake_data.get('discharge_date', '')}</div>
          </div>
"""
        
        lake_section += """
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
        
        # Insert lake section INSIDE the container div, before the footer
        # Look for the footer div or the last section inside container
        import re
        
        # Find the footer section
        footer_match = re.search(r'<div class="footer">', html_content)
        
        if footer_match:
            # Insert right before the footer
            insert_pos = footer_match.start()
            html_content = html_content[:insert_pos] + lake_section + '\n    ' + html_content[insert_pos:]
            print("  ✓ Lake section inserted before footer (inside container)")
        else:
            # Fallback: look for closing container div
            # The container should close right before </body>
            # Find the second-to-last </div> before </body>
            body_pos = html_content.rfind('</body>')
            if body_pos > 0:
                # Get the last 500 chars before </body>
                search_area = html_content[max(0, body_pos-500):body_pos]
                
                # Find all </div> positions
                div_positions = [m.start() for m in re.finditer(r'</div>', search_area)]
                
                if len(div_positions) >= 2:
                    # Insert before the second-to-last </div> (which should be container closing)
                    insert_relative = div_positions[-2]
                    insert_absolute = max(0, body_pos-500) + insert_relative
                    html_content = html_content[:insert_absolute] + '\n' + lake_section + '\n    ' + html_content[insert_absolute:]
                    print("  ✓ Lake section inserted inside container (before closing div)")
                else:
                    # Last resort: just before </body>
                    html_content = html_content.replace('</body>', f'{lake_section}\n</body>', 1)
                    print("  ⚠ Lake section added before </body> (fallback)")
            else:
                html_content += lake_section
                print("  ⚠ Lake section appended to end")
    
    # Write back to public/index.html (Netlify will deploy this)
    with open('public/index.html', 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"  ✓ public/index.html updated successfully ({len(html_content)} characters)")
    
    # Double-check the lake section was added
    if lake_data and 'KOOTENAY LAKE' in html_content:
        print("  ✓ Confirmed: Lake section is in the HTML")
    elif lake_data:
        print("  ✗ WARNING: Lake section may not have been added!")
    else:
        print("  ℹ No lake data to add")

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
