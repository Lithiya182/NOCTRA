"""Pre-fetch OSM land-use polygons via Overpass API for the four demo regions.

Usage:  python scripts/fetch_osm.py
Queries industrial / agricultural / residential / forest features and caches to
data/osm_seed.geojson. Run once during setup, never live during a demo.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

DATA = Path(__file__).resolve().parent.parent / "data"

BOXES = {
    "jharia": "(23.70,86.30,23.86,86.50)",
    "jamnagar": "(22.35,69.85,22.60,70.25)",
    "punjab": "(30.15,74.70,31.30,76.80)",
    "uttarakhand": "(29.95,79.00,30.20,79.35)",
}
TAGS = ["landuse~industrial", "landuse=farmland", "landuse=residential", "landuse=forest",
        "natural=wood"]


def query(box: str) -> list[dict]:
    tag_filter = "|".join(TAGS)
    overpass = (
        f'[out:json][timeout:60];'
        f'((way["{tag_filter}"]{box};););out geom;'
    )
    resp = requests.post("https://overpass-api.de/api/interpreter",
                         data={"data": overpass}, timeout=120)
    resp.raise_for_status()
    return resp.json().get("elements", [])


KIND_MAP = {
    "industrial": "industrial",
    "farmland": "agricultural",
    "residential": "residential",
    "forest": "forest",
    "wood": "forest",
}


def to_feature(el: dict) -> dict:
    kind = "other"
    tags = el.get("tags", {})
    landuse = tags.get("landuse", "")
    kind = KIND_MAP.get(landuse, KIND_MAP.get(tags.get("natural", ""), "other"))
    coords = [[(pt["lon"], pt["lat"]) for pt in el.get("geometry", [])]]
    return {
        "type": "Feature",
        "properties": {"kind": kind, "name": tags.get("name", landuse)},
        "geometry": {"type": "Polygon", "coordinates": coords},
    }


def main() -> None:
    features: list[dict] = []
    for name, box in BOXES.items():
        try:
            els = query(box)
            feats = [to_feature(e) for e in els if len(e.get("geometry", [])) >= 3] or []
            print(f"  {name}: {len(feats)} polygons")
            features.extend(feats)
        except Exception as exc:  # noqa: BLE001
            print(f"  {name}: FAILED ({exc})")
        time.sleep(5)
    if not features:
        print("No OSM data fetched.")
        return
    out = DATA / "osm_seed.geojson"
    out.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": features,
    }, indent=1), encoding="utf-8")
    print(f"Wrote {len(features)} polygons -> {out}")


if __name__ == "__main__":
    main()