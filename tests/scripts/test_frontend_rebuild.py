from pathlib import Path
import json
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from scripts import (
    journal_guamar_run,
    rebuild_frontend_artifacts_from_local_run,
    rerun_case_studies_light,
    run_complete_analysis,
)


def test_frontend_artifacts_not_required_for_sensitivity_runs() -> None:
    assert run_complete_analysis._frontend_artifacts_required(None) is True
    assert (
        run_complete_analysis._frontend_artifacts_required(
            type("_Scenario", (), {"scenario_id": "all-default"})()
        )
        is False
    )


def test_rebuild_case_study_frontend_artifacts_does_not_pass_removed_fallback_flags(monkeypatch, tmp_path):
    popen_calls: list[dict[str, object]] = []
    supervision_events: list[dict[str, object]] = []

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
        "load_settings",
        lambda: type("_Settings", (), {"hazard_dynamic_max_tracks": 1200})(),
    )
    monkeypatch.setattr(
        run_complete_analysis,
        "launch_frontend_supervision_monitor",
        lambda **kwargs: type("_MonitorProcess", (), {"pid": 54321})(),
    )
    monkeypatch.setattr(
        run_complete_analysis,
        "_compact_process_memory",
        lambda: {
            "gc_collected": 7,
            "malloc_trim_supported": True,
            "malloc_trim_result": 1,
            "rss_kb_before": 420000,
            "rss_kb_after": 180000,
            "mem_available_kb_before": 900000,
            "mem_available_kb_after": 1250000,
        },
    )
    monkeypatch.setattr(
        run_complete_analysis,
        "write_frontend_supervision_event",
        lambda *args, **kwargs: supervision_events.append(dict(kwargs)),
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
    assert "--page-component-light-spacing-m" not in cmd
    assert "--page-component-light-max-points-total" not in cmd
    assert "--page-component-light-max-points-per-feature" not in cmd
    assert "--page-component-light-dynamic-max-tracks" not in cmd
    env = popen_calls[0]["env"]
    assert env[run_complete_analysis.ENV_FRONTEND_SUPERVISION_RUN_ID] == "20260512_080434"
    assert env[run_complete_analysis.ENV_FRONTEND_SUPERVISION_JOURNAL].endswith(
        "frontend-supervision.jsonl"
    )
    assert "SIB_RISK_HAZARD_DYNAMIC_MAX_TRACKS" not in env
    assert [event.get("event") for event in supervision_events[:2]] == [
        "frontend_parent_memory_compacted",
        "frontend_rebuild_requested",
    ]
    assert supervision_events[0]["rss_kb_before"] == 420000
    assert supervision_events[0]["rss_kb_after"] == 180000
    assert supervision_events[0]["malloc_trim_result"] == 1
    assert supervision_events[1]["frontend_page_component_dynamic_max_tracks"] is None


def test_rebuild_case_study_frontend_artifacts_aligns_page_analysis_dynamic_tracks_for_fast_runs(monkeypatch, tmp_path):
    popen_calls: list[dict[str, object]] = []
    supervision_events: list[dict[str, object]] = []

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
        "load_settings",
        lambda: type("_Settings", (), {"hazard_dynamic_max_tracks": 1200})(),
    )
    monkeypatch.setattr(
        run_complete_analysis,
        "launch_frontend_supervision_monitor",
        lambda **kwargs: type("_MonitorProcess", (), {"pid": 54321})(),
    )
    monkeypatch.setattr(
        run_complete_analysis,
        "_compact_process_memory",
        lambda: {
            "gc_collected": 3,
            "malloc_trim_supported": True,
            "malloc_trim_result": 1,
            "rss_kb_before": 640000,
            "rss_kb_after": 320000,
            "mem_available_kb_before": 900000,
            "mem_available_kb_after": 1200000,
        },
    )
    monkeypatch.setattr(
        run_complete_analysis,
        "write_frontend_supervision_event",
        lambda *args, **kwargs: supervision_events.append(dict(kwargs)),
    )

    run_complete_analysis.rebuild_case_study_frontend_artifacts(
        ["guadeloupe"],
        150,
        run_id="20260527_063207",
        supervision_journal=tmp_path / "frontend-supervision.jsonl",
    )

    assert len(popen_calls) == 1
    env = popen_calls[0]["env"]
    assert env["SIB_RISK_HAZARD_DYNAMIC_MAX_TRACKS"] == "150"
    assert supervision_events[1]["configured_dynamic_max_tracks"] == 1200
    assert supervision_events[1]["requested_dynamic_max_tracks"] == 150
    assert supervision_events[1]["frontend_page_component_dynamic_max_tracks"] == 150


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


def test_case_study_output_paths_include_water_infra_geojson(monkeypatch, tmp_path):
    monkeypatch.setattr(rerun_case_studies_light, "REPO_ROOT", tmp_path)

    names = [path.name for path in rerun_case_studies_light._case_study_output_paths("guadeloupe")]

    assert "guadeloupe-water-infra.geojson" in names


def test_case_study_output_paths_use_page7_for_saint_barthelemy(monkeypatch, tmp_path):
    monkeypatch.setattr(rerun_case_studies_light, "REPO_ROOT", tmp_path)

    names = [path.name for path in rerun_case_studies_light._case_study_output_paths("saint-barthelemy")]

    assert "saint-barthelemy-page7-analysis.json" in names


def test_resolve_archived_complete_analysis_json_prefers_run_archive(tmp_path) -> None:
    journal_path = tmp_path / "20260527_160919" / "frontend-supervision.jsonl"
    manifest_path = journal_path.parent / "manifest.json"
    archived_path = journal_path.parent / "territories" / "martinique" / "web" / "data" / "martinique-complete-analysis.json"
    archived_path.parent.mkdir(parents=True, exist_ok=True)
    archived_path.write_text("{}", encoding="utf-8")
    manifest_path.write_text(
        json.dumps(
            {
                "run_id": "20260527_160919",
                "territories": {
                    "martinique": {
                        "archived_complete_analysis_path": str(archived_path),
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    resolved = rerun_case_studies_light._resolve_archived_complete_analysis_json(
        "martinique",
        journal_path=journal_path,
        complete_analysis_run_id="20260527_160919",
    )

    assert resolved == archived_path


def test_main_passes_archived_complete_analysis_json_to_proxy_and_page(monkeypatch, tmp_path) -> None:
    journal_path = tmp_path / "20260527_160919" / "frontend-supervision.jsonl"
    manifest_path = journal_path.parent / "manifest.json"
    archived_path = journal_path.parent / "territories" / "guadeloupe" / "web" / "data" / "guadeloupe-complete-analysis.json"
    archived_path.parent.mkdir(parents=True, exist_ok=True)
    archived_path.write_text("{}", encoding="utf-8")
    manifest_path.write_text(
        json.dumps(
            {
                "run_id": "20260527_160919",
                "territories": {
                    "guadeloupe": {
                        "archived_complete_analysis_path": str(archived_path),
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    recorded_runs: list[dict[str, object]] = []
    monkeypatch.setenv("SIB_FRONTEND_SUPERVISION_RUN_ID", "20260527_160919")
    monkeypatch.setattr(
        rerun_case_studies_light.sys,
        "argv",
        ["rerun_case_studies_light.py", "--territories", "guadeloupe"],
    )
    monkeypatch.setattr(rerun_case_studies_light, "load_settings", lambda: type("_Settings", (), {"surge_grid_deg": 0.02})())
    monkeypatch.setattr(rerun_case_studies_light, "_resolve_landslide_python", lambda: rerun_case_studies_light.PYTHON)
    monkeypatch.setattr(rerun_case_studies_light, "_build_territory_env", lambda territory, base_settings: {})
    monkeypatch.setattr(
        rerun_case_studies_light,
        "_resolve_page_component_light_config",
        lambda **kwargs: {
            "spacing_m": 100.0,
            "max_points_total": 0,
            "max_points_per_feature": 120,
            "dynamic_max_tracks": 1200,
        },
    )
    monkeypatch.setattr(rerun_case_studies_light, "_assert_supported_page_component_light_config", lambda **kwargs: None)
    monkeypatch.setattr(rerun_case_studies_light, "_purge_case_study_outputs", lambda territory: None)
    monkeypatch.setattr(rerun_case_studies_light, "_assert_case_study_coherence", lambda territory, run_id: None)
    monkeypatch.setattr(rerun_case_studies_light, "record_guamar_run", lambda territory, session_run_id: None)
    monkeypatch.setattr(rerun_case_studies_light, "write_frontend_supervision_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        rerun_case_studies_light,
        "_run",
        lambda cmd, **kwargs: recorded_runs.append({"cmd": list(cmd), **kwargs}),
    )

    exit_code = rerun_case_studies_light.main(journal_path=journal_path)

    assert exit_code == 0
    proxy_cmd = next(item["cmd"] for item in recorded_runs if item.get("step") == "build_multi_hazard_proxy")
    page_cmd = next(item["cmd"] for item in recorded_runs if item.get("step") == "build_page_analysis")
    assert "--complete-analysis-json" in proxy_cmd
    assert proxy_cmd[proxy_cmd.index("--complete-analysis-json") + 1] == str(archived_path)
    assert "--complete-analysis-json" in page_cmd
    assert page_cmd[page_cmd.index("--complete-analysis-json") + 1] == str(archived_path)


def test_resolve_local_requested_dynamic_max_tracks_reads_complete_analysis_payloads(monkeypatch, tmp_path) -> None:
    data_root = tmp_path / "web" / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "modeling": {
                "hazard_dynamic_max_tracks_requested": 150,
            }
        }
    }
    for territory in ("guadeloupe", "martinique"):
        (data_root / f"{territory}-complete-analysis.json").write_text(
            json.dumps(payload),
            encoding="utf-8",
        )

    dynamic_max_tracks, resolved = rebuild_frontend_artifacts_from_local_run.resolve_local_requested_dynamic_max_tracks(
        ["guadeloupe", "martinique"],
        data_root=data_root,
    )

    assert dynamic_max_tracks == 150
    assert resolved == {"guadeloupe": 150, "martinique": 150}


def test_rebuild_wrapper_propagates_local_dynamic_tracks(monkeypatch, tmp_path) -> None:
    data_root = tmp_path / "web" / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "modeling": {
                "hazard_dynamic_max_tracks_requested": 150,
            }
        }
    }
    (data_root / "guadeloupe-complete-analysis.json").write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(rebuild_frontend_artifacts_from_local_run, "WEB_DATA_DIR", data_root)

    captured: dict[str, object] = {}

    def _fake_run(cmd, check, env):
        captured["cmd"] = list(cmd)
        captured["check"] = bool(check)
        captured["env"] = dict(env)
        return None

    monkeypatch.setattr(rebuild_frontend_artifacts_from_local_run.subprocess, "run", _fake_run)

    exit_code = rebuild_frontend_artifacts_from_local_run.main([
        "--territories",
        "guadeloupe",
    ])

    assert exit_code == 0
    assert captured["check"] is True
    assert captured["env"]["SIB_RISK_HAZARD_DYNAMIC_MAX_TRACKS"] == "150"
    assert "--page-component-light-dynamic-max-tracks" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--page-component-light-dynamic-max-tracks") + 1] == "150"


def test_assert_case_study_coherence_requires_hydraulic_geojson_outputs(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(rerun_case_studies_light, "REPO_ROOT", tmp_path)

    data_root = tmp_path / "web" / "data"
    data_root.mkdir(parents=True, exist_ok=True)

    payload = {
        "meta": {
            "case_study_run_id": "guadeloupe_case_20260527T070221Z",
            "generated_at": "2026-05-27T07:08:39+00:00",
        }
    }
    for name in (
        "guadeloupe-wind-maps.json",
        "guadeloupe-landslide-maps.json",
        "guadeloupe-multi-hazard-proxy.json",
        "guadeloupe-page1-analysis.json",
    ):
        (data_root / name).write_text(__import__("json").dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match="missing required case-study geojson artefacts: water-infra, network-states"):
        rerun_case_studies_light._assert_case_study_coherence(
            "guadeloupe",
            "guadeloupe_case_20260527T070221Z",
        )


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


def test_resolve_page_component_light_config_defaults_to_safe_full_coverage_settings() -> None:
    settings = type(
        "_Settings",
        (),
        {"climada_max_points_per_feature": 300, "hazard_dynamic_max_tracks": 1200},
    )()
    env = {"SIB_RISK_CLIMADA_MAX_POINTS_PER_FEATURE": "120"}

    config = rerun_case_studies_light._resolve_page_component_light_config(
        page_spacing_m=150.0,
        component_light_spacing_m=None,
        component_light_max_points_total=None,
        component_light_max_points_per_feature=None,
        component_light_dynamic_max_tracks=None,
        settings=settings,
        env=env,
    )

    assert config == {
        "spacing_m": 150.0,
        "max_points_total": 0,
        "max_points_per_feature": 120,
        "dynamic_max_tracks": 1200,
    }


def test_resolve_page_component_light_config_keeps_explicit_overrides() -> None:
    settings = type(
        "_Settings",
        (),
        {"climada_max_points_per_feature": 300, "hazard_dynamic_max_tracks": 1200},
    )()

    config = rerun_case_studies_light._resolve_page_component_light_config(
        page_spacing_m=100.0,
        component_light_spacing_m=100.0,
        component_light_max_points_total=0,
        component_light_max_points_per_feature=120,
        component_light_dynamic_max_tracks=1200,
        settings=settings,
        env={},
    )

    assert config == {
        "spacing_m": 100.0,
        "max_points_total": 0,
        "max_points_per_feature": 120,
        "dynamic_max_tracks": 1200,
    }


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


def test_deploy_verify_relative_paths_include_water_infra_geojson() -> None:
    assert "data/guadeloupe-water-infra.geojson" in run_complete_analysis.DEPLOY_VERIFY_RELATIVE_PATHS
    assert "data/martinique-water-infra.geojson" in run_complete_analysis.DEPLOY_VERIFY_RELATIVE_PATHS
    assert "data/saint-barthelemy-water-infra.geojson" in run_complete_analysis.DEPLOY_VERIFY_RELATIVE_PATHS
    assert "data/saint-barthelemy-page7-analysis.json" in run_complete_analysis.DEPLOY_VERIFY_RELATIVE_PATHS
