#!/usr/bin/env python3
"""
Wind Monitor with SMS Alerts via Telnyx
Checks wind conditions every 2 hours and sends SMS alerts
when wind speed or gusts exceed 15 km/h threshold.
"""
import os
import requests
import json
from datetime import datetime, timezone
import glob as glob_module

from utils import LAT, LON, MS_TO_KMH, OPENWEATHER_URL, PACIFIC, convert_to_pst, get_cardinal

# Configuration from environment variables
OPENWEATHER_API_KEY = os.environ.get('OPENWEATHER_API_KEY')
TELNYX_API_KEY = os.environ.get('TELNYX_API_KEY')
TELNYX_PHONE_NUMBER = os.environ.get('TELNYX_PHONE_NUMBER')
PHONE_NUMBERS = os.environ.get('PHONE_NUMBERS')

# Directory for state files
STATE_DIR = 'wind_sms_states'


def format_datetime(dt):
    """Format datetime with timezone abbreviation"""
    return dt.strftime("%Y-%m-%d %H:%M:%S %Z")


def cleanup_old_state_files(current_date_str):
    """Delete all state files that are not from today"""
    if not os.path.exists(STATE_DIR):
        return

    pattern = os.path.join(STATE_DIR, 'wind_sms_*.json')
    for filepath in glob_module.glob(pattern):
        filename = os.path.basename(filepath)
        # Extract date from filename (format: wind_sms_YYYY-MM-DD_*.json)
        try:
            file_date = filename.split('_')[2]  # Get YYYY-MM-DD part
            if file_date != current_date_str:
                os.remove(filepath)
                print(f"  Deleted old state file: {filename}")
        except:
            pass


def get_latest_state_file(current_date_str):
    """Get the most recent state file from today"""
    if not os.path.exists(STATE_DIR):
        os.makedirs(STATE_DIR)
        return None

    pattern = os.path.join(STATE_DIR, f'wind_sms_{current_date_str}_*.json')
    files = glob_module.glob(pattern)

    if not files:
        return None

    # Sort by filename (which includes timestamp) and get the latest
    latest_file = sorted(files)[-1]

    try:
        with open(latest_file, 'r') as f:
            return json.load(f)
    except:
        return None


def save_state_file(current_time, peak_value, peak_time, end_time):
    """Save state to a new JSON file with timestamp in filename"""
    if not os.path.exists(STATE_DIR):
        os.makedirs(STATE_DIR)

    # Format: wind_sms_YYYY-MM-DD_HHMMSS.json
    filename = current_time.strftime('wind_sms_%Y-%m-%d_%H%M%S.json')
    filepath = os.path.join(STATE_DIR, filename)

    state = {
        'sent_time': current_time.isoformat(),
        'peak_value': peak_value,
        'peak_time': peak_time.isoformat() if peak_time else None,
        'end_time': end_time.isoformat() if end_time else None
    }

    with open(filepath, 'w') as f:
        json.dump(state, f, indent=2)

    print(f"  Saved state to: {filename}")


def check_material_changes(current_time, current_peak, current_peak_time, current_end_time):
    """
    Check if we should send SMS based on material changes:
    - First alert of the day
    - Minimum 4 hours since last SMS
    - Peak changed by 2+ km/h
    - Peak timing changed by 2+ hours
    - End timing changed by 2+ hours
    """
    current_date_str = current_time.strftime('%Y-%m-%d')

    # Clean up old files first
    print("\nCleaning up old state files...")
    cleanup_old_state_files(current_date_str)

    # Get latest state from today
    last_state = get_latest_state_file(current_date_str)

    if not last_state:
        print("  \u2192 No SMS sent today yet - SENDING")
        return True, "First alert of the day"

    # Check minimum time delay (4 hours = 240 minutes)
    last_sent_time = datetime.fromisoformat(last_state['sent_time'])
    minutes_since_last = (current_time - last_sent_time).total_seconds() / 60

    print(f"\n  Time since last SMS: {minutes_since_last:.0f} minutes ({minutes_since_last/60:.1f} hours)")

    if minutes_since_last < 240:
        print(f"  \u2192 Too soon since last SMS (minimum 4 hours) - SKIPPING")
        return False, f"Only {minutes_since_last:.0f} minutes since last alert"

    print(f"\n  Last SMS details:")
    print(f"    Peak: {last_state['peak_value']:.1f} km/h")
    print(f"    Peak time: {last_state.get('peak_time', 'N/A')}")
    print(f"    End time: {last_state.get('end_time', 'N/A')}")

    print(f"\n  Current forecast:")
    print(f"    Peak: {current_peak:.1f} km/h")
    print(f"    Peak time: {current_peak_time.strftime('%Y-%m-%d %H:%M:%S %Z') if current_peak_time else 'N/A'}")
    print(f"    End time: {current_end_time.strftime('%Y-%m-%d %H:%M:%S %Z') if current_end_time else 'N/A'}")

    # Check for material changes
    changes = []

    # 1. Peak value change
    peak_diff = abs(current_peak - last_state['peak_value'])
    if peak_diff >= 2.0:
        changes.append(f"Peak changed by {peak_diff:.1f} km/h")

    # 2. Peak timing change
    if current_peak_time and last_state.get('peak_time'):
        last_peak_time = datetime.fromisoformat(last_state['peak_time'])
        peak_time_diff_hours = abs((current_peak_time - last_peak_time).total_seconds() / 3600)
        if peak_time_diff_hours >= 2.0:
            changes.append(f"Peak timing changed by {peak_time_diff_hours:.1f} hours")

    # 3. End timing change
    if current_end_time and last_state.get('end_time'):
        last_end_time = datetime.fromisoformat(last_state['end_time'])
        end_time_diff_hours = abs((current_end_time - last_end_time).total_seconds() / 3600)
        if end_time_diff_hours >= 2.0:
            changes.append(f"End timing changed by {end_time_diff_hours:.1f} hours")

    if changes:
        reason = "; ".join(changes)
        print(f"\n  \u2192 MATERIAL CHANGES DETECTED - SENDING")
        print(f"    Changes: {reason}")
        return True, reason
    else:
        print(f"\n  \u2192 No material changes - SKIPPING")
        return False, "No material changes"


def main():
    try:
        print(f"Wind data for location: LAT {LAT}, LON {LON}")
        print("=" * 80)
        print("Fetching weather data from OpenWeather API...")

        params = {
            "lat": LAT,
            "lon": LON,
            "appid": OPENWEATHER_API_KEY,
            "units": "metric",
            "exclude": "minutely,daily,alerts"
        }

        response = requests.get(OPENWEATHER_URL, params=params, timeout=15)
        response.raise_for_status()

        data = response.json()

        # Get current time in PST
        current_time = datetime.now(PACIFIC)

        print(f"Current time: {format_datetime(current_time)}")
        print("=" * 80)

        # Parse current conditions
        current = data['current']
        current_wind_speed_ms = current['wind_speed']
        current_wind_speed_kmh = current_wind_speed_ms * MS_TO_KMH
        current_wind_deg = current.get('wind_deg')
        current_wind_gust_ms = current.get('wind_gust', 0)
        current_wind_gust_kmh = current_wind_gust_ms * MS_TO_KMH
        current_cardinal = get_cardinal(current_wind_deg)
        current_dt = convert_to_pst(current['dt'])

        print("\n" + "=" * 80)
        print("CURRENT CONDITIONS")
        print("=" * 80)
        print(f"Time: {format_datetime(current_dt)}")
        print(f"Wind Speed: {current_wind_speed_ms:.2f} m/s | {current_wind_speed_kmh:.1f} km/h")
        print(f"Direction: {current_wind_deg}\u00b0 ({current_cardinal})")
        print(f"Gusts: {current_wind_gust_ms:.2f} m/s | {current_wind_gust_kmh:.1f} km/h")
        print("=" * 80)

        # Parse hourly forecast
        hourly = data['hourly']

        print("\n" + "=" * 80)
        print("HOURLY WIND FORECAST (Next 48 Hours)")
        print("=" * 80)
        print()

        # Display first 24 hours in detail
        for i, hour in enumerate(hourly[:24]):
            dt_forecast = convert_to_pst(hour['dt'])
            wind_speed_ms = hour['wind_speed']
            wind_speed_kmh = wind_speed_ms * MS_TO_KMH
            wind_deg = hour.get('wind_deg')
            wind_gust_ms = hour.get('wind_gust', 0)
            wind_gust_kmh = wind_gust_ms * MS_TO_KMH
            cardinal = get_cardinal(wind_deg)

            # Calculate time difference from now
            time_diff = (dt_forecast - current_time).total_seconds()
            hours_diff = time_diff / 3600

            # Determine if this is current or future
            if abs(hours_diff) < 0.5:
                time_status = "NOW"
            else:
                time_status = f"(in {hours_diff:.1f} hours)"

            print(f"[{i + 1}] {format_datetime(dt_forecast)} {time_status}")
            print(f"    Wind Speed: {wind_speed_ms:.2f} m/s | {wind_speed_kmh:.1f} km/h")
            print(f"    Direction: {wind_deg}\u00b0 ({cardinal})")
            print(f"    Gusts: {wind_gust_ms:.2f} m/s | {wind_gust_kmh:.1f} km/h")
            print()

        if len(hourly) > 24:
            print(f"... and {len(hourly) - 24} more forecast points available")
            print()

        # Analyze wind conditions for SMS threshold
        print("\n" + "=" * 80)
        print("WIND ANALYSIS")
        print("=" * 80)

        summary_text = ""
        should_send_sms = False
        trigger_reasons = []

        # Check current wind speed and gusts
        print(f"\nChecking current conditions:")
        print(f"  Wind speed: {current_wind_speed_kmh:.1f} km/h (threshold: 15.0 km/h)")
        print(f"  Wind gusts: {current_wind_gust_kmh:.1f} km/h (threshold: 15.0 km/h)")

        if current_wind_speed_kmh > 15.0:
            should_send_sms = True
            trigger_reasons.append(f"Current wind speed: {current_wind_speed_kmh:.1f} km/h")
            print(f"  Current wind speed EXCEEDS threshold")

        if current_wind_gust_kmh > 15.0:
            should_send_sms = True
            trigger_reasons.append(f"Current wind gusts: {current_wind_gust_kmh:.1f} km/h")
            print(f"  Current wind gusts EXCEED threshold")

        # Check forecasts for next 6 hours (both wind speed and gusts)
        print(f"\nChecking forecasts for next 6 hours:")
        max_wind_next_6hrs = current_wind_speed_kmh
        max_gust_next_6hrs = current_wind_gust_kmh
        max_wind_time = current_dt
        max_gust_time = current_dt

        for hour in hourly:
            dt_forecast = convert_to_pst(hour['dt'])
            hours_diff = (dt_forecast - current_time).total_seconds() / 3600

            if 0 <= hours_diff <= 6:
                wind_speed_kmh = hour['wind_speed'] * MS_TO_KMH
                wind_gust_kmh = hour.get('wind_gust', 0) * MS_TO_KMH

                if wind_speed_kmh > max_wind_next_6hrs:
                    max_wind_next_6hrs = wind_speed_kmh
                    max_wind_time = dt_forecast

                if wind_gust_kmh > max_gust_next_6hrs:
                    max_gust_next_6hrs = wind_gust_kmh
                    max_gust_time = dt_forecast

                if wind_speed_kmh > 15.0:
                    if not any("Wind speed forecast" in r for r in trigger_reasons):
                        should_send_sms = True
                        trigger_reasons.append(f"Wind speed forecast: {wind_speed_kmh:.1f} km/h at {dt_forecast.strftime('%I:%M %p')}")
                        print(f"  Wind speed forecast EXCEEDS threshold: {wind_speed_kmh:.1f} km/h at {dt_forecast.strftime('%I:%M %p')}")

                if wind_gust_kmh > 15.0:
                    if not any("Wind gust forecast" in r for r in trigger_reasons):
                        should_send_sms = True
                        trigger_reasons.append(f"Wind gust forecast: {wind_gust_kmh:.1f} km/h at {dt_forecast.strftime('%I:%M %p')}")
                        print(f"  Wind gust forecast EXCEEDS threshold: {wind_gust_kmh:.1f} km/h at {dt_forecast.strftime('%I:%M %p')}")

        print(f"\n  Max wind in next 6 hours: {max_wind_next_6hrs:.1f} km/h")
        print(f"  Max gusts in next 6 hours: {max_gust_next_6hrs:.1f} km/h")

        if not should_send_sms:
            print(f"\nWind conditions below threshold")
            print(f"   Current wind: {current_wind_speed_kmh:.1f} km/h | Current gusts: {current_wind_gust_kmh:.1f} km/h")
            print(f"   Max wind in next 6 hours: {max_wind_next_6hrs:.1f} km/h")
            print(f"   Max gusts in next 6 hours: {max_gust_next_6hrs:.1f} km/h")
            print("   No SMS will be sent.")
        else:
            print(f"\nSMS WILL BE SENT - Triggered by:")
            for reason in trigger_reasons:
                print(f"   - {reason}")

        # Build summary for SMS
        print("\n" + "=" * 80)
        print("WIND SUMMARY")
        print("=" * 80)

        # Build alert info if SMS is being sent
        summary_text = ""
        peak_value = 0
        peak_time = None
        end_time = None

        if should_send_sms and trigger_reasons:
            # Find when gusts/wind exceed threshold and when they drop back below
            exceed_periods = []

            for hour in hourly:
                dt_forecast = convert_to_pst(hour['dt'])
                hours_diff = (dt_forecast - current_time).total_seconds() / 3600

                if 0 <= hours_diff <= 12:  # Look ahead 12 hours for the full picture
                    wind_speed_kmh = hour['wind_speed'] * MS_TO_KMH
                    wind_gust_kmh = hour.get('wind_gust', 0) * MS_TO_KMH

                    if wind_speed_kmh > 15.0 or wind_gust_kmh > 15.0:
                        exceed_periods.append({
                            'time': dt_forecast,
                            'wind': wind_speed_kmh,
                            'gust': wind_gust_kmh
                        })

            if exceed_periods:
                # Find when significant gusts start (use first period above 15 km/h threshold)
                significant_start = exceed_periods[0] if exceed_periods else None

                # Find peak
                peak_exceed = max(exceed_periods, key=lambda x: max(x['wind'], x['gust']))

                # Find last time exceeding threshold
                last_exceed = exceed_periods[-1]

                # Check if there's a period after where it drops below threshold
                end_time_forecast = None
                for hour in hourly:
                    dt_forecast = convert_to_pst(hour['dt'])
                    if dt_forecast > last_exceed['time']:
                        wind_speed_kmh = hour['wind_speed'] * MS_TO_KMH
                        wind_gust_kmh = hour.get('wind_gust', 0) * MS_TO_KMH
                        if wind_speed_kmh <= 15.0 and wind_gust_kmh <= 15.0:
                            end_time_forecast = dt_forecast
                            break

                # Store values for state tracking
                peak_value = max(peak_exceed['wind'], peak_exceed['gust'])
                peak_time = peak_exceed['time']
                end_time = end_time_forecast

                # Check if we should send SMS based on material changes
                print("\n" + "=" * 80)
                print("CHECKING FOR MATERIAL CHANGES")
                print("=" * 80)

                send_this_sms, reason = check_material_changes(
                    current_time,
                    peak_value,
                    peak_time,
                    end_time
                )

                if not send_this_sms:
                    print(f"\nSKIPPING SMS - {reason}")
                    should_send_sms = False
                else:
                    print(f"\nWILL SEND SMS - {reason}")

                # Build the message - KEEP UNDER 159 CHARACTERS
                peak_type = "gusts" if peak_exceed['gust'] > peak_exceed['wind'] else "wind"

                # Current conditions (compact format)
                current_part = f"Now: {current_wind_speed_kmh:.1f}km/h wind, {current_wind_gust_kmh:.1f}km/h gusts."

                # Format times with AM/PM for readability
                start_time_str = significant_start['time'].strftime('%-I%p').lower()
                peak_time_str = peak_exceed['time'].strftime('%-I%p').lower()

                # Build forecast part
                # Check if start time is in the past (already started)
                if significant_start['time'] <= current_time:
                    # Already elevated, skip start time
                    if end_time_forecast:
                        end_time_str = end_time_forecast.strftime('%-I%p').lower()
                        forecast_part = f"Alert: {peak_type.capitalize()} peak {peak_value:.1f}km/h at {peak_time_str}, calm by {end_time_str}"
                    else:
                        last_time_str = last_exceed['time'].strftime('%-I%p').lower()
                        forecast_part = f"Alert: {peak_type.capitalize()} peak {peak_value:.1f}km/h at {peak_time_str}, elevated til {last_time_str}"
                else:
                    # Not started yet, include start time
                    if end_time_forecast:
                        end_time_str = end_time_forecast.strftime('%-I%p').lower()
                        forecast_part = f"Alert: {peak_type.capitalize()} start {start_time_str}, peak {peak_value:.1f}km/h at {peak_time_str}, calm by {end_time_str}"
                    else:
                        last_time_str = last_exceed['time'].strftime('%-I%p').lower()
                        forecast_part = f"Alert: {peak_type.capitalize()} start {start_time_str}, peak {peak_value:.1f}km/h at {peak_time_str}, elevated til {last_time_str}"

                # Combine parts
                summary_text = f"{current_part} {forecast_part}"

                # Safety check - if over 159 chars, fall back to shorter format
                if len(summary_text) > 159:
                    # Fallback: skip current conditions
                    if significant_start['time'] <= current_time:
                        if end_time_forecast:
                            end_time_str = end_time_forecast.strftime('%-I%p').lower()
                            summary_text = f"{peak_type.capitalize()} peak {peak_value:.1f}km/h at {peak_time_str}, calm by {end_time_str}"
                        else:
                            last_time_str = last_exceed['time'].strftime('%-I%p').lower()
                            summary_text = f"{peak_type.capitalize()} peak {peak_value:.1f}km/h at {peak_time_str}, elevated til {last_time_str}"
                    else:
                        if end_time_forecast:
                            end_time_str = end_time_forecast.strftime('%-I%p').lower()
                            summary_text = f"{peak_type.capitalize()} start {start_time_str}, peak {peak_value:.1f}km/h at {peak_time_str}, calm {end_time_str}"
                        else:
                            last_time_str = last_exceed['time'].strftime('%-I%p').lower()
                            summary_text = f"{peak_type.capitalize()} start {start_time_str}, peak {peak_value:.1f}km/h at {peak_time_str}, til {last_time_str}"

                print(f"\nSMS text ({len(summary_text)} chars): {summary_text}")

                # Final safety check
                if len(summary_text) > 159:
                    print(f"WARNING: Message is {len(summary_text)} chars, truncating to 159")
                    summary_text = summary_text[:159]
            else:
                # Shouldn't happen, but fallback
                summary_text = "Wind alert: Gusts expected >9km/h"
                should_send_sms = False
        else:
            # No alert being sent
            summary_text = ""

        # Send SMS via Telnyx - ONLY if wind conditions warrant it
        if should_send_sms:
            print("\n" + "=" * 80)
            print("SENDING SMS VIA TELNYX")
            print("=" * 80)

            try:
                # Telnyx API endpoint
                telnyx_url = "https://api.telnyx.com/v2/messages"

                headers = {
                    "Authorization": f"Bearer {TELNYX_API_KEY}",
                    "Content-Type": "application/json"
                }

                # Get list of recipients
                try:
                    recipients = PHONE_NUMBERS
                    # If it's a string, try to parse it as JSON
                    if isinstance(recipients, str):
                        recipients = json.loads(recipients)
                    # Ensure it's a list
                    if not isinstance(recipients, list):
                        recipients = [recipients]

                    print(f"DEBUG - Recipients type: {type(recipients)}")
                    print(f"DEBUG - Number of recipients: {len(recipients)}")

                except (NameError, TypeError):
                    print("No phone numbers configured!")
                    recipients = []
                except Exception as e:
                    print(f"Error parsing PHONE_NUMBERS: {e}")
                    recipients = []

                if recipients:
                    print(f"Sending to {len(recipients)} recipient(s)...")

                    for i, recipient in enumerate(recipients):
                        # Ensure recipient is a string, not a list
                        if isinstance(recipient, list):
                            recipient = recipient[0]

                        print(f"\n[{i+1}/{len(recipients)}] Sending to: {recipient}")

                        payload = {
                            "from": TELNYX_PHONE_NUMBER,
                            "to": recipient,
                            "text": summary_text
                        }

                        response = requests.post(telnyx_url, headers=headers, json=payload)

                        print(f"  Response status: {response.status_code}")

                        response.raise_for_status()
                        result = response.json()

                        print(f"\nSMS sent to {recipient}!")
                        print(f"   Message ID: {result['data']['id']}")
                        print(f"   Status: {result['data']['to'][0]['status']}")

                    # Save state after successful send
                    print("\nSaving state file...")
                    save_state_file(current_time, peak_value, peak_time, end_time)
                    print("State saved successfully")

            except Exception as e:
                print(f"\nError sending SMS: {e}")
                if hasattr(e, 'response') and e.response is not None:
                    print(f"Response: {e.response.text}")
        else:
            print("\n" + "=" * 80)
            print("SMS NOT SENT - Wind conditions below threshold")
            print("=" * 80)
            print("SMS will only be sent if:")
            print("  - Current wind speed > 15 km/h, OR")
            print("  - Current wind gusts > 15 km/h, OR")
            print("  - Forecast wind speed in next 6 hours > 15 km/h, OR")
            print("  - Forecast wind gusts in next 6 hours > 15 km/h")

        # Save full data to JSON file for reference
        with open('openweather_wind_data.json', 'w') as f:
            json.dump(data, f, indent=2)
        print("\n" + "=" * 80)
        print("Full response data saved to: openweather_wind_data.json")
        print("=" * 80)

    except requests.exceptions.RequestException as e:
        print(f"Error making API request: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response status: {e.response.status_code}")
            print(f"Response body: {e.response.text}")
    except KeyError as e:
        print(f"Error parsing response data: {e}")
        if 'data' in locals():
            print("Available keys in response:", list(data.keys()))


if __name__ == '__main__':
    main()
