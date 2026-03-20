"""Network, routing, isochrone, and coverage tools."""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

import networkx as nx

from geoclaw.tools.base import GeoTool
from geoclaw.tools.osm import _load_geometry_from_input


def _mode_speed_kph(mode: str) -> float:
    speeds = {
        "walk": 5.0,
        "bike": 15.0,
        "drive": 35.0,
        "all": 20.0,
    }
    return speeds.get(mode, 5.0)


def _network_type(mode: str) -> str:
    mapping = {"walk": "walk", "bike": "bike", "drive": "drive", "all": "all"}
    return mapping.get(mode, "walk")


def _point_feature_to_tuple(point: dict[str, Any]) -> tuple[float, float]:
    if "lon" in point and "lat" in point:
        return float(point["lon"]), float(point["lat"])
    if "x" in point and "y" in point:
        return float(point["x"]), float(point["y"])
    raise ValueError(f"Point must contain lon/lat or x/y, got: {point}")


def _build_graph_for_aoi(
    *,
    mode: str,
    bbox: dict | None = None,
    geojson: dict | None = None,
    file_path: str | None = None,
    place_name: str | None = None,
):
    import osmnx as ox

    geometry = _load_geometry_from_input(
        bbox=bbox,
        geojson=geojson,
        file_path=file_path,
        place_name=place_name,
    )
    graph = ox.graph_from_polygon(geometry, network_type=_network_type(mode), simplify=True)
    speed_kph = _mode_speed_kph(mode)
    speed_mps = speed_kph * 1000 / 3600
    for _, _, _, data in graph.edges(keys=True, data=True):
        length = float(data.get("length", 0.0))
        data["travel_time"] = length / speed_mps if speed_mps > 0 else length
    return graph


def _nearest_node(graph, lon: float, lat: float) -> Any:
    import osmnx as ox

    return ox.distance.nearest_nodes(graph, lon, lat)


def _route_linestring(graph, path_nodes: list[Any]):
    from shapely.geometry import LineString

    coords = [(graph.nodes[node]["x"], graph.nodes[node]["y"]) for node in path_nodes]
    if len(coords) < 2:
        raise ValueError("Route path needs at least 2 nodes.")
    return LineString(coords)


def _nodes_to_polygon(graph, nodes: list[Any]):
    import geopandas as gpd

    pts = gpd.GeoDataFrame(
        geometry=gpd.points_from_xy(
            [graph.nodes[n]["x"] for n in nodes],
            [graph.nodes[n]["y"] for n in nodes],
        ),
        crs="EPSG:4326",
    )
    projected = pts.to_crs("EPSG:3857")
    poly = projected.buffer(60).union_all().convex_hull
    return gpd.GeoSeries([poly], crs="EPSG:3857").to_crs("EPSG:4326").iloc[0]


class BuildNetworkTool(GeoTool):
    @property
    def name(self) -> str:
        return "geo_build_network"

    @property
    def description(self) -> str:
        return "Build an OSMnx street network for an AOI and save it as GraphML."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "bbox": {"type": "object"},
                "geojson": {"type": "object"},
                "file_path": {"type": "string"},
                "place_name": {"type": "string"},
                "mode": {"type": "string", "enum": ["walk", "bike", "drive", "all"]},
                "run_id": {"type": "string"},
            },
        }

    async def execute(self, **kwargs: Any) -> str:
        import osmnx as ox

        t0 = time.monotonic()
        run_id = kwargs.get("run_id") or self._new_run_id()
        mode = kwargs.get("mode", "walk")
        params = {k: v for k, v in kwargs.items() if k != "run_id"}
        try:
            graph = _build_graph_for_aoi(
                mode=mode,
                bbox=kwargs.get("bbox"),
                geojson=kwargs.get("geojson"),
                file_path=kwargs.get("file_path"),
                place_name=kwargs.get("place_name"),
            )
            graph_path = self._artifact_dir(run_id) / "network.graphml"
            ox.save_graphml(graph, graph_path)
            result = self._ok(
                summary=(
                    f"Built {mode} network with {graph.number_of_nodes()} node(s) and "
                    f"{graph.number_of_edges()} edge(s)."
                ),
                data={
                    "run_id": run_id,
                    "mode": mode,
                    "node_count": graph.number_of_nodes(),
                    "edge_count": graph.number_of_edges(),
                    "graphml_path": str(graph_path),
                },
                artifacts=[
                    self._save_artifact(
                        run_id,
                        "network_manifest.json",
                        json.dumps({"graphml_path": str(graph_path)}, ensure_ascii=False),
                        "json",
                        "Network manifest",
                    )
                ],
                provenance=self._make_provenance(params, time.monotonic() - t0),
            )
            return result.to_llm_string()
        except Exception as exc:
            return self._fail(str(exc)).to_llm_string()


class ComputeRouteTool(GeoTool):
    @property
    def name(self) -> str:
        return "geo_compute_route"

    @property
    def description(self) -> str:
        return "Compute shortest route between origin and destination on an OSMnx network."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "bbox": {"type": "object"},
                "geojson": {"type": "object"},
                "file_path": {"type": "string"},
                "place_name": {"type": "string"},
                "mode": {"type": "string", "enum": ["walk", "bike", "drive", "all"]},
                "origin": {"type": "object"},
                "destination": {"type": "object"},
                "run_id": {"type": "string"},
            },
            "required": ["origin", "destination"],
        }

    async def execute(self, **kwargs: Any) -> str:
        import geopandas as gpd

        t0 = time.monotonic()
        run_id = kwargs.get("run_id") or self._new_run_id()
        mode = kwargs.get("mode", "walk")
        try:
            graph = _build_graph_for_aoi(
                mode=mode,
                bbox=kwargs.get("bbox"),
                geojson=kwargs.get("geojson"),
                file_path=kwargs.get("file_path"),
                place_name=kwargs.get("place_name"),
            )
            origin_lon, origin_lat = _point_feature_to_tuple(kwargs["origin"])
            dest_lon, dest_lat = _point_feature_to_tuple(kwargs["destination"])
            origin_node = _nearest_node(graph, origin_lon, origin_lat)
            dest_node = _nearest_node(graph, dest_lon, dest_lat)
            path = nx.shortest_path(graph, origin_node, dest_node, weight="length")
            length_m = float(nx.shortest_path_length(graph, origin_node, dest_node, weight="length"))
            travel_s = float(nx.shortest_path_length(graph, origin_node, dest_node, weight="travel_time"))
            line = _route_linestring(graph, path)
            gdf = gpd.GeoDataFrame(
                [{"length_m": length_m, "travel_time_s": travel_s}],
                geometry=[line],
                crs="EPSG:4326",
            )
            out_path = self._artifact_dir(run_id) / "route.geojson"
            gdf.to_file(out_path, driver="GeoJSON")
            result = self._ok(
                summary=f"Computed route of {length_m:.0f} m in ~{travel_s/60:.1f} min.",
                data={
                    "run_id": run_id,
                    "mode": mode,
                    "path_node_count": len(path),
                    "length_m": round(length_m, 2),
                    "travel_time_s": round(travel_s, 2),
                    "origin_node": origin_node,
                    "destination_node": dest_node,
                },
                artifacts=[
                    self._save_artifact(
                        run_id,
                        "route_manifest.json",
                        json.dumps({"route_path": str(out_path)}, ensure_ascii=False),
                        "json",
                        "Route manifest",
                    )
                ],
                provenance=self._make_provenance(
                    {
                        "mode": mode,
                        "origin": kwargs["origin"],
                        "destination": kwargs["destination"],
                    },
                    time.monotonic() - t0,
                ),
            )
            return result.to_llm_string()
        except Exception as exc:
            return self._fail(str(exc)).to_llm_string()


class ComputeIsochroneTool(GeoTool):
    @property
    def name(self) -> str:
        return "geo_compute_isochrone"

    @property
    def description(self) -> str:
        return "Compute an isochrone / service area around an origin point."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "bbox": {"type": "object"},
                "geojson": {"type": "object"},
                "file_path": {"type": "string"},
                "place_name": {"type": "string"},
                "mode": {"type": "string", "enum": ["walk", "bike", "drive", "all"]},
                "origin": {"type": "object"},
                "time_threshold_minutes": {"type": "number"},
                "distance_threshold_meters": {"type": "number"},
                "run_id": {"type": "string"},
            },
            "required": ["origin"],
        }

    async def execute(self, **kwargs: Any) -> str:
        import geopandas as gpd

        t0 = time.monotonic()
        run_id = kwargs.get("run_id") or self._new_run_id()
        mode = kwargs.get("mode", "walk")
        try:
            graph = _build_graph_for_aoi(
                mode=mode,
                bbox=kwargs.get("bbox"),
                geojson=kwargs.get("geojson"),
                file_path=kwargs.get("file_path"),
                place_name=kwargs.get("place_name"),
            )
            origin_lon, origin_lat = _point_feature_to_tuple(kwargs["origin"])
            origin_node = _nearest_node(graph, origin_lon, origin_lat)
            if kwargs.get("time_threshold_minutes") is not None:
                threshold = float(kwargs["time_threshold_minutes"]) * 60
                weight = "travel_time"
            elif kwargs.get("distance_threshold_meters") is not None:
                threshold = float(kwargs["distance_threshold_meters"])
                weight = "length"
            else:
                return self._fail("Provide time_threshold_minutes or distance_threshold_meters.").to_llm_string()

            lengths = nx.single_source_dijkstra_path_length(graph, origin_node, cutoff=threshold, weight=weight)
            reachable_nodes = list(lengths.keys())
            polygon = _nodes_to_polygon(graph, reachable_nodes)
            gdf = gpd.GeoDataFrame(
                [{"node_count": len(reachable_nodes), "threshold": threshold, "weight": weight}],
                geometry=[polygon],
                crs="EPSG:4326",
            )
            out_path = self._artifact_dir(run_id) / "isochrone.geojson"
            gdf.to_file(out_path, driver="GeoJSON")
            result = self._ok(
                summary=f"Isochrone reaches {len(reachable_nodes)} node(s) for threshold {threshold:.0f} {weight}.",
                data={
                    "run_id": run_id,
                    "mode": mode,
                    "origin_node": origin_node,
                    "reachable_node_count": len(reachable_nodes),
                    "threshold": threshold,
                    "weight": weight,
                },
                artifacts=[
                    self._save_artifact(
                        run_id,
                        "isochrone_manifest.json",
                        json.dumps({"isochrone_path": str(out_path)}, ensure_ascii=False),
                        "json",
                        "Isochrone manifest",
                    )
                ],
                provenance=self._make_provenance(
                    {
                        "mode": mode,
                        "origin": kwargs["origin"],
                        "time_threshold_minutes": kwargs.get("time_threshold_minutes"),
                        "distance_threshold_meters": kwargs.get("distance_threshold_meters"),
                    },
                    time.monotonic() - t0,
                ),
            )
            return result.to_llm_string()
        except Exception as exc:
            return self._fail(str(exc)).to_llm_string()


class ComputeServiceCoverageTool(GeoTool):
    @property
    def name(self) -> str:
        return "geo_compute_service_coverage"

    @property
    def description(self) -> str:
        return "Count reachable destination points from one or more origins within a threshold."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "bbox": {"type": "object"},
                "geojson": {"type": "object"},
                "file_path": {"type": "string"},
                "place_name": {"type": "string"},
                "mode": {"type": "string", "enum": ["walk", "bike", "drive", "all"]},
                "origins": {"type": "array", "items": {"type": "object"}},
                "destinations_geojson": {"type": "object"},
                "time_threshold_minutes": {"type": "number"},
                "distance_threshold_meters": {"type": "number"},
            },
            "required": ["origins", "destinations_geojson"],
        }

    async def execute(self, **kwargs: Any) -> str:
        import geopandas as gpd
        from shapely.geometry import shape

        t0 = time.monotonic()
        mode = kwargs.get("mode", "walk")
        try:
            graph = _build_graph_for_aoi(
                mode=mode,
                bbox=kwargs.get("bbox"),
                geojson=kwargs.get("geojson"),
                file_path=kwargs.get("file_path"),
                place_name=kwargs.get("place_name"),
            )
            if kwargs.get("time_threshold_minutes") is not None:
                threshold = float(kwargs["time_threshold_minutes"]) * 60
                weight = "travel_time"
            elif kwargs.get("distance_threshold_meters") is not None:
                threshold = float(kwargs["distance_threshold_meters"])
                weight = "length"
            else:
                return self._fail("Provide time_threshold_minutes or distance_threshold_meters.").to_llm_string()

            origins = [_point_feature_to_tuple(item) for item in kwargs["origins"]]
            destinations_gj = kwargs["destinations_geojson"]
            if destinations_gj.get("type") == "FeatureCollection":
                dest_gdf = gpd.GeoDataFrame.from_features(destinations_gj["features"], crs="EPSG:4326")
            elif destinations_gj.get("type") == "Feature":
                dest_gdf = gpd.GeoDataFrame.from_features([destinations_gj], crs="EPSG:4326")
            else:
                dest_gdf = gpd.GeoDataFrame(geometry=[shape(destinations_gj)], crs="EPSG:4326")
            dest_points = dest_gdf[dest_gdf.geometry.geom_type == "Point"].copy()
            if dest_points.empty:
                return self._fail("destinations_geojson must contain Point features.").to_llm_string()

            origin_nodes = [_nearest_node(graph, lon, lat) for lon, lat in origins]
            dest_points["dest_node"] = dest_points.geometry.apply(lambda geom: _nearest_node(graph, geom.x, geom.y))

            reachable_mask = []
            min_costs = []
            for dest_node in dest_points["dest_node"]:
                costs = []
                for origin_node in origin_nodes:
                    try:
                        cost = nx.shortest_path_length(graph, origin_node, dest_node, weight=weight)
                        costs.append(float(cost))
                    except nx.NetworkXNoPath:
                        continue
                min_cost = min(costs) if costs else math.inf
                min_costs.append(min_cost)
                reachable_mask.append(min_cost <= threshold)

            dest_points["min_cost"] = min_costs
            dest_points["reachable"] = reachable_mask
            reachable_count = int(dest_points["reachable"].sum())
            total = len(dest_points)

            result = self._ok(
                summary=f"Reachable destinations: {reachable_count}/{total} within threshold {threshold:.0f}.",
                data={
                    "mode": mode,
                    "weight": weight,
                    "threshold": threshold,
                    "origin_count": len(origins),
                    "destination_count": total,
                    "reachable_count": reachable_count,
                    "uncovered_count": total - reachable_count,
                },
                provenance=self._make_provenance(
                    {
                        "mode": mode,
                        "origin_count": len(origins),
                        "destination_count": total,
                        "threshold": threshold,
                        "weight": weight,
                    },
                    time.monotonic() - t0,
                ),
            )
            return result.to_llm_string()
        except Exception as exc:
            return self._fail(str(exc)).to_llm_string()
