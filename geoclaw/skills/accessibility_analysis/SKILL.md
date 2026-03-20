---
name: accessibility_analysis
description: Compute routes, isochrones, and service-area coverage
metadata: {"nanobot":{"always":false,"emoji":"🚗"}}
---

# Accessibility Analysis

Use this skill when the user wants route distance, travel-time reach, service areas, or reachable destination counts from one or more origins.

## Current Implementation
- Backed by real tools: `geo_build_network`, `geo_compute_route`, `geo_compute_isochrone`, `geo_compute_service_coverage`, `geo_render_workflow`
- Uses OSM-derived network construction through the GeoClaw tool layer rather than arbitrary shell commands
- Produces route, isochrone, or coverage artifacts under `runs/<run_id>/`

## When To Trigger
- The user asks for a route between places.
- The user asks how far someone can go within a time threshold.
- The user asks how many POIs, services, or destinations are reachable.
- The user asks which places remain uncovered.

## Accepted Inputs
- AOI as bbox, place name, inline GeoJSON, or local file path
- origin and destination point objects with `lon` / `lat`
- one or more origins for service coverage
- destination points as GeoJSON for coverage analysis
- mode: `walk`, `bike`, `drive`, or `all`
- time threshold in minutes or distance threshold in meters

## Preferred Tool Sequence
1. Call `geo_inspect_aoi` if the AOI is not already normalized.
2. Call `geo_build_network` with the AOI and requested mode.
3. If the user wants a single route, call `geo_compute_route`.
4. If the user wants a reachable area, call `geo_compute_isochrone`.
5. If the user wants counts of reachable destinations, call `geo_compute_service_coverage`.
6. Call `geo_render_workflow` to save outputs and provenance.

## Tool Sequence Preference
- Prefer `walk` for pedestrian accessibility, `drive` for travel-time routing, and `bike` only when explicitly requested.
- Prefer time thresholds when the user frames accessibility in minutes.
- Prefer service coverage over route-only output when the user asks about reachable opportunities, not just path geometry.

## Fallback Logic
- If the network build fails for a very large AOI, ask the user to reduce the AOI.
- If routing fails because origin and destination are disconnected, explain that no network path exists.
- If destination coverage fails because inputs are not points, ask for point destinations.
- If both time and distance thresholds are missing, ask the user which one they want to use.

## Expected Outputs
- Route geometry and travel distance / time.
- Isochrone or service-area geometry.
- Reachable destination counts and uncovered totals.
- Saved outputs suitable for later spatial aggregation or reporting.

## Explanation Template
Explain the result in this order:
1. Which AOI and travel mode were used.
2. What network analysis was run.
3. The key accessibility metric: route time, reachable area, or reachable destination count.
4. Any important caveats such as disconnected streets or coarse AOI boundaries.
5. Suggested next step, such as OSM place profiling for destinations or H3 aggregation of uncovered points.
