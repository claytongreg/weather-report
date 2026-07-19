// Netlify Serverless Function: firesmoke.js
// Builds the FireSmoke.ca surface-PM2.5 forecast for a point ON DEMAND (when
// the page is opened) instead of via a daily cron. FireSmoke has no API -- it
// publishes an ~84 MB NetCDF-3 file per run. We parse the ~16 KB header and use
// a single multipart HTTP range request to read just the bytes for one grid
// cell across all timesteps, so the function stays fast and light.
// Mirrors scripts/firesmoke.py (used by the daily email).

const NC_URL = 'https://firesmoke.ca/forecasts/current/dispersion.nc';
const DEFAULT_LAT = 50.038417;
const DEFAULT_LON = -116.892033;

// US EPA PM2.5 -> AQI breakpoints (2024): [C_low, C_high, AQI_low, AQI_high, category]
const AQI_BP = [
  [0.0, 9.0, 0, 50, 'Good'],
  [9.1, 35.4, 51, 100, 'Moderate'],
  [35.5, 55.4, 101, 150, 'Unhealthy for Sensitive Groups'],
  [55.5, 125.4, 151, 200, 'Unhealthy'],
  [125.5, 225.4, 201, 300, 'Very Unhealthy'],
  [225.5, 325.4, 301, 500, 'Hazardous'],
];
function pm25ToAqi(conc) {
  if (conc == null || conc < 0) return [null, null];
  const c = Math.trunc(conc * 10) / 10;
  for (const [clo, chi, alo, ahi, cat] of AQI_BP) {
    if (c <= chi) return [Math.round((ahi - alo) / (chi - clo) * (c - clo) + alo), cat];
  }
  return [500, 'Hazardous'];
}

const TSIZE = { 1: 1, 2: 1, 3: 2, 4: 4, 5: 4, 6: 8 };
function parseHeader(u8) {
  const dv = new DataView(u8.buffer, u8.byteOffset, u8.byteLength);
  let p = 0;
  const u4 = () => { const v = dv.getUint32(p, false); p += 4; return v; };
  const name = () => {
    const n = u4();
    let s = '';
    for (let i = 0; i < n; i++) s += String.fromCharCode(u8[p + i]);
    p += n + ((4 - (n % 4)) % 4);
    return s;
  };
  const attrs = () => {
    u4(); const ne = u4(); const out = {};
    for (let k = 0; k < ne; k++) {
      const an = name(); const t = u4(); const nv = u4(); const sz = TSIZE[t] * nv;
      const vals = [];
      for (let j = 0; j < nv; j++) {
        if (t === 4) vals.push(dv.getInt32(p + j * 4, false));
        else if (t === 5) vals.push(dv.getFloat32(p + j * 4, false));
        else if (t === 6) vals.push(dv.getFloat64(p + j * 8, false));
        else if (t === 3) vals.push(dv.getInt16(p + j * 2, false));
        else vals.push(u8[p + j]);
      }
      p += sz + ((4 - (sz % 4)) % 4);
      out[an] = (t === 2) ? String.fromCharCode(...vals) : vals;
    }
    return out;
  };
  if (String.fromCharCode(u8[0], u8[1], u8[2]) !== 'CDF') throw new Error('not a NetCDF-3 classic file');
  p = 4;
  const numrecs = u4();
  u4(); const nd = u4(); const dims = [];
  for (let i = 0; i < nd; i++) dims.push([name(), u4()]);
  const gattrs = attrs();
  u4(); const nv = u4(); const vars = {};
  for (let i = 0; i < nv; i++) {
    const vn = name(); const ndv = u4(); const dimids = [];
    for (let j = 0; j < ndv; j++) dimids.push(u4());
    attrs(); const type = u4(); const vsize = u4(); const begin = u4();
    vars[vn] = { dimids, type, vsize, begin };
  }
  return { numrecs, dims, gattrs, vars };
}

async function ranged(a, b) {
  const r = await fetch(NC_URL, { headers: { Range: `bytes=${a}-${b}` } });
  if (r.status !== 206) throw new Error(`range read expected 206, got ${r.status}`);
  return new Uint8Array(await r.arrayBuffer());
}

function indexOfSeq(hay, needle, from) {
  outer: for (let i = from; i <= hay.length - needle.length; i++) {
    for (let j = 0; j < needle.length; j++) if (hay[i + j] !== needle[j]) continue outer;
    return i;
  }
  return -1;
}

// Read one float32 from each byte offset, via a single multipart range request.
// Falls back to chunked parallel single-range reads if the server doesn't
// return multipart/byteranges.
async function readFloatsAtOffsets(offsets) {
  const enc = new TextEncoder();
  const rangeHeader = offsets.map(o => `${o}-${o + 3}`).join(',');
  const resp = await fetch(NC_URL, { headers: { Range: `bytes=${rangeHeader}` } });
  const ct = resp.headers.get('content-type') || '';
  if (resp.status === 206 && /multipart\/byteranges/i.test(ct)) {
    const body = new Uint8Array(await resp.arrayBuffer());
    const boundary = enc.encode('--' + ct.match(/boundary=(.+)$/i)[1].trim());
    const crlf2 = enc.encode('\r\n\r\n');
    const byOff = new Map();
    let pos = indexOfSeq(body, boundary, 0);
    while (pos !== -1) {
      const hdrEnd = indexOfSeq(body, crlf2, pos + boundary.length);
      if (hdrEnd === -1) break;
      let hdr = '';
      for (let i = pos + boundary.length; i < hdrEnd; i++) hdr += String.fromCharCode(body[i]);
      const m = hdr.match(/Content-Range:\s*bytes\s+(\d+)-(\d+)\//i);
      const bodyStart = hdrEnd + 4;
      if (m) {
        const start = parseInt(m[1], 10);
        const dv = new DataView(body.buffer, body.byteOffset + bodyStart, 4);
        byOff.set(start, dv.getFloat32(0, false));
      }
      pos = indexOfSeq(body, boundary, bodyStart);
    }
    return offsets.map(o => byOff.get(o));
  }
  // Fallback: parallel single-range reads in chunks of 12.
  const out = new Array(offsets.length);
  for (let i = 0; i < offsets.length; i += 12) {
    const chunk = offsets.slice(i, i + 12);
    const bufs = await Promise.all(chunk.map(o => ranged(o, o + 3)));
    bufs.forEach((b, k) => { out[i + k] = new DataView(b.buffer, b.byteOffset, 4).getFloat32(0, false); });
  }
  return out;
}

function fmtLocal(date) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/Los_Angeles', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZoneName: 'short',
  }).formatToParts(date);
  const p = Object.fromEntries(parts.map(x => [x.type, x.value]));
  return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute} ${p.timeZoneName}`;
}

function ioapiToUtc(yyyyddd, hhmmss) {
  const year = Math.floor(yyyyddd / 1000), doy = yyyyddd % 1000;
  const h = Math.floor(hhmmss / 10000), m = Math.floor((hhmmss % 10000) / 100), s = hhmmss % 100;
  return new Date(Date.UTC(year, 0, 1) + (doy - 1) * 86400000 + ((h * 3600 + m * 60 + s) * 1000));
}

async function buildForecast(lat, lon) {
  const meta = parseHeader(await ranged(0, 16383));
  const g = meta.gattrs;
  const NCOLS = g.NCOLS[0], NROWS = g.NROWS[0];
  const XORIG = g.XORIG[0], YORIG = g.YORIG[0], XCELL = g.XCELL[0], YCELL = g.YCELL[0];
  const col = Math.round((lon - XORIG) / XCELL - 0.5);
  const row = Math.round((lat - YORIG) / YCELL - 0.5);
  if (col < 0 || col >= NCOLS || row < 0 || row >= NROWS) {
    const err = new Error(`(${lat}, ${lon}) is outside the forecast domain`);
    err.statusCode = 422;
    throw err;
  }
  const pm = meta.vars.PM25;
  const recsize = Object.values(meta.vars).filter(v => v.dimids[0] === 0).reduce((a, v) => a + v.vsize, 0);
  const cellOff = (row * NCOLS + col) * 4;
  const offsets = [];
  for (let t = 0; t < meta.numrecs; t++) offsets.push(pm.begin + t * recsize + cellOff);
  const floats = await readFloatsAtOffsets(offsets);

  const runStart = ioapiToUtc(g.SDATE[0], g.STIME[0]);
  const tstepHours = Math.floor(g.TSTEP[0] / 10000) || 1;
  const series = floats.map((v, t) => {
    const conc = Math.round(Math.max(0, v) * 100) / 100;
    const [aqi, category] = pm25ToAqi(conc);
    const utc = new Date(runStart.getTime() + t * tstepHours * 3600000);
    return {
      time_utc: utc.toISOString().replace('.000Z', 'Z'),
      time_local: fmtLocal(utc),
      pm25: conc, aqi, category,
    };
  });
  const peak = series.reduce((a, b) => (b.pm25 > a.pm25 ? b : a), series[0]);
  return {
    source: 'FireSmoke.ca (BlueSky/HYSPLIT surface PM2.5)',
    url: 'https://firesmoke.ca/forecasts/current/',
    lat, lon,
    cell: {
      row, col,
      center_lat: Math.round((YORIG + (row + 0.5) * YCELL) * 1e4) / 1e4,
      center_lon: Math.round((XORIG + (col + 0.5) * XCELL) * 1e4) / 1e4,
      resolution_deg: Math.round(XCELL * 1e4) / 1e4,
    },
    run_start_utc: runStart.toISOString().replace('.000Z', 'Z'),
    hours: series.length,
    peak, series,
  };
}

exports.handler = async function (event) {
  const headers = {
    'Access-Control-Allow-Origin': '*',
    'Content-Type': 'application/json',
    // Cache per edge for 30 min: the model publishes a few times daily.
    'Cache-Control': 'public, max-age=1800',
  };
  if (event.httpMethod === 'OPTIONS') return { statusCode: 200, headers, body: '' };
  if (event.httpMethod !== 'GET') return { statusCode: 405, headers, body: JSON.stringify({ error: 'Method not allowed' }) };
  try {
    const q = event.queryStringParameters || {};
    const lat = q.lat ? parseFloat(q.lat) : DEFAULT_LAT;
    const lon = q.lon ? parseFloat(q.lon) : DEFAULT_LON;
    const fc = await buildForecast(lat, lon);
    return { statusCode: 200, headers, body: JSON.stringify(fc) };
  } catch (e) {
    return {
      statusCode: e.statusCode || 502,
      headers,
      body: JSON.stringify({ error: String(e.message || e) }),
    };
  }
};
