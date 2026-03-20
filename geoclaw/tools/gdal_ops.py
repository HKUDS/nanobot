"""GDAL-style dataset operations with safe Python-first implementations."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from geoclaw.tools.base import GeoTool


def _is_raster(path: Path) -> bool:
    return path.suffix.lower() in {".tif", ".tiff", ".img", ".vrt"}


class InspectDatasetTool(GeoTool):
    @property
    def name(self) -> str:
        return "geo_gdal_inspect_dataset"

    @property
    def description(self) -> str:
        return "Inspect raster or vector dataset metadata in a GDAL-style envelope."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }

    async def execute(self, **kwargs: Any) -> str:
        import geopandas as gpd
        import rasterio

        t0 = time.monotonic()
        try:
            path = Path(kwargs["path"]).expanduser()
            if _is_raster(path):
                with rasterio.open(path) as src:
                    data = {
                        "dataset_type": "raster",
                        "crs": str(src.crs) if src.crs else None,
                        "bounds": list(src.bounds),
                        "width": src.width,
                        "height": src.height,
                        "band_count": src.count,
                        "dtypes": list(src.dtypes),
                        "driver": src.driver,
                    }
            else:
                gdf = gpd.read_file(path)
                data = {
                    "dataset_type": "vector",
                    "crs": str(gdf.crs) if gdf.crs else None,
                    "bounds": gdf.total_bounds.tolist() if not gdf.empty else [None] * 4,
                    "feature_count": len(gdf),
                    "columns": list(gdf.columns),
                    "geometry_types": list(gdf.geometry.geom_type.unique()) if not gdf.empty else [],
                }
            result = self._ok(
                summary=f"Inspected dataset {path.name}.",
                data=data,
                provenance=self._make_provenance({"path": str(path)}, time.monotonic() - t0),
            )
            return result.to_llm_string()
        except Exception as exc:
            return self._fail(str(exc)).to_llm_string()


class ReprojectDatasetTool(GeoTool):
    @property
    def name(self) -> str:
        return "geo_gdal_reproject_dataset"

    @property
    def description(self) -> str:
        return "Reproject raster or vector dataset to a target CRS and save the result."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "target_crs": {"type": "string"},
                "run_id": {"type": "string"},
            },
            "required": ["path", "target_crs"],
        }

    async def execute(self, **kwargs: Any) -> str:
        import geopandas as gpd
        import rasterio
        from rasterio.warp import Resampling, calculate_default_transform, reproject

        t0 = time.monotonic()
        run_id = kwargs.get("run_id") or self._new_run_id()
        try:
            path = Path(kwargs["path"]).expanduser()
            target_crs = kwargs["target_crs"]
            if _is_raster(path):
                with rasterio.open(path) as src:
                    transform, width, height = calculate_default_transform(
                        src.crs, target_crs, src.width, src.height, *src.bounds
                    )
                    meta = src.meta.copy()
                    meta.update({"crs": target_crs, "transform": transform, "width": width, "height": height})
                    out_path = self._artifact_dir(run_id) / f"{path.stem}_reprojected.tif"
                    with rasterio.open(out_path, "w", **meta) as dst:
                        for i in range(1, src.count + 1):
                            reproject(
                                source=rasterio.band(src, i),
                                destination=rasterio.band(dst, i),
                                src_transform=src.transform,
                                src_crs=src.crs,
                                dst_transform=transform,
                                dst_crs=target_crs,
                                resampling=Resampling.nearest,
                            )
            else:
                gdf = gpd.read_file(path).to_crs(target_crs)
                out_path = self._artifact_dir(run_id) / f"{path.stem}_reprojected.geojson"
                gdf.to_file(out_path, driver="GeoJSON")

            result = self._ok(
                summary=f"Reprojected {path.name} to {target_crs}.",
                data={"output_path": str(out_path), "target_crs": target_crs, "run_id": run_id},
                artifacts=[
                    self._save_artifact(
                        run_id,
                        "reproject_manifest.json",
                        json.dumps({"output_path": str(out_path)}, ensure_ascii=False),
                        "json",
                        "Reproject manifest",
                    )
                ],
                provenance=self._make_provenance(
                    {"path": str(path), "target_crs": target_crs},
                    time.monotonic() - t0,
                    crs_used=target_crs,
                ),
            )
            return result.to_llm_string()
        except Exception as exc:
            return self._fail(str(exc)).to_llm_string()


class ClipDatasetTool(GeoTool):
    @property
    def name(self) -> str:
        return "geo_gdal_clip_dataset"

    @property
    def description(self) -> str:
        return "Clip raster or vector dataset by bbox or GeoJSON and save the result."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "bbox": {"type": "object"},
                "geojson": {"type": "object"},
                "run_id": {"type": "string"},
            },
            "required": ["path"],
        }

    async def execute(self, **kwargs: Any) -> str:
        import geopandas as gpd
        from shapely.geometry import box, shape

        t0 = time.monotonic()
        run_id = kwargs.get("run_id") or self._new_run_id()
        try:
            path = Path(kwargs["path"]).expanduser()
            if kwargs.get("geojson") is not None:
                clip_geom = shape(kwargs["geojson"])
            elif kwargs.get("bbox") is not None:
                from geoclaw.tools.common import parse_bbox

                bb = parse_bbox(kwargs["bbox"])
                clip_geom = box(bb.west, bb.south, bb.east, bb.north)
            else:
                return self._fail("Provide bbox or geojson.").to_llm_string()

            if _is_raster(path):
                from geoclaw.tools.raster import ClipRasterTool

                return await ClipRasterTool(self._workspace).execute(
                    raster_path=str(path),
                    bbox=kwargs.get("bbox"),
                    geojson=kwargs.get("geojson"),
                    run_id=run_id,
                )
            else:
                gdf = gpd.read_file(path)
                clipped = gdf.clip(clip_geom)
                out_path = self._artifact_dir(run_id) / f"{path.stem}_clipped.geojson"
                clipped.to_file(out_path, driver="GeoJSON")
                result = self._ok(
                    summary=f"Clipped vector dataset to {len(clipped)} feature(s).",
                    data={"output_path": str(out_path), "feature_count": len(clipped), "run_id": run_id},
                    artifacts=[
                        self._save_artifact(
                            run_id,
                            "clip_dataset_manifest.json",
                            json.dumps({"output_path": str(out_path)}, ensure_ascii=False),
                            "json",
                            "Dataset clip manifest",
                        )
                    ],
                    provenance=self._make_provenance(
                        {"path": str(path), "has_bbox": kwargs.get("bbox") is not None},
                        time.monotonic() - t0,
                    ),
                )
                return result.to_llm_string()
        except Exception as exc:
            return self._fail(str(exc)).to_llm_string()


class ConvertFormatTool(GeoTool):
    @property
    def name(self) -> str:
        return "geo_gdal_convert_format"

    @property
    def description(self) -> str:
        return "Convert raster or vector dataset to another common format."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "target_format": {"type": "string"},
                "run_id": {"type": "string"},
            },
            "required": ["path", "target_format"],
        }

    async def execute(self, **kwargs: Any) -> str:
        import geopandas as gpd
        import rasterio
        from rasterio.shutil import copy as rio_copy

        t0 = time.monotonic()
        run_id = kwargs.get("run_id") or self._new_run_id()
        try:
            path = Path(kwargs["path"]).expanduser()
            target_format = kwargs["target_format"].lower()
            if _is_raster(path):
                ext_map = {"gtiff": ".tif", "tiff": ".tif", "cog": ".tif"}
                out_path = self._artifact_dir(run_id) / f"{path.stem}_converted{ext_map.get(target_format, '.tif')}"
                driver = "COG" if target_format == "cog" else "GTiff"
                rio_copy(str(path), str(out_path), driver=driver)
            else:
                gdf = gpd.read_file(path)
                if target_format in {"geojson", "json"}:
                    out_path = self._artifact_dir(run_id) / f"{path.stem}_converted.geojson"
                    gdf.to_file(out_path, driver="GeoJSON")
                elif target_format in {"parquet", "geoparquet"}:
                    out_path = self._artifact_dir(run_id) / f"{path.stem}_converted.parquet"
                    gdf.to_parquet(out_path)
                else:
                    return self._fail(f"Unsupported vector target format: {target_format}").to_llm_string()

            result = self._ok(
                summary=f"Converted {path.name} to {target_format}.",
                data={"output_path": str(out_path), "target_format": target_format, "run_id": run_id},
                artifacts=[
                    self._save_artifact(
                        run_id,
                        "convert_manifest.json",
                        json.dumps({"output_path": str(out_path)}, ensure_ascii=False),
                        "json",
                        "Format conversion manifest",
                    )
                ],
                provenance=self._make_provenance(
                    {"path": str(path), "target_format": target_format},
                    time.monotonic() - t0,
                ),
            )
            return result.to_llm_string()
        except Exception as exc:
            return self._fail(str(exc)).to_llm_string()


class TranslateToCOGTool(GeoTool):
    @property
    def name(self) -> str:
        return "geo_gdal_translate_to_cog"

    @property
    def description(self) -> str:
        return "Translate a raster dataset to a Cloud Optimized GeoTIFF (COG) when supported."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "run_id": {"type": "string"},
            },
            "required": ["path"],
        }

    async def execute(self, **kwargs: Any) -> str:
        from rasterio.shutil import copy as rio_copy

        t0 = time.monotonic()
        run_id = kwargs.get("run_id") or self._new_run_id()
        try:
            path = Path(kwargs["path"]).expanduser()
            if not _is_raster(path):
                return self._fail("translate_to_cog only supports raster datasets.").to_llm_string()
            out_path = self._artifact_dir(run_id) / f"{path.stem}.cog.tif"
            rio_copy(str(path), str(out_path), driver="COG")
            result = self._ok(
                summary=f"Translated {path.name} to COG.",
                data={"output_path": str(out_path), "run_id": run_id},
                artifacts=[
                    self._save_artifact(
                        run_id,
                        "cog_manifest.json",
                        json.dumps({"output_path": str(out_path)}, ensure_ascii=False),
                        "json",
                        "COG translation manifest",
                    )
                ],
                provenance=self._make_provenance({"path": str(path)}, time.monotonic() - t0),
            )
            return result.to_llm_string()
        except Exception as exc:
            return self._fail(str(exc)).to_llm_string()
