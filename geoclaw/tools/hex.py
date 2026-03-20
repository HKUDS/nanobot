"""H3 hex aggregation tools."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import h3

from geoclaw.tools.base import GeoTool


def _load_geodataframe(file_path: str | None = None, geojson: dict | None = None):
    import geopandas as gpd
    from shapely.geometry import shape

    if file_path:
        gdf = gpd.read_file(str(Path(file_path).expanduser()))
    elif geojson is not None:
        geo_type = geojson.get("type", "")
        if geo_type == "FeatureCollection":
            gdf = gpd.GeoDataFrame.from_features(geojson["features"], crs="EPSG:4326")
        elif geo_type == "Feature":
            gdf = gpd.GeoDataFrame.from_features([geojson], crs="EPSG:4326")
        else:
            gdf = gpd.GeoDataFrame(geometry=[shape(geojson)], crs="EPSG:4326")
    else:
        raise ValueError("Provide file_path or geojson.")
    if gdf.crs and str(gdf.crs).upper() != "EPSG:4326":
        gdf = gdf.to_crs("EPSG:4326")
    return gdf


class PointToH3Tool(GeoTool):
    @property
    def name(self) -> str:
        return "geo_point_to_h3"

    @property
    def description(self) -> str:
        return "Assign point features to H3 cells at the requested resolution."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "geojson": {"type": "object"},
                "resolution": {"type": "integer"},
                "run_id": {"type": "string"},
            },
            "required": ["resolution"],
        }

    async def execute(self, **kwargs: Any) -> str:
        t0 = time.monotonic()
        run_id = kwargs.get("run_id") or self._new_run_id()
        try:
            gdf = _load_geodataframe(kwargs.get("file_path"), kwargs.get("geojson"))
            points = gdf[gdf.geometry.geom_type.isin(["Point", "MultiPoint"])].copy()
            if points.empty:
                return self._fail("No point geometries found in input.").to_llm_string()

            resolution = kwargs["resolution"]
            points["h3_cell"] = points.geometry.apply(lambda geom: h3.latlng_to_cell(geom.y, geom.x, resolution))
            out_path = self._artifact_dir(run_id) / "points_h3.geojson"
            points.to_file(out_path, driver="GeoJSON")
            result = self._ok(
                summary=f"Assigned {len(points)} point(s) to H3 resolution {resolution}.",
                data={
                    "resolution": resolution,
                    "feature_count": len(points),
                    "unique_cells": int(points["h3_cell"].nunique()),
                    "run_id": run_id,
                },
                artifacts=[
                    self._save_artifact(
                        run_id,
                        "points_h3_manifest.json",
                        json.dumps({"path": str(out_path)}, ensure_ascii=False),
                        "json",
                        "H3 point manifest",
                    ),
                ],
                provenance=self._make_provenance(
                    {"resolution": resolution, "feature_count": len(points)},
                    time.monotonic() - t0,
                    crs_used="EPSG:4326",
                ),
            )
            return result.to_llm_string()
        except Exception as exc:
            return self._fail(str(exc)).to_llm_string()


class PolygonToH3Tool(GeoTool):
    @property
    def name(self) -> str:
        return "geo_polygon_to_h3"

    @property
    def description(self) -> str:
        return "Polyfill polygon features into H3 cells at the requested resolution."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "geojson": {"type": "object"},
                "resolution": {"type": "integer"},
            },
            "required": ["resolution"],
        }

    async def execute(self, **kwargs: Any) -> str:
        from shapely.geometry import mapping

        t0 = time.monotonic()
        try:
            gdf = _load_geodataframe(kwargs.get("file_path"), kwargs.get("geojson"))
            polys = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
            if polys.empty:
                return self._fail("No polygon geometries found in input.").to_llm_string()
            resolution = kwargs["resolution"]
            cell_counts = []
            for geom in polys.geometry:
                cells = h3.geo_to_cells(mapping(geom), resolution)
                cell_counts.append(len(cells))
            result = self._ok(
                summary=f"Polyfilled {len(polys)} polygon(s) to H3 resolution {resolution}.",
                data={
                    "resolution": resolution,
                    "feature_count": len(polys),
                    "cell_counts": cell_counts,
                    "total_cells": int(sum(cell_counts)),
                },
                provenance=self._make_provenance(
                    {"resolution": resolution, "feature_count": len(polys)},
                    time.monotonic() - t0,
                    crs_used="EPSG:4326",
                ),
            )
            return result.to_llm_string()
        except Exception as exc:
            return self._fail(str(exc)).to_llm_string()


class AggregateByH3Tool(GeoTool):
    @property
    def name(self) -> str:
        return "geo_aggregate_by_h3"

    @property
    def description(self) -> str:
        return "Aggregate point features by H3 cell using count, sum, or mean."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "geojson": {"type": "object"},
                "resolution": {"type": "integer"},
                "metric_property": {"type": "string"},
                "agg_method": {"type": "string", "enum": ["count", "sum", "mean"]},
                "run_id": {"type": "string"},
            },
            "required": ["resolution"],
        }

    async def execute(self, **kwargs: Any) -> str:
        import geopandas as gpd
        import pandas as pd
        from shapely.geometry import Polygon

        t0 = time.monotonic()
        run_id = kwargs.get("run_id") or self._new_run_id()
        try:
            gdf = _load_geodataframe(kwargs.get("file_path"), kwargs.get("geojson"))
            points = gdf[gdf.geometry.geom_type == "Point"].copy()
            if points.empty:
                return self._fail("Aggregation currently supports Point features only.").to_llm_string()

            resolution = kwargs["resolution"]
            points["h3_cell"] = points.geometry.apply(lambda geom: h3.latlng_to_cell(geom.y, geom.x, resolution))

            metric = kwargs.get("metric_property")
            method = kwargs.get("agg_method", "count")
            if method == "count" or not metric:
                agg = points.groupby("h3_cell").size().reset_index(name="value")
            elif method == "sum":
                agg = points.groupby("h3_cell")[metric].sum().reset_index(name="value")
            else:
                agg = points.groupby("h3_cell")[metric].mean().reset_index(name="value")

            agg["geometry"] = agg["h3_cell"].apply(
                lambda cell: Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(cell)])
            )
            hex_gdf = gpd.GeoDataFrame(agg, geometry="geometry", crs="EPSG:4326")
            out_path = self._artifact_dir(run_id) / "hex_aggregation.geojson"
            hex_gdf.to_file(out_path, driver="GeoJSON")

            values = hex_gdf["value"]
            data = {
                "resolution": resolution,
                "hex_count": len(hex_gdf),
                "distribution": {
                    "min": float(values.min()) if len(values) else None,
                    "max": float(values.max()) if len(values) else None,
                    "mean": float(values.mean()) if len(values) else None,
                },
                "metric_property": metric,
                "agg_method": method,
                "run_id": run_id,
            }
            result = self._ok(
                summary=f"Aggregated {len(points)} point(s) into {len(hex_gdf)} H3 cell(s).",
                data=data,
                artifacts=[
                    self._save_artifact(
                        run_id,
                        "hex_aggregation_manifest.json",
                        json.dumps({"path": str(out_path)}, ensure_ascii=False),
                        "json",
                        "Hex aggregation manifest",
                    )
                ],
                provenance=self._make_provenance(
                    {
                        "resolution": resolution,
                        "metric_property": metric,
                        "agg_method": method,
                    },
                    time.monotonic() - t0,
                    crs_used="EPSG:4326",
                ),
            )
            return result.to_llm_string()
        except Exception as exc:
            return self._fail(str(exc)).to_llm_string()


class NeighborhoodSummaryTool(GeoTool):
    @property
    def name(self) -> str:
        return "geo_neighborhood_summary"

    @property
    def description(self) -> str:
        return "Summarize the H3 neighborhood around a cell using grid distance k."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "h3_cell": {"type": "string"},
                "k": {"type": "integer"},
            },
            "required": ["h3_cell"],
        }

    async def execute(self, **kwargs: Any) -> str:
        t0 = time.monotonic()
        try:
            h3_cell = kwargs["h3_cell"]
            k = kwargs.get("k", 1)
            neighbors = list(h3.grid_disk(h3_cell, k))
            center = h3.cell_to_latlng(h3_cell)
            result = self._ok(
                summary=f"H3 neighborhood contains {len(neighbors)} cell(s) for k={k}.",
                data={
                    "h3_cell": h3_cell,
                    "k": k,
                    "neighbor_count": len(neighbors),
                    "center_latlng": center,
                    "neighbors": neighbors,
                },
                provenance=self._make_provenance(
                    {"h3_cell": h3_cell, "k": k},
                    time.monotonic() - t0,
                ),
            )
            return result.to_llm_string()
        except Exception as exc:
            return self._fail(str(exc)).to_llm_string()
