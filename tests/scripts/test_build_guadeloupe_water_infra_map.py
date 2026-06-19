from __future__ import annotations

from pathlib import Path
import sys

import geopandas as gpd
import pytest
from shapely.geometry import Point, Polygon


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from scripts import build_guadeloupe_water_infra_map


def test_load_hydraulic_zone_layer_uses_zone_component_keys(monkeypatch) -> None:
    hydraulic_gdf = gpd.GeoDataFrame(
        {
            "zone_component_key": ["AEP_001__P1", "EU_001__P1"],
            "network_kind": ["AEP", "EU"],
        },
        geometry=[
            Polygon([(0.0, 0.0), (0.1, 0.0), (0.1, 0.1), (0.0, 0.1)]),
            Polygon([(0.2, 0.2), (0.3, 0.2), (0.3, 0.3), (0.2, 0.3)]),
        ],
        crs="EPSG:4326",
    )

    def _fake_read_file(path: Path, layer: str | None = None):
        assert Path(path).name == "hydraulic.gpkg"
        assert layer == "hydraulic_zones"
        return hydraulic_gdf.copy()

    monkeypatch.setattr(
        build_guadeloupe_water_infra_map,
        "gpd",
        type("_FakeGpd", (), {"read_file": staticmethod(_fake_read_file), "GeoDataFrame": gpd.GeoDataFrame})(),
    )
    monkeypatch.setattr(build_guadeloupe_water_infra_map, "_clip_case_gdf", lambda gdf, cfg: gdf)

    out = build_guadeloupe_water_infra_map._load_hydraulic_zone_layer(
        Path("hydraulic.gpkg"),
        {},
        layer="hydraulic_zones",
    )

    assert out["feature_id"].tolist() == ["AEP_001__P1", "EU_001__P1"]
    assert out["infra_type"].tolist() == ["aep_cana", "eu_cana"]
    assert out["service_unit_kind"].tolist() == ["hydraulic_zone_component", "hydraulic_zone_component"]


def test_load_hydraulic_asset_layer_maps_roles_to_public_infra_types(monkeypatch) -> None:
    hydraulic_gdf = gpd.GeoDataFrame(
        {
            "feature_id": ["asset-pr-1", "asset-cap-1"],
            "source_feature_id": ["src-pr-1", "src-cap-1"],
            "zone_component_key": ["EU_001__P1", "AEP_001__P1"],
            "network_kind": ["EU", "AEP"],
            "feature_role": ["poste_refoulement", "captage_aep"],
            "criticality": ["essential", "essential"],
        },
        geometry=[Point(0.0, 0.0), Point(0.1, 0.1)],
        crs="EPSG:4326",
    )

    def _fake_read_file(path: Path, layer: str | None = None):
        assert Path(path).name == "hydraulic.gpkg"
        assert layer == "hydraulic_assets"
        return hydraulic_gdf.copy()

    monkeypatch.setattr(
        build_guadeloupe_water_infra_map,
        "gpd",
        type("_FakeGpd", (), {"read_file": staticmethod(_fake_read_file), "GeoDataFrame": gpd.GeoDataFrame})(),
    )
    monkeypatch.setattr(build_guadeloupe_water_infra_map, "_clip_case_gdf", lambda gdf, cfg: gdf)

    out = build_guadeloupe_water_infra_map._load_hydraulic_asset_layer(
        Path("hydraulic.gpkg"),
        {},
        layer="hydraulic_assets",
    )

    assert out["feature_id"].tolist() == ["asset-pr-1", "asset-cap-1"]
    assert out["infra_type"].tolist() == ["eu_pr", "aep_ouvrage"]
    assert out["zone_component_key"].tolist() == ["EU_001__P1", "AEP_001__P1"]
    assert out["criticality"].tolist() == ["essential", "essential"]


def test_load_hydraulic_asset_layer_falls_back_for_unassigned_assets(monkeypatch) -> None:
    hydraulic_gdf = gpd.GeoDataFrame(
        {
            "feature_id": ["eu-step-43"],
            "source_feature_id": ["943"],
            "zone_component_key": [None],
            "zone_uid": [None],
            "network_kind": ["EU"],
            "feature_role": ["step"],
            "criticality": ["essential"],
        },
        geometry=[Point(0.0, 0.0)],
        crs="EPSG:4326",
    )

    def _fake_read_file(path: Path, layer: str | None = None):
        assert Path(path).name == "hydraulic.gpkg"
        assert layer == "hydraulic_assets"
        return hydraulic_gdf.copy()

    monkeypatch.setattr(
        build_guadeloupe_water_infra_map,
        "gpd",
        type("_FakeGpd", (), {"read_file": staticmethod(_fake_read_file), "GeoDataFrame": gpd.GeoDataFrame})(),
    )
    monkeypatch.setattr(build_guadeloupe_water_infra_map, "_clip_case_gdf", lambda gdf, cfg: gdf)

    out = build_guadeloupe_water_infra_map._load_hydraulic_asset_layer(
        Path("hydraulic.gpkg"),
        {},
        layer="hydraulic_assets",
    )

    assert out["feature_id"].tolist() == ["eu-step-43"]
    assert out["infra_type"].tolist() == ["eu_step"]
    assert out["zone_component_key"].tolist() == ["hydraulic-native:eu-step-43"]
    assert out["service_unit_kind"].tolist() == ["native_feature"]


def test_load_hydraulic_asset_layer_falls_back_to_zone_uid_for_legacy_assigned_assets(monkeypatch) -> None:
    hydraulic_gdf = gpd.GeoDataFrame(
        {
            "feature_id": ["martinique-step-13"],
            "source_feature_id": ["src-step-13"],
            "zone_component_key": [None],
            "zone_uid": ["EU_080000797213"],
            "network_kind": ["EU"],
            "feature_role": ["step"],
            "criticality": ["essential"],
        },
        geometry=[Point(0.0, 0.0)],
        crs="EPSG:4326",
    )

    def _fake_read_file(path: Path, layer: str | None = None):
        assert Path(path).name == "hydraulic.gpkg"
        assert layer == "hydraulic_assets"
        return hydraulic_gdf.copy()

    monkeypatch.setattr(
        build_guadeloupe_water_infra_map,
        "gpd",
        type("_FakeGpd", (), {"read_file": staticmethod(_fake_read_file), "GeoDataFrame": gpd.GeoDataFrame})(),
    )
    monkeypatch.setattr(build_guadeloupe_water_infra_map, "_clip_case_gdf", lambda gdf, cfg: gdf)

    out = build_guadeloupe_water_infra_map._load_hydraulic_asset_layer(
        Path("hydraulic.gpkg"),
        {},
        layer="hydraulic_assets",
    )

    assert out["feature_id"].tolist() == ["martinique-step-13"]
    assert out["infra_type"].tolist() == ["eu_step"]
    assert out["zone_component_key"].tolist() == ["EU_080000797213"]
    assert out["service_unit_kind"].tolist() == ["hydraulic_zone_uid_legacy"]


def test_load_hydraulic_zone_layer_requires_zone_component_key(monkeypatch) -> None:
    hydraulic_gdf = gpd.GeoDataFrame(
        {
            "zone_component_key": [""],
            "network_kind": ["AEP"],
        },
        geometry=[Polygon([(0.0, 0.0), (0.1, 0.0), (0.1, 0.1), (0.0, 0.1)])],
        crs="EPSG:4326",
    )

    def _fake_read_file(path: Path, layer: str | None = None):
        assert layer == "hydraulic_zones"
        return hydraulic_gdf.copy()

    monkeypatch.setattr(
        build_guadeloupe_water_infra_map,
        "gpd",
        type("_FakeGpd", (), {"read_file": staticmethod(_fake_read_file), "GeoDataFrame": gpd.GeoDataFrame})(),
    )
    monkeypatch.setattr(build_guadeloupe_water_infra_map, "_clip_case_gdf", lambda gdf, cfg: gdf)

    with pytest.raises(ValueError, match="zone_component_key"):
        build_guadeloupe_water_infra_map._load_hydraulic_zone_layer(
            Path("hydraulic.gpkg"),
            {},
            layer="hydraulic_zones",
        )