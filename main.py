#!/usr/bin/env python3
"""
Birchdale Weather Report - Enhanced with Kootenay Lake Levels
Fetches weather data, lake levels, generates report, and updates index.html
"""
import os
import requests
from datetime import datetime
import pytz
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from twilio.rest import Client
import re
from bs4 import BeautifulSoup
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend for GitHub Actions
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# Configuration
LAT = 50.038417
LON = -116.892033
OPENWEATHER_API_KEY = os.environ.get('OPENWEATHER_API_KEY')

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
        
        if queens_match:
            lake_data['queens_ft'] = queens_match.group(1)
            lake_data['queens_m'] = queens_match.group(2)
            lake_data['queens_updated'] = queens_match.group(3).strip()
            print(f"  ✓ Queen's Bay: {queens_match.group(1)} ft ({queens_match.group(2)} m)")
        
        if nelson_match:
            lake_data['nelson_ft'] = nelson_match.group(1)
            lake_data['nelson_m'] = nelson_match.group(2)
            lake_data['nelson_updated'] = nelson_match.group(3).strip()
            print(f"  ✓ Nelson: {nelson_match.group(1)} ft ({nelson_match.group(2)} m)")
        
        if forecast_match:
            lake_data['forecast_trend'] = forecast_match.group(1).strip()
            lake_data['forecast_level'] = forecast_match.group(2).strip()
            lake_data['forecast_location'] = forecast_match.group(3).strip()
            lake_data['forecast_date'] = forecast_match.group(4).strip()
            print(f"  ✓ Forecast: {forecast_match.group(2)} ft by {forecast_match.group(4)}")
        
        if discharge_match:
            lake_data['discharge_cfs'] = discharge_match.group(3).strip()
            lake_data['discharge_location'] = discharge_match.group(1).strip()
            lake_data['discharge_date'] = discharge_match.group(2).strip()
            print(f"  ✓ Discharge: {discharge_match.group(3)} cfs")
        
        return lake_data
        
    except Exception as e:
        print(f"  ✗ Error fetching lake data: {e}")
        return None

def create_lake_chart(lake_data_history):
    """Generate Kootenay Lake chart"""
    print("\n[CHART] Generating lake level chart...")
    
    try:
        if not lake_data_history or len(lake_data_history) < 2:
            print("  ⚠ Not enough historical data for chart yet")
            return False
        
        # Convert to DataFrame
        df = pd.DataFrame(lake_data_history)
        df['date'] = pd.to_datetime(df['date'])
        df['level'] = pd.to_numeric(df['level'], errors='coerce')
        df = df.dropna(subset=['level'])
        
        if len(df) < 2:
            print("  ⚠ Not enough valid data points")
            return False
        
        # Create figure
        fig, ax = plt.subplots(figsize=(12, 6))
        
        # Plot data
        ax.plot(df['date'], df['level'], 
                color='#e74c3c', linewidth=3, marker='o', markersize=6, 
                label='2025 Actual', zorder=10)
        
        # Add forecast if available
        if 'forecast_level' in df.columns and 'forecast_date' in df.columns:
            forecast_data = df[df['forecast_level'].notna()].tail(1)
            if not forecast_data.empty:
                try:
                    forecast_level = float(forecast_data['forecast_level'].iloc[0])
                    forecast_date = pd.to_datetime(forecast_data['forecast_date'].iloc[0])
                    last_date = df['date'].iloc[-1]
                    last_level = df['level'].iloc[-1]
                    
                    ax.plot([last_date, forecast_date], [last_level, forecast_level],
                           'k--', linewidth=2, zorder=9, label='Forecast')
                    ax.plot([last_date, forecast_date], [last_level, forecast_level],
                           'k^', markersize=8, zorder=9)
                except:
                    pass
        
        # Reference lines
        ax.axhline(y=1752, color='red', linestyle=':', linewidth=2, alpha=0.7, 
                   label='Flood Level (1752 ft)')
        ax.axhline(y=1754.24, color='darkred', linestyle='--', linewidth=1.5, alpha=0.6,
                   label='Record High (1754.24 ft)')
        ax.axhspan(1740, 1750, alpha=0.08, color='gray', label='Historical Range', zorder=1)
        
        # Formatting
        ax.set_title('Kootenay Lake Levels - Queens Bay', fontsize=16, fontweight='bold', pad=20)
        ax.set_xlabel('Date', fontsize=12, fontweight='bold')
        ax.set_ylabel('Elevation (feet)', fontsize=12, fontweight='bold')
        ax.grid(True, alpha=0.3, linestyle='-', linewidth=0.5)
        ax.set_axisbelow(True)
        
        current_level = df['level'].iloc[-1]
        ax.set_ylim(max(1737, current_level - 8), min(1755, current_level + 8))
        
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
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

def load_lake_history():
    """Load historical lake data from CSV file"""
    csv_file = 'lake_data_history.csv'
    
    if os.path.exists(csv_file):
        try:
            df = pd.read_csv(csv_file)
            return df.to_dict('records')
        except:
            return []
    return []

def save_lake_history(history, new_data):
    """Append new lake data to history CSV"""
    csv_file = 'lake_data_history.csv'
    
    timestamp = datetime.now().strftime('%Y-%m-%d')
    
    # Create new entry
    new_entry = {
        'date': timestamp,
        'level': new_data.get('queens_ft', ''),
        'level_m': new_data.get('queens_m', ''),
        'forecast_level': new_data.get('forecast_level', ''),
        'forecast_date': new_data.get('forecast_date', ''),
        'discharge': new_data.get('discharge_cfs', '')
    }
    
    # Check if today's data already exists
    history = [h for h in history if h.get('date') != timestamp]
    history.append(new_entry)
    
    # Save to CSV
    df = pd.DataFrame(history)
    df.to_csv(csv_file, index=False)
    print(f"  ✓ Lake history updated ({len(history)} days)")

# ============================================================================
# WEATHER FUNCTIONS (keep your existing ones)
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

def format_weather_report(weather_data, lake_data=None):
    """Format weather data into readable report"""
    current = weather_data['current']
    daily = weather_data['daily'][0]
    
    pst = pytz.timezone('America/Los_Angeles')
    now = datetime.now(pst)
    
    temp = current['temp']
    feels_like = current['feels_like']
    desc = current['weather'][0]['description']
    wind_speed = current['wind_speed'] * 3.6  # m/s to km/h
    humidity = current['humidity']
    
    report = f"""
🌤️ BIRCHDALE WEATHER REPORT
{now.strftime('%A, %B %d, %Y - %I:%M %p PST')}

Current Conditions:
Temperature: {temp:.1f}°C (Feels like {feels_like:.1f}°C)
Conditions: {desc.title()}
Wind: {wind_speed:.1f} km/h
Humidity: {humidity}%
High: {daily['temp']['max']:.0f}°C / Low: {daily['temp']['min']:.0f}°C
"""
    
    # Add lake data if available
    if lake_data:
        report += f"""
🌊 KOOTENAY LAKE LEVELS:
Queen's Bay: {lake_data.get('queens_ft', 'N/A')} feet ({lake_data.get('queens_m', 'N/A')} meters)
"""
        if 'forecast_level' in lake_data:
            report += f"Forecast: {lake_data['forecast_level']} ft by {lake_data.get('forecast_date', 'N/A')}\n"
    
    return report

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
          Data from FortisBC | Updated Daily
        </div>
      </div>
    </div>
"""
        
        # Insert before </body>
        html_content = html_content.replace('</body>', f'{lake_section}\n</body>')
    
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
        lake_data = scrape_lake_data()
        
        # Load and update lake history
        if lake_data:
            history = load_lake_history()
            save_lake_history(history, lake_data)
            
            # Generate chart
            create_lake_chart(history)
        
        # Generate HTML
        generate_index_html(weather_data, lake_data)
        
        # Generate weather report for email/SMS
        report = format_weather_report(weather_data, lake_data)
        
        # Send email/SMS (keep your existing email/SMS code here if you have it)
        
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
