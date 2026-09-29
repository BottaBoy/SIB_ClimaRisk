from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app import config
from backend.app.job_store import JobStore
from backend.app.risk_engine.errors import InputValidationError
from backend.app.risk_engine.hazard_loader import list_default_basin_coverages
from backend.app.risk_engine.quick_impact import list_quick_zones, run_quick_pipeline


SURFACES_PATH = Path(__file__).resolve().parents[2] / "web" / "data" / "user-impact-surfaces.json"


def _drawn_payload(lon: float = -61.53, lat: float = 16.23) -> str:
    return json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "asset_id": "A001",
                        "label": "Actif test",
                        "value_eur": 1_000_000,
                        "asset_type": "eau_aep_cana",
                        "exposure_category": "ouvrage_eau",
                    },
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                }
            ],
        }
    )


def test_quick_zones_include_complete_analysis_and_si_screening() -> None:
    settings = config.Settings(user_impact_surfaces_path=SURFACES_PATH)

    zones = {zone["key"]: zone for zone in list_quick_zones(settings)}
    basin_codes = {coverage["code"] for coverage in list_default_basin_coverages()}

    assert {"guadeloupe", "martinique", "saint-barthelemy", "la-reunion", "mayotte", "basin-na", "basin-si"} <= set(zones)
    assert zones["guadeloupe"]["mode"] == "complete_analysis_calibrated"
    assert zones["la-reunion"]["mode"] == "si_screening_generic"
    assert zones["basin-na"]["mode"] == "na_basin_screening_generic"
    assert zones["basin-si"]["mode"] == "si_basin_screening_generic"
    assert {"NA", "SI"} <= basin_codes


def test_quick_pipeline_returns_aligned_result_and_exports(tmp_path: Path) -> None:
    settings = config.Settings(
        job_root=tmp_path,
        user_impact_surfaces_path=SURFACES_PATH,
        quick_max_features=20,
        job_ttl_hours=168,
    )
    store = JobStore(settings.job_root, ttl_hours=settings.job_ttl_hours, max_runs_kept=settings.max_runs_kept)
    job = store.create_job(
        params={
            "input_mode": "drawn_geojson",
            "drawn_geojson": _drawn_payload(),
            "target_zone": "guadeloupe",
            "run_label": "unit-quick",
        }
    )

    result = run_quick_pipeline(job.job_id, store.get_params(job.job_id), settings, store)

    assert result["meta"]["engine"] == "precomputed_user_impact_v1"
    assert result["meta"]["reference_engine"] == "climada_with_interdependency_v1"
    assert result["meta"]["quick_zone"] == "guadeloupe"
    assert result["meta"]["approximation"] is True
    assert result["portfolio_results"]["storm"]["eai_eur"] > 0
    assert result["portfolio_results"]["storm"]["pml_100_eur"] > 0
    assert result["pml_network_graph_inputs"]["schema_version"] == "user_quick_pml_network_graph_inputs_v1"
    assert result["input_features_geojson"]["features"][0]["properties"]["asset_type"] == "eau_aep_cana"

    assert result["artifacts"]["downloads"] == []
    assert result["artifacts"]["visuals"] == []


def test_quick_pipeline_accepts_auto_point_anywhere_in_na_basin(tmp_path: Path) -> None:
    settings = config.Settings(
        job_root=tmp_path,
        user_impact_surfaces_path=SURFACES_PATH,
        quick_max_features=20,
        job_ttl_hours=168,
    )
    store = JobStore(settings.job_root, ttl_hours=settings.job_ttl_hours, max_runs_kept=settings.max_runs_kept)
    job = store.create_job(
        params={
            "input_mode": "drawn_geojson",
            "drawn_geojson": _drawn_payload(lon=-72.0, lat=19.0),
            "target_zone": "auto",
            "run_label": "unit-quick-na-basin",
        }
    )

    result = run_quick_pipeline(job.job_id, store.get_params(job.job_id), settings, store)

    assert result["meta"]["quick_zone"] == "basin-na"
    assert result["meta"]["quick_zone_mode"] == "na_basin_screening_generic"
    assert result["meta"]["quick_basin_codes"] == ["NA"]
    assert result["asset_results"][0]["quick_zone"] == "basin-na"
    assert result["portfolio_results"]["storm"]["eai_eur"] > 0


def test_quick_pipeline_accepts_mixed_na_si_portfolio(tmp_path: Path) -> None:
    settings = config.Settings(
        job_root=tmp_path,
        user_impact_surfaces_path=SURFACES_PATH,
        quick_max_features=20,
        job_ttl_hours=168,
    )
    store = JobStore(settings.job_root, ttl_hours=settings.job_ttl_hours, max_runs_kept=settings.max_runs_kept)
    mixed_payload = json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                json.loads(_drawn_payload())["features"][0],
                {
                    "type": "Feature",
                    "properties": {
                        "asset_id": "SI001",
                        "label": "Actif SI",
                        "value_eur": 2_000_000,
                        "asset_type": "habitation",
                        "exposure_category": "habitation",
                    },
                    "geometry": {"type": "Point", "coordinates": [80.0, -20.0]},
                },
            ],
        }
    )
    job = store.create_job(
        params={
            "input_mode": "drawn_geojson",
            "drawn_geojson": mixed_payload,
            "target_zone": "auto",
            "run_label": "unit-quick-mixed",
        }
    )

    result = run_quick_pipeline(job.job_id, store.get_params(job.job_id), settings, store)

    assert result["meta"]["quick_zone"] == "mixed"
    assert result["meta"]["quick_basin_codes"] == ["NA", "SI"]
    assert {row["quick_zone"] for row in result["asset_results"]} == {"guadeloupe", "basin-si"}
    assert result["exposure_summary"]["quick_basin_counts"] == {"NA": 1, "SI": 1}
    assert len(result["territory_results"]) == 4


def test_quick_pipeline_rejects_feature_outside_selected_zone(tmp_path: Path) -> None:
    settings = config.Settings(job_root=tmp_path, user_impact_surfaces_path=SURFACES_PATH)
    store = JobStore(settings.job_root, ttl_hours=settings.job_ttl_hours, max_runs_kept=settings.max_runs_kept)
    job = store.create_job(
        params={
            "input_mode": "drawn_geojson",
            "drawn_geojson": _drawn_payload(lon=55.5, lat=-21.1),
            "target_zone": "guadeloupe",
            "run_label": "outside",
        }
    )

    with pytest.raises(InputValidationError, match="outside selected quick-impact zone"):
        run_quick_pipeline(job.job_id, store.get_params(job.job_id), settings, store)
