# nanobot Runtime Skills

This directory contains built-in runtime skills inherited from nanobot.

In this repository, GeoClaw is the primary product layer. Its packaged geospatial workflow skills live under `geoclaw/skills/`, are synced by `geoclaw sync-skills`, and are intentionally kept separate from these generic runtime skills.

## Skill Format

Each skill is a directory containing a `SKILL.md` file with:
- YAML frontmatter (name, description, metadata)
- Markdown instructions for the agent

## Attribution

These skills are adapted from [OpenClaw](https://github.com/openclaw/openclaw)'s skill system.
The skill format and metadata structure follow OpenClaw's conventions to maintain compatibility.

## Available Skills

| Skill | Description |
|-------|-------------|
| `github` | Interact with GitHub using the `gh` CLI |
| `weather` | Get weather info using wttr.in and Open-Meteo |
| `summarize` | Summarize URLs, files, and YouTube videos |
| `tmux` | Remote-control tmux sessions |
| `clawhub` | Search and install skills from ClawHub registry |
| `skill-creator` | Create new skills |

## GeoClaw Packaged Skills

GeoClaw currently ships these domain workflows:

| Skill | Purpose |
|-------|---------|
| `aoi_sanity_check` | Validate AOI geometry, extent, area, and suggested CRS |
| `osm_place_profile` | Extract and summarize OSM features for an area |
| `accessibility_analysis` | Build networks, routes, isochrones, and service coverage |
| `raster_exposure_summary` | Clip raster data, compute statistics, and render previews |
| `stac_search_preview` | Search STAC catalogs, rank scenes, and preview assets |
| `hex_service_coverage` | Aggregate points or polygons into H3-based summaries |