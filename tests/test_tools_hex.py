from __future__ import annotations

import pytest

from geoclaw.tools.hex import AggregateByH3Tool, NeighborhoodSummaryTool, PointToH3Tool


POINT_FEATURES = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"weight": 1},
            "geometry": {"type": "Point", "coordinates": [116.31, 39.91]},
        },
        {
            "type": "Feature",
            "properties": {"weight": 2},
            "geometry": {"type": "Point", "coordinates": [116.311, 39.911]},
        },
        {
            "type": "Feature",
            "properties": {"weight": 3},
            "geometry": {"type": "Point", "coordinates": [116.35, 39.95]},
        },
    ],
}


@pytest.mark.asyncio
async def test_point_to_h3_and_aggregate(tmp_path):
    point_tool = PointToH3Tool(tmp_path)
    agg_tool = AggregateByH3Tool(tmp_path)

    point_output = await point_tool.execute(geojson=POINT_FEATURES, resolution=8, run_id="hex_run")
    agg_output = await agg_tool.execute(
        geojson=POINT_FEATURES,
        resolution=8,
        metric_property="weight",
        agg_method="sum",
        run_id="hex_agg_run",
    )

    assert "[geo_point_to_h3] OK" in point_output
    assert "[geo_aggregate_by_h3] OK" in agg_output


@pytest.mark.asyncio
async def test_neighborhood_summary(tmp_path):
    tool = NeighborhoodSummaryTool(tmp_path)
    output = await tool.execute(h3_cell="8828308281fffff", k=1)
    assert "[geo_neighborhood_summary] OK" in output
    assert "neighbor_count" in output
