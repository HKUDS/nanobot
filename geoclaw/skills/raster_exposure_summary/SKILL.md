---
name: raster_exposure_summary
description: Clip a raster to an AOI and produce zonal statistics
metadata: {"nanobot":{"always":false,"emoji":"🛰️"}}
---

# Raster Exposure Summary

Use this skill when the user wants to quantify raster values inside an AOI, inspect a clipped raster, or generate a quick EO preview.

## Current Implementation
- Backed by real tools: `geo_read_raster`, `geo_clip_raster`, `geo_raster_summary`, `geo_export_raster_preview`, `geo_render_workflow`
- Supports local rasters and raster assets handed off from a prior STAC workflow
- Writes clipped rasters, preview PNGs, and structured summaries under `runs/<run_id>/`

## When To Trigger
- The user provides a raster file and asks for summary statistics.
- The user wants exposure, intensity, elevation, hazard, land-cover, or EO pixel summaries for an AOI.
- The user wants a clipped raster and preview image saved for later use.

## Accepted Inputs
- AOI as bbox, place name, inline GeoJSON, or vector file
- local raster path
- optionally a raster selected from a previous STAC workflow
- optional band number

## Preferred Tool Sequence
1. Call `geo_inspect_aoi` to normalize the AOI and obtain bounds.
2. If geometry-based AOI is used, call `geo_validate_geometry`.
3. Call `geo_read_raster` to inspect raster CRS, dimensions, and metadata.
4. Call `geo_clip_raster` with the AOI and the source raster.
5. Call `geo_raster_summary` on the clipped raster.
6. Call `geo_export_raster_preview` to produce a PNG preview.
7. Call `geo_render_workflow` to save `summary.md` and `result.json`.

## Tool Sequence Preference
- Prefer clipping before summarizing so the reported statistics are AOI-specific.
- Prefer the first band unless the user explicitly specifies another band.
- If the raster is large, warn that clipping may take longer and keep the analysis focused on the AOI.

## Fallback Logic
- If AOI and raster CRS differ, explain that reprojection may be needed before precise zonal work.
- If clipping fails, fall back to reporting source raster metadata and ask the user to verify the AOI overlap.
- If preview generation fails, continue with clipped raster and statistics.
- If the raster band has no valid pixels, explain that the AOI may fall outside data coverage or into nodata.

## Expected Outputs
- Source raster metadata.
- Clipped raster saved to `artifacts/`.
- Basic statistics such as min, max, mean, std, and valid pixel count.
- PNG preview image.
- Method notes about clipping and band selection.

## Explanation Template
Explain the result in this order:
1. Which raster and AOI were used.
2. What clip was produced.
3. What the core pixel statistics mean.
4. Any nodata or CRS caveats.
5. Whether the output is suitable for downstream reporting or further STAC/raster workflows.
