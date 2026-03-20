"""AOI inspection, validation, and CRS suggestion tools."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool

from geoclaw.adapters.crs import describe_crs, suggest_projected_crs, validate_epsg
from geoclaw.schemas.common import ArtifactMeta, ToolResult
from geoclaw.tools.base import GeoTool
from geoclaw.tools.common import bbox_from_geojson, estimate_area_sq_km, parse_bbox


# ---------------------------------------------------------------------------
# geo_inspect_aoi
# ---------------------------------------------------------------------------

class InspectAOITool(GeoTool):
    """Load an AOI from bbox / GeoJSON / file / place name and return key properties."""

    @property
    def name(self) -> str:
        return "geo_inspect_aoi"

    @property
    def description(self) -> str:
        return (
            "Inspect an Area of Interest. Accepts a bbox, inline GeoJSON, "
            "a file path (GeoJSON/GPKG/SHP), or a place name. Returns CRS, "
            "extent, feature count, area estimate, and geometry type."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "bbox": {
                    "type": "object",
                    "description": "Bounding box {west, south, east, north} or [w,s,e,n]",
                },
                "geojson": {
                    "type": "object",
                    "description": "Inline GeoJSON geometry, Feature, or FeatureCollection",
                },
                "file_path": {
                    "type": "string",
                    "description": "Path to a vector file (GeoJSON, GPKG, SHP)",
                },
                "place_name": {
                    "type": "string",
                    "description": "Place name to geocode (e.g. 'Beijing')",
                },
                "run_id": {
                    "type": "string",
                    "description": "Optional run ID for artifact storage",
                },
            },
        }

    async def execute(self, **kwargs: Any) -> str:
        t0 = time.monotonic()
        run_id = kwargs.get("run_id") or self._new_run_id()
        params = {k: v for k, v in kwargs.items() if k != "run_id"}
        try:
            result = self._inspect(params, run_id)
            prov = self._make_provenance(params, time.monotonic() - t0)
            result.provenance = prov
            return result.to_llm_string()
        except Exception as exc:
            return self._fail(str(exc)).to_llm_string()

    def _inspect(self, params: dict, run_id: str) -> ToolResult:
        import geopandas as gpd
        from shapely.geometry import box, mapping, shape

        bbox_raw = params.get("bbox")
        geojson_raw = params.get("geojson")
        file_path = params.get("file_path")
        place_name = params.get("place_name")

        gdf: gpd.GeoDataFrame | None = None
        source = "unknown"

        if file_path:
            p = Path(file_path).expanduser()
            if not p.exists():
                return self._fail(f"File not found: {file_path}")
            gdf = gpd.read_file(str(p))
            source = f"file:{p.name}"

        elif geojson_raw:
            geom_type = geojson_raw.get("type", "")
            if geom_type == "FeatureCollection":
                gdf = gpd.GeoDataFrame.from_features(geojson_raw["features"], crs="EPSG:4326")
            elif geom_type == "Feature":
                gdf = gpd.GeoDataFrame.from_features([geojson_raw], crs="EPSG:4326")
            else:
                s = shape(geojson_raw)
                gdf = gpd.GeoDataFrame(geometry=[s], crs="EPSG:4326")
            source = "inline_geojson"

        elif bbox_raw:
            bb = parse_bbox(bbox_raw)
            s = box(bb.west, bb.south, bb.east, bb.north)
            gdf = gpd.GeoDataFrame(geometry=[s], crs="EPSG:4326")
            source = "bbox"

        elif place_name:
            try:
                import osmnx as ox
                gdf = ox.geocode_to_gdf(place_name)
                source = f"geocode:{place_name}"
            except Exception as exc:
                return self._fail(f"Geocoding '{place_name}' failed: {exc}")

        else:
            return self._fail("No AOI provided. Supply bbox, geojson, file_path, or place_name.")

        if gdf is None or gdf.empty:
            return self._fail("Resulting GeoDataFrame is empty.")

        crs_str = str(gdf.crs) if gdf.crs else "unknown"
        bounds = gdf.total_bounds  # [minx, miny, maxx, maxy]
        bb = parse_bbox(list(bounds))
        area_km2 = estimate_area_sq_km(bb)
        geom_types = list(gdf.geometry.geom_type.unique())
        feature_count = len(gdf)

        # Save as GeoJSON artifact
        artifacts: list[ArtifactMeta] = []
        try:
            geojson_str = gdf.to_json(ensure_ascii=False)
            art = self._save_artifact(run_id, "aoi.geojson", geojson_str, "geojson", "Inspected AOI")
            artifacts.append(art)
        except Exception:
            pass

        data = {
            "source": source,
            "crs": crs_str,
            "feature_count": feature_count,
            "geometry_types": geom_types,
            "bounds": {"west": bounds[0], "south": bounds[1], "east": bounds[2], "north": bounds[3]},
            "area_estimate_sq_km": round(area_km2, 2),
            "run_id": run_id,
        }
        summary = (
            f"AOI from {source}: {feature_count} feature(s), "
            f"CRS={crs_str}, ~{area_km2:.1f} km², "
            f"geometry type(s): {', '.join(geom_types)}"
        )
        warnings: list[str] = []
        if area_km2 > 50_000:
            warnings.append(f"Large AOI ({area_km2:.0f} km²) — downstream operations may be slow.")

        return self._ok(summary, data=data, artifacts=artifacts, warnings=warnings)


# ---------------------------------------------------------------------------
# geo_validate_geometry
# ---------------------------------------------------------------------------

class ValidateGeometryTool(GeoTool):
    """Check geometry validity and report issues."""

    @property
    def name(self) -> str:
        return "geo_validate_geometry"

    @property
    def description(self) -> str:
        return (
            "Validate geometries in a GeoJSON or file. Reports invalid geometries "
            "and optionally auto-fixes them with buffer(0)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "geojson": {
                    "type": "object",
                    "description": "Inline GeoJSON to validate",
                },
                "file_path": {
                    "type": "string",
                    "description": "Path to a vector file to validate",
                },
                "auto_fix": {
                    "type": "boolean",
                    "description": "Attempt to fix invalid geometries with buffer(0)",
                },
            },
        }

    async def execute(self, **kwargs: Any) -> str:
        t0 = time.monotonic()
        try:
            result = self._validate(kwargs)
            prov = self._make_provenance(kwargs, time.monotonic() - t0)
            result.provenance = prov
            return result.to_llm_string()
        except Exception as exc:
            return self._fail(str(exc)).to_llm_string()

    def _validate(self, params: dict) -> ToolResult:
        import geopandas as gpd
        from shapely.geometry import shape

        geojson_raw = params.get("geojson")
        file_path = params.get("file_path")
        auto_fix = params.get("auto_fix", False)

        if file_path:
            gdf = gpd.read_file(str(Path(file_path).expanduser()))
        elif geojson_raw:
            geom_type = geojson_raw.get("type", "")
            if geom_type == "FeatureCollection":
                gdf = gpd.GeoDataFrame.from_features(geojson_raw["features"], crs="EPSG:4326")
            elif geom_type == "Feature":
                gdf = gpd.GeoDataFrame.from_features([geojson_raw], crs="EPSG:4326")
            else:
                s = shape(geojson_raw)
                gdf = gpd.GeoDataFrame(geometry=[s], crs="EPSG:4326")
        else:
            return self._fail("Provide geojson or file_path to validate.")

        total = len(gdf)
        invalid_mask = ~gdf.geometry.is_valid
        invalid_count = int(invalid_mask.sum())
        reasons: list[str] = []

        from shapely.validation import explain_validity
        for idx in gdf.index[invalid_mask]:
            r = explain_validity(gdf.geometry[idx])
            reasons.append(f"Feature {idx}: {r}")

        fixed = False
        if auto_fix and invalid_count > 0:
            gdf.geometry = gdf.geometry.buffer(0)
            remaining = int((~gdf.geometry.is_valid).sum())
            fixed = True
        else:
            remaining = invalid_count

        data = {
            "total_features": total,
            "invalid_count": invalid_count,
            "invalid_reasons": reasons[:20],
            "auto_fixed": fixed,
            "remaining_invalid": remaining,
        }
        if invalid_count == 0:
            summary = f"All {total} geometries are valid."
        elif fixed and remaining == 0:
            summary = f"{invalid_count}/{total} invalid geometries fixed with buffer(0)."
        else:
            summary = f"{invalid_count}/{total} geometries are invalid."

        return self._ok(summary, data=data)


# ---------------------------------------------------------------------------
# geo_suggest_crs
# ---------------------------------------------------------------------------

class SuggestCRSTool(GeoTool):
    """Suggest a projected CRS for a given extent."""

    @property
    def name(self) -> str:
        return "geo_suggest_crs"

    @property
    def description(self) -> str:
        return (
            "Suggest a suitable projected CRS (e.g. UTM zone) for an extent. "
            "Takes a bounding box in EPSG:4326 and returns a recommended EPSG code."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "west": {"type": "number", "description": "Western longitude"},
                "south": {"type": "number", "description": "Southern latitude"},
                "east": {"type": "number", "description": "Eastern longitude"},
                "north": {"type": "number", "description": "Northern latitude"},
            },
            "required": ["west", "south", "east", "north"],
        }

    async def execute(self, **kwargs: Any) -> str:
        t0 = time.monotonic()
        try:
            w, s, e, n = kwargs["west"], kwargs["south"], kwargs["east"], kwargs["north"]
            suggested = suggest_projected_crs(w, s, e, n)
            info = describe_crs(suggested)
            data = {
                "suggested_crs": suggested,
                "crs_info": info,
                "input_bounds": {"west": w, "south": s, "east": e, "north": n},
            }
            summary = f"Recommended projected CRS: {suggested} ({info.get('name', '')})"
            prov = self._make_provenance(kwargs, time.monotonic() - t0, crs_used=suggested)
            return self._ok(summary, data=data, provenance=prov).to_llm_string()
        except Exception as exc:
            return self._fail(str(exc)).to_llm_string()


# ---------------------------------------------------------------------------
# geo_render_workflow
# ---------------------------------------------------------------------------

class RenderWorkflowTool(GeoTool):
    """Render workflow results to summary.md + result.json in a run directory."""

    @property
    def name(self) -> str:
        return "geo_render_workflow"

    @property
    def description(self) -> str:
        return (
            "Render a completed workflow's results to summary.md and result.json. "
            "Provide the run_id and a list of result JSON strings."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "run_id": {
                    "type": "string",
                    "description": "The run ID to render results for",
                },
                "title": {
                    "type": "string",
                    "description": "Workflow title for the summary",
                },
                "results_json": {
                    "type": "string",
                    "description": "JSON array of ToolResult dicts to render",
                },
            },
            "required": ["run_id", "title"],
        }

    async def execute(self, **kwargs: Any) -> str:
        try:
            run_id = kwargs["run_id"]
            title = kwargs.get("title", "GeoClaw Workflow")
            results_raw = kwargs.get("results_json", "[]")
            results = json.loads(results_raw) if isinstance(results_raw, str) else results_raw

            from geoclaw.renderers.workflow import WorkflowRenderer
            renderer = WorkflowRenderer()
            output_dir = self._runs_dir() / run_id
            renderer.render_from_dicts(results, run_id, title, output_dir)

            return self._ok(
                f"Workflow rendered to {output_dir}",
                data={"run_dir": str(output_dir)},
            ).to_llm_string()
        except Exception as exc:
            return self._fail(str(exc)).to_llm_string()
