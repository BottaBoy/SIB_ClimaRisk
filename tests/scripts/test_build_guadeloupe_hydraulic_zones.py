from __future__ import annotations

from pathlib import Path
import sys

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, Point


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from scripts import build_guadeloupe_hydraulic_zones


def test_zone_style_categories_requires_zone_component_key() -> None:
    gdf = gpd.GeoDataFrame(
        {
            "zone_uid": ["AEP_001"],
            "zone_label": ["Zone 1"],
            "zone_color": ["#123456"],
        },
        geometry=[Point(0.0, 0.0)],
        crs="EPSG:4326",
    )

    with pytest.raises(ValueError, match="zone_component_key"):
        build_guadeloupe_hydraulic_zones._zone_style_categories(gdf)


def test_build_zone_polygons_requires_zone_component_key() -> None:
    lines = gpd.GeoDataFrame(
        {
            "zone_uid": ["AEP_001"],
            "zone_label": ["Zone 1"],
            "zone_name": ["Zone 1"],
            "zone_color": ["#123456"],
            "network_kind": ["AEP"],
            "zone_basis": ["source_field"],
            "zone_basis_note": ["manual"],
            "zone_confidence": [0.98],
            "line_length_m": [100.0],
        },
        geometry=[LineString([(0.0, 0.0), (0.0, 1.0)])],
        crs="EPSG:4326",
    )
    assets = gpd.GeoDataFrame(
        {
            "zone_component_key": pd.Series(dtype="object"),
            "zone_uid": pd.Series(dtype="object"),
            "method": pd.Series(dtype="object"),
            "confidence": pd.Series(dtype="float64"),
        },
        geometry=gpd.GeoSeries([], crs="EPSG:4326"),
        crs="EPSG:4326",
    )

    with pytest.raises(ValueError, match="zone_component_key"):
        build_guadeloupe_hydraulic_zones._build_zone_polygons(lines, assets)