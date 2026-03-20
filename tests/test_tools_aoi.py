from __future__ import annotations

import json

import pytest

from geoclaw.tools.aoi import InspectAOITool, SuggestCRSTool, ValidateGeometryTool

geopandas = pytest.importorskip("geopandas")


@pytest.mark.asyncio
async def test_inspect_aoi_from_geojson_creates_run_artifact(tmp_path, sample_geojson_dict):
    tool = InspectAOITool(tmp_path)
    output = await tool.execute(geojson=sample_geojson_dict, run_id="demo_run")

    assert "[geo_inspect_aoi] OK" in output
    assert "feature_count" in output
    assert (tmp_path / "runs" / "demo_run" / "artifacts" / "aoi.geojson").exists()


@pytest.mark.asyncio
async def test_validate_geometry_reports_valid_geometry(tmp_path, sample_geojson_dict):
    tool = ValidateGeometryTool(tmp_path)
    output = await tool.execute(geojson=sample_geojson_dict)

    assert "[geo_validate_geometry] OK" in output
    assert "valid" in output.lower()


@pytest.mark.asyncio
async def test_suggest_crs_returns_epsg(tmp_path):
    tool = SuggestCRSTool(tmp_path)
    output = await tool.execute(west=116.3, south=39.9, east=116.5, north=40.0)

    assert "[geo_suggest_crs] OK" in output
    assert "EPSG:" in output


@pytest.mark.asyncio
async def test_inspect_aoi_from_file_path(tmp_path, sample_geojson_path):
    tool = InspectAOITool(tmp_path)
    output = await tool.execute(file_path=str(sample_geojson_path), run_id="file_run")

    assert "[geo_inspect_aoi] OK" in output
    artifact_path = tmp_path / "runs" / "file_run" / "artifacts" / "aoi.geojson"
    assert artifact_path.exists()
    loaded = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert loaded["type"] == "FeatureCollection"
