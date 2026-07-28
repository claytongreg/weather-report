"""
Shared BC Wildfire Service lookups for Birchdale weather scripts.

Used by both the daily email (50 km context section) and the SMS monitor
(15 km new-fire alerts), so it deliberately avoids heavy plotting imports.
"""
import math
from urllib.parse import urlencode

import requests

from utils import LAT, LON, convert_to_pst

WILDFIRE_API_URL = (
    "https://services6.arcgis.com/ubm4tcTYICKBpist/arcgis/rest/services/"
    "BCWS_ActiveFires_PublicView/FeatureServer/0/query"
)
WILDFIRE_MAP_URL = "https://wildfiresituation.nrs.gov.bc.ca/map?" + urlencode({
    "longitude": LON,
    "latitude": LAT,
    "activeWildfires": "true",
    "zoom": 9,
})


def distance_km(lat1, lon1, lat2, lon2):
    """Return the great-circle distance between two coordinates."""
    earth_radius_km = 6371.0088
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad)
        * math.cos(lat2_rad)
        * math.sin(delta_lon / 2) ** 2
    )
    haversine = min(1, max(0, haversine))
    return 2 * earth_radius_km * math.atan2(
        math.sqrt(haversine), math.sqrt(1 - haversine)
    )


def fetch_nearby_wildfires(radius_km):
    """Fetch active BC wildfires within radius_km of Birchdale."""
    params = {
        "where": "FIRE_STATUS <> 'Out'",
        "outFields": ",".join([
            "FIRE_YEAR",
            "FIRE_NUMBER",
            "INCIDENT_NAME",
            "FIRE_STATUS",
            "FIRE_CAUSE",
            "GEOGRAPHIC_DESCRIPTION",
            "CURRENT_SIZE",
            "IGNITION_DATE",
            "LATITUDE",
            "LONGITUDE",
        ]),
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
    }
    response = requests.get(WILDFIRE_API_URL, params=params, timeout=15)
    response.raise_for_status()

    payload = response.json()
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise ValueError("BC Wildfire API returned an unexpected response")

    nearby_fires = []
    for feature in payload.get("features", []):
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        if not isinstance(properties, dict) or not isinstance(geometry, dict):
            continue
        coordinates = geometry.get("coordinates") or []

        try:
            longitude, latitude = map(float, coordinates[:2])
        except (TypeError, ValueError):
            try:
                latitude = float(properties["LATITUDE"])
                longitude = float(properties["LONGITUDE"])
            except (KeyError, TypeError, ValueError):
                continue

        fire_distance = distance_km(LAT, LON, latitude, longitude)
        if fire_distance > radius_km:
            continue

        fire_number = properties.get("FIRE_NUMBER")
        if not fire_number:
            continue
        fire_number = str(fire_number)
        incident_params = {"incidentNumber": fire_number}
        if properties.get("FIRE_YEAR"):
            incident_params["fireYear"] = properties["FIRE_YEAR"]
        incident_url = (
            "https://wildfiresituation.nrs.gov.bc.ca/incidents?"
            + urlencode(incident_params)
        )

        ignition_date = None
        ignition_timestamp = properties.get("IGNITION_DATE")
        if ignition_timestamp:
            try:
                ignition_date = convert_to_pst(float(ignition_timestamp) / 1000)
            except (TypeError, ValueError, OSError):
                pass

        nearby_fires.append({
            "fire_year": properties.get("FIRE_YEAR"),
            "fire_number": fire_number,
            "incident_name": str(properties["INCIDENT_NAME"]).strip()
            if properties.get("INCIDENT_NAME") else None,
            "status": str(properties.get("FIRE_STATUS") or "Status unavailable"),
            "cause": str(properties.get("FIRE_CAUSE") or "Cause undetermined"),
            "location": str(properties["GEOGRAPHIC_DESCRIPTION"]).strip()
            if properties.get("GEOGRAPHIC_DESCRIPTION") else None,
            "size_ha": properties.get("CURRENT_SIZE"),
            "ignition_date": ignition_date,
            "distance_km": fire_distance,
            "url": incident_url,
        })

    return sorted(nearby_fires, key=lambda fire: fire["distance_km"])


def format_fire_size(size_ha):
    """Format a wildfire size without implying more precision than supplied."""
    if size_ha is None:
        return "Size unavailable"
    try:
        size_ha = float(size_ha)
    except (TypeError, ValueError):
        return "Size unavailable"
    if size_ha >= 10:
        return f"{size_ha:,.0f} ha"
    if size_ha >= 1:
        return f"{size_ha:,.1f} ha"
    return f"{size_ha:,.3f}".rstrip("0").rstrip(".") + " ha"


def fire_display_name(fire):
    """Best human-readable name for a fire, or None if only the number is known.

    BCWS often sets INCIDENT_NAME to the fire number itself, in which case the
    geographic description ("Davis Creek") is the more useful label.
    """
    display_name = fire.get("incident_name")
    if not display_name or display_name.strip().lower() == fire["fire_number"].lower():
        display_name = fire.get("location")
    if not display_name or not display_name.strip():
        return None
    return display_name.strip()


def fire_key(fire):
    """Stable identity for a fire across runs.

    Fire numbers are unique within a fire year but may be reused across years,
    so the year is part of the key.
    """
    return f"{fire.get('fire_year') or 'unknown'}-{fire['fire_number']}"
