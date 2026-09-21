"""Generate deterministic, realistic seed data for ThermalGuard's offline demo.

Writes:
  data/firms_seed.csv   - synthesized VIIRS detections (5 satellite passes) across
                          Jharia coalfield (mine fire), Jamnagar refinery (flares),
                          Punjab stubble-burning window (agricultural bursts), and
                          an expanding Uttarakhand forest wildfire, plus noise rows.
  data/osm_seed.geojson - OSM land-use polygons (industrial / agricultural /
                          residential / forest) bounding all four regions.

Use scripts/fetch_firms.py + scripts/fetch_osm.py to replace with real pre-fetched
data; this generator exists so the demo never depends on live APIs.
"""
from __future__ import annotations

import csv
import json
import math
import random
from pathlib import Path

random.seed(42)

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

ACQ_DATES = ["2025-11-10", "2025-11-11", "2025-11-12", "2025-11-13", "2025-11-14"]
DAY_TIMES = ["1340", "1355", "0140"]

CSV_HEADERS = [
    "latitude", "longitude", "bright_ti4", "scan", "track", "acq_date", "acq_time",
    "satellite", "instrument", "confidence", "version", "bright_ti5", "frp", "daynight",
]

FIRMS_VERSION = "10.1.1_NRT"


def _gauss(cx: float, cy: float, spread: float) -> tuple[float, float]:
    return (cx + random.gauss(0, spread), cy + random.gauss(0, spread))


def _jitter_small(cx: float, cy: float, spread: float = 0.0015) -> tuple[float, float]:
    return (cx + random.uniform(-spread, spread), cy + random.uniform(-spread, spread))


def _row(lat, lon, ti4, ti5, acq_date, acq_time, conf, frp, sat=None) -> dict:
    sat = sat or random.choice(["NPP", "NOAA-20"])
    return {
        "latitude": round(lat, 5),
        "longitude": round(lon, 5),
        "bright_ti4": round(ti4, 2),
        "scan": round(random.uniform(0.35, 0.45), 3),
        "track": round(random.uniform(0.35, 0.45), 3),
        "acq_date": acq_date,
        "acq_time": acq_time,
        "satellite": sat,
        "instrument": "VIIRS",
        "confidence": int(conf),
        "version": FIRMS_VERSION,
        "bright_ti5": round(ti5, 2),
        "frp": round(frp, 2),
        "daynight": "D" if acq_time < "1200" else "N",
    }


def jharia_rows() -> list[dict]:
    """Persistent underground mine-fire clusters (active on 4-5 of 5 passes).
    Mine fires persist at a fixed bench, so detections stay tight (~450 m)."""
    rows = []
    clusters = [
        ((23.742, 86.338), 0.004, 0.97, 60.0, 352.0),  # mine benches
        ((23.756, 86.362), 0.004, 0.95, 48.0, 355.0),
        ((23.728, 86.325), 0.004, 0.93, 85.0, 348.0),
        ((23.805, 86.428), 0.004, 0.96, 42.0, 351.0),
        ((23.818, 86.447), 0.004, 0.90, 38.0, 350.0),
    ]
    for (cx, cy), spread, persist, base_frp, base_ti4 in clusters:
        for dt in ACQ_DATES:
            if random.random() > persist:
                continue
            n = random.randint(2, 5)
            for _ in range(n):
                lat, lon = _gauss(cx, cy, spread)
                frp = max(5.0, random.gauss(base_frp, base_frp * 0.18))
                ti4 = min(400.0, base_ti4 + random.gauss(0, 6))
                rows.append(_row(lat, lon, ti4, 298.0 + random.random() * 6,
                                 dt, random.choice(DAY_TIMES), random.uniform(85, 99),
                                 frp))
    return rows


def jamnagar_rows() -> list[dict]:
    """Refinery flare stacks - very hot, moderately persistent."""
    rows = []
    clusters = [(22.466, 70.023), (22.478, 70.048), (22.485, 70.005)]
    for cx, cy in clusters:
        for dt in ACQ_DATES:
            if random.random() > 0.9:
                continue
            n = random.randint(1, 3)
            for _ in range(n):
                lat, lon = _jitter_small(cx, cy, 0.0018)
                frp = random.uniform(8, 45)
                ti4 = random.gauss(388, 8)
                rows.append(_row(lat, lon, ti4, 306.0 + random.random() * 4,
                                 dt, random.choice(DAY_TIMES), random.uniform(90, 99), frp))
    return rows


def punjab_rows() -> list[dict]:
    """Stubble-burning bursts - many patches, each active only 1-2 days."""
    rows = []
    patches = []
    for _ in range(60):
        patches.append((random.uniform(30.30, 31.18), random.uniform(74.95, 76.55)))
    for cx, cy in patches:
        ndays = random.choice([1, 1, 2, 2, 2, 3])
        start = random.randrange(len(ACQ_DATES) - ndays + 1)
        for k in range(ndays):
            dt = ACQ_DATES[start + k]
            n = random.randint(1, 3)
            for _ in range(n):
                lat, lon = _gauss(cx, cy, 0.004)
                frp = random.uniform(2, 25)
                conf = random.uniform(40, 95)
                ti4 = random.uniform(315, 340)
                rows.append(_row(lat, lon, ti4, 288.0 + random.random() * 8,
                                 dt, random.choice(DAY_TIMES), conf, frp))
    return rows


def uttarakhand_rows() -> list[dict]:
    """Expanding forest wildfire - footprint grows day over day, frp climbing.
    Kept compact enough that every point sits within 3 km of the fire centroid so
    the day-over-day expansion is detected by every site nearby."""
    rows = []
    phases = [
        (0.004, 5, 58.0),
        (0.007, 9, 72.0),
        (0.010, 14, 85.0),
        (0.013, 19, 102.0),
        (0.016, 26, 128.0),
    ]
    cx, cy = 30.075, 79.185
    for idx, (spread, n, base_frp) in enumerate(phases):
        dt = ACQ_DATES[idx]
        for _ in range(n):
            lat, lon = _gauss(cx, cy, spread)
            frp = max(50.0, random.gauss(base_frp, base_frp * 0.15))
            ti4 = random.gauss(344, 8)
            rows.append(_row(lat, lon, ti4, 300.0 + random.random() * 6,
                             dt, random.choice(DAY_TIMES), random.uniform(60, 100), frp))
    return rows


def noise_rows() -> list[dict]:
    """Isolated low-FRP detections with no persistence -> 'other'."""
    rows = []
    spots = [
        (24.320, 84.760, 5.0),
        (24.150, 84.050, 8.0),
        (23.950, 85.320, 3.0),
        (24.450, 85.100, 11.0),
        (24.620, 86.420, 4.0),
        (23.500, 85.020, 7.0),
        (24.080, 85.700, 2.0),
        (23.380, 84.600, 12.0),
        (24.300, 85.520, 6.0),
        (23.860, 84.820, 9.0),
    ]
    for lat, lon, frp in spots:
        dt = random.choice(ACQ_DATES)
        rows.append(_row(lat, lon, random.uniform(305, 325), 286.0 + random.random() * 6,
                         dt, random.choice(DAY_TIMES), random.uniform(20, 60), frp))
    return rows


def build_osm_features() -> list[dict]:
    def poly(coords, kind, name):
        # coords are in (lon, lat) order for standard GeoJSON [lon, lat]
        return {
            "type": "Feature",
            "properties": {"kind": kind, "name": name},
            "geometry": {"type": "Polygon", "coordinates": [coords]},
        }

    features = [
        # --- Jharia coalfield industrial (mine leases) - sized to cover the
        # persistent mine-fire clusters ---
        poly([(86.290, 23.695), (86.290, 23.790), (86.385, 23.790), (86.385, 23.695)],
             "industrial", "Jharia Colliery Block A"),
        poly([(86.385, 23.780), (86.385, 23.850), (86.475, 23.850), (86.475, 23.780)],
             "industrial", "Jharia Colliery Block B"),
        poly([(86.420, 23.748), (86.420, 23.772), (86.450, 23.772), (86.450, 23.748)],
             "residential", "Dhanbad City"),
        # --- Jamnagar refinery belt ---
        poly([(69.972, 22.428), (69.972, 22.502), (70.058, 22.502), (70.058, 22.428)],
             "industrial", "Jamnagar Refinery Complex"),
        poly([(70.175, 22.355), (70.175, 22.422), (70.243, 22.422), (70.243, 22.355)],
             "industrial", "Gujarat Industrial Estate"),
        poly([(70.055, 22.458), (70.055, 22.502), (70.105, 22.502), (70.105, 22.458)],
             "residential", "Jamnagar City"),
        # --- Punjab agricultural belts (stubble window) - tiled & overlapping so
        # every stubble point sits inside farmland ---
        poly([(74.70, 30.15), (74.70, 30.80), (75.55, 30.80), (75.55, 30.15)],
             "agricultural", "Farmland Punjab SW"),
        poly([(75.55, 30.15), (75.55, 30.80), (76.25, 30.80), (76.25, 30.15)],
             "agricultural", "Farmland Punjab S"),
        poly([(74.70, 30.80), (74.70, 31.35), (75.55, 31.35), (75.55, 30.80)],
             "agricultural", "Farmland Punjab NW"),
        poly([(75.55, 30.80), (75.55, 31.35), (76.25, 31.35), (76.25, 30.80)],
             "agricultural", "Farmland Punjab N"),
        poly([(76.25, 30.15), (76.25, 31.35), (76.95, 31.35), (76.95, 30.15)],
             "agricultural", "Farmland Punjab E"),
        poly([(75.835, 30.875), (75.835, 30.930), (75.900, 30.930), (75.900, 30.875)],
             "residential", "Ludhiana City"),
        # --- Uttarakhand forest wildfire ---
        poly([(79.05, 30.00), (79.05, 30.16), (79.32, 30.16), (79.32, 30.00)],
             "forest", "Almora Forest Range"),
        poly([(79.265, 30.055), (79.265, 30.110), (79.330, 30.110), (79.330, 30.055)],
             "residential", "Pithoragarh Town"),
    ]
    return {
        "type": "FeatureCollection",
        "name": "thermalguard_osm_seed",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": features,
    }


def main() -> None:
    DATA.mkdir(exist_ok=True)
    all_rows = (jharia_rows() + jamnagar_rows() + punjab_rows() +
                uttarakhand_rows() + noise_rows())
    random.shuffle(all_rows)

    csv_path = DATA / "firms_seed.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()
        writer.writerows(all_rows)

    geojson_path = DATA / "osm_seed.geojson"
    with open(geojson_path, "w", encoding="utf-8") as f:
        json.dump(build_osm_features(), f, indent=1)

    kinds = {}
    for feat in build_osm_features()["features"]:
        kinds[feat["properties"]["kind"]] = kinds.get(feat["properties"]["kind"], 0) + 1

    print(f"firms_seed.csv  : {len(all_rows):>5} detection rows")
    print(f"osm_seed.geojson: {sum(kinds.values())} polygons  {kinds}")
    print(f"regions         : Jharia {len(jharia_rows())}, Jamnagar {len(jamnagar_rows())}, "
          f"Punjab {len(punjab_rows())}, Uttarakhand {len(uttarakhand_rows())}, "
          f"noise {len(noise_rows())}")


if __name__ == "__main__":
    main()