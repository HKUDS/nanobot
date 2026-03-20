"""STAC search, ranking, and scene selection tools."""

from __future__ import annotations

import json
import time
from typing import Any

from geoclaw.tools.base import GeoTool
from geoclaw.tools.common import parse_bbox


def _normalise_search_results(items) -> list[dict[str, Any]]:
    normalised = []
    for item in items:
        item_dict = item.to_dict() if hasattr(item, "to_dict") else item
        props = item_dict.get("properties", {})
        assets = item_dict.get("assets", {})
        normalised.append(
            {
                "id": item_dict.get("id"),
                "collection": item_dict.get("collection"),
                "datetime": props.get("datetime"),
                "cloud_cover": props.get("eo:cloud_cover", props.get("cloud_cover")),
                "assets": {
                    key: {"href": value.get("href"), "type": value.get("type")}
                    for key, value in assets.items()
                },
                "bbox": item_dict.get("bbox"),
                "properties": props,
            }
        )
    return normalised


class SearchSTACTool(GeoTool):
    @property
    def name(self) -> str:
        return "geo_search_stac"

    @property
    def description(self) -> str:
        return "Search a STAC API by AOI, time range, collections, and optional query filters."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "catalog_url": {"type": "string"},
                "bbox": {"type": "object"},
                "datetime": {"type": "string"},
                "collections": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer"},
                "query": {"type": "object"},
            },
            "required": ["catalog_url"],
        }

    async def execute(self, **kwargs: Any) -> str:
        from pystac_client import Client

        t0 = time.monotonic()
        try:
            catalog = Client.open(kwargs["catalog_url"])
            search_kwargs: dict[str, Any] = {"limit": kwargs.get("limit", 10)}
            if kwargs.get("bbox"):
                search_kwargs["bbox"] = list(parse_bbox(kwargs["bbox"]).as_tuple())
            if kwargs.get("datetime"):
                search_kwargs["datetime"] = kwargs["datetime"]
            if kwargs.get("collections"):
                search_kwargs["collections"] = kwargs["collections"]
            if kwargs.get("query"):
                search_kwargs["query"] = kwargs["query"]

            items = list(catalog.search(**search_kwargs).items())
            results = _normalise_search_results(items)
            result = self._ok(
                summary=f"Found {len(results)} STAC item(s).",
                data={"catalog_url": kwargs["catalog_url"], "items": results},
                provenance=self._make_provenance(search_kwargs, time.monotonic() - t0),
            )
            return result.to_llm_string()
        except Exception as exc:
            return self._fail(str(exc)).to_llm_string()


class RankSTACAssetsTool(GeoTool):
    @property
    def name(self) -> str:
        return "geo_rank_stac_assets"

    @property
    def description(self) -> str:
        return "Rank STAC search results by cloud cover and preferred asset keys."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "items_json": {"type": "string"},
                "asset_preferences": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["items_json"],
        }

    async def execute(self, **kwargs: Any) -> str:
        t0 = time.monotonic()
        try:
            items = json.loads(kwargs["items_json"])
            prefs = kwargs.get("asset_preferences") or ["visual", "rendered_preview", "thumbnail", "B04", "image"]

            ranked = []
            for item in items:
                assets = item.get("assets", {})
                asset_bonus = 0
                matched_assets = []
                for pref in prefs:
                    if pref in assets:
                        asset_bonus += 10
                        matched_assets.append(pref)
                cloud = item.get("cloud_cover")
                cloud_penalty = float(cloud) if cloud is not None else 50.0
                score = asset_bonus - cloud_penalty
                ranked.append(
                    {
                        **item,
                        "score": score,
                        "matched_assets": matched_assets,
                    }
                )

            ranked.sort(key=lambda x: x["score"], reverse=True)
            result = self._ok(
                summary=f"Ranked {len(ranked)} STAC item(s).",
                data={"ranked_items": ranked},
                provenance=self._make_provenance(
                    {"asset_preferences": prefs, "item_count": len(items)},
                    time.monotonic() - t0,
                ),
            )
            return result.to_llm_string()
        except Exception as exc:
            return self._fail(str(exc)).to_llm_string()


class PreviewSTACAssetsTool(GeoTool):
    @property
    def name(self) -> str:
        return "geo_preview_stac_assets"

    @property
    def description(self) -> str:
        return "Extract preview/thumbnail asset references from STAC items."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "items_json": {"type": "string"},
            },
            "required": ["items_json"],
        }

    async def execute(self, **kwargs: Any) -> str:
        t0 = time.monotonic()
        try:
            items = json.loads(kwargs["items_json"])
            previews = []
            for item in items:
                assets = item.get("assets", {})
                preview = None
                for key in ("thumbnail", "rendered_preview", "visual", "overview", "image"):
                    if key in assets:
                        preview = {"asset_key": key, "href": assets[key].get("href")}
                        break
                previews.append({"id": item.get("id"), "preview": preview})
            result = self._ok(
                summary=f"Collected preview references for {len(previews)} item(s).",
                data={"previews": previews},
                provenance=self._make_provenance({"item_count": len(items)}, time.monotonic() - t0),
            )
            return result.to_llm_string()
        except Exception as exc:
            return self._fail(str(exc)).to_llm_string()


class SelectBestSceneTool(GeoTool):
    @property
    def name(self) -> str:
        return "geo_select_best_scene"

    @property
    def description(self) -> str:
        return "Select the best STAC scene from ranked results and explain the decision."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "ranked_items_json": {"type": "string"},
            },
            "required": ["ranked_items_json"],
        }

    async def execute(self, **kwargs: Any) -> str:
        t0 = time.monotonic()
        try:
            ranked_items = json.loads(kwargs["ranked_items_json"])
            if not ranked_items:
                return self._fail("No ranked items provided.").to_llm_string()
            best = ranked_items[0]
            reasoning = (
                f"Selected {best.get('id')} because it has the highest score "
                f"({best.get('score')}) with cloud_cover={best.get('cloud_cover')} "
                f"and preferred assets {best.get('matched_assets', [])}."
            )
            result = self._ok(
                summary=f"Selected best STAC scene: {best.get('id')}.",
                data={"best_scene": best, "reasoning": reasoning},
                provenance=self._make_provenance(
                    {"item_count": len(ranked_items)},
                    time.monotonic() - t0,
                ),
            )
            return result.to_llm_string()
        except Exception as exc:
            return self._fail(str(exc)).to_llm_string()
