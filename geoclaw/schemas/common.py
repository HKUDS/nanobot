"""Common schemas shared across all GeoClaw tools."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ArtifactMeta(BaseModel):
    """Metadata for a single output artifact."""

    path: str
    format: str = Field(description="File format: geojson, geoparquet, tif, png, csv, etc.")
    size_bytes: int = 0
    description: str = ""


class ProvenanceMeta(BaseModel):
    """Reproducibility metadata for a tool invocation."""

    tool_name: str
    tool_version: str = "0.1.0"
    timestamp: datetime = Field(default_factory=datetime.now)
    input_hash: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    duration_seconds: float = 0.0
    crs_used: str | None = None


class ToolResult(BaseModel):
    """Standard result envelope returned by every GeoClaw tool."""

    success: bool
    tool_name: str
    summary: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[ArtifactMeta] = Field(default_factory=list)
    provenance: ProvenanceMeta | None = None
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def to_llm_string(self) -> str:
        """Serialize to a concise string suitable for LLM consumption."""
        parts = [f"[{self.tool_name}] {'OK' if self.success else 'FAILED'}"]
        if self.summary:
            parts.append(self.summary)
        if self.errors:
            parts.append("Errors: " + "; ".join(self.errors))
        if self.warnings:
            parts.append("Warnings: " + "; ".join(self.warnings))
        if self.artifacts:
            arts = ", ".join(f"{a.path} ({a.format})" for a in self.artifacts)
            parts.append(f"Artifacts: {arts}")
        if self.data:
            import json
            parts.append("Data: " + json.dumps(self.data, ensure_ascii=False, default=str))
        return "\n".join(parts)


class BBox(BaseModel):
    """Bounding box in (west, south, east, north) order."""

    west: float
    south: float
    east: float
    north: float
    crs: str = "EPSG:4326"

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.west, self.south, self.east, self.north)

    def area_degrees(self) -> float:
        return abs(self.east - self.west) * abs(self.north - self.south)


class AOIInput(BaseModel):
    """Flexible AOI specification — exactly one field should be set."""

    bbox: BBox | None = None
    geojson: dict | None = None
    file_path: str | None = None
    place_name: str | None = None
