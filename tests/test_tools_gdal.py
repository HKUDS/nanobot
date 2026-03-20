from __future__ import annotations

import json

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from geoclaw.tools.gdal_ops import (
    ClipDatasetTool,
    ConvertFormatTool,
    InspectDatasetTool,
    ReprojectDatasetTool,
    TranslateToCOGTool,
)


@pytest.fixture()
def gdal_sample_raster(tmp_path):
    path = tmp_path / "gdal_sample.tif"
    data = np.arange(25, dtype="float32").reshape((5, 5))
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=5,
        width=5,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(116.3, 40.0, 0.01, 0.01),
        nodata=-9999,
    ) as dst:
        dst.write(data, 1)
    return path


@pytest.mark.asyncio
async def test_inspect_and_reproject_vector(tmp_path, sample_geojson_path):
    inspect_tool = InspectDatasetTool(tmp_path)
    inspect_output = await inspect_tool.execute(path=str(sample_geojson_path))
    assert "[geo_gdal_inspect_dataset] OK" in inspect_output

    reproject_tool = ReprojectDatasetTool(tmp_path)
    reproject_output = await reproject_tool.execute(
        path=str(sample_geojson_path),
        target_crs="EPSG:3857",
        run_id="gdal_vec",
    )
    assert "[geo_gdal_reproject_dataset] OK" in reproject_output


@pytest.mark.asyncio
async def test_clip_and_convert_vector(tmp_path, sample_geojson_path):
    clip_tool = ClipDatasetTool(tmp_path)
    clip_output = await clip_tool.execute(
        path=str(sample_geojson_path),
        bbox={"west": 116.31, "south": 39.91, "east": 116.49, "north": 39.99},
        run_id="gdal_clip",
    )
    assert "[geo_gdal_clip_dataset] OK" in clip_output

    convert_tool = ConvertFormatTool(tmp_path)
    convert_output = await convert_tool.execute(
        path=str(sample_geojson_path),
        target_format="geoparquet",
        run_id="gdal_convert",
    )
    assert "[geo_gdal_convert_format] OK" in convert_output


@pytest.mark.asyncio
async def test_inspect_raster_and_translate_to_cog(tmp_path, gdal_sample_raster, monkeypatch):
    inspect_tool = InspectDatasetTool(tmp_path)
    inspect_output = await inspect_tool.execute(path=str(gdal_sample_raster))
    assert "[geo_gdal_inspect_dataset] OK" in inspect_output

    def fake_copy(src, dst, driver="GTiff", **kwargs):
        from shutil import copyfile

        copyfile(src, dst)

    monkeypatch.setattr("rasterio.shutil.copy", fake_copy)
    cog_tool = TranslateToCOGTool(tmp_path)
    cog_output = await cog_tool.execute(path=str(gdal_sample_raster), run_id="cog_run")
    assert "[geo_gdal_translate_to_cog] OK" in cog_output
