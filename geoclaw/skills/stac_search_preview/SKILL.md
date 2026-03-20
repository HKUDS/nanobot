---
name: stac_search_preview
description: Search STAC catalogs for imagery and rank candidate scenes
metadata: {"nanobot":{"always":false,"emoji":"🔍"}}
---

# STAC Search & Preview

Use this skill when the user wants to discover imagery for an AOI, compare candidate scenes, or pick a best scene before download or raster analysis.

## Current Implementation
- Backed by real tools: `geo_search_stac`, `geo_rank_stac_assets`, `geo_preview_stac_assets`, `geo_select_best_scene`, `geo_render_workflow`
- Keeps outputs compact by ranking scenes and surfacing only the most relevant preview metadata
- Designed to hand off selected scenes into later raster workflows without losing provenance

## When To Trigger
- The user asks for satellite scenes over an AOI and time range.
- The user mentions cloud cover, scene ranking, quicklooks, previews, or best imagery selection.
- The user needs a shortlist before running raster analysis.

## Accepted Inputs
- `catalog_url`
- AOI as bbox
- time interval via `datetime`
- optional `collections`
- optional `query` filters
- optional asset preference list

## Preferred Tool Sequence
1. Call `geo_inspect_aoi` if the AOI is not already normalized.
2. Call `geo_search_stac` with catalog URL, bbox, datetime, collections, and query filters.
3. Call `geo_rank_stac_assets` with the returned items and user asset preferences.
4. Call `geo_preview_stac_assets` to surface quicklook or thumbnail references.
5. Call `geo_select_best_scene` using the ranked items.
6. Call `geo_render_workflow` to write `summary.md` and `result.json`.

## Tool Sequence Preference
- Prefer user-specified collections if provided.
- Prefer low cloud cover plus availability of `visual`, `thumbnail`, or explicitly requested assets.
- Keep the ranked list short and relevant; do not overwhelm the user with raw STAC payloads.

## Fallback Logic
- If no scenes are found, suggest widening the date range, relaxing filters, or checking a different collection.
- If cloud metadata is missing, rank by asset availability and recency instead.
- If preview assets are unavailable, continue with the ranked list and explain the missing quicklooks.
- If multiple scenes are tied, explain the tie and return the top few candidates.

## Expected Outputs
- Ranked candidate scenes.
- Preview references where available.
- A selected best scene with reasoning.
- Enough metadata to hand off to raster workflows.

## Explanation Template
Explain the result in this order:
1. Which catalog, AOI, and date range were searched.
2. How many scenes matched.
3. Why the top scene ranked highest.
4. Which preview assets are available.
5. Whether the selected scene is ready for raster clipping and summary.
