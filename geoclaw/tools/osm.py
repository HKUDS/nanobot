"""OSM extraction and place profile tools."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from geoclaw.tools.base import GeoTool
from geoclaw.tools.common import parse_bbox


def _load_geometry_from_input(
    *,
    bbox: dict | list | None = None,
    geojson: dict | None = None,
    file_path: str | None = None,
    place_name: str | None = None,
):
    import geopandas as gpd
    from shapely.geometry import box, shape

    if geojson is not None:
        geo_type = geojson.get("type", "")
        if geo_type == "FeatureCollection":
            gdf = gpd.GeoDataFrame.from_features(geojson["features"], crs="EPSG:4326")
        elif geo_type == "Feature":
            gdf = gpd.GeoDataFrame.from_features([geojson], crs="EPSG:4326")
        else:
            gdf = gpd.GeoDataFrame(geometry=[shape(geojson)], crs="EPSG:4326")
        return gdf.union_all()

    if bbox is not None:
        bb = parse_bbox(bbox)
        return box(bb.west, bb.south, bb.east, bb.north)

    if file_path:
        gdf = gpd.read_file(str(Path(file_path).expanduser()))
        if gdf.crs and str(gdf.crs).upper() != "EPSG:4326":
            gdf = gdf.to_crs("EPSG:4326")
        return gdf.union_all()

    if place_name:
        import osmnx as ox

        gdf = ox.geocode_to_gdf(place_name)
        if gdf.crs and str(gdf.crs).upper() != "EPSG:4326":
            gdf = gdf.to_crs("EPSG:4326")
        return gdf.union_all()

    raise ValueError("Provide bbox, geojson, file_path, or place_name.")


class ExtractOSMByGeometryTool(GeoTool):
    """Extract OpenStreetMap features for an AOI using QuackOSM."""

    @property
    def name(self) -> str:
        return "geo_extract_osm"

    @property
    def description(self) -> str:
        return (
            "Extract OpenStreetMap features for an AOI using QuackOSM. Accepts "
            "bbox, GeoJSON, file path, or place name plus optional tags_filter."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "bbox": {"type": "object"},
                "geojson": {"type": "object"},
                "file_path": {"type": "string"},
                "place_name": {"type": "string"},
                "tags_filter": {
                    "type": "object",
                    "description": "QuackOSM tag filter mapping, e.g. {'amenity': True}",
                },
                "run_id": {"type": "string"},
            },
        }

    async def execute(self, **kwargs: Any) -> str:
        from quackosm import convert_geometry_to_geodataframe

        t0 = time.monotonic()
        run_id = kwargs.get("run_id") or self._new_run_id()
        params = {k: v for k, v in kwargs.items() if k != "run_id"}
        try:
            geometry = _load_geometry_from_input(
                bbox=kwargs.get("bbox"),
                geojson=kwargs.get("geojson"),
                file_path=kwargs.get("file_path"),
                place_name=kwargs.get("place_name"),
            )
            tags_filter = kwargs.get("tags_filter") or {
                "amenity": True,
                "shop": True,
                "leisure": True,
                "tourism": True,
                "building": True,
            }
            work_dir = self._artifact_dir(run_id)
            gdf = convert_geometry_to_geodataframe(
                geometry_filter=geometry,
                tags_filter=tags_filter,
                working_directory=work_dir,
                allow_uncovered_geometry=True,
                verbosity_mode="silent",
            )
            if gdf.crs and str(gdf.crs).upper() != "EPSG:4326":
                gdf = gdf.to_crs("EPSG:4326")

            category_counts: dict[str, int] = {}
            for col in ("amenity", "shop", "leisure", "tourism", "building", "highway"):
                if col in gdf.columns:
                    values = gdf[col].dropna().astype(str)
                    if not values.empty:
                        category_counts[col] = int(values.shape[0])

            artifacts = []
            geojson_artifact = self._save_artifact(
                run_id,
                "osm_extract.geojson",
                gdf.to_json(),
                "geojson",
                "OSM extract",
            )
            artifacts.append(geojson_artifact)
            try:
                parquet_path = self._artifact_dir(run_id) / "osm_extract.parquet"
                gdf.to_parquet(parquet_path)
                artifacts.append(
                    type(geojson_artifact)(
                        path=str(parquet_path),
                        format="geoparquet",
                        size_bytes=parquet_path.stat().st_size,
                        description="OSM extract (GeoParquet)",
                    )
                )
            except Exception:
                pass

            result = self._ok(
                summary=f"Extracted {len(gdf)} OSM feature(s) for the AOI.",
                data={
                    "run_id": run_id,
                    "feature_count": len(gdf),
                    "columns": list(gdf.columns),
                    "category_counts": category_counts,
                    "tags_filter": tags_filter,
                },
                artifacts=artifacts,
                provenance=self._make_provenance(params, time.monotonic() - t0, crs_used="EPSG:4326"),
            )
            return result.to_llm_string()
        except Exception as exc:
            return self._fail(str(exc)).to_llm_string()


class BuildPlaceProfileTool(GeoTool):
    """Build a narrative place profile from extracted OSM features."""

    @property
    def name(self) -> str:
        return "geo_build_place_profile"

    @property
    def description(self) -> str:
        return (
            "Build a place profile from an OSM extraction GeoJSON or file. Returns "
            "category counts, summary stats, and a short narrative."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "geojson": {"type": "object"},
            },
        }

    async def execute(self, **kwargs: Any) -> str:
        import geopandas as gpd
        from shapely.geometry import shape

        t0 = time.monotonic()
        try:
            if kwargs.get("file_path"):
                gdf = gpd.read_file(str(Path(kwargs["file_path"]).expanduser()))
            elif kwargs.get("geojson"):
                geojson = kwargs["geojson"]
                geo_type = geojson.get("type", "")
                if geo_type == "FeatureCollection":
                    gdf = gpd.GeoDataFrame.from_features(geojson["features"], crs="EPSG:4326")
                elif geo_type == "Feature":
                    gdf = gpd.GeoDataFrame.from_features([geojson], crs="EPSG:4326")
                else:
                    gdf = gpd.GeoDataFrame(geometry=[shape(geojson)], crs="EPSG:4326")
            else:
                return self._fail("Provide file_path or geojson.").to_llm_string()

            category_values: dict[str, dict[str, int]] = {}
            for col in ("amenity", "shop", "leisure", "tourism", "building", "highway"):
                if col in gdf.columns:
                    series = gdf[col].dropna().astype(str)
                    if not series.empty:
                        category_values[col] = series.value_counts().head(10).astype(int).to_dict()

            geom_mix = (
                gdf.geometry.geom_type.value_counts().astype(int).to_dict()
                if not gdf.empty
                else {}
            )
            top_sections = []
            for key, vals in category_values.items():
                if vals:
                    preview = ", ".join(f"{k} ({v})" for k, v in list(vals.items())[:3])
                    top_sections.append(f"{key}: {preview}")
            narrative = (
                f"The AOI contains {len(gdf)} mapped OSM features. "
                + ("Top mapped categories are " + "; ".join(top_sections) + "." if top_sections else "Few thematic tags were present.")
            )

            result = self._ok(
                summary=f"Built place profile for {len(gdf)} OSM feature(s).",
                data={
                    "feature_count": len(gdf),
                    "geometry_mix": geom_mix,
                    "category_values": category_values,
                    "narrative": narrative,
                },
                provenance=self._make_provenance(
                    {
                        "file_path": kwargs.get("file_path"),
                        "has_geojson": kwargs.get("geojson") is not None,
                    },
                    time.monotonic() - t0,
                    crs_used=str(gdf.crs) if gdf.crs else None,
                ),
            )
            return result.to_llm_string()
        except Exception as exc:
            return self._fail(str(exc)).to_llm_string()
