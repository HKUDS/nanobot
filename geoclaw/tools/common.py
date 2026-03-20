"""Shared helpers used across GeoClaw tool modules."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from geoclaw.adapters.workspace import WorkspaceManager
from geoclaw.schemas.common import BBox


def parse_bbox(raw: Any) -> BBox:
    """Coerce various bbox representations into a BBox.

    Accepts:
      - a dict with west/south/east/north keys
      - a list/tuple of [west, south, east, north]
      - a JSON string of either form
    """
    if isinstance(raw, str):
        raw = json.loads(raw)
    if isinstance(raw, BBox):
        return raw
    if isinstance(raw, (list, tuple)) and len(raw) == 4:
        return BBox(west=raw[0], south=raw[1], east=raw[2], north=raw[3])
    if isinstance(raw, dict):
        return BBox(**raw)
    raise ValueError(f"Cannot parse bbox from {type(raw).__name__}: {raw!r}")


def bbox_from_geojson(geojson: dict) -> BBox:
    """Compute the bounding box of a GeoJSON geometry or feature."""
    from shapely.geometry import shape
    geom = _extract_geometry(geojson)
    s = shape(geom)
    minx, miny, maxx, maxy = s.bounds
    return BBox(west=minx, south=miny, east=maxx, north=maxy)


def _extract_geometry(geojson: dict) -> dict:
    """Pull the geometry dict from a GeoJSON object (Feature, FeatureCollection, or bare)."""
    t = geojson.get("type", "")
    if t == "Feature":
        return geojson["geometry"]
    if t == "FeatureCollection":
        return geojson["features"][0]["geometry"]
    return geojson


def estimate_area_sq_km(bbox: BBox) -> float:
    """Rough area estimate for a geographic bbox in square kilometres.

    Uses a simple cos(mid-latitude) scaling.  Not suitable for precise work.
    """
    import math
    mid_lat = (bbox.south + bbox.north) / 2
    lat_km = 111.32
    lon_km = 111.32 * math.cos(math.radians(mid_lat))
    width = abs(bbox.east - bbox.west) * lon_km
    height = abs(bbox.north - bbox.south) * lat_km
    return width * height


def safe_read_geojson(path: Path) -> dict:
    """Read a GeoJSON file and return the parsed dict."""
    text = path.read_text(encoding="utf-8")
    return json.loads(text)
