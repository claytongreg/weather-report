#!/usr/bin/env python3
"""
FireSmoke Canada smoke-forecast fetcher for Birchdale.

FireSmoke.ca (UBC Weather Forecast Research Team, BlueSky/HYSPLIT model) has no
JSON API. It publishes each forecast run as a single ~84 MB NetCDF-3 file:

    https://firesmoke.ca/forecasts/current/dispersion.nc

That file is an IOAPI regular lat-lon grid (GDTYP=1) of near-surface PM2.5 in
ug/m^3, dims (TSTEP, LAY, ROW, COL) -- typically 51 hourly steps on a 0.1-deg
grid covering most of North America.

Rather than download all 84 MB, this module parses the ~11 KB header, computes
the grid cell for a given lat/lon, and uses HTTP range requests to read only the
few bytes for that one cell across every timestep. A full pull is ~100 tiny
reads over a keep-alive session (~4 s) and needs nothing beyond `requests` -- no
netCDF4/scipy dependency.

CLI:
    python firesmoke.py                     # Birchdale, pretty table
    python firesmoke.py --lat 49.9 --lon -119.5
    python firesmoke.py --json public/firesmoke_data.json
"""
import argparse
import json
import struct
from datetime import datetime, timedelta, timezone

import requests

from utils import LAT, LON, PACIFIC

FIRESMOKE_URL = "https://firesmoke.ca/forecasts/current/dispersion.nc"

# US EPA PM2.5 -> AQI breakpoints (2024 revision), (C_low, C_high, AQI_low, AQI_high).
# Concentration is truncated to 0.1 ug/m^3 before interpolation, per EPA method.
_AQI_BREAKPOINTS = [
    (0.0, 9.0, 0, 50, "Good"),
    (9.1, 35.4, 51, 100, "Moderate"),
    (35.5, 55.4, 101, 150, "Unhealthy for Sensitive Groups"),
    (55.5, 125.4, 151, 200, "Unhealthy"),
    (125.5, 225.4, 201, 300, "Very Unhealthy"),
    (225.5, 325.4, 301, 500, "Hazardous"),
]


def pm25_to_aqi(conc):
    """Convert a PM2.5 concentration (ug/m^3) to US EPA AQI and category."""
    if conc is None or conc < 0:
        return None, None
    c = int(conc * 10) / 10.0  # truncate to 0.1
    for c_lo, c_hi, a_lo, a_hi, cat in _AQI_BREAKPOINTS:
        if c <= c_hi:
            aqi = round((a_hi - a_lo) / (c_hi - c_lo) * (c - c_lo) + a_lo)
            return aqi, cat
    return 500, "Hazardous"


# ---------------------------------------------------------------------------
# Minimal NetCDF-3 "classic" (CDF\x01) header reader
# ---------------------------------------------------------------------------
_TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 4, 6: 8}  # byte,char,short,int,float,double


class _Reader:
    def __init__(self, buf):
        self.b = buf
        self.p = 0

    def u4(self):
        v = struct.unpack_from(">I", self.b, self.p)[0]
        self.p += 4
        return v

    def name(self):
        n = self.u4()
        s = self.b[self.p:self.p + n].decode("latin1")
        self.p += n + ((4 - (n % 4)) % 4)  # skip 4-byte padding
        return s

    def attrs(self):
        self.u4()  # tag (NC_ATTRIBUTE or absent)
        out = {}
        for _ in range(self.u4()):
            an = self.name()
            t = self.u4()
            nv = self.u4()
            sz = _TYPE_SIZE[t] * nv
            raw = self.b[self.p:self.p + sz]
            self.p += sz + ((4 - (sz % 4)) % 4)
            if t == 2:
                out[an] = raw.decode("latin1")
            elif t in (5, 6):
                out[an] = struct.unpack(">%d%s" % (nv, "f" if t == 5 else "d"), raw)
            else:
                out[an] = struct.unpack(">%d%s" % (nv, {1: "b", 3: "h", 4: "i"}[t]), raw)
        return out


def parse_header(hdr):
    """Parse a NetCDF-3 classic header into dims/global-attrs/var-layout."""
    r = _Reader(hdr)
    if r.b[:4] != b"CDF\x01":
        raise ValueError("Not a NetCDF-3 classic file (bad magic %r)" % r.b[:4])
    r.p = 4
    numrecs = r.u4()
    r.u4()  # NC_DIMENSION tag
    dims = [(r.name(), r.u4()) for _ in range(r.u4())]
    gattrs = r.attrs()
    r.u4()  # NC_VARIABLE tag
    variables = {}
    for _ in range(r.u4()):
        vn = r.name()
        dimids = [r.u4() for _ in range(r.u4())]
        r.attrs()  # per-variable attributes (unused here)
        vtype = r.u4()
        vsize = r.u4()
        begin = r.u4()
        variables[vn] = {"dimids": dimids, "type": vtype, "vsize": vsize, "begin": begin}
    return {"numrecs": numrecs, "dims": dims, "gattrs": gattrs, "vars": variables}


def _ioapi_to_utc(yyyyddd, hhmmss):
    """IOAPI date (YYYYDDD) + time (HHMMSS) -> aware UTC datetime."""
    year, doy = divmod(yyyyddd, 1000)
    h, rem = divmod(hhmmss, 10000)
    m, s = divmod(rem, 100)
    base = datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=doy - 1)
    return base + timedelta(hours=h, minutes=m, seconds=s)


# ---------------------------------------------------------------------------
# Forecast extraction
# ---------------------------------------------------------------------------
def fetch_pm25_forecast(lat=LAT, lon=LON, url=FIRESMOKE_URL, timeout=30):
    """
    Return the hourly surface-PM2.5 forecast for the grid cell at (lat, lon).

    Reads only the bytes for that single cell via HTTP range requests.
    Returns a dict: metadata + `series` list of hourly points.
    """
    sess = requests.Session()

    def ranged(a, b):
        resp = sess.get(url, headers={"Range": "bytes=%d-%d" % (a, b)}, timeout=timeout)
        resp.raise_for_status()
        if resp.status_code != 206:
            raise RuntimeError("Server ignored Range request (status %d)" % resp.status_code)
        return resp.content

    meta = parse_header(ranged(0, 16383))
    g = meta["gattrs"]
    ncols, nrows = g["NCOLS"][0], g["NROWS"][0]
    xorig, yorig = g["XORIG"][0], g["YORIG"][0]
    xcell, ycell = g["XCELL"][0], g["YCELL"][0]
    numrecs = meta["numrecs"]

    # Grid cell whose center is nearest (lat, lon). XORIG/YORIG is the SW corner
    # of cell (0,0); cell center = ORIG + (index + 0.5) * CELL.
    col = round((lon - xorig) / xcell - 0.5)
    row = round((lat - yorig) / ycell - 0.5)
    if not (0 <= col < ncols and 0 <= row < nrows):
        raise ValueError(
            "(%.4f, %.4f) is outside the forecast domain "
            "[lon %.1f..%.1f, lat %.1f..%.1f]"
            % (lat, lon, xorig, xorig + ncols * xcell, yorig, yorig + nrows * ycell)
        )

    pm25 = meta["vars"]["PM25"]
    tflag = meta["vars"]["TFLAG"]
    # All record variables share one interleaved record; recsize spans them all.
    recsize = sum(v["vsize"] for v in meta["vars"].values() if v["dimids"] and v["dimids"][0] == 0)
    cell_off = (row * ncols + col) * 4  # LAY=0; float32 element within a record

    series = []
    for t in range(numrecs):
        d, hms = struct.unpack(">2i", ranged(tflag["begin"] + t * recsize,
                                             tflag["begin"] + t * recsize + 7))
        conc = struct.unpack(">f", ranged(pm25["begin"] + t * recsize + cell_off,
                                          pm25["begin"] + t * recsize + cell_off + 3))[0]
        conc = round(max(0.0, conc), 2)
        aqi, cat = pm25_to_aqi(conc)
        utc = _ioapi_to_utc(d, hms)
        series.append({
            "time_utc": utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "time_local": utc.astimezone(PACIFIC).strftime("%Y-%m-%d %H:%M %Z"),
            "pm25": conc,
            "aqi": aqi,
            "category": cat,
        })

    peak = max(series, key=lambda p: p["pm25"]) if series else None
    return {
        "source": "FireSmoke.ca (BlueSky/HYSPLIT surface PM2.5)",
        "url": url,
        "lat": lat,
        "lon": lon,
        "cell": {
            "row": row,
            "col": col,
            "center_lat": round(yorig + (row + 0.5) * ycell, 4),
            "center_lon": round(xorig + (col + 0.5) * xcell, 4),
            "resolution_deg": round(xcell, 4),
        },
        "run_start_utc": _ioapi_to_utc(g["SDATE"][0], g["STIME"][0]).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hours": len(series),
        "peak": peak,
        "series": series,
    }


def main():
    ap = argparse.ArgumentParser(description="Fetch FireSmoke.ca PM2.5 forecast for a point.")
    ap.add_argument("--lat", type=float, default=LAT)
    ap.add_argument("--lon", type=float, default=LON)
    ap.add_argument("--url", default=FIRESMOKE_URL)
    ap.add_argument("--json", metavar="PATH", help="write full forecast to this JSON file")
    args = ap.parse_args()

    fc = fetch_pm25_forecast(args.lat, args.lon, args.url)

    print("FireSmoke PM2.5 forecast for (%.4f, %.4f)" % (fc["lat"], fc["lon"]))
    print("  grid cell center: (%.3f, %.3f)  run start: %s UTC"
          % (fc["cell"]["center_lat"], fc["cell"]["center_lon"], fc["run_start_utc"]))
    pk = fc["peak"]
    if pk:
        print("  peak: %.1f ug/m^3 (AQI %s, %s) at %s"
              % (pk["pm25"], pk["aqi"], pk["category"], pk["time_local"]))
    print()
    print("  %-22s %10s %6s  %s" % ("local time", "PM2.5", "AQI", "category"))
    for p in fc["series"]:
        print("  %-22s %8.1f  %5s  %s" % (p["time_local"], p["pm25"], p["aqi"], p["category"]))

    if args.json:
        with open(args.json, "w") as f:
            json.dump(fc, f, indent=2)
        print("\nWrote %d hours to %s" % (fc["hours"], args.json))


if __name__ == "__main__":
    main()
