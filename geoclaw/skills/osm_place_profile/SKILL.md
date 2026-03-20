---
name: osm_place_profile
description: Extract and summarise OpenStreetMap features for an AOI
metadata: {"nanobot":{"always":false,"emoji":"🏙️"}}
---

# OSM Place Profile

Use this skill when the user wants place intelligence from OpenStreetMap for a neighborhood, campus, district, city block, or explicit AOI.

## Current Implementation
- Backed by real tools: `geo_inspect_aoi`, `geo_validate_geometry`, `geo_extract_osm`, `geo_build_place_profile`, `geo_render_workflow`
- Saves extracted features and workflow outputs inside `runs/<run_id>/artifacts`
- Best suited for local-scale AOIs where OSM completeness is expected to be reasonable

## When To Trigger
- The user asks what is in an area.
- The user asks for amenities, shops, leisure, tourism, buildings, or other OSM-tagged context.
- The user wants a saved OSM extract plus a concise narrative profile.

## Accepted Inputs
- bbox
- place name
- inline GeoJSON
- local vector file path
- optional `tags_filter` to constrain extraction

## Preferred Tool Sequence
1. Call `geo_inspect_aoi` to normalize the AOI and get the `run_id`.
2. If the AOI came from geometry or file input, call `geo_validate_geometry`.
3. Call `geo_extract_osm` with the AOI and either the supplied `tags_filter` or the default thematic tags.
4. Call `geo_build_place_profile` on the saved OSM output or returned GeoJSON.
5. Call `geo_render_workflow` with the shared `run_id` to write `summary.md` and `result.json`.

## Tool Sequence Preference
- Prefer broad discovery tags first: `amenity`, `shop`, `leisure`, `tourism`, `building`.
- Use a user-provided `tags_filter` only when the request is clearly thematic.
- If the AOI is large, warn before extraction and recommend narrowing the area.

## Fallback Logic
- If AOI resolution fails, ask for a bbox or local file.
- If OSM extraction returns zero features, explain that either the area is sparsely mapped or the tag filter is too restrictive.
- If extraction fails for a large AOI, ask the user to reduce the search area or narrow tags.
- If GeoParquet export fails, still continue with GeoJSON output and explain the degraded export.

## Expected Outputs
- Extracted OSM features saved as GeoJSON and, if possible, GeoParquet.
- Category counts by major OSM tag family.
- Place profile narrative summarizing the dominant land uses or amenities.
- Reproducible workflow artifacts under `runs/<run_id>/artifacts`.

## Explanation Template
Explain the result in this order:
1. What AOI was used.
2. How many OSM features were extracted.
3. Which categories dominated the extract.
4. What the area seems to be based on mapped features.
5. Which downstream workflow is most useful next, such as routing, raster summary, or H3 aggregation.
