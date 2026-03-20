from __future__ import annotations

import json

import pytest

from geoclaw.tools.stac import (
    PreviewSTACAssetsTool,
    RankSTACAssetsTool,
    SearchSTACTool,
    SelectBestSceneTool,
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
            "properties": {
                "datetime": "2024-06-01T00:00:00Z",
                "eo:cloud_cover": self._cloud_cover,
            },
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


@pytest.mark.asyncio
async def test_search_rank_preview_and_select_stac(monkeypatch, tmp_path):
    monkeypatch.setattr("pystac_client.Client.open", lambda url: _FakeClient())

    search_tool = SearchSTACTool(tmp_path)
    rank_tool = RankSTACAssetsTool(tmp_path)
    preview_tool = PreviewSTACAssetsTool(tmp_path)
    select_tool = SelectBestSceneTool(tmp_path)

    search_output = await search_tool.execute(
        catalog_url="https://example.com/stac",
        bbox={"west": 116.3, "south": 39.9, "east": 116.5, "north": 40.0},
        limit=2,
    )
    assert "[geo_search_stac] OK" in search_output

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
    rank_output = await rank_tool.execute(items_json=json.dumps(items), asset_preferences=["visual", "thumbnail"])
    preview_output = await preview_tool.execute(items_json=json.dumps(items))
    ranked = [
        {**items[0], "score": 7, "matched_assets": ["visual"]},
        {**items[1], "score": -50, "matched_assets": ["thumbnail"]},
    ]
    select_output = await select_tool.execute(ranked_items_json=json.dumps(ranked))

    assert "[geo_rank_stac_assets] OK" in rank_output
    assert "[geo_preview_stac_assets] OK" in preview_output
    assert "[geo_select_best_scene] OK" in select_output
    assert "scene-low-cloud" in select_output
