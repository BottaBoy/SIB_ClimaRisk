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

from scripts import generate_run_graphs


def _run_record(manifest: dict | None = None) -> generate_run_graphs.RunRecord:
    return generate_run_graphs.RunRecord(
        run_id="20260527_072457",
        status="success",
        created_at=None,
        updated_at=None,
        territories=["guadeloupe"],
        dynamic_max_tracks=None,
        memory_budget_gb=None,
        manifest_path="/tmp/manifest.json",
        manifest=manifest or {"territories": {"guadeloupe": {}}},
        archived_ready_count=1,
    )


def test_load_territory_payload_rejects_mutable_only_paths(tmp_path, monkeypatch):
    run_outputs_dir = tmp_path / "runs"
    run_outputs_dir.mkdir()
    mutable_payload = tmp_path / "guadeloupe-complete-analysis.json"
    mutable_payload.write_text('{"portfolio_results": {}}', encoding="utf-8")
    manifest = {
        "territories": {
            "guadeloupe": {
                "complete_analysis_path": str(mutable_payload),
                "phases": {
                    "export": {
                        "output_file": str(mutable_payload),
                    }
                },
            }
        }
    }
    monkeypatch.setattr(generate_run_graphs, "RUN_OUTPUTS_DIR", run_outputs_dir)

    with pytest.raises(FileNotFoundError, match="No archived complete-analysis JSON found"):
        generate_run_graphs.load_territory_payload(_run_record(manifest), "guadeloupe")


def test_build_hazard_metric_scorecard_is_chart():
    payload = {
        "portfolio_results": {
            "storm": {
                "eai_eur": 10.0,
                "eai_direct_eur": 7.0,
                "eai_indirect_eur": 3.0,
                "pml_100_eur": 100.0,
                "pml_1000_eur": 1000.0,
                "tvar_95_eur": 1200.0,
                "percentile_99_loss_eur": 900.0,
            },
            "storm_cmcc": {
                "eai_eur": 20.0,
                "eai_direct_eur": 13.0,
                "eai_indirect_eur": 7.0,
                "pml_100_eur": 110.0,
                "pml_1000_eur": 1100.0,
                "tvar_95_eur": 1250.0,
                "percentile_99_loss_eur": 950.0,
            },
        }
    }

    graph = generate_run_graphs.build_hazard_metric_scorecard(
        "guadeloupe",
        payload,
        ["storm", "storm_cmcc"],
    )

    assert graph.kind == "chart"
    assert graph.table_headers is None
    assert graph.png_payload is not None
    assert graph.png_payload["type"] == "grouped_bar"
    assert graph.png_payload["categories"] == ["Annual EAI", "Direct EAI", "Indirect EAI", "PML100", "PML1000", "TVaR95", "P99"]


def test_render_integrated_vincennes_assets_cleans_stale_outputs_and_collects_new_files(tmp_path, monkeypatch):
    output_dir = tmp_path / "graphs"
    stale_chart = output_dir / "charts" / "stale.png"
    stale_map = output_dir / "maps" / "stale.png"
    stale_table = output_dir / "tables" / "stale.png"
    stale_chart.parent.mkdir(parents=True)
    stale_map.parent.mkdir(parents=True)
    stale_table.parent.mkdir(parents=True)
    stale_chart.write_text("old", encoding="utf-8")
    stale_map.write_text("old", encoding="utf-8")
    stale_table.write_text("old", encoding="utf-8")

    def _fake_run(cmd, capture_output, text):
        (output_dir / "charts").mkdir(parents=True, exist_ok=True)
        (output_dir / "maps").mkdir(parents=True, exist_ok=True)
        (output_dir / "tables").mkdir(parents=True, exist_ok=True)
        (output_dir / "charts" / "fresh.png").write_text("new", encoding="utf-8")
        (output_dir / "maps" / "fresh.png").write_text("new", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(generate_run_graphs.subprocess, "run", _fake_run)

    paths = generate_run_graphs._render_integrated_vincennes_assets(_run_record(), output_dir)

    assert sorted(Path(path).relative_to(output_dir).as_posix() for path in paths) == [
        "charts/fresh.png",
        "maps/fresh.png",
    ]
    assert not stale_chart.exists()
    assert not stale_map.exists()
    assert not stale_table.exists()


def test_generated_output_records_count_technical_types_and_families(tmp_path):
    output_dir = tmp_path / "graphs"
    png_paths = [
        str(output_dir / "png" / "run-overview-summary.png"),
        str(output_dir / "png" / "wind-year-hist-by-hazard-guadeloupe-storm.png"),
    ]
    auxiliary_paths = [
        str(output_dir / "charts" / "guadeloupe_vent_max_par_evenement.png"),
        str(output_dir / "maps" / "guadeloupe_aep_canalisations.png"),
    ]
    graphs = [
        generate_run_graphs.GraphSpec(
            graph_id="run_overview_summary",
            graph_type="run_overview_summary",
            title="Run Overview",
            section="overview",
            territory=None,
            hazard=None,
            kind="table",
            description="summary",
        ),
        generate_run_graphs.GraphSpec(
            graph_id="wind_year_hist_by_hazard__guadeloupe__storm",
            graph_type="wind_year_hist_by_hazard",
            title="Wind Histogram",
            section="wind",
            territory="guadeloupe",
            hazard="storm",
            kind="chart",
            description="wind",
        ),
    ]

    records = generate_run_graphs._build_generated_output_records(output_dir, graphs, png_paths, auxiliary_paths)

    assert generate_run_graphs._count_generated_outputs(records, "technical_type") == {
        "chart": 2,
        "map": 1,
        "table": 1,
    }
    assert generate_run_graphs._count_generated_outputs(records, "family") == {
        "alea": 2,
        "exposition": 1,
        "synthese": 1,
    }


def test_normalize_territory_supports_saint_barthelemy_aliases() -> None:
    assert generate_run_graphs._normalize_territory("stb") == "saint-barthelemy"
    assert generate_run_graphs._normalize_territory("blm") == "saint-barthelemy"
