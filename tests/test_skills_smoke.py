from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point

from geoclaw.tools.aoi import InspectAOITool, RenderWorkflowTool, SuggestCRSTool, ValidateGeometryTool
from geoclaw.tools.hex import AggregateByH3Tool, PointToH3Tool
from geoclaw.tools.network import BuildNetworkTool, ComputeRouteTool
from geoclaw.tools.osm import BuildPlaceProfileTool, ExtractOSMByGeometryTool
from geoclaw.tools.raster import ClipRasterTool, ExportRasterPreviewTool, RasterSummaryTool, ReadRasterTool
from geoclaw.tools.stac import PreviewSTACAssetsTool, RankSTACAssetsTool, SearchSTACTool, SelectBestSceneTool


def _summary_result(tool_name: str, output: str) -> dict:
    return {
        "tool_name": tool_name,
        "success": "[FAILED]" not in output,
        "summary": output,
        "errors": [],
        "warnings": [],
        "artifacts": [],
    }


def _fake_graph():
    graph = nx.MultiDiGraph()
    graph.add_node(1, x=116.30, y=39.90)
    graph.add_node(2, x=116.31, y=39.91)
    graph.add_node(3, x=116.32, y=39.92)
    graph.add_edge(1, 2, key=0, length=1000.0, travel_time=600.0)
    graph.add_edge(2, 3, key=0, length=1000.0, travel_time=600.0)
    graph.add_edge(2, 1, key=0, length=1000.0, travel_time=600.0)
    graph.add_edge(3, 2, key=0, length=1000.0, travel_time=600.0)
    return graph


def _fake_nearest_node(graph, lon: float, lat: float):
    return min(
        graph.nodes,
        key=lambda n: (graph.nodes[n]["x"] - lon) ** 2 + (graph.nodes[n]["y"] - lat) ** 2,
    )


class _FakeItem:
    def __init__(self, item_id: str, cloud_cover: float, assets: dict):
        self._item_id = item_id
        self._cloud_cover = cloud_cover
        self._assets = assets

    def to_dict(self):
        return {
            "id": self._item_id,
            "collection": "sentinel-2-l2a",
            "bbox": [116.3, 39.9, 116.5, 40.0],
            "properties": {"datetime": "2024-06-01T00:00:00Z", "eo:cloud_cover": self._cloud_cover},
            "assets": self._assets,
        }


class _FakeSearch:
    def items(self):
        return [
            _FakeItem("scene-low-cloud", 3, {"visual": {"href": "https://example.com/low.png", "type": "image/png"}}),
            _FakeItem("scene-high-cloud", 60, {"thumbnail": {"href": "https://example.com/high.png", "type": "image/png"}}),
        ]


class _FakeClient:
    def search(self, **kwargs):
        return _FakeSearch()


@pytest.fixture()
def smoke_raster_path(tmp_path):
    path = tmp_path / "smoke.tif"
    data = np.arange(100, dtype="float32").reshape((10, 10))
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(116.3, 40.0, 0.01, 0.01),
        nodata=-9999,
    ) as dst:
        dst.write(data, 1)
    return path


@pytest.mark.asyncio
async def test_aoi_sanity_check_smoke(tmp_path, sample_geojson_dict):
    run_id = "skill_aoi"
    inspect_tool = InspectAOITool(tmp_path)
    validate_tool = ValidateGeometryTool(tmp_path)
    suggest_tool = SuggestCRSTool(tmp_path)
    render_tool = RenderWorkflowTool(tmp_path)

    inspect_output = await inspect_tool.execute(geojson=sample_geojson_dict, run_id=run_id)
    validate_output = await validate_tool.execute(geojson=sample_geojson_dict)
    suggest_output = await suggest_tool.execute(west=116.3, south=39.9, east=116.5, north=40.0)
    render_output = await render_tool.execute(
        run_id=run_id,
        title="AOI Sanity Check",
        results_json=json.dumps(
            [
                _summary_result("geo_inspect_aoi", inspect_output),
                _summary_result("geo_validate_geometry", validate_output),
                _summary_result("geo_suggest_crs", suggest_output),
            ]
        ),
    )

    assert "[geo_render_workflow] OK" in render_output
    assert (tmp_path / "runs" / run_id / "summary.md").exists()


@pytest.mark.asyncio
async def test_osm_place_profile_smoke(tmp_path, monkeypatch):
    def fake_convert_geometry_to_geodataframe(**kwargs):
        return gpd.GeoDataFrame(
            {"amenity": ["school", "cafe"], "shop": [None, "supermarket"]},
            geometry=[Point(116.31, 39.91), Point(116.32, 39.92)],
            crs="EPSG:4326",
        )

    monkeypatch.setattr("quackosm.convert_geometry_to_geodataframe", fake_convert_geometry_to_geodataframe)

    run_id = "skill_osm"
    extract_tool = ExtractOSMByGeometryTool(tmp_path)
    profile_tool = BuildPlaceProfileTool(tmp_path)
    render_tool = RenderWorkflowTool(tmp_path)

    extract_output = await extract_tool.execute(
        bbox={"west": 116.3, "south": 39.9, "east": 116.4, "north": 40.0},
        run_id=run_id,
    )
    profile_output = await profile_tool.execute(
        file_path=str(tmp_path / "runs" / run_id / "artifacts" / "osm_extract.geojson")
    )
    render_output = await render_tool.execute(
        run_id=run_id,
        title="OSM Place Profile",
        results_json=json.dumps(
            [
                _summary_result("geo_extract_osm", extract_output),
                _summary_result("geo_build_place_profile", profile_output),
            ]
        ),
    )
    assert "[geo_render_workflow] OK" in render_output


@pytest.mark.asyncio
async def test_accessibility_analysis_smoke(tmp_path, monkeypatch):
    graph = _fake_graph()
    monkeypatch.setattr("geoclaw.tools.network._build_graph_for_aoi", lambda **kwargs: graph)
    monkeypatch.setattr("geoclaw.tools.network._nearest_node", _fake_nearest_node)
    monkeypatch.setattr("osmnx.save_graphml", lambda g, path: Path(path).write_text("graphml", encoding="utf-8"))

    run_id = "skill_access"
    build_tool = BuildNetworkTool(tmp_path)
    route_tool = ComputeRouteTool(tmp_path)
    render_tool = RenderWorkflowTool(tmp_path)

    build_output = await build_tool.execute(
        bbox={"west": 116.3, "south": 39.9, "east": 116.35, "north": 39.95},
        mode="walk",
        run_id=run_id,
    )
    route_output = await route_tool.execute(
        bbox={"west": 116.3, "south": 39.9, "east": 116.35, "north": 39.95},
        origin={"lon": 116.3001, "lat": 39.9001},
        destination={"lon": 116.319, "lat": 39.919},
        mode="walk",
        run_id=run_id,
    )
    render_output = await render_tool.execute(
        run_id=run_id,
        title="Accessibility Analysis",
        results_json=json.dumps(
            [
                _summary_result("geo_build_network", build_output),
                _summary_result("geo_compute_route", route_output),
            ]
        ),
    )
    assert "[geo_render_workflow] OK" in render_output


@pytest.mark.asyncio
async def test_raster_exposure_summary_smoke(tmp_path, smoke_raster_path):
    run_id = "skill_raster"
    read_tool = ReadRasterTool(tmp_path)
    clip_tool = ClipRasterTool(tmp_path)
    summary_tool = RasterSummaryTool(tmp_path)
    preview_tool = ExportRasterPreviewTool(tmp_path)
    render_tool = RenderWorkflowTool(tmp_path)

    read_output = await read_tool.execute(raster_path=str(smoke_raster_path))
    clip_output = await clip_tool.execute(
        raster_path=str(smoke_raster_path),
        bbox={"west": 116.32, "south": 39.93, "east": 116.36, "north": 39.98},
        run_id=run_id,
    )
    clipped_path = str(tmp_path / "runs" / run_id / "artifacts" / "clipped.tif")
    summary_output = await summary_tool.execute(raster_path=clipped_path, band=1)
    preview_output = await preview_tool.execute(raster_path=clipped_path, band=1, run_id=run_id)
    render_output = await render_tool.execute(
        run_id=run_id,
        title="Raster Exposure Summary",
        results_json=json.dumps(
            [
                _summary_result("geo_read_raster", read_output),
                _summary_result("geo_clip_raster", clip_output),
                _summary_result("geo_raster_summary", summary_output),
                _summary_result("geo_export_raster_preview", preview_output),
            ]
        ),
    )
    assert "[geo_render_workflow] OK" in render_output


@pytest.mark.asyncio
async def test_stac_search_preview_smoke(tmp_path, monkeypatch):
    monkeypatch.setattr("pystac_client.Client.open", lambda url: _FakeClient())

    run_id = "skill_stac"
    search_tool = SearchSTACTool(tmp_path)
    rank_tool = RankSTACAssetsTool(tmp_path)
    preview_tool = PreviewSTACAssetsTool(tmp_path)
    select_tool = SelectBestSceneTool(tmp_path)
    render_tool = RenderWorkflowTool(tmp_path)

    items = [
        {
            "id": "scene-low-cloud",
            "collection": "sentinel-2-l2a",
            "datetime": "2024-06-01T00:00:00Z",
            "cloud_cover": 3,
            "assets": {"visual": {"href": "https://example.com/low.png", "type": "image/png"}},
            "bbox": [116.3, 39.9, 116.5, 40.0],
            "properties": {},
        },
        {
            "id": "scene-high-cloud",
            "collection": "sentinel-2-l2a",
            "datetime": "2024-06-02T00:00:00Z",
            "cloud_cover": 60,
            "assets": {"thumbnail": {"href": "https://example.com/high.png", "type": "image/png"}},
            "bbox": [116.3, 39.9, 116.5, 40.0],
            "properties": {},
        },
    ]
    ranked = [
        {**items[0], "score": 7, "matched_assets": ["visual"]},
        {**items[1], "score": -50, "matched_assets": ["thumbnail"]},
    ]

    search_output = await search_tool.execute(
        catalog_url="https://example.com/stac",
        bbox={"west": 116.3, "south": 39.9, "east": 116.5, "north": 40.0},
        limit=2,
    )
    rank_output = await rank_tool.execute(items_json=json.dumps(items), asset_preferences=["visual", "thumbnail"])
    preview_output = await preview_tool.execute(items_json=json.dumps(items))
    select_output = await select_tool.execute(ranked_items_json=json.dumps(ranked))
    render_output = await render_tool.execute(
        run_id=run_id,
        title="STAC Search Preview",
        results_json=json.dumps(
            [
                _summary_result("geo_search_stac", search_output),
                _summary_result("geo_rank_stac_assets", rank_output),
                _summary_result("geo_preview_stac_assets", preview_output),
                _summary_result("geo_select_best_scene", select_output),
            ]
        ),
    )
    assert "[geo_render_workflow] OK" in render_output


@pytest.mark.asyncio
async def test_hex_service_coverage_smoke(tmp_path):
    points = {
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
        ],
    }
    run_id = "skill_hex"
    point_tool = PointToH3Tool(tmp_path)
    agg_tool = AggregateByH3Tool(tmp_path)
    render_tool = RenderWorkflowTool(tmp_path)

    point_output = await point_tool.execute(geojson=points, resolution=8, run_id=run_id)
    agg_output = await agg_tool.execute(
        geojson=points,
        resolution=8,
        metric_property="weight",
        agg_method="sum",
        run_id=run_id,
    )
    render_output = await render_tool.execute(
        run_id=run_id,
        title="Hex Service Coverage",
        results_json=json.dumps(
            [
                _summary_result("geo_point_to_h3", point_output),
                _summary_result("geo_aggregate_by_h3", agg_output),
            ]
        ),
    )
    assert "[geo_render_workflow] OK" in render_output
