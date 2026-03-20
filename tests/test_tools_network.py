from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
import pytest

from geoclaw.tools.network import (
    BuildNetworkTool,
    ComputeIsochroneTool,
    ComputeRouteTool,
    ComputeServiceCoverageTool,
)


def _fake_graph():
    graph = nx.MultiDiGraph()
    graph.add_node(1, x=116.30, y=39.90)
    graph.add_node(2, x=116.31, y=39.91)
    graph.add_node(3, x=116.32, y=39.92)
    graph.add_node(4, x=116.34, y=39.94)
    graph.add_edge(1, 2, key=0, length=1000.0, travel_time=600.0)
    graph.add_edge(2, 3, key=0, length=1000.0, travel_time=600.0)
    graph.add_edge(3, 4, key=0, length=1200.0, travel_time=720.0)
    graph.add_edge(2, 1, key=0, length=1000.0, travel_time=600.0)
    graph.add_edge(3, 2, key=0, length=1000.0, travel_time=600.0)
    graph.add_edge(4, 3, key=0, length=1200.0, travel_time=720.0)
    return graph


def _fake_nearest_node(graph, lon: float, lat: float):
    nodes = list(graph.nodes(data=True))
    node_id, _ = min(
        nodes,
        key=lambda item: (item[1]["x"] - lon) ** 2 + (item[1]["y"] - lat) ** 2,
    )
    return node_id


@pytest.mark.asyncio
async def test_build_network(monkeypatch, tmp_path):
    graph = _fake_graph()
    monkeypatch.setattr("geoclaw.tools.network._build_graph_for_aoi", lambda **kwargs: graph)

    def fake_save_graphml(graph_obj, path):
        Path(path).write_text("graphml", encoding="utf-8")

    monkeypatch.setattr("osmnx.save_graphml", fake_save_graphml)

    tool = BuildNetworkTool(tmp_path)
    output = await tool.execute(
        bbox={"west": 116.3, "south": 39.9, "east": 116.35, "north": 39.95},
        mode="walk",
        run_id="network_run",
    )

    assert "[geo_build_network] OK" in output
    assert (tmp_path / "runs" / "network_run" / "artifacts" / "network.graphml").exists()


@pytest.mark.asyncio
async def test_compute_route(monkeypatch, tmp_path):
    graph = _fake_graph()
    monkeypatch.setattr("geoclaw.tools.network._build_graph_for_aoi", lambda **kwargs: graph)
    monkeypatch.setattr("geoclaw.tools.network._nearest_node", _fake_nearest_node)

    tool = ComputeRouteTool(tmp_path)
    output = await tool.execute(
        bbox={"west": 116.3, "south": 39.9, "east": 116.35, "north": 39.95},
        origin={"lon": 116.3001, "lat": 39.9001},
        destination={"lon": 116.339, "lat": 39.939},
        mode="walk",
        run_id="route_run",
    )

    assert "[geo_compute_route] OK" in output
    assert "length_m" in output


@pytest.mark.asyncio
async def test_compute_isochrone(monkeypatch, tmp_path):
    graph = _fake_graph()
    monkeypatch.setattr("geoclaw.tools.network._build_graph_for_aoi", lambda **kwargs: graph)
    monkeypatch.setattr("geoclaw.tools.network._nearest_node", _fake_nearest_node)

    tool = ComputeIsochroneTool(tmp_path)
    output = await tool.execute(
        bbox={"west": 116.3, "south": 39.9, "east": 116.35, "north": 39.95},
        origin={"lon": 116.3001, "lat": 39.9001},
        time_threshold_minutes=20,
        mode="walk",
        run_id="iso_run",
    )

    assert "[geo_compute_isochrone] OK" in output
    assert "reachable_node_count" in output


@pytest.mark.asyncio
async def test_compute_service_coverage(monkeypatch, tmp_path):
    graph = _fake_graph()
    monkeypatch.setattr("geoclaw.tools.network._build_graph_for_aoi", lambda **kwargs: graph)
    monkeypatch.setattr("geoclaw.tools.network._nearest_node", _fake_nearest_node)

    destinations = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "near"},
                "geometry": {"type": "Point", "coordinates": [116.31, 39.91]},
            },
            {
                "type": "Feature",
                "properties": {"name": "far"},
                "geometry": {"type": "Point", "coordinates": [116.34, 39.94]},
            },
        ],
    }

    tool = ComputeServiceCoverageTool(tmp_path)
    output = await tool.execute(
        bbox={"west": 116.3, "south": 39.9, "east": 116.35, "north": 39.95},
        origins=[{"lon": 116.3001, "lat": 39.9001}],
        destinations_geojson=destinations,
        time_threshold_minutes=25,
        mode="walk",
    )

    assert "[geo_compute_service_coverage] OK" in output
    assert "reachable_count" in output
