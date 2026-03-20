from __future__ import annotations

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from geoclaw.tools.raster import ClipRasterTool, ExportRasterPreviewTool, RasterSummaryTool, ReadRasterTool


@pytest.fixture()
def sample_raster_path(tmp_path):
    path = tmp_path / "sample.tif"
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
async def test_read_raster(sample_raster_path, tmp_path):
    tool = ReadRasterTool(tmp_path)
    output = await tool.execute(raster_path=str(sample_raster_path))
    assert "[geo_read_raster] OK" in output
    assert "band_count" in output


@pytest.mark.asyncio
async def test_clip_raster(sample_raster_path, tmp_path):
    tool = ClipRasterTool(tmp_path)
    output = await tool.execute(
        raster_path=str(sample_raster_path),
        bbox={"west": 116.32, "south": 39.93, "east": 116.36, "north": 39.98},
        run_id="raster_run",
    )
    assert "[geo_clip_raster] OK" in output
    assert (tmp_path / "runs" / "raster_run" / "artifacts" / "clipped.tif").exists()


@pytest.mark.asyncio
async def test_raster_summary_and_preview(sample_raster_path, tmp_path):
    summary_tool = RasterSummaryTool(tmp_path)
    preview_tool = ExportRasterPreviewTool(tmp_path)

    summary_output = await summary_tool.execute(raster_path=str(sample_raster_path), band=1)
    preview_output = await preview_tool.execute(
        raster_path=str(sample_raster_path),
        band=1,
        run_id="preview_run",
    )

    assert "[geo_raster_summary] OK" in summary_output
    assert "mean" in summary_output
    assert "[geo_export_raster_preview] OK" in preview_output
    assert (tmp_path / "runs" / "preview_run" / "artifacts" / "preview.png").exists()
