from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from scripts import build_guadeloupe_page1_data, journal_guamar_run, rerun_case_studies_light, run_complete_analysis


def test_rebuild_case_study_frontend_artifacts_uses_complete_analysis_fallbacks(monkeypatch):
    calls: list[dict[str, object]] = []

    def _fake_run(cmd, timeout=None, **kwargs):
        calls.append({"cmd": list(cmd), "timeout": timeout, "kwargs": dict(kwargs)})

        class _Result:
            returncode = 0

        return _Result()

    monkeypatch.setattr(run_complete_analysis.subprocess, "run", _fake_run)

    run_complete_analysis.rebuild_case_study_frontend_artifacts(["guadeloupe", "martinique"], 1500)

    assert len(calls) == 1
    cmd = calls[0]["cmd"]
    assert "--prefer-complete-analysis-proxy-fallback" in cmd
    assert "--prefer-complete-analysis-page-fallback" in cmd


def test_normalize_called_process_exit_code_maps_sigkill_to_137(capsys):
    exc = subprocess.CalledProcessError(-9, ["python", "child.py"])

    code = rerun_case_studies_light._normalize_called_process_exit_code(exc)

    assert code == 137
    assert "signal 9" in capsys.readouterr().err


def test_complete_analysis_fallback_reinjects_landslide_with_asset_id_alignment(monkeypatch):
    payload = {
        "meta": {
            "updated_at": "2026-04-21T10:39:56+00:00",
            "sampling_spacing_m": 100.0,
            "modeling": {
                "hazard_track_count_storm": 1500,
                "hazard_track_count_storm_cmcc": 1500,
                "sharding_checkpoint_dir": "/home/ubuntu/sib-work/outputs/complete-analysis-runs/20260421_091134/territories/guadeloupe/checkpoints",
            },
        },
        "asset_results": [
            {
                "asset_id": "asset-a",
                "asset_type": "elec_bt_aerien",
                "exposure_eur": 100.0,
                "eai_storm_direct_eur": 10.0,
                "eai_storm_eur": 10.0,
                "eai_cmcc_direct_eur": 0.0,
                "eai_cmcc_eur": 0.0,
            },
            {
                "asset_id": "asset-b",
                "asset_type": "elec_hta_aerien",
                "exposure_eur": 100.0,
                "eai_storm_direct_eur": 20.0,
                "eai_storm_eur": 20.0,
                "eai_cmcc_direct_eur": 0.0,
                "eai_cmcc_eur": 0.0,
            },
        ],
        "portfolio_results": {
            "storm": {
                "eai_eur": 30.0,
                "pml_50_eur": 30.0,
                "pml_100_eur": 30.0,
                "percentile_99_loss_eur": 30.0,
            },
            "storm_cmcc": {
                "eai_eur": 0.0,
                "pml_50_eur": 0.0,
                "pml_100_eur": 0.0,
                "percentile_99_loss_eur": 0.0,
            },
            "event_summary": {
                "storm_top_events": [{"event_id": 1, "loss_eur": 30.0}],
                "storm_cmcc_top_events": [],
            },
        },
        "exposure_summary": {"asset_count_points": 2},
    }

    fake_bundle = SimpleNamespace(
        point_records=[
            {"feature_id": "asset-b", "value_eur": 100.0, "asset_type": "elec_hta_aerien"},
            {"feature_id": "asset-a", "value_eur": 100.0, "asset_type": "elec_bt_aerien"},
        ]
    )

    monkeypatch.setattr(build_guadeloupe_page1_data, "build_climada_exposure", lambda *args, **kwargs: fake_bundle)
    monkeypatch.setattr(
        build_guadeloupe_page1_data,
        "_build_landslide_proxy_losses_lightweight",
        lambda *args, **kwargs: {
            "storm": {
                "scenario_arrays": {
                    scenario: build_guadeloupe_page1_data.np.array([7.0, 5.0], dtype=float)
                    for scenario in build_guadeloupe_page1_data.MAP_SCENARIOS
                }
            },
            "storm_cmcc": {
                "scenario_arrays": {
                    scenario: build_guadeloupe_page1_data.np.zeros(2, dtype=float)
                    for scenario in build_guadeloupe_page1_data.MAP_SCENARIOS
                }
            },
        },
    )

    impact_metrics, aux = build_guadeloupe_page1_data._compute_impact_metrics_from_complete_analysis(
        payload,
        spacing_m=200.0,
        network_value_per_km={
            "elec_bt_aerien": 100.0,
            "elec_hta_aerien": 100.0,
        },
        exposure_value_by_class={
            "elec_bt_aerien": 100.0,
            "elec_hta_aerien": 100.0,
        },
        landslide_exposure=object(),
        settings=SimpleNamespace(climada_metric_crs="EPSG:32620", climada_max_points_per_feature=0),
        territory="guadeloupe",
        landslide_bbox=(-61.8, 15.8, -60.9, 16.6),
    )

    annual_rows = {
        row["class_key"]: row["storm"]
        for row in impact_metrics["state_damage_tables"]["annual"]
    }

    assert annual_rows["elec_bt_aerien"]["damage_eur"] == 15.0
    assert annual_rows["elec_hta_aerien"]["damage_eur"] == 27.0
    assert annual_rows["elec_bt_aerien"]["damage_components_eur"]["landslide"] > 0.0
    assert impact_metrics["summary_metrics"]["storm"]["eai_total_eur"] == 42.0
    assert aux["fallback_landslide_supported"] is True
    assert aux["complete_analysis_source"]["dynamic_max_tracks"]["storm"] == 1500
    assert aux["complete_analysis_source"]["run_id"] == "20260421_091134"


def test_extract_run_entry_prefers_complete_analysis_track_count_for_fallback_page():
    track_blob = journal_guamar_run.encode_track_ids(["track-1", "track-2"])

    row = journal_guamar_run._extract_run_entry(
        territory="guadeloupe",
        hazard_key="storm",
        wind_meta={
            "generated_at": "2026-04-21T12:41:05+00:00",
            "dynamic_max_tracks": 300,
            "track_journal": {
                "storm": {
                    "track_ids_compressed": track_blob,
                    "n_events": 2,
                    "event_frequency_sum": 0.25,
                }
            },
        },
        page_meta={
            "generated_at": "2026-04-21T12:41:06+00:00",
            "case_study_run_id": "guadeloupe_case_20260421T124106Z",
            "sampling_spacing_m": 1000.0,
            "component_light_rerun": {"max_points_total": 400, "max_points_per_feature": 4},
            "modeling": {"fallback": True},
            "complete_analysis_source": {
                "run_id": "20260421_091134",
                "generated_at": "2026-04-21T10:39:56+00:00",
                "dynamic_max_tracks": {"storm": 1500, "storm_cmcc": 1500},
            },
        },
        proxy_meta={"max_points_total": 600, "max_points_per_feature": 6},
        impact_summary={"storm": {"rp50_total_loss_eur": 123.0, "rp100_total_loss_eur": 456.0}},
    )

    assert row["dynamic_max_tracks"] == 1500
    assert row["wind_map_dynamic_max_tracks"] == 300
    assert row["source_dynamic_max_tracks"] == 1500
    assert row["complete_analysis_run_id"] == "20260421_091134"
    assert row["track_ids_count"] == 2