from __future__ import annotations

import json
from pathlib import Path
import sys
import types

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString, Point, Polygon


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

try:
    import shapely.geometry  # noqa: F401
except Exception:
    shapely_module = types.ModuleType("shapely")
    shapely_geometry_module = types.ModuleType("shapely.geometry")
    shapely_geometry_module.box = lambda *args, **kwargs: None
    shapely_module.geometry = shapely_geometry_module
    sys.modules.setdefault("shapely", shapely_module)
    sys.modules.setdefault("shapely.geometry", shapely_geometry_module)

from scripts import build_guadeloupe_page1_data


def test_extract_complete_analysis_public_loss_targets_maps_public_scenarios() -> None:
    payload = {
        "portfolio_results": {
            "storm": {
                "eai_eur": 12.5,
                "pml_10_eur": 20.0,
                "pml_50_eur": 40.0,
                "pml_100_eur": 60.0,
                "pml_1000_eur": 100.0,
                "percentile_99_loss_eur": 80.0,
            }
        }
    }

    assert build_guadeloupe_page1_data._extract_complete_analysis_public_loss_targets(payload, "storm") == {
        "annual": 12.5,
        "rp10": 20.0,
        "rp50": 40.0,
        "rp100": 60.0,
        "rp1000": 100.0,
        "event_max": 80.0,
    }


def test_calibrate_scenario_results_to_complete_analysis_hits_requested_totals() -> None:
    values = np.array([100.0, 100.0, 100.0], dtype=float)
    mask = np.array([True, True, True], dtype=bool)
    scenario_results = {
        "annual": {
            "total_loss": np.array([5.0, 10.0, 0.0], dtype=float),
            "direct_loss": np.array([4.0, 8.0, 0.0], dtype=float),
        },
        "rp50": {
            "total_loss": np.array([10.0, 20.0, 0.0], dtype=float),
            "direct_loss": np.array([8.0, 16.0, 0.0], dtype=float),
        },
        "rp100": {
            "total_loss": np.array([12.0, 30.0, 0.0], dtype=float),
            "direct_loss": np.array([10.0, 24.0, 0.0], dtype=float),
        },
        "event_max": {
            "total_loss": np.array([15.0, 35.0, 0.0], dtype=float),
            "direct_loss": np.array([12.0, 28.0, 0.0], dtype=float),
        },
    }

    applied = build_guadeloupe_page1_data._calibrate_scenario_results_to_complete_analysis(
        scenario_results,
        values=values,
        all_infra_mask=mask,
        target_totals={
            "annual": 30.0,
            "rp50": 45.0,
            "rp100": 70.0,
            "event_max": 90.0,
        },
    )

    assert applied["rp50"]["pre_calibration_total_eur"] == 30.0
    assert scenario_results["annual"]["total_loss"].sum() == pytest.approx(30.0)
    assert scenario_results["rp50"]["total_loss"].sum() == pytest.approx(45.0)
    assert scenario_results["rp100"]["total_loss"].sum() == pytest.approx(70.0)
    assert scenario_results["event_max"]["total_loss"].sum() == pytest.approx(90.0)
    assert np.all(scenario_results["event_max"]["direct_loss"] <= scenario_results["event_max"]["total_loss"])


def test_recalculate_calibrated_scenario_states_refreshes_state_fields_from_direct_loss() -> None:
    scenario_results = {
        "rp50": {
            "total_loss": np.array([40.0, 5.0], dtype=float),
            "direct_loss": np.array([40.0, 5.0], dtype=float),
            "direct_state": np.array(["S0", "S0"], dtype=object),
            "final_state": np.array(["S0", "S0"], dtype=object),
            "indirect_s3_flag": np.array([False, False], dtype=bool),
        },
        "rp100": {
            "total_loss": np.array([10.0, 1.0], dtype=float),
            "direct_loss": np.array([10.0, 1.0], dtype=float),
            "direct_state": np.array(["S1", "S0"], dtype=object),
            "final_state": np.array(["S1", "S0"], dtype=object),
            "indirect_s3_flag": np.array([False, False], dtype=bool),
        },
    }

    def _fake_evaluator(direct_loss: np.ndarray) -> dict[str, np.ndarray]:
        severe = bool(float(np.asarray(direct_loss, dtype=float).sum()) >= 40.0)
        state_code = "S3" if severe else "S1"
        return {
            "direct_state": np.array([state_code, "S0"], dtype=object),
            "final_state": np.array([state_code, "S0"], dtype=object),
            "indirect_s3_flag": np.array([severe, False], dtype=bool),
        }

    build_guadeloupe_page1_data._recalculate_calibrated_scenario_states(
        scenario_results,
        scenario_keys=("rp50",),
        values_size=2,
        evaluator=_fake_evaluator,
    )

    assert scenario_results["rp50"]["direct_state"].tolist() == ["S3", "S0"]
    assert scenario_results["rp50"]["final_state"].tolist() == ["S3", "S0"]
    assert scenario_results["rp50"]["indirect_s3_flag"].tolist() == [True, False]
    assert scenario_results["rp100"]["direct_state"].tolist() == ["S1", "S0"]


def test_build_state_geojson_rejects_incomplete_feature_states(tmp_path: Path) -> None:
    geometry_features = [
        {"feature_id": "f1", "class_key": "eau_aep", "class_label": "Eau AEP", "geometry": {"id": 1}},
        {"feature_id": "f2", "class_key": "eau_eu", "class_label": "Eau EU", "geometry": {"id": 2}},
    ]
    hazard_feature_states = {
        hazard_key: {
            scenario: ({"f1": "S1"} if scenario == "annual" and hazard_key == "storm" else {"f1": "S1", "f2": "S0"})
            for scenario in build_guadeloupe_page1_data.PUBLIC_MAP_SCENARIOS
        }
        for hazard_key in ("storm", "storm_cmcc")
    }

    with pytest.raises(RuntimeError, match=r"Incomplete feature states for storm\.annual"):
        build_guadeloupe_page1_data._build_state_geojson(
            geometry_features,
            hazard_feature_states,
            tmp_path / "network-states.geojson",
        )


def test_build_state_geojson_writes_complete_feature_states(monkeypatch, tmp_path: Path) -> None:
    class _FakeGeoDataFrame:
        def __init__(self, rows, geometry=None, crs=None):
            self._rows = rows
            self._geometry = geometry
            self._crs = crs

        def to_json(self) -> str:
            return json.dumps(
                {
                    "rows": self._rows,
                    "geometry_count": len(self._geometry or []),
                    "crs": self._crs,
                },
                ensure_ascii=False,
            )

    monkeypatch.setattr(
        build_guadeloupe_page1_data,
        "gpd",
        type("_FakeGpd", (), {"GeoDataFrame": _FakeGeoDataFrame})(),
    )
    geometry_features = [
        {
            "feature_id": "f1",
            "class_key": "eau_aep",
            "class_label": "Eau AEP",
            "geometry": {"id": 1},
            "service_feature_id": "AEP_001__P1",
            "zone_component_key": "AEP_001__P1",
            "zone_uid": "AEP_001",
            "network_kind": "AEP",
            "feature_role": "canalisation",
        },
        {
            "feature_id": "f2",
            "class_key": "eau_eu",
            "class_label": "Eau EU",
            "geometry": {"id": 2},
            "service_feature_id": "EU_001__P1",
            "zone_component_key": "EU_001__P1",
            "zone_uid": "EU_001",
            "network_kind": "EU",
            "feature_role": "canalisation",
        },
    ]
    hazard_feature_states = {
        hazard_key: {
            scenario: {"AEP_001__P1": "S1", "EU_001__P1": "S2"}
            for scenario in build_guadeloupe_page1_data.PUBLIC_MAP_SCENARIOS
        }
        for hazard_key in ("storm", "storm_cmcc")
    }
    out_path = tmp_path / "network-states.geojson"

    build_guadeloupe_page1_data._build_state_geojson(
        geometry_features,
        hazard_feature_states,
        out_path,
    )

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    rows = {row["feature_id"]: row for row in payload["rows"]}

    assert payload["geometry_count"] == 2
    assert payload["crs"] == build_guadeloupe_page1_data.WGS84
    assert payload["metadata"]["state_geometry_mode"] == "native_network_geometry"
    assert payload["metadata"]["schema_version"] == "aggregated_service_state_v1"
    assert payload["metadata"]["aggregation_method"] == "aggregated_service_state"
    assert payload["metadata"]["geometry_semantics"] == "native_service_geometry"
    assert payload["metadata"]["methodology_breaks_comparability"] is True
    assert rows["f1"]["service_feature_id"] == "AEP_001__P1"
    assert rows["f1"]["zone_component_key"] == "AEP_001__P1"
    assert rows["f1"]["zone_uid"] == "AEP_001"
    assert rows["f1"]["network_kind"] == "AEP"
    assert rows["f1"]["feature_role"] == "canalisation"
    assert rows["f1"]["state_annual_storm"] == "S1"
    assert rows["f1"]["state_rp10_storm"] == "S1"
    assert rows["f1"]["state_rp1000_storm"] == "S1"
    assert rows["f1"]["cause_rp10_storm"] == "direct_damage"
    assert rows["f2"]["state_p99_storm_cmcc"] == "S2"
    assert rows["f2"]["cause_rp1000_storm_cmcc"] == "direct_damage"


def test_build_network_geometry_features_uses_hydraulic_water_zones_and_electric_lines(monkeypatch) -> None:
    elec_gdf = gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[LineString([(0.0, 0.0), (0.0, 0.1)])],
        crs="EPSG:4326",
    )
    hydraulic_gdf = gpd.GeoDataFrame(
        {
            "zone_component_key": ["AEP_001__P1", "EU_001__P1"],
            "zone_uid": ["AEP_001", "EU_001"],
            "network_kind": ["AEP", "EU"],
        },
        geometry=[
            Polygon([(0.0, 0.0), (0.1, 0.0), (0.1, 0.1), (0.0, 0.1)]),
            Polygon([(0.2, 0.2), (0.3, 0.2), (0.3, 0.3), (0.2, 0.3)]),
        ],
        crs="EPSG:4326",
    )
    hydraulic_lines_gdf = gpd.GeoDataFrame(
        {
            "feature_id": ["aep-line-legacy-1"],
            "source_feature_id": ["src-line-legacy-1"],
            "zone_component_key": [None],
            "zone_uid": [None],
            "network_kind": ["AEP"],
        },
        geometry=[LineString([(0.4, 0.4), (0.45, 0.45)])],
        crs="EPSG:4326",
    )
    hydraulic_assets_gdf = gpd.GeoDataFrame(
        {
            "feature_id": ["aep-asset-1", "eu-pr-1", "eu-step-1"],
            "source_feature_id": ["src-aep-1", "src-pr-1", "src-step-1"],
            "network_kind": ["AEP", "EU", "EU"],
            "feature_role": ["captage_aep", "poste_refoulement", "step"],
        },
        geometry=[Point(0.05, 0.05), Point(0.25, 0.25), Point(0.27, 0.27)],
        crs="EPSG:4326",
    )

    def _fake_read_file(path: Path, layer: str | None = None):
        name = Path(path).name
        if name == "elec-lines.gpkg":
            return elec_gdf.copy()
        if name == "hydraulic.gpkg" and layer == "hydraulic_zones":
            return hydraulic_gdf.copy()
        if name == "hydraulic.gpkg" and layer == "hydraulic_lines":
            return hydraulic_lines_gdf.copy()
        if name == "hydraulic.gpkg" and layer == "hydraulic_assets":
            return hydraulic_assets_gdf.copy()
        raise AssertionError(f"Unexpected read_file call: path={path} layer={layer}")

    monkeypatch.setattr(
        build_guadeloupe_page1_data,
        "gpd",
        type("_FakeGpd", (), {"read_file": staticmethod(_fake_read_file), "GeoDataFrame": gpd.GeoDataFrame})(),
    )
    monkeypatch.setattr(
        build_guadeloupe_page1_data,
        "_read_vector",
        lambda path, layer=None, source_crs=None: _fake_read_file(path, layer),
    )
    monkeypatch.setattr(build_guadeloupe_page1_data, "_ensure_crs", lambda gdf: gdf)
    monkeypatch.setattr(build_guadeloupe_page1_data, "_clip_case_gdf", lambda gdf, cfg: gdf)

    case_cfg = {
        "network_geometry_sources": [
            {"class_key": "elec_bt_aerien", "prefix": "elec-bt-aerien", "paths": [Path("elec-lines.gpkg")]},
            {"class_key": "eau_aep", "prefix": "aep-cana", "paths": [Path("unused-water-lines.gpkg")]},
        ],
        "hydraulic_zone_sources": [
            {"path": Path("hydraulic.gpkg"), "zone_layer": "hydraulic_zones", "line_layer": "hydraulic_lines", "asset_layer": "hydraulic_assets"},
        ],
    }

    features = build_guadeloupe_page1_data._build_network_geometry_features(case_cfg)

    assert [feature["feature_id"] for feature in features] == [
        "elec-bt-aerien-1-1",
        "AEP_001__P1",
        "EU_001__P1",
        "hydraulic-native:aep-line-legacy-1",
        "aep-asset-1",
        "eu-pr-1",
        "eu-step-1",
    ]
    assert [feature["class_key"] for feature in features] == [
        "elec_bt_aerien",
        "eau_aep",
        "eau_eu",
        "eau_aep",
        "eau_aep_ouvrages",
        "eau_eu_pr",
        "eau_eu_step",
    ]
    assert [feature["state_geometry_mode"] for feature in features] == [
        "native_network_geometry",
        "hydraulic_zoning_v2",
        "hydraulic_zoning_v2",
        "native_network_geometry",
        "native_network_geometry",
        "native_network_geometry",
        "native_network_geometry",
    ]
    assert [feature["service_unit_kind"] for feature in features] == [
        "native_feature",
        "hydraulic_zone_component",
        "hydraulic_zone_component",
        "native_feature",
        "native_feature",
        "native_feature",
        "native_feature",
    ]
    assert [feature["service_feature_id"] for feature in features] == [
        "",
        "AEP_001__P1",
        "EU_001__P1",
        "hydraulic-native:aep-line-legacy-1",
        "hydraulic-native:aep-asset-1",
        "hydraulic-native:eu-pr-1",
        "hydraulic-native:eu-step-1",
    ]
    assert [feature["zone_component_key"] for feature in features] == [
        "",
        "AEP_001__P1",
        "EU_001__P1",
        "hydraulic-native:aep-line-legacy-1",
        "hydraulic-native:aep-asset-1",
        "hydraulic-native:eu-pr-1",
        "hydraulic-native:eu-step-1",
    ]
    assert [feature["network_kind"] for feature in features] == [
        "",
        "AEP",
        "EU",
        "AEP",
        "AEP",
        "EU",
        "EU",
    ]
    assert [feature["feature_role"] for feature in features] == [
        "",
        "canalisation",
        "canalisation",
        "canalisation",
        "captage_aep",
        "poste_refoulement",
        "step",
    ]


def test_build_network_geometry_features_falls_back_to_service_lines_when_zone_ids_do_not_match(monkeypatch) -> None:
    hydraulic_gdf = gpd.GeoDataFrame(
        {
            "zone_component_key": ["AEP_COMP_001", "AEP_COMP_002"],
            "zone_uid": ["AEP_COMP_001", "AEP_COMP_002"],
            "network_kind": ["AEP", "AEP"],
        },
        geometry=[
            Polygon([(0.0, 0.0), (0.1, 0.0), (0.1, 0.1), (0.0, 0.1)]),
            Polygon([(0.2, 0.0), (0.3, 0.0), (0.3, 0.1), (0.2, 0.1)]),
        ],
        crs="EPSG:4326",
    )
    hydraulic_lines_gdf = gpd.GeoDataFrame(
        {
            "feature_id": ["aep-line-1", "aep-line-2"],
            "source_feature_id": ["src-aep-1", "src-aep-2"],
            "zone_component_key": ["AEP_SECT_001", "AEP_SECT_002"],
            "zone_uid": ["AEP_SECT_001", "AEP_SECT_002"],
            "network_kind": ["AEP", "AEP"],
            "feature_role": ["canalisation", "canalisation"],
        },
        geometry=[
            LineString([(0.0, 0.0), (0.1, 0.1)]),
            LineString([(0.2, 0.0), (0.3, 0.1)]),
        ],
        crs="EPSG:4326",
    )
    hydraulic_assets_gdf = gpd.GeoDataFrame(
        {
            "feature_id": [],
            "source_feature_id": [],
            "network_kind": [],
            "feature_role": [],
        },
        geometry=[],
        crs="EPSG:4326",
    )

    def _fake_read_file(path: Path, layer: str | None = None):
        if layer == "hydraulic_zones":
            return hydraulic_gdf.copy()
        if layer == "hydraulic_lines":
            return hydraulic_lines_gdf.copy()
        if layer == "hydraulic_assets":
            return hydraulic_assets_gdf.copy()
        raise AssertionError(f"Unexpected read_file call: path={path} layer={layer}")

    monkeypatch.setattr(
        build_guadeloupe_page1_data,
        "gpd",
        type("_FakeGpd", (), {"read_file": staticmethod(_fake_read_file), "GeoDataFrame": gpd.GeoDataFrame})(),
    )
    monkeypatch.setattr(
        build_guadeloupe_page1_data,
        "_read_vector",
        lambda path, layer=None, source_crs=None: _fake_read_file(path, layer),
    )
    monkeypatch.setattr(build_guadeloupe_page1_data, "_ensure_crs", lambda gdf: gdf)
    monkeypatch.setattr(build_guadeloupe_page1_data, "_clip_case_gdf", lambda gdf, cfg: gdf)

    case_cfg = {
        "network_geometry_sources": [],
        "hydraulic_zone_sources": [
            {"path": Path("hydraulic.gpkg"), "zone_layer": "hydraulic_zones", "line_layer": "hydraulic_lines", "asset_layer": "hydraulic_assets"},
        ],
    }

    features = build_guadeloupe_page1_data._build_network_geometry_features(case_cfg)

    assert [feature["feature_id"] for feature in features] == ["AEP_SECT_001", "AEP_SECT_002"]
    assert [feature["service_feature_id"] for feature in features] == ["AEP_SECT_001", "AEP_SECT_002"]
    assert [feature["state_geometry_mode"] for feature in features] == ["hydraulic_zoning_v2", "hydraulic_zoning_v2"]


def test_build_network_geometry_features_falls_back_to_zone_uid_for_legacy_hydraulic_assets(monkeypatch) -> None:
    hydraulic_zones_gdf = gpd.GeoDataFrame(
        {
            "zone_component_key": [],
            "zone_uid": [],
            "network_kind": [],
        },
        geometry=[],
        crs="EPSG:4326",
    )
    hydraulic_lines_gdf = gpd.GeoDataFrame(
        {
            "feature_id": [],
            "source_feature_id": [],
            "zone_component_key": [],
            "zone_uid": [],
            "network_kind": [],
            "feature_role": [],
        },
        geometry=[],
        crs="EPSG:4326",
    )
    hydraulic_assets_gdf = gpd.GeoDataFrame(
        {
            "feature_id": ["martinique-pr-171"],
            "source_feature_id": ["src-pr-171"],
            "network_kind": ["EU"],
            "feature_role": ["poste_refoulement"],
            "zone_component_key": [None],
            "zone_uid": ["EU_080000497206"],
        },
        geometry=[Point(0.25, 0.25)],
        crs="EPSG:4326",
    )

    def _fake_read_file(path: Path, layer: str | None = None):
        if layer == "hydraulic_zones":
            return hydraulic_zones_gdf.copy()
        if layer == "hydraulic_lines":
            return hydraulic_lines_gdf.copy()
        if layer == "hydraulic_assets":
            return hydraulic_assets_gdf.copy()
        raise AssertionError(f"Unexpected read_file call: path={path} layer={layer}")

    monkeypatch.setattr(
        build_guadeloupe_page1_data,
        "gpd",
        type("_FakeGpd", (), {"read_file": staticmethod(_fake_read_file), "GeoDataFrame": gpd.GeoDataFrame})(),
    )
    monkeypatch.setattr(
        build_guadeloupe_page1_data,
        "_read_vector",
        lambda path, layer=None, source_crs=None: _fake_read_file(path, layer),
    )
    monkeypatch.setattr(build_guadeloupe_page1_data, "_ensure_crs", lambda gdf: gdf)
    monkeypatch.setattr(build_guadeloupe_page1_data, "_clip_case_gdf", lambda gdf, cfg: gdf)

    case_cfg = {
        "network_geometry_sources": [],
        "hydraulic_zone_sources": [
            {
                "path": Path("hydraulic.gpkg"),
                "zone_layer": "hydraulic_zones",
                "line_layer": "hydraulic_lines",
                "asset_layer": "hydraulic_assets",
            },
        ],
    }

    features = build_guadeloupe_page1_data._build_network_geometry_features(case_cfg)

    assert len(features) == 1
    assert features[0]["feature_id"] == "martinique-pr-171"
    assert features[0]["service_feature_id"] == "EU_080000497206"
    assert features[0]["zone_component_key"] == "EU_080000497206"
    assert features[0]["service_unit_kind"] == "hydraulic_zone_uid_legacy"


def test_overlay_complete_analysis_service_states_on_public_map_promotes_p99_water_states() -> None:
    geometry_features = [
        {"feature_id": "AEP_SECT_001", "class_key": "eau_aep", "service_feature_id": "AEP_SECT_001"},
        {"feature_id": "EU_COMP_001", "class_key": "eau_eu", "service_feature_id": "EU_COMP_001"},
        {"feature_id": "cell-1", "class_key": "elec_grid_0p1deg", "service_feature_id": ""},
    ]
    hazard_feature_states = {
        hazard_key: {
            scenario: {
                "AEP_SECT_001": "S0",
                "EU_COMP_001": "S0",
                "cell-1": "S0",
            }
            for scenario in build_guadeloupe_page1_data.PUBLIC_MAP_SCENARIOS
        }
        for hazard_key in ("storm", "storm_cmcc")
    }
    complete_analysis_payload = {
        "territory_results": [
            {
                "network_states_native": {
                    "storm": {
                        "water_aep": {"service_unit_id": "AEP_SECT_001", "state": "S2"},
                        "water_eu": {"service_unit_id": "EU_COMP_001", "state": "S1"},
                    },
                    "storm_cmcc": {
                        "water_aep": {"service_unit_id": "AEP_SECT_001", "state": "S3"},
                        "water_eu": {"service_unit_id": "EU_COMP_001", "state": "S2"},
                    },
                }
            }
        ]
    }

    build_guadeloupe_page1_data._overlay_complete_analysis_service_states_on_public_map(
        geometry_features,
        hazard_feature_states,
        complete_analysis_payload=complete_analysis_payload,
    )

    assert hazard_feature_states["storm"]["p99"]["AEP_SECT_001"] == "S2"
    assert hazard_feature_states["storm"]["top10"]["EU_COMP_001"] == "S1"
    assert hazard_feature_states["storm_cmcc"]["top5"]["AEP_SECT_001"] == "S3"
    assert hazard_feature_states["storm"]["annual"]["AEP_SECT_001"] == "S0"


def test_aggregate_native_service_states_keeps_hydraulic_native_step_assets() -> None:
    bundle = build_guadeloupe_page1_data.ClimadaExposureBundle(
        exposures=None,
        point_records=[
            {
                "asset_type": "eau_eu_step",
                "feature_id": "eu-step-43",
                "service_feature_id": "hydraulic-native:eu-step-43",
                "territory_id": "cell-+16.00_-61.80",
                "lat": 16.0,
                "lon": -61.8,
                "infra_class": "eau_ouvrage",
                "feature_role": "step",
            }
        ],
        metric_crs="EPSG:3857",
        warnings=[],
    )
    hazard_outputs = {
        hazard_key: {
            "scenario_results": {
                scenario: {
                    "total_loss": np.array([20.0]),
                    "direct_state": np.array(["S2"], dtype=object),
                    "final_state": np.array(["S2"], dtype=object),
                }
                for scenario in build_guadeloupe_page1_data.MAP_SCENARIOS
            }
        }
        for hazard_key in ("storm", "storm_cmcc")
    }

    native_states, native_causes, electric_unit_ids = build_guadeloupe_page1_data._aggregate_native_service_states_for_public_map(
        bundle=bundle,
        values=np.array([100.0]),
        class_keys=[None],
        water_service_classes=["eau_eu"],
        service_feature_ids=["hydraulic-native:eu-step-43"],
        is_blocking_asset=[True],
        weights_km=np.array([0.0]),
        hazard_outputs=hazard_outputs,
    )

    assert electric_unit_ids == set()
    for hazard_key in ("storm", "storm_cmcc"):
        for scenario in build_guadeloupe_page1_data.PUBLIC_MAP_SCENARIOS:
            assert native_states[hazard_key][scenario]["hydraulic-native:eu-step-43"] == "S2"
            assert native_causes[hazard_key][scenario]["hydraulic-native:eu-step-43"] == "direct_damage"


def test_public_state_feature_id_uses_hydraulic_service_key_for_water() -> None:
    assert build_guadeloupe_page1_data._public_state_feature_id(
        {
            "feature_id": "line-1",
            "asset_type": "eau_aep_cana",
            "service_feature_id": "AEP_001__P1",
        }
    ) == "AEP_001__P1"
    assert build_guadeloupe_page1_data._public_state_feature_id(
        {
            "feature_id": "elec-1",
            "asset_type": "elec_bt_aerien",
        }
    ) == "elec-1"


def test_build_exposure_metrics_uses_hydraulic_water_bundle(monkeypatch) -> None:
    elec_gdf = gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[LineString([(0.0, 0.0), (0.0, 0.1)])],
        crs="EPSG:4326",
    )
    hydraulic_lines = gpd.GeoDataFrame(
        {"network_kind": ["AEP", "EU"]},
        geometry=[
            LineString([(0.0, 0.0), (0.0, 0.1)]),
            LineString([(0.2, 0.2), (0.2, 0.3)]),
        ],
        crs="EPSG:4326",
    )
    hydraulic_assets = gpd.GeoDataFrame(
        {
            "network_kind": ["AEP", "EU", "EU"],
            "feature_role": ["captage_aep", "poste_refoulement", "step"],
            "asset_type_code": ["CAP", "PR", "STEP"],
        },
        geometry=[
            Polygon([(0.0, 0.0), (0.01, 0.0), (0.01, 0.01), (0.0, 0.01)]).centroid,
            Polygon([(0.2, 0.2), (0.21, 0.2), (0.21, 0.21), (0.2, 0.21)]).centroid,
            Polygon([(0.3, 0.3), (0.31, 0.3), (0.31, 0.31), (0.3, 0.31)]).centroid,
        ],
        crs="EPSG:4326",
    )

    def _fake_read_file(path: Path, layer: str | None = None):
        name = Path(path).name
        if name == "elec-lines.gpkg":
            return elec_gdf.copy()
        if name == "hydraulic.gpkg" and layer == "hydraulic_lines":
            return hydraulic_lines.copy()
        if name == "hydraulic.gpkg" and layer == "hydraulic_assets":
            return hydraulic_assets.copy()
        raise AssertionError(f"Unexpected read_file call: path={path} layer={layer}")

    monkeypatch.setattr(
        build_guadeloupe_page1_data,
        "gpd",
        type("_FakeGpd", (), {"read_file": staticmethod(_fake_read_file), "GeoDataFrame": gpd.GeoDataFrame})(),
    )
    monkeypatch.setattr(
        build_guadeloupe_page1_data,
        "_read_vector",
        lambda path, layer=None, source_crs=None: _fake_read_file(path, layer),
    )
    monkeypatch.setattr(build_guadeloupe_page1_data, "_ensure_crs", lambda gdf: gdf)
    monkeypatch.setattr(build_guadeloupe_page1_data, "_clip_case_gdf", lambda gdf, cfg: gdf)

    metrics = build_guadeloupe_page1_data._build_exposure_metrics(
        {
            "elec_line_sources": [
                {"class_key": "elec_bt_aerien", "paths": [Path("elec-lines.gpkg")]},
            ],
            "hydraulic_zone_sources": [
                {"path": Path("hydraulic.gpkg"), "line_layer": "hydraulic_lines", "asset_layer": "hydraulic_assets"},
            ],
        },
        "guadeloupe",
    )

    assert metrics["counts"]["water_lines_total"] == 2
    assert metrics["counts"]["aep_ouvrages_total"] == 1
    assert metrics["counts"]["eu_pr_total"] == 1
    assert metrics["counts"]["eu_step_total"] == 1
    assert metrics["counts"]["aep_ouvrages_by_type"] == {"CAP": 1}
    assert metrics["total_value_by_type_eur"]["eau_aep_ouvrages"] == pytest.approx(1_000_000.0)
    assert metrics["total_value_by_type_eur"]["eau_eu_pr"] == pytest.approx(397_636.0)
    assert metrics["total_value_by_type_eur"]["eau_eu_step"] == pytest.approx(8_785_714.0)


def test_network_dependency_scenario_adds_proxy_loss_for_electric_dependency() -> None:
    scenario = build_guadeloupe_page1_data._evaluate_network_dependency_scenario(
        direct_loss=np.array([100.0, 20.0], dtype=float),
        values=np.array([100.0, 100.0], dtype=float),
        class_keys=["elec_aerien", "eau_aep"],
        territories=["cell-1", "cell-1"],
        weights_km=np.array([1.0, 1.0], dtype=float),
        water_service_classes=[None, "eau_aep"],
        service_feature_ids=[None, "AEP_001__P1"],
        is_service_network=[False, True],
        is_blocking_asset=[False, False],
    )

    assert scenario["direct_state"].tolist() == ["S3", "S2"]
    assert scenario["final_state"].tolist() == ["S3", "S3"]
    assert scenario["direct_loss"].tolist() == [100.0, 20.0]
    assert scenario["dysfunction_loss"].tolist() == [0.0, 15.0]
    assert scenario["blocking_loss"].tolist() == [0.0, 0.0]
    assert scenario["total_loss"].tolist() == [100.0, 35.0]
    assert scenario["dominant_outage_cause"].tolist() == ["direct_damage", "electric_dependency"]
    assert scenario["indirect_s3_flag"].tolist() == [False, True]


def test_network_dependency_scenario_propagates_blocking_ouvrage_to_linked_network() -> None:
    scenario = build_guadeloupe_page1_data._evaluate_network_dependency_scenario(
        direct_loss=np.array([100.0, 0.0, 0.0], dtype=float),
        values=np.array([100.0, 100.0, 100.0], dtype=float),
        class_keys=["elec_aerien", None, "eau_eu"],
        territories=["cell-1", "cell-1", "cell-1"],
        weights_km=np.array([1.0, 0.0, 1.0], dtype=float),
        water_service_classes=[None, "eau_eu", "eau_eu"],
        service_feature_ids=[None, "EU_001__P1", "EU_001__P1"],
        is_service_network=[False, False, True],
        is_blocking_asset=[False, True, False],
    )

    assert scenario["direct_state"].tolist() == ["S3", "S0", "S0"]
    assert scenario["final_state"].tolist() == ["S3", "S3", "S3"]
    assert scenario["direct_loss"].tolist() == [100.0, 0.0, 0.0]
    assert scenario["dysfunction_loss"].tolist() == [0.0, 35.0, 0.0]
    assert scenario["blocking_loss"].tolist() == [0.0, 0.0, 35.0]
    assert scenario["total_loss"].tolist() == [100.0, 35.0, 35.0]
    assert scenario["dominant_outage_cause"].tolist() == [
        "direct_damage",
        "electric_dependency",
        "blocking_ouvrage",
    ]
    assert scenario["indirect_s3_flag"].tolist() == [False, True, True]


def test_event_max_series_from_hazard_groups_synthetic_years() -> None:
    from scipy import sparse

    class HazardStub:
        def __init__(self) -> None:
            self.event_name = [
                "STORM_1218|1_1218_3",
                "STORM_1219|1_1218_4",
                "STORM_1301|1_1301_1",
            ]
            self.intensity = sparse.csr_matrix(
                np.array(
                    [
                        [10.0, 20.0],
                        [15.0, 12.0],
                        [30.0, 1.0],
                    ],
                    dtype=float,
                )
            )

    assert build_guadeloupe_page1_data._parse_synthetic_year_from_event_name("STORM_1218|1_1218_3") == 1218
    track_series, year_series = build_guadeloupe_page1_data._event_max_series_from_hazard(HazardStub())
    assert track_series.tolist() == [20.0, 15.0, 30.0]
    assert sorted(year_series.tolist()) == [20.0, 30.0]
