from __future__ import annotations

import json

import pytest

from geoclaw.tools.duckdb_ops import AggregateFeaturesTool, RunSpatialSQLTool, SummarizeByGeometryTool


@pytest.mark.asyncio
async def test_run_spatial_sql(tmp_path):
    tool = RunSpatialSQLTool(tmp_path)
    output = await tool.execute(sql="SELECT ST_AsText(ST_Point(1, 2)) AS wkt")
    assert "[geo_duckdb_run_spatial_sql] OK" in output
    assert "POINT (1 2)" in output


@pytest.mark.asyncio
async def test_aggregate_features_and_summarize_by_geometry(tmp_path):
    data = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"category": "a", "value": 1},
                "geometry": {"type": "Point", "coordinates": [116.31, 39.91]},
            },
            {
                "type": "Feature",
                "properties": {"category": "a", "value": 2},
                "geometry": {"type": "Point", "coordinates": [116.32, 39.92]},
            },
            {
                "type": "Feature",
                "properties": {"category": "b", "value": 4},
                "geometry": {"type": "Point", "coordinates": [116.45, 40.05]},
            },
        ],
    }
    src = tmp_path / "duck.geojson"
    src.write_text(json.dumps(data), encoding="utf-8")

    agg_tool = AggregateFeaturesTool(tmp_path)
    agg_output = await agg_tool.execute(
        file_path=str(src),
        group_by="category",
        metric_field="value",
        agg_method="sum",
    )
    assert "[geo_duckdb_aggregate_features] OK" in agg_output
    assert "group_by" in agg_output

    summarize_tool = SummarizeByGeometryTool(tmp_path)
    summarize_output = await summarize_tool.execute(
        file_path=str(src),
        geojson={
            "type": "Polygon",
            "coordinates": [[[116.3, 39.9], [116.35, 39.9], [116.35, 39.95], [116.3, 39.95], [116.3, 39.9]]],
        },
        metric_field="value",
        agg_method="sum",
    )
    assert "[geo_duckdb_summarize_by_geometry] OK" in summarize_output
    assert "matched_features" in summarize_output
