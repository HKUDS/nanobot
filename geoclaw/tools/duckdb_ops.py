"""DuckDB Spatial tools."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from geoclaw.tools.base import GeoTool


def _connect_spatial():
    import duckdb

    con = duckdb.connect()
    con.execute("INSTALL spatial")
    con.execute("LOAD spatial")
    return con


def _duckdb_path_literal(path: str) -> str:
    return str(Path(path).expanduser()).replace("\\", "/")


class RunSpatialSQLTool(GeoTool):
    @property
    def name(self) -> str:
        return "geo_duckdb_run_spatial_sql"

    @property
    def description(self) -> str:
        return "Run spatial SQL in DuckDB with the spatial extension loaded."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "sql": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["sql"],
        }

    async def execute(self, **kwargs: Any) -> str:
        t0 = time.monotonic()
        try:
            con = _connect_spatial()
            sql = kwargs["sql"]
            if kwargs.get("limit"):
                sql = f"SELECT * FROM ({sql}) t LIMIT {int(kwargs['limit'])}"
            rows = con.execute(sql).fetchall()
            columns = [c[0] for c in con.description] if con.description else []
            result = self._ok(
                summary=f"Executed DuckDB spatial SQL and returned {len(rows)} row(s).",
                data={"columns": columns, "rows": rows},
                provenance=self._make_provenance(
                    {"sql": kwargs["sql"], "limit": kwargs.get("limit")},
                    time.monotonic() - t0,
                ),
            )
            return result.to_llm_string()
        except Exception as exc:
            return self._fail(str(exc)).to_llm_string()


class AggregateFeaturesTool(GeoTool):
    @property
    def name(self) -> str:
        return "geo_duckdb_aggregate_features"

    @property
    def description(self) -> str:
        return "Aggregate features from a vector dataset by group field using DuckDB."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "group_by": {"type": "string"},
                "metric_field": {"type": "string"},
                "agg_method": {"type": "string", "enum": ["count", "sum", "avg", "min", "max"]},
            },
            "required": ["file_path", "group_by"],
        }

    async def execute(self, **kwargs: Any) -> str:
        t0 = time.monotonic()
        try:
            con = _connect_spatial()
            file_path = _duckdb_path_literal(kwargs["file_path"])
            group_by = kwargs["group_by"]
            metric_field = kwargs.get("metric_field")
            method = kwargs.get("agg_method", "count")

            source = f"ST_Read('{file_path}')"
            if method == "count" or not metric_field:
                expr = "COUNT(*) AS value"
            else:
                expr = f"{method.upper()}({metric_field}) AS value"

            sql = f"""
                SELECT {group_by} AS group_key, {expr}
                FROM {source}
                GROUP BY {group_by}
                ORDER BY value DESC
            """
            rows = con.execute(sql).fetchall()
            result = self._ok(
                summary=f"Aggregated {len(rows)} grouped result(s) with DuckDB.",
                data={
                    "group_by": group_by,
                    "metric_field": metric_field,
                    "agg_method": method,
                    "rows": rows,
                },
                provenance=self._make_provenance(
                    {
                        "file_path": kwargs["file_path"],
                        "group_by": group_by,
                        "metric_field": metric_field,
                        "agg_method": method,
                    },
                    time.monotonic() - t0,
                ),
            )
            return result.to_llm_string()
        except Exception as exc:
            return self._fail(str(exc)).to_llm_string()


class SummarizeByGeometryTool(GeoTool):
    @property
    def name(self) -> str:
        return "geo_duckdb_summarize_by_geometry"

    @property
    def description(self) -> str:
        return "Summarize features intersecting a geometry using DuckDB spatial predicates."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "geojson": {"type": "object"},
                "metric_field": {"type": "string"},
                "agg_method": {"type": "string", "enum": ["count", "sum", "avg", "min", "max"]},
            },
            "required": ["file_path", "geojson"],
        }

    async def execute(self, **kwargs: Any) -> str:
        import json as _json
        from shapely.geometry import shape

        t0 = time.monotonic()
        try:
            con = _connect_spatial()
            file_path = _duckdb_path_literal(kwargs["file_path"])
            geom_wkt = shape(kwargs["geojson"]).wkt
            metric_field = kwargs.get("metric_field")
            method = kwargs.get("agg_method", "count")
            expr = "COUNT(*) AS value" if method == "count" or not metric_field else f"{method.upper()}({metric_field}) AS value"
            sql = f"""
                SELECT
                    COUNT(*) AS matched_features,
                    {expr}
                FROM ST_Read('{file_path}')
                WHERE ST_Intersects(geom, ST_GeomFromText('{geom_wkt}'))
            """
            row = con.execute(sql).fetchone()
            result = self._ok(
                summary=f"Summarized features intersecting the supplied geometry.",
                data={
                    "matched_features": row[0] if row else 0,
                    "value": row[1] if row and len(row) > 1 else None,
                    "agg_method": method,
                    "metric_field": metric_field,
                },
                provenance=self._make_provenance(
                    {
                        "file_path": kwargs["file_path"],
                        "metric_field": metric_field,
                        "agg_method": method,
                    },
                    time.monotonic() - t0,
                ),
            )
            return result.to_llm_string()
        except Exception as exc:
            return self._fail(str(exc)).to_llm_string()
