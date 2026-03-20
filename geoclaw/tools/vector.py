"""Basic vector tools for the GeoClaw MVP."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from geoclaw.schemas.common import ArtifactMeta
from geoclaw.tools.base import GeoTool


class ReadVectorTool(GeoTool):
    """Read a vector dataset and save a normalized GeoJSON artifact."""

    @property
    def name(self) -> str:
        return "geo_read_vector"

    @property
    def description(self) -> str:
        return (
            "Read a vector dataset from a local file path and return feature count, "
            "CRS, geometry types, bounds, and a normalized GeoJSON artifact."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to a vector dataset supported by GeoPandas/Fiona",
                },
                "run_id": {
                    "type": "string",
                    "description": "Optional run ID for artifact storage",
                },
            },
            "required": ["file_path"],
        }

    async def execute(self, **kwargs: Any) -> str:
        import geopandas as gpd

        t0 = time.monotonic()
        run_id = kwargs.get("run_id") or self._new_run_id()
        file_path = Path(kwargs["file_path"]).expanduser()
        try:
            gdf = gpd.read_file(str(file_path))
            bounds = gdf.total_bounds.tolist() if not gdf.empty else [None, None, None, None]
            artifacts: list[ArtifactMeta] = []
            try:
                artifact = self._save_artifact(
                    run_id,
                    f"{file_path.stem}.geojson",
                    gdf.to_json(),
                    "geojson",
                    "Normalized vector dataset",
                )
                artifacts.append(artifact)
            except Exception:
                pass

            result = self._ok(
                summary=(
                    f"Loaded {len(gdf)} feature(s) from {file_path.name} "
                    f"with CRS {gdf.crs or 'unknown'}."
                ),
                data={
                    "file_path": str(file_path),
                    "feature_count": len(gdf),
                    "columns": list(gdf.columns),
                    "geometry_types": list(gdf.geometry.geom_type.unique()) if not gdf.empty else [],
                    "crs": str(gdf.crs) if gdf.crs else None,
                    "bounds": bounds,
                    "run_id": run_id,
                },
                artifacts=artifacts,
                provenance=self._make_provenance(
                    {"file_path": str(file_path)},
                    time.monotonic() - t0,
                    crs_used=str(gdf.crs) if gdf.crs else None,
                ),
            )
            return result.to_llm_string()
        except Exception as exc:
            return self._fail(str(exc)).to_llm_string()


class SummarizeVectorTool(GeoTool):
    """Summarize geometry and attribute properties of a vector dataset."""

    @property
    def name(self) -> str:
        return "geo_summarize_vector"

    @property
    def description(self) -> str:
        return (
            "Summarize a vector dataset from file_path or inline GeoJSON. Returns feature "
            "count, bounds, geometry mix, CRS, columns, null counts, and approximate area."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to a vector dataset"},
                "geojson": {"type": "object", "description": "Inline GeoJSON"},
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

            bounds = gdf.total_bounds.tolist() if not gdf.empty else [None, None, None, None]
            area_estimate = None
            if not gdf.empty and str(gdf.crs).upper() == "EPSG:4326":
                from geoclaw.tools.common import estimate_area_sq_km, parse_bbox

                area_estimate = round(estimate_area_sq_km(parse_bbox(bounds)), 2)

            null_counts = {
                col: int(gdf[col].isna().sum())
                for col in gdf.columns
                if col != gdf.geometry.name
            }
            result = self._ok(
                summary=f"Vector summary: {len(gdf)} feature(s), CRS={gdf.crs or 'unknown'}.",
                data={
                    "feature_count": len(gdf),
                    "columns": list(gdf.columns),
                    "geometry_types": list(gdf.geometry.geom_type.unique()) if not gdf.empty else [],
                    "crs": str(gdf.crs) if gdf.crs else None,
                    "bounds": bounds,
                    "null_counts": null_counts,
                    "area_estimate_sq_km": area_estimate,
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
