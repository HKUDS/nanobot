from __future__ import annotations

from geoclaw.schemas.common import AOIInput, ArtifactMeta, BBox, ProvenanceMeta, ToolResult


def test_bbox_tuple_and_area():
    bbox = BBox(west=116.3, south=39.9, east=116.5, north=40.0)
    assert bbox.as_tuple() == (116.3, 39.9, 116.5, 40.0)
    assert bbox.area_degrees() > 0


def test_tool_result_llm_string_contains_key_sections():
    result = ToolResult(
        success=True,
        tool_name="geo_inspect_aoi",
        summary="AOI looks good",
        data={"feature_count": 1},
        artifacts=[
            ArtifactMeta(
                path="runs/demo/artifacts/aoi.geojson",
                format="geojson",
                size_bytes=123,
                description="AOI output",
            )
        ],
        provenance=ProvenanceMeta(tool_name="geo_inspect_aoi"),
    )
    text = result.to_llm_string()
    assert "[geo_inspect_aoi] OK" in text
    assert "AOI looks good" in text
    assert "Artifacts:" in text
    assert "feature_count" in text


def test_aoi_input_accepts_bbox():
    aoi = AOIInput(bbox=BBox(west=0, south=0, east=1, north=1))
    assert aoi.bbox is not None
    assert aoi.file_path is None
