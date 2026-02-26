"""
Shared utilities for Birchdale weather scripts.
Common constants, coordinate data, and helper functions.
"""
from datetime import datetime, timezone
import pytz

# ============================================================================
# SHARED CONSTANTS
# ============================================================================
LAT = 50.038417
LON = -116.892033
MS_TO_KMH = 3.6
OPENWEATHER_URL = "https://api.openweathermap.org/data/3.0/onecall"
ICON_BASE = "https://openweathermap.org/img/wn"
PACIFIC = pytz.timezone('America/Los_Angeles')


# ============================================================================
# SHARED HELPER FUNCTIONS
# ============================================================================
def convert_to_pst(ts):
    """Convert Unix timestamp to PST/PDT datetime."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(PACIFIC)


def get_cardinal(deg):
    """Convert wind degrees to 16-point cardinal direction."""
    if deg is None:
        return "N/A"
    dirs = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
            'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
    return dirs[int((deg + 11.25) / 22.5) % 16]
