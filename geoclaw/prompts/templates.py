"""Prompt templates for skill explanations."""

AOI_SUMMARY_TEMPLATE = """## AOI Sanity Check Results

**CRS**: {crs}
**Geometry Valid**: {is_valid}
**Feature Count**: {feature_count}
**Extent**: {extent}
**Estimated Area**: {area_estimate}
**Recommended Projected CRS**: {suggested_crs}

### Downstream Suggestions
{suggestions}
"""

OSM_PROFILE_TEMPLATE = """## OSM Place Profile

**Area**: {area_name}
**Total Features Extracted**: {total_features}

### Category Breakdown
{category_table}

### Summary
{narrative}
"""

RASTER_SUMMARY_TEMPLATE = """## Raster Exposure Summary

**Source**: {source}
**Clipped Extent**: {extent}
**Resolution**: {resolution}
**Band Count**: {band_count}

### Statistics
{stats_table}

### Method Notes
{method_notes}
"""
