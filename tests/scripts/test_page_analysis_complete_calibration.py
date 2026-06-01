from __future__ import annotations

import json
from pathlib import Path
import sys
import types

import numpy as np
import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

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
                "pml_50_eur": 40.0,
                "pml_100_eur": 60.0,
                "percentile_99_loss_eur": 80.0,
            }
        }
    }

    assert build_guadeloupe_page1_data._extract_complete_analysis_public_loss_targets(payload, "storm") == {
        "annual": 12.5,
        "rp50": 40.0,
        "rp100": 60.0,
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
        {"feature_id": "f1", "class_key": "eau_aep", "class_label": "Eau AEP", "geometry": {"id": 1}},
        {"feature_id": "f2", "class_key": "eau_eu", "class_label": "Eau EU", "geometry": {"id": 2}},
    ]
    hazard_feature_states = {
        hazard_key: {
            scenario: {"f1": "S1", "f2": "S2"}
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
    assert rows["f1"]["state_annual_storm"] == "S1"
    assert rows["f2"]["state_p99_storm_cmcc"] == "S2"