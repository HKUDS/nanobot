"""Render workflow results to summary.md, result.json, and provenance.json."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from geoclaw.schemas.common import ToolResult


class WorkflowRenderer:
    """Produces the standard output files for a completed GeoClaw workflow."""

    def render(
        self,
        results: list[ToolResult],
        run_id: str,
        title: str,
        output_dir: Path,
    ) -> Path:
        """Write summary.md, result.json, and provenance.json to *output_dir*."""
        output_dir.mkdir(parents=True, exist_ok=True)

        md = self._build_markdown(results, run_id, title)
        (output_dir / "summary.md").write_text(md, encoding="utf-8")

        payload = {
            "run_id": run_id,
            "title": title,
            "timestamp": datetime.now().isoformat(),
            "results": [r.model_dump(mode="json") for r in results],
        }
        (output_dir / "result.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

        provenance = [
            r.provenance.model_dump(mode="json")
            for r in results
            if r.provenance is not None
        ]
        if provenance:
            (output_dir / "provenance.json").write_text(
                json.dumps(provenance, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )

        return output_dir

    def render_from_dicts(
        self,
        result_dicts: list[dict[str, Any]],
        run_id: str,
        title: str,
        output_dir: Path,
    ) -> Path:
        """Convenience variant that accepts raw dicts instead of ToolResult objects."""
        output_dir.mkdir(parents=True, exist_ok=True)

        md_parts = [f"# {title}", f"**Run ID**: `{run_id}`", f"**Generated**: {datetime.now().isoformat()}", ""]
        for i, rd in enumerate(result_dicts, 1):
            tool = rd.get("tool_name", "unknown")
            success = rd.get("success", False)
            status = "OK" if success else "FAILED"
            summary = rd.get("summary", "")
            md_parts.append(f"## Step {i}: {tool} [{status}]")
            if summary:
                md_parts.append(summary)
            if rd.get("errors"):
                md_parts.append("**Errors**: " + "; ".join(rd["errors"]))
            if rd.get("warnings"):
                md_parts.append("**Warnings**: " + "; ".join(rd["warnings"]))
            if rd.get("artifacts"):
                md_parts.append("**Artifacts**:")
                for a in rd["artifacts"]:
                    path = a.get("path", "")
                    fmt = a.get("format", "")
                    md_parts.append(f"  - `{path}` ({fmt})")
            md_parts.append("")

        (output_dir / "summary.md").write_text("\n".join(md_parts), encoding="utf-8")

        payload = {
            "run_id": run_id,
            "title": title,
            "timestamp": datetime.now().isoformat(),
            "results": result_dicts,
        }
        (output_dir / "result.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

        provenance = [rd.get("provenance") for rd in result_dicts if rd.get("provenance")]
        if provenance:
            (output_dir / "provenance.json").write_text(
                json.dumps(provenance, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )

        return output_dir

    # ------------------------------------------------------------------

    def _build_markdown(
        self, results: list[ToolResult], run_id: str, title: str
    ) -> str:
        parts = [
            f"# {title}",
            f"**Run ID**: `{run_id}`",
            f"**Generated**: {datetime.now().isoformat()}",
            "",
        ]
        for i, r in enumerate(results, 1):
            status = "OK" if r.success else "FAILED"
            parts.append(f"## Step {i}: {r.tool_name} [{status}]")
            if r.summary:
                parts.append(r.summary)
            if r.errors:
                parts.append("**Errors**: " + "; ".join(r.errors))
            if r.warnings:
                parts.append("**Warnings**: " + "; ".join(r.warnings))
            if r.artifacts:
                parts.append("**Artifacts**:")
                for a in r.artifacts:
                    parts.append(f"  - `{a.path}` ({a.format})")
            if r.data:
                parts.append("**Data**:")
                parts.append("```json")
                parts.append(json.dumps(r.data, indent=2, ensure_ascii=False, default=str))
                parts.append("```")
            parts.append("")
        return "\n".join(parts)
