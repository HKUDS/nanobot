from __future__ import annotations

import pytest

from geoclaw.tools.vector import ReadVectorTool, SummarizeVectorTool

pytest.importorskip("geopandas")


@pytest.mark.asyncio
async def test_read_vector_returns_summary_and_artifact(tmp_path, sample_geojson_path):
    tool = ReadVectorTool(tmp_path)
    output = await tool.execute(file_path=str(sample_geojson_path), run_id="vector_run")

    assert "[geo_read_vector] OK" in output
    assert "feature_count" in output
    assert (tmp_path / "runs" / "vector_run" / "artifacts" / "sample.geojson").exists()


@pytest.mark.asyncio
async def test_summarize_vector_with_geojson(tmp_path, sample_geojson_dict):
    tool = SummarizeVectorTool(tmp_path)
    output = await tool.execute(geojson=sample_geojson_dict)

    assert "[geo_summarize_vector] OK" in output
    assert "feature_count" in output
    assert "EPSG:4326" in output
