from __future__ import annotations

import json

import geopandas as gpd
import pytest
from shapely.geometry import Point

from geoclaw.tools.osm import BuildPlaceProfileTool, ExtractOSMByGeometryTool


@pytest.mark.asyncio
async def test_extract_osm_with_monkeypatched_quackosm(tmp_path, monkeypatch):
    def fake_convert_geometry_to_geodataframe(**kwargs):
        return gpd.GeoDataFrame(
            {
                "amenity": ["school", "cafe"],
                "shop": [None, "supermarket"],
            },
            geometry=[Point(116.31, 39.91), Point(116.32, 39.92)],
            crs="EPSG:4326",
        )

    monkeypatch.setattr(
        "quackosm.convert_geometry_to_geodataframe",
        fake_convert_geometry_to_geodataframe,
    )

    tool = ExtractOSMByGeometryTool(tmp_path)
    output = await tool.execute(
        bbox={"west": 116.3, "south": 39.9, "east": 116.4, "north": 40.0},
        run_id="osm_run",
    )

    assert "[geo_extract_osm] OK" in output
    assert "feature_count" in output
    assert (tmp_path / "runs" / "osm_run" / "artifacts" / "osm_extract.geojson").exists()


@pytest.mark.asyncio
async def test_build_place_profile_from_geojson(tmp_path):
    gdf = gpd.GeoDataFrame(
        {
            "amenity": ["school", "school", "cafe"],
            "shop": [None, None, "supermarket"],
        },
        geometry=[Point(116.31, 39.91), Point(116.32, 39.92), Point(116.33, 39.93)],
        crs="EPSG:4326",
    )
    geojson = json.loads(gdf.to_json())

    tool = BuildPlaceProfileTool(tmp_path)
    output = await tool.execute(geojson=geojson)

    assert "[geo_build_place_profile] OK" in output
    assert "narrative" in output
