from __future__ import annotations

import json
from pathlib import Path
import sys

import matplotlib.axes
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
BACKEND_ROOT = REPO_ROOT / "backend"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts.generate_sensitivity_graphs import (
    ScenarioPayload,
    add_baseline_deltas,
    build_quality_report,
    clean_legacy_outputs,
    extract_rows_from_payload,
    plot_network_state_tornado,
    plot_tornado,
    summarize_network_state_distribution,
)


def test_add_baseline_deltas_uses_service_and_network_metric_for_network_states() -> None:
    df = pd.DataFrame(
        [
            {
                "scenario_id": "all-default",
                "territory": "guadeloupe",
                "hazard": "storm",
                "metric": "network_state_pct",
                "return_period": "network_state",
                "service": "elec",
                "network_metric": "non_nominal_pct",
                "value": 40.0,
            },
            {
                "scenario_id": "all-default",
                "territory": "guadeloupe",
                "hazard": "storm",
                "metric": "network_state_pct",
                "return_period": "network_state",
                "service": "elec",
                "network_metric": "outage_pct",
                "value": 10.0,
            },
            {
                "scenario_id": "scenario-a",
                "territory": "guadeloupe",
                "hazard": "storm",
                "metric": "network_state_pct",
                "return_period": "network_state",
                "service": "elec",
                "network_metric": "non_nominal_pct",
                "value": 55.0,
            },
            {
                "scenario_id": "scenario-a",
                "territory": "guadeloupe",
                "hazard": "storm",
                "metric": "network_state_pct",
                "return_period": "network_state",
                "service": "elec",
                "network_metric": "outage_pct",
                "value": 15.0,
            },
        ]
    )

    merged = add_baseline_deltas(df)
    non_nominal = merged[
        (merged["scenario_id"] == "scenario-a")
        & (merged["network_metric"] == "non_nominal_pct")
    ].iloc[0]
    outage = merged[
        (merged["scenario_id"] == "scenario-a")
        & (merged["network_metric"] == "outage_pct")
    ].iloc[0]

    assert non_nominal["baseline_value"] == 40.0
    assert non_nominal["delta_abs"] == 15.0
    assert outage["baseline_value"] == 10.0
    assert outage["delta_abs"] == 5.0


def test_build_quality_report_flags_duplicate_network_state_baselines() -> None:
    df = pd.DataFrame(
        [
            {
                "scenario_id": "all-default",
                "territory": "guadeloupe",
                "hazard": "storm",
                "metric": "network_state_pct",
                "return_period": "network_state",
                "service": "elec",
                "network_metric": "non_nominal_pct",
                "value": 40.0,
                "baseline_value": 40.0,
                "delta_abs": 0.0,
                "parameter_key": None,
            },
            {
                "scenario_id": "all-default",
                "territory": "guadeloupe",
                "hazard": "storm",
                "metric": "network_state_pct",
                "return_period": "network_state",
                "service": "elec",
                "network_metric": "non_nominal_pct",
                "value": 41.0,
                "baseline_value": 41.0,
                "delta_abs": 0.0,
                "parameter_key": None,
            },
        ]
    )

    report = build_quality_report(df)

    assert report["status"] == "failed"
    duplicate_check = next(item for item in report["checks"] if item["check"] == "baseline_uniqueness::network_state_pct")
    assert duplicate_check["status"] == "failed"
    assert duplicate_check["duplicate_key_count"] == 1


def test_extract_rows_from_payload_uses_network_states_native(tmp_path: Path) -> None:
    payload_path = tmp_path / "guadeloupe-complete-analysis.json"
    payload_path.write_text(
        json.dumps(
            {
                "portfolio_results": {
                    "storm": {
                        "eai_eur": 1000.0,
                        "pml_50_eur": 2000.0,
                        "pml_100_eur": 3000.0,
                    }
                },
                "territory_results": [
                    {
                        "network_states_native": {
                            "storm": {
                                "elec": {"degraded_share": 0.25, "state": "S1"},
                                "water_aep": {"degraded_share": 0.40, "state": "S3"},
                                "water_eu": {"degraded_share": 0.10, "state": "S0"},
                            }
                        }
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    rows, warnings = extract_rows_from_payload(
        ScenarioPayload(
            scenario_id="scenario-a",
            scenario_label="Scenario A",
            parameter_key="param",
            status="completed",
            payload_path=payload_path,
            child_manifest_path=None,
        )
    )
    df = pd.DataFrame(rows)
    network_rows = df[df["metric"] == "network_state_pct"].copy()

    assert warnings == []
    assert network_rows.shape[0] == 6

    assert network_rows[
        (network_rows["service"] == "elec")
        & (network_rows["network_metric"] == "non_nominal_pct")
    ]["value"].iloc[0] == 25.0
    assert network_rows[
        (network_rows["service"] == "elec")
        & (network_rows["network_metric"] == "outage_pct")
    ]["value"].iloc[0] == 0.0
    assert network_rows[
        (network_rows["service"] == "water_aep")
        & (network_rows["network_metric"] == "non_nominal_pct")
    ]["value"].iloc[0] == 40.0
    assert network_rows[
        (network_rows["service"] == "water_aep")
        & (network_rows["network_metric"] == "outage_pct")
    ]["value"].iloc[0] == 40.0
    assert network_rows[
        (network_rows["service"] == "water_eu")
        & (network_rows["network_metric"] == "non_nominal_pct")
    ]["value"].iloc[0] == 0.0


def test_summarize_network_state_distribution_handles_nested_service_units() -> None:
    summary = summarize_network_state_distribution(
        {
            "unit-a": {"degraded_share": 0.10, "state": "S1", "asset_count": 40},
            "unit-b": {"degraded_share": 0.30, "state": "S3", "asset_count": 60},
        }
    )

    assert summary == (22.0, 18.0)


def test_clean_legacy_outputs_removes_curves_and_legacy_pngs(tmp_path: Path) -> None:
    curves_dir = tmp_path / "curves"
    curves_dir.mkdir()
    (curves_dir / "curve_old.png").write_text("legacy", encoding="utf-8")

    tornado_dir = tmp_path / "tornado"
    tornado_dir.mkdir()
    legacy_tornado = tornado_dir / "tornado_guadeloupe_storm_annual.png"
    legacy_tornado.write_text("legacy", encoding="utf-8")
    legacy_combined_delta = tornado_dir / "tornado_guadeloupe_delta_annual_rp50_rp100.png"
    legacy_combined_delta.write_text("legacy", encoding="utf-8")
    combined_tornado = tornado_dir / "tornado_guadeloupe_storm_annual_rp50_rp100.png"
    combined_tornado.write_text("new", encoding="utf-8")

    tornado_network_dir = tmp_path / "tornado-network-states"
    tornado_network_dir.mkdir()
    legacy_network = tornado_network_dir / "tornado_network_states_guadeloupe_storm_elec_non_nominal_pct.png"
    legacy_network.write_text("legacy", encoding="utf-8")

    clean_legacy_outputs(tmp_path)

    assert not curves_dir.exists()
    assert not legacy_tornado.exists()
    assert not legacy_combined_delta.exists()
    assert combined_tornado.exists()
    assert not legacy_network.exists()


def test_plot_tornado_combines_return_periods_and_keeps_top_25(
    tmp_path: Path,
    monkeypatch,
) -> None:
    rows: list[dict[str, object]] = []
    for return_period in ("annual", "rp50", "rp100"):
        rows.append(
            {
                "scenario_id": "all-default",
                "scenario_label": "Default",
                "parameter_key": "param",
                "parameter_value": "default",
                "territory": "guadeloupe",
                "hazard": "storm",
                "metric": "impact_eur",
                "return_period": return_period,
                "value": 100.0,
            }
        )

    for idx in range(30):
        for return_period, value in {
            "annual": 100.0 + idx,
            "rp50": 100.0 + idx / 2.0,
            "rp100": 100.0 + idx / 4.0,
        }.items():
            rows.append(
                {
                    "scenario_id": f"scenario-{idx}",
                    "scenario_label": f"Scenario {idx}",
                    "parameter_key": "param",
                    "parameter_value": str(idx),
                    "territory": "guadeloupe",
                    "hazard": "storm",
                    "metric": "impact_eur",
                    "return_period": return_period,
                    "value": value,
                }
            )

    df = add_baseline_deltas(pd.DataFrame(rows))
    captured_labels: list[list[str]] = []
    original = matplotlib.axes.Axes.set_yticklabels

    def spy(self, labels, *args, **kwargs):  # type: ignore[no-untyped-def]
        captured_labels.append(list(labels))
        return original(self, labels, *args, **kwargs)

    monkeypatch.setattr(matplotlib.axes.Axes, "set_yticklabels", spy)

    output_paths = plot_tornado(df, tmp_path)

    assert [path.name for path in output_paths] == ["tornado_guadeloupe_storm_annual_rp50_rp100.png"]
    assert output_paths[0].exists()
    assert captured_labels
    assert len(captured_labels[0]) == 25
    assert captured_labels[0][0] == "param = 5"
    assert captured_labels[0][-1] == "param = 29"


def test_plot_network_state_tornado_produces_two_combined_outputs(tmp_path: Path) -> None:
    rows: list[dict[str, object]] = []
    for hazard in ("storm", "storm_cmcc"):
        for service in ("elec", "water_aep", "water_eu"):
            for network_metric, baseline_value, scenario_value in (
                ("non_nominal_pct", 10.0, 16.0),
                ("outage_pct", 2.0, 4.5),
            ):
                rows.append(
                    {
                        "scenario_id": "all-default",
                        "scenario_label": "Default",
                        "parameter_key": "param",
                        "parameter_value": "default",
                        "territory": "guadeloupe",
                        "hazard": hazard,
                        "metric": "network_state_pct",
                        "return_period": "network_state",
                        "service": service,
                        "network_metric": network_metric,
                        "value": baseline_value,
                    }
                )
                rows.append(
                    {
                        "scenario_id": "scenario-a",
                        "scenario_label": "Scenario A",
                        "parameter_key": "param",
                        "parameter_value": "1",
                        "territory": "guadeloupe",
                        "hazard": hazard,
                        "metric": "network_state_pct",
                        "return_period": "network_state",
                        "service": service,
                        "network_metric": network_metric,
                        "value": scenario_value,
                    }
                )

    df = add_baseline_deltas(pd.DataFrame(rows))
    output_paths = plot_network_state_tornado(df, tmp_path)

    assert sorted(path.name for path in output_paths) == [
        "tornado_network_states_guadeloupe_combined_pct_reseaux_hors_s0.png",
        "tornado_network_states_guadeloupe_combined_pct_reseaux_s3.png",
    ]
    assert all(path.exists() for path in output_paths)
