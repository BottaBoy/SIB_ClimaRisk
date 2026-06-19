from __future__ import annotations

from pathlib import Path
import sys

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from scripts import build_guadeloupe_complete_analysis


def test_hydraulic_line_features_attach_service_metadata() -> None:
    gdf = gpd.GeoDataFrame(
        {
            "feature_id": ["hyd-line-1"],
            "source_feature_id": ["src-line-1"],
            "network_kind": ["AEP"],
            "feature_role": ["canalisation"],
            "zone_uid": ["AEP_001"],
            "zone_component_key": ["AEP_001__P1"],
            "zone_component_label": ["Zone AEP 1"],
        },
        geometry=[LineString([(0.0, 0.0), (0.0, 0.01)])],
        crs="EPSG:4326",
    )

    features = build_guadeloupe_complete_analysis._hydraulic_line_features(
        gdf,
        water_values={"eau_aep": 1000.0, "eau_eu": 2000.0, "eau_eu_pr": 300.0, "eau_eu_step": 400.0},
        context="unit-test-lines",
    )

    feature = features[0]
    assert feature.feature_id == "hyd-line-1"
    assert feature.properties["asset_type"] == "eau_aep_cana"
    assert feature.properties["zone_component_key"] == "AEP_001__P1"
    assert feature.properties["service_feature_id"] == "AEP_001__P1"
    assert feature.properties["feature_role"] == "canalisation"
    assert feature.properties["hydraulic_service_key_source"] == "zone_component_key"
    assert feature.properties["service_unit_kind"] == "hydraulic_zone_component"


def test_hydraulic_line_features_fallback_to_native_service_key_when_unassigned() -> None:
    gdf = gpd.GeoDataFrame(
        {
            "feature_id": ["aep-line-2454"],
            "source_feature_id": ["62119"],
            "network_kind": ["AEP"],
            "feature_role": ["canalisation"],
            "zone_uid": [None],
            "zone_component_key": [None],
            "zone_component_label": [None],
        },
        geometry=[LineString([(0.0, 0.0), (0.0, 0.01)])],
        crs="EPSG:4326",
    )

    features = build_guadeloupe_complete_analysis._hydraulic_line_features(
        gdf,
        water_values={"eau_aep": 1000.0, "eau_eu": 2000.0, "eau_eu_pr": 300.0, "eau_eu_step": 400.0},
        context="unit-test-lines",
    )

    feature = features[0]
    assert feature.label == "eau_aep_cana 62119"
    assert feature.properties["zone_component_key"] == "hydraulic-native:aep-line-2454"
    assert feature.properties["service_feature_id"] == "hydraulic-native:aep-line-2454"
    assert feature.properties["hydraulic_service_key_source"] == "feature_id_fallback"
    assert feature.properties["service_unit_kind"] == "native_feature"


def test_hydraulic_line_features_stay_strict_for_assigned_rows_without_zone_component_key() -> None:
    gdf = gpd.GeoDataFrame(
        {
            "feature_id": ["hyd-line-1"],
            "network_kind": ["AEP"],
            "feature_role": ["canalisation"],
            "zone_uid": ["AEP_001"],
            "zone_component_key": [None],
        },
        geometry=[LineString([(0.0, 0.0), (0.0, 0.01)])],
        crs="EPSG:4326",
    )

    with pytest.raises(ValueError, match="assigned hydraulic feature hyd-line-1"):
        build_guadeloupe_complete_analysis._hydraulic_line_features(
            gdf,
            water_values={"eau_aep": 1000.0, "eau_eu": 2000.0, "eau_eu_pr": 300.0, "eau_eu_step": 400.0},
            context="unit-test-lines",
        )


def test_hydraulic_asset_features_map_blocking_roles_to_asset_types() -> None:
    gdf = gpd.GeoDataFrame(
        {
            "feature_id": ["hyd-asset-1", "hyd-asset-2"],
            "source_feature_id": ["src-pr-1", "src-cap-1"],
            "network_kind": ["EU", "AEP"],
            "feature_role": ["poste_refoulement", "captage_aep"],
            "criticality": ["essential", "essential"],
            "asset_type_code": ["PR", "CAP"],
            "asset_name": ["PR 1", "Captage 1"],
            "zone_uid": ["EU_001", "AEP_001"],
            "zone_component_key": ["EU_001__P1", "AEP_001__P1"],
        },
        geometry=[Point(0.0, 0.0), Point(0.01, 0.01)],
        crs="EPSG:4326",
    )

    features = build_guadeloupe_complete_analysis._hydraulic_asset_features(
        gdf,
        territory="guadeloupe",
        water_values={"eau_aep": 1.0, "eau_eu": 2.0, "eau_eu_pr": 300.0, "eau_eu_step": 400.0},
        context="unit-test-assets",
    )

    asset_types = [feature.properties["asset_type"] for feature in features]
    assert asset_types == ["eau_eu_pr", "eau_aep_ouvrage_CAP"]
    assert features[0].value_eur == pytest.approx(300.0)
    assert features[1].properties["service_feature_id"] == "AEP_001__P1"
    assert features[1].properties["criticality"] == "essential"


def test_hydraulic_asset_features_fallback_to_zone_uid_for_legacy_assigned_assets() -> None:
    gdf = gpd.GeoDataFrame(
        {
            "feature_id": ["martinique-pr-171"],
            "source_feature_id": ["src-pr-171"],
            "network_kind": ["EU"],
            "feature_role": ["poste_refoulement"],
            "criticality": ["essential"],
            "asset_type_code": ["PR"],
            "asset_name": ["La Michele 1"],
            "zone_uid": ["EU_080000497206"],
            "zone_component_key": [None],
        },
        geometry=[Point(0.0, 0.0)],
        crs="EPSG:4326",
    )

    features = build_guadeloupe_complete_analysis._hydraulic_asset_features(
        gdf,
        territory="guadeloupe",
        water_values={"eau_aep": 1.0, "eau_eu": 2.0, "eau_eu_pr": 300.0, "eau_eu_step": 400.0},
        context="unit-test-assets",
    )

    feature = features[0]
    assert feature.properties["zone_component_key"] == "EU_080000497206"
    assert feature.properties["service_feature_id"] == "EU_080000497206"
    assert feature.properties["hydraulic_service_key_source"] == "zone_uid_fallback"
    assert feature.properties["service_unit_kind"] == "hydraulic_zone_uid_legacy"
