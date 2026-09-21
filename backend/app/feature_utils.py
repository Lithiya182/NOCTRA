"""Spatial helpers built on the haversine package (no GIS extension required)."""
from __future__ import annotations

import json
import math
from pathlib import Path

from haversine import Unit, haversine

from .config import OSM_GEOJSON

M = Unit.METERS


def dist_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in metres between (lat, lon) pairs."""
    return haversine(a, b, unit=M)


def point_in_polygon(lat: float, lon: float, ring: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test (planar approximation; fine at this scale).
    
    Args:
        lat: Point latitude
        lon: Point longitude
        ring: Polygon ring as list of (lat, lon) tuples
    """
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        lat_i, lon_i = ring[i]
        lat_j, lon_j = ring[j]
        # Check if ray crosses edge
        if ((lat_i > lat) != (lat_j > lat)) and (
            lon < (lon_j - lon_i) * (lat - lat_i) / (lat_j - lat_i) + lon_i
        ):
            inside = not inside
        j = i
    return inside


def _sample_ring(ring: list[tuple[float, float]], step_m: float = 150.0) -> list[tuple[float, float]]:
    """Densify a polygon ring into points ~step_m apart so haversine gives good
    point-to-boundary distances."""
    pts: list[tuple[float, float]] = []
    n = len(ring)
    for i in range(n):
        a, b = ring[i], ring[(i + 1) % n]
        d = dist_m(a, b)
        steps = max(1, int(math.ceil(d / step_m)))
        for k in range(steps):
            t = k / steps
            pts.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return pts


def distance_to_polygon(
    lat: float, lon: float, ring: list[tuple[float, float]]
) -> float:
    """Distance in metres from a point to a polygon: 0 if inside, else distance to
    the densified boundary."""
    if point_in_polygon(lat, lon, ring):
        return 0.0
    return min(dist_m((lat, lon), p) for p in _sample_ring(ring))


def load_polygons(path: Path | str = OSM_GEOJSON) -> list[dict]:
    """Load OSM seed polygons -> [{kind, name, ring: [(lat, lon), ...]}].
    Source GeoJSON uses standard [lon, lat] ordering (CRS84).
    Converts to internal (lat, lon) representation."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    polys = []
    for feature in raw.get("features", []):
        geom = feature.get("geometry", {})
        ring_coords = geom.get("coordinates", [[]])[0]  # standard [lon, lat] ordering
        # Convert from [lon, lat] to (lat, lon) for internal use
        ring = [(pt[1], pt[0]) for pt in ring_coords if len(pt) >= 2]
        if len(ring) >= 3:
            polys.append({
                "kind": feature.get("properties", {}).get("kind", "other"),
                "name": feature.get("properties", {}).get("name", ""),
                "ring": ring,
            })
    return polys


def nearest_polygon_dist(
    lat: float, lon: float, polys: list[dict], kind: str
) -> float:
    """Minimum distance to any polygon of the given kind (large if none present)."""
    candidates = [p for p in polys if p["kind"] == kind]
    if not candidates:
        return 999_999.0
    return min(distance_to_polygon(lat, lon, p["ring"]) for p in candidates)


def inside_polygon(lat: float, lon: float, polys: list[dict], kind: str) -> bool:
    return any(
        point_in_polygon(lat, lon, p["ring"]) for p in polys if p["kind"] == kind
    )