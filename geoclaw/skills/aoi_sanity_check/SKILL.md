---
name: aoi_sanity_check
description: Validate and inspect an Area of Interest before downstream geospatial analysis
metadata: {"nanobot":{"always":false,"emoji":"🗺️"}}
---

# AOI Sanity Check

Use this skill when the user supplies a geographic area and wants to understand:
- whether the geometry is valid
- what CRS it uses
- how large the area is
- what downstream workflows make sense

## Current Implementation
- Backed by real tools: `geo_inspect_aoi`, `geo_validate_geometry`, `geo_suggest_crs`, `geo_render_workflow`
- Produces reproducible outputs under `runs/<run_id>/`
- Use this as the default entrypoint before OSM, raster, STAC, network, or H3 workflows

## Accepted Inputs
- bounding box
- place name
- inline GeoJSON geometry / Feature / FeatureCollection
- local file path to GeoJSON / Shapefile / GeoPackage

## Preferred Tool Sequence
1. Call `geo_inspect_aoi` with the most concrete AOI representation available.
2. If a geometry or file is involved, call `geo_validate_geometry`.
3. Call `geo_suggest_crs` with the AOI bounds.
4. Call `geo_render_workflow` to create `summary.md` and `result.json` under the same `run_id`.

## Fallback Logic
- If `place_name` geocoding fails, ask for a bbox or local file path.
- If the file cannot be read, report the exact path / format error and ask for GeoJSON, GPKG, or SHP.
- If the geometry is invalid, explain why and offer `auto_fix=true` with `geo_validate_geometry`.
- If the AOI is extremely large, warn that OSM, routing, and raster analysis may be slow.

## Expected Outputs
- CRS description
- geometry validity
- extent / bounding box
- feature count
- area estimate
- recommended projected CRS
- downstream suggestions such as:
  - `osm_place_profile` for place intelligence
  - `raster_exposure_summary` for raster or EO summaries
  - `stac_search_preview` for imagery discovery
  - `hex_service_coverage` for aggregation

## Explanation Template
Explain the result in this order:
1. What input was interpreted as the AOI
2. Whether the geometry is valid
3. Which CRS was detected and which projected CRS is recommended
4. Approximate area and why it matters for later workflows
5. The most suitable next workflow(s)
