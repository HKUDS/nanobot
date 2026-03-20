"""GeoClaw geospatial tools."""

from __future__ import annotations

from pathlib import Path

from geoclaw.tools.aoi import (
    InspectAOITool,
    RenderWorkflowTool,
    SuggestCRSTool,
    ValidateGeometryTool,
)
from geoclaw.tools.duckdb_ops import (
    AggregateFeaturesTool,
    RunSpatialSQLTool,
    SummarizeByGeometryTool,
)
from geoclaw.tools.gdal_ops import (
    ClipDatasetTool,
    ConvertFormatTool,
    InspectDatasetTool,
    ReprojectDatasetTool,
    TranslateToCOGTool,
)
from geoclaw.tools.hex import (
    AggregateByH3Tool,
    NeighborhoodSummaryTool,
    PointToH3Tool,
    PolygonToH3Tool,
)
from geoclaw.tools.network import (
    BuildNetworkTool,
    ComputeIsochroneTool,
    ComputeRouteTool,
    ComputeServiceCoverageTool,
)
from geoclaw.tools.osm import BuildPlaceProfileTool, ExtractOSMByGeometryTool
from geoclaw.tools.raster import (
    ClipRasterTool,
    ExportRasterPreviewTool,
    RasterSummaryTool,
    ReadRasterTool,
)
from geoclaw.tools.stac import (
    PreviewSTACAssetsTool,
    RankSTACAssetsTool,
    SearchSTACTool,
    SelectBestSceneTool,
)
from geoclaw.tools.vector import ReadVectorTool, SummarizeVectorTool


def register_all_geo_tools(workspace: Path) -> list:
    """Instantiate the GeoClaw tool set for a workspace."""
    return [
        InspectAOITool(workspace),
        ValidateGeometryTool(workspace),
        SuggestCRSTool(workspace),
        RenderWorkflowTool(workspace),
        InspectDatasetTool(workspace),
        ReprojectDatasetTool(workspace),
        ClipDatasetTool(workspace),
        ConvertFormatTool(workspace),
        TranslateToCOGTool(workspace),
        RunSpatialSQLTool(workspace),
        AggregateFeaturesTool(workspace),
        SummarizeByGeometryTool(workspace),
        ReadVectorTool(workspace),
        SummarizeVectorTool(workspace),
        BuildNetworkTool(workspace),
        ComputeRouteTool(workspace),
        ComputeIsochroneTool(workspace),
        ComputeServiceCoverageTool(workspace),
        ExtractOSMByGeometryTool(workspace),
        BuildPlaceProfileTool(workspace),
        ReadRasterTool(workspace),
        ClipRasterTool(workspace),
        RasterSummaryTool(workspace),
        ExportRasterPreviewTool(workspace),
        SearchSTACTool(workspace),
        RankSTACAssetsTool(workspace),
        PreviewSTACAssetsTool(workspace),
        SelectBestSceneTool(workspace),
        PointToH3Tool(workspace),
        PolygonToH3Tool(workspace),
        AggregateByH3Tool(workspace),
        NeighborhoodSummaryTool(workspace),
    ]


__all__ = ["register_all_geo_tools"]
