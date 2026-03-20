"""CRS inference and validation utilities."""

from __future__ import annotations

from typing import Any


def suggest_utm_crs(lon: float, lat: float) -> str:
    """Return the EPSG code for the UTM zone covering (*lon*, *lat*)."""
    zone_number = int((lon + 180) / 6) + 1
    if lat >= 0:
        return f"EPSG:{32600 + zone_number}"
    return f"EPSG:{32700 + zone_number}"


def suggest_projected_crs(west: float, south: float, east: float, north: float) -> str:
    """Suggest a projected CRS for a bounding box.

    Uses the centroid to pick a UTM zone.  For very large extents that span
    many UTM zones a Web Mercator fallback is returned.
    """
    lon_span = abs(east - west)
    if lon_span > 12:
        return "EPSG:3857"
    center_lon = (west + east) / 2
    center_lat = (south + north) / 2
    return suggest_utm_crs(center_lon, center_lat)


def validate_epsg(code: str) -> bool:
    """Check whether *code* looks like a valid EPSG string."""
    if not code.upper().startswith("EPSG:"):
        return False
    try:
        int(code.split(":")[1])
        return True
    except (IndexError, ValueError):
        return False


def describe_crs(crs_input: Any) -> dict[str, Any]:
    """Return a dict describing the CRS in human-readable terms.

    Accepts pyproj.CRS, a string like 'EPSG:4326', or a WKT string.
    """
    try:
        from pyproj import CRS
        crs = CRS(crs_input)
        return {
            "name": crs.name,
            "authority": crs.to_authority() if crs.to_authority() else None,
            "is_geographic": crs.is_geographic,
            "is_projected": crs.is_projected,
            "units": str(crs.axis_info[0].unit_name) if crs.axis_info else "unknown",
        }
    except Exception as exc:
        return {"error": str(exc)}
