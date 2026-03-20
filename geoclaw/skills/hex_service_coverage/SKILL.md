---
name: hex_service_coverage
description: Aggregate spatial data into H3 hexagons for coverage analysis
metadata: {"nanobot":{"always":false,"emoji":"⬡"}}
---

# Hex Service Coverage

Use this skill when the user wants spatial aggregation, hotspot identification, service intensity mapping, or scale-sensitive hex summaries.

## Current Implementation
- Backed by real tools: `geo_point_to_h3`, `geo_polygon_to_h3`, `geo_aggregate_by_h3`, `geo_neighborhood_summary`, `geo_render_workflow`
- Supports both point-to-cell assignment and polygon polyfill workflows
- Produces aggregation layers and summary outputs under `runs/<run_id>/`

## When To Trigger
- The user asks where coverage is strong or weak.
- The user wants point or polygon data aggregated into H3 cells.
- The user wants a scale-sensitive summary instead of raw feature maps.

## Accepted Inputs
- point dataset as GeoJSON or file path
- polygon dataset when polyfill is appropriate
- H3 resolution
- optional metric property and aggregation method

## Preferred Tool Sequence
1. If the request includes an AOI, call `geo_inspect_aoi` first.
2. For point data, call `geo_point_to_h3`.
3. For polygon data, call `geo_polygon_to_h3`.
4. Call `geo_aggregate_by_h3` with the requested resolution and metric.
5. Optionally call `geo_neighborhood_summary` for a hotspot cell if the user asks about local context.
6. Call `geo_render_workflow` to save the workflow outputs.

## Tool Sequence Preference
- Prefer `count` aggregation when the user does not specify a metric.
- Use `sum` or `mean` only when a numeric property is explicitly available.
- Explain the trade-off between coarse and fine H3 resolution.

## Fallback Logic
- If the input contains no supported geometry type, ask the user for point or polygon features.
- If polygon-to-H3 produces too many cells, recommend a coarser resolution.
- If no metric field is available, fall back to feature counts.
- If the user wants service accessibility rather than density, suggest `accessibility_analysis` instead.

## Expected Outputs
- H3 aggregation output layer.
- Coverage distribution statistics.
- Hot/cold or dense/sparse cell interpretation.
- A short note on how the chosen resolution affects interpretation.

## Explanation Template
Explain the result in this order:
1. What dataset and H3 resolution were used.
2. How many cells were produced.
3. What the distribution looks like.
4. Which cells appear dense or sparse.
5. Whether a finer or coarser resolution would be better for the next iteration.
