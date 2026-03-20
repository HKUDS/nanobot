"""GeoClaw-specific configuration extensions."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class GeoClawConfig(BaseModel):
    """Configuration knobs specific to geoclaw tools."""

    workspace: str = "~/.nanobot/workspace"
    max_aoi_area_sq_km: float = 50_000.0
    max_raster_pixels: int = 100_000_000
    default_h3_resolution: int = 8
    osm_timeout_seconds: int = 120
    stac_timeout_seconds: int = 60

    @property
    def workspace_path(self) -> Path:
        return Path(self.workspace).expanduser()
