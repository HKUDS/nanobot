"""GeoTool — base class for all GeoClaw geospatial tools."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool

from geoclaw.schemas.common import ArtifactMeta, ProvenanceMeta, ToolResult


class GeoTool(Tool):
    """Abstract base for GeoClaw tools.

    Extends the nanobot Tool ABC with:
    - workspace-scoped artifact management
    - automatic provenance tracking
    - standardised ToolResult serialisation
    """

    def __init__(self, workspace: Path):
        self._workspace = workspace

    # ------------------------------------------------------------------
    # Workspace helpers
    # ------------------------------------------------------------------

    def _runs_dir(self) -> Path:
        d = self._workspace / "runs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _new_run_id(self) -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]

    def _artifact_dir(self, run_id: str) -> Path:
        d = self._runs_dir() / run_id / "artifacts"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _save_artifact(
        self,
        run_id: str,
        filename: str,
        content: str | bytes,
        fmt: str,
        description: str = "",
    ) -> ArtifactMeta:
        """Write *content* to the run's artifact directory and return metadata."""
        art_dir = self._artifact_dir(run_id)
        path = art_dir / filename
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        return ArtifactMeta(
            path=str(path),
            format=fmt,
            size_bytes=path.stat().st_size,
            description=description,
        )

    # ------------------------------------------------------------------
    # Provenance helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _hash_params(params: dict[str, Any]) -> str:
        serialised = json.dumps(params, sort_keys=True, default=str)
        return hashlib.sha256(serialised.encode()).hexdigest()

    def _make_provenance(
        self,
        params: dict[str, Any],
        duration: float,
        crs_used: str | None = None,
    ) -> ProvenanceMeta:
        return ProvenanceMeta(
            tool_name=self.name,
            tool_version="0.1.0",
            timestamp=datetime.now(),
            input_hash=self._hash_params(params),
            parameters=params,
            duration_seconds=round(duration, 3),
            crs_used=crs_used,
        )

    # ------------------------------------------------------------------
    # Result helpers
    # ------------------------------------------------------------------

    def _ok(
        self,
        summary: str,
        data: dict[str, Any] | None = None,
        artifacts: list[ArtifactMeta] | None = None,
        provenance: ProvenanceMeta | None = None,
        warnings: list[str] | None = None,
    ) -> ToolResult:
        return ToolResult(
            success=True,
            tool_name=self.name,
            summary=summary,
            data=data or {},
            artifacts=artifacts or [],
            provenance=provenance,
            warnings=warnings or [],
        )

    def _fail(self, error: str, warnings: list[str] | None = None) -> ToolResult:
        return ToolResult(
            success=False,
            tool_name=self.name,
            summary=f"Error: {error}",
            errors=[error],
            warnings=warnings or [],
        )

    # ------------------------------------------------------------------
    # Execution wrapper
    # ------------------------------------------------------------------

    async def _run_with_provenance(
        self, params: dict[str, Any], coro
    ) -> tuple[Any, float, ProvenanceMeta]:
        """Await *coro*, measure wall time, and build provenance."""
        t0 = time.monotonic()
        result = await coro
        duration = time.monotonic() - t0
        prov = self._make_provenance(params, duration)
        return result, duration, prov
