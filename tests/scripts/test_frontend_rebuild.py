from pathlib import Path
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from scripts import journal_guamar_run, rerun_case_studies_light, run_complete_analysis


def test_rebuild_case_study_frontend_artifacts_does_not_pass_removed_fallback_flags(monkeypatch, tmp_path):
    popen_calls: list[dict[str, object]] = []

    class _FakeProcess:
        pid = 12345

        def wait(self, timeout=None):
            return 0

    def _fake_popen(cmd, env=None, **kwargs):
        popen_calls.append({"cmd": list(cmd), "env": dict(env or {}), "kwargs": dict(kwargs)})
        return _FakeProcess()

    monkeypatch.setattr(run_complete_analysis.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(run_complete_analysis, "read_process_start_ticks", lambda pid: int(pid) + 1)
    monkeypatch.setattr(
        run_complete_analysis,
        "launch_frontend_supervision_monitor",
        lambda **kwargs: type("_MonitorProcess", (), {"pid": 54321})(),
    )
    monkeypatch.setattr(
        run_complete_analysis,
        "write_frontend_supervision_event",
        lambda *args, **kwargs: None,
    )

    run_complete_analysis.rebuild_case_study_frontend_artifacts(
        ["guadeloupe", "martinique"],
        1500,
        run_id="20260512_080434",
        supervision_journal=tmp_path / "frontend-supervision.jsonl",
    )

    assert len(popen_calls) == 1
    cmd = popen_calls[0]["cmd"]
    assert "--prefer-complete-analysis-proxy-fallback" not in cmd
    assert "--prefer-complete-analysis-page-fallback" not in cmd
    env = popen_calls[0]["env"]
    assert env[run_complete_analysis.ENV_FRONTEND_SUPERVISION_RUN_ID] == "20260512_080434"
    assert env[run_complete_analysis.ENV_FRONTEND_SUPERVISION_JOURNAL].endswith(
        "frontend-supervision.jsonl"
    )


def test_normalize_called_process_exit_code_maps_sigkill_to_137(capsys):
    exc = subprocess.CalledProcessError(-9, ["python", "child.py"])

    code = rerun_case_studies_light._normalize_called_process_exit_code(exc)

    assert code == 137
    assert "signal 9" in capsys.readouterr().err


def test_build_territory_env_does_not_force_disable_multi_hazard(monkeypatch, tmp_path):
    topo_path = tmp_path / "Guadeloupe.tif"
    topo_path.write_text("topo", encoding="utf-8")

    monkeypatch.setattr(
        rerun_case_studies_light,
        "resolve_surge_topo_path_for_territory",
        lambda territory, settings, env: topo_path,
    )

    env = rerun_case_studies_light._build_territory_env("guadeloupe", base_settings=object())

    assert env["SIB_RISK_HAZARD_SURGE_TOPO_PATH"] == str(topo_path)
    assert env["SIB_RISK_CLIMADA_MAX_POINTS_PER_FEATURE"] == "120"
    assert "SIB_RISK_MULTI_HAZARD_ENABLED" not in env


def test_purge_case_study_outputs_removes_stale_frontend_files(monkeypatch, tmp_path):
    monkeypatch.setattr(rerun_case_studies_light, "REPO_ROOT", tmp_path)

    for path in rerun_case_studies_light._case_study_output_paths("guadeloupe"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stale", encoding="utf-8")

    rerun_case_studies_light._purge_case_study_outputs("guadeloupe")

    for path in rerun_case_studies_light._case_study_output_paths("guadeloupe"):
        assert not path.exists()


def test_assert_supported_page_component_light_config_accepts_full_coverage_settings() -> None:
    settings = type(
        "_Settings",
        (),
        {"climada_max_points_per_feature": 300, "hazard_dynamic_max_tracks": 1200},
    )()
    env = {"SIB_RISK_CLIMADA_MAX_POINTS_PER_FEATURE": "120"}

    rerun_case_studies_light._assert_supported_page_component_light_config(
        territory="guadeloupe",
        page_spacing_m=100.0,
        component_light_spacing_m=100.0,
        component_light_max_points_total=0,
        component_light_max_points_per_feature=120,
        component_light_dynamic_max_tracks=1200,
        settings=settings,
        env=env,
    )


def test_assert_supported_page_component_light_config_rejects_partial_coverage_shortcuts() -> None:
    settings = type(
        "_Settings",
        (),
        {"climada_max_points_per_feature": 300, "hazard_dynamic_max_tracks": 1200},
    )()
    env = {"SIB_RISK_CLIMADA_MAX_POINTS_PER_FEATURE": "120"}

    with pytest.raises(RuntimeError) as exc_info:
        rerun_case_studies_light._assert_supported_page_component_light_config(
            territory="guadeloupe",
            page_spacing_m=100.0,
            component_light_spacing_m=1000.0,
            component_light_max_points_total=400,
            component_light_max_points_per_feature=4,
            component_light_dynamic_max_tracks=50,
            settings=settings,
            env=env,
        )

    message = str(exc_info.value)
    assert "unsupported page component-light configuration" in message
    assert "spacing_m=1000.0 differs from page spacing 100.0" in message
    assert "max_points_total is unsupported" in message
    assert "max_points_per_feature=4 differs from configured 120" in message
    assert "dynamic_max_tracks=50 differs from configured 1200" in message


def test_extract_run_entry_uses_wind_map_track_count_even_if_page_meta_mentions_fallback():
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

    assert row["dynamic_max_tracks"] == 300
    assert row["wind_map_dynamic_max_tracks"] == 300
    assert row["source_dynamic_max_tracks"] == 1500
    assert row["complete_analysis_run_id"] == "20260421_091134"
    assert row["track_ids_count"] == 2