"""Raster tools for clipping, summary, and preview export."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from geoclaw.tools.base import GeoTool
from geoclaw.tools.common import parse_bbox


def _geometry_mapping_from_input(*, bbox=None, geojson=None):
    from shapely.geometry import box, mapping, shape

    if geojson is not None:
        return mapping(shape(geojson))
    if bbox is not None:
        bb = parse_bbox(bbox)
        return mapping(box(bb.west, bb.south, bb.east, bb.north))
    raise ValueError("Provide bbox or geojson.")


class ReadRasterTool(GeoTool):
    @property
    def name(self) -> str:
        return "geo_read_raster"

    @property
    def description(self) -> str:
        return "Read raster metadata including CRS, bounds, shape, band count, dtype, and nodata."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "raster_path": {"type": "string"},
            },
            "required": ["raster_path"],
        }

    async def execute(self, **kwargs: Any) -> str:
        import rasterio

        t0 = time.monotonic()
        try:
            raster_path = Path(kwargs["raster_path"]).expanduser()
            with rasterio.open(raster_path) as src:
                result = self._ok(
                    summary=f"Raster {raster_path.name}: {src.count} band(s), {src.width}x{src.height}.",
                    data={
                        "raster_path": str(raster_path),
                        "crs": str(src.crs) if src.crs else None,
                        "bounds": list(src.bounds),
                        "width": src.width,
                        "height": src.height,
                        "band_count": src.count,
                        "dtypes": list(src.dtypes),
                        "nodata": src.nodata,
                        "transform": list(src.transform)[:6],
                    },
                    provenance=self._make_provenance(
                        {"raster_path": str(raster_path)},
                        time.monotonic() - t0,
                        crs_used=str(src.crs) if src.crs else None,
                    ),
                )
                return result.to_llm_string()
        except Exception as exc:
            return self._fail(str(exc)).to_llm_string()


class ClipRasterTool(GeoTool):
    @property
    def name(self) -> str:
        return "geo_clip_raster"

    @property
    def description(self) -> str:
        return "Clip a raster by bbox or GeoJSON AOI and save the clipped raster to artifacts."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "raster_path": {"type": "string"},
                "bbox": {"type": "object"},
                "geojson": {"type": "object"},
                "run_id": {"type": "string"},
            },
            "required": ["raster_path"],
        }

    async def execute(self, **kwargs: Any) -> str:
        import rasterio
        from rasterio.mask import mask

        t0 = time.monotonic()
        run_id = kwargs.get("run_id") or self._new_run_id()
        try:
            raster_path = Path(kwargs["raster_path"]).expanduser()
            geom = _geometry_mapping_from_input(bbox=kwargs.get("bbox"), geojson=kwargs.get("geojson"))
            with rasterio.open(raster_path) as src:
                out_image, out_transform = mask(src, [geom], crop=True)
                out_meta = src.meta.copy()
                out_meta.update(
                    {
                        "height": out_image.shape[1],
                        "width": out_image.shape[2],
                        "transform": out_transform,
                    }
                )
                out_path = self._artifact_dir(run_id) / "clipped.tif"
                with rasterio.open(out_path, "w", **out_meta) as dst:
                    dst.write(out_image)

            artifact = self._save_artifact(
                run_id,
                "clip_manifest.json",
                json.dumps({"clipped_raster": str(out_path)}, ensure_ascii=False),
                "json",
                "Clip manifest",
            )
            result = self._ok(
                summary=f"Clipped raster saved to {out_path}.",
                data={"run_id": run_id, "clipped_raster_path": str(out_path)},
                artifacts=[
                    artifact,
                    type(artifact)(
                        path=str(out_path),
                        format="tif",
                        size_bytes=out_path.stat().st_size,
                        description="Clipped raster",
                    ),
                ],
                provenance=self._make_provenance(
                    {
                        "raster_path": str(raster_path),
                        "has_bbox": kwargs.get("bbox") is not None,
                        "has_geojson": kwargs.get("geojson") is not None,
                    },
                    time.monotonic() - t0,
                ),
            )
            return result.to_llm_string()
        except Exception as exc:
            return self._fail(str(exc)).to_llm_string()


class RasterSummaryTool(GeoTool):
    @property
    def name(self) -> str:
        return "geo_raster_summary"

    @property
    def description(self) -> str:
        return "Compute basic raster statistics such as min, max, mean, std, and valid pixel count."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "raster_path": {"type": "string"},
                "band": {"type": "integer"},
            },
            "required": ["raster_path"],
        }

    async def execute(self, **kwargs: Any) -> str:
        import rasterio

        t0 = time.monotonic()
        try:
            raster_path = Path(kwargs["raster_path"]).expanduser()
            band = kwargs.get("band", 1)
            with rasterio.open(raster_path) as src:
                arr = src.read(band, masked=True)
                valid = arr.compressed()
                stats = {
                    "band": band,
                    "min": float(valid.min()) if valid.size else None,
                    "max": float(valid.max()) if valid.size else None,
                    "mean": float(valid.mean()) if valid.size else None,
                    "std": float(valid.std()) if valid.size else None,
                    "valid_pixel_count": int(valid.size),
                    "nodata": src.nodata,
                }
                result = self._ok(
                    summary=f"Raster summary for {raster_path.name}, band {band}.",
                    data=stats,
                    provenance=self._make_provenance(
                        {"raster_path": str(raster_path), "band": band},
                        time.monotonic() - t0,
                        crs_used=str(src.crs) if src.crs else None,
                    ),
                )
                return result.to_llm_string()
        except Exception as exc:
            return self._fail(str(exc)).to_llm_string()


class ExportRasterPreviewTool(GeoTool):
    @property
    def name(self) -> str:
        return "geo_export_raster_preview"

    @property
    def description(self) -> str:
        return "Export a PNG preview for a raster band, optionally with percentile stretch."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "raster_path": {"type": "string"},
                "band": {"type": "integer"},
                "run_id": {"type": "string"},
            },
            "required": ["raster_path"],
        }

    async def execute(self, **kwargs: Any) -> str:
        import matplotlib.pyplot as plt
        import rasterio

        t0 = time.monotonic()
        run_id = kwargs.get("run_id") or self._new_run_id()
        try:
            raster_path = Path(kwargs["raster_path"]).expanduser()
            band = kwargs.get("band", 1)
            with rasterio.open(raster_path) as src:
                arr = src.read(band, masked=True).astype("float32")
                valid = arr.compressed()
                if valid.size == 0:
                    return self._fail("Raster band has no valid pixels.").to_llm_string()
                lo, hi = np.percentile(valid, [2, 98])
                stretched = np.clip((arr.filled(lo) - lo) / max(hi - lo, 1e-9), 0, 1)
                preview_path = self._artifact_dir(run_id) / "preview.png"
                plt.imsave(preview_path, stretched, cmap="viridis")

            result = self._ok(
                summary=f"Raster preview saved to {preview_path}.",
                data={"preview_path": str(preview_path), "run_id": run_id, "band": band},
                artifacts=[
                    self._save_artifact(
                        run_id,
                        "preview_manifest.json",
                        json.dumps({"preview_path": str(preview_path)}, ensure_ascii=False),
                        "json",
                        "Preview manifest",
                    ),
                    type(self._save_artifact(run_id, "preview.meta", "generated", "txt", "Preview metadata"))(
                        path=str(preview_path),
                        format="png",
                        size_bytes=preview_path.stat().st_size,
                        description="Raster preview",
                    ),
                ],
                provenance=self._make_provenance(
                    {"raster_path": str(raster_path), "band": band},
                    time.monotonic() - t0,
                ),
            )
            return result.to_llm_string()
        except Exception as exc:
            return self._fail(str(exc)).to_llm_string()
