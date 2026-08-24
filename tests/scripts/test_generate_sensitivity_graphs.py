from __future__ import annotations

import json
from pathlib import Path
import sys

import matplotlib.axes
import pandas as pd
import pytest

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
    build_impact_legend_spec,
    build_quality_report,
    build_scenario_metadata,
    clean_legacy_outputs,
    extract_rows_from_payload,
    filter_significant_scenarios,
    plot_delta_annual_tornado,
    plot_network_state_tornado,
    plot_portfolio_risk_tornado,
    plot_risk_index_tornado,
    plot_social_metric_tornado,
    plot_social_state_tornado,
    plot_super_impact_monetary_tornado,
    plot_super_network_state_tornado,
    plot_super_social_state_tornado,
    plot_tornado,
    resolve_scenario_payloads,
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


def test_resolve_scenario_payloads_requires_explicit_complete_analysis_path(tmp_path: Path) -> None:
    payload_path = tmp_path / "guadeloupe-complete-analysis.json"
    payload_path.write_text("{}", encoding="utf-8")

    resolved = resolve_scenario_payloads(
        {
            "scenarios": [
                {
                    "scenario_id": "all-default",
                    "label": "Default",
                    "parameter_key": "param",
                    "supported": True,
                    "status": "complete",
                    "complete_analysis_json_path": str(payload_path),
                }
            ]
        }
    )

    assert len(resolved) == 1
    assert resolved[0].payload_path == payload_path

    with pytest.raises(RuntimeError, match="missing complete_analysis_json_path"):
        resolve_scenario_payloads(
            {
                "scenarios": [
                    {
                        "scenario_id": "scenario-a",
                        "label": "Scenario A",
                        "parameter_key": "param",
                        "supported": True,
                        "status": "complete",
                    }
                ]
            }
        )


def test_resolve_scenario_payloads_skips_incomplete_scenarios(tmp_path: Path) -> None:
    payload_path = tmp_path / "guadeloupe-complete-analysis.json"
    payload_path.write_text("{}", encoding="utf-8")
    skipped: list[dict[str, str]] = []

    resolved = resolve_scenario_payloads(
        {
            "scenarios": [
                {
                    "scenario_id": "all-default",
                    "label": "Default",
                    "parameter_key": None,
                    "supported": True,
                    "status": "complete",
                    "complete_analysis_json_path": str(payload_path),
                },
                {
                    "scenario_id": "failed-scenario",
                    "label": "Failed",
                    "parameter_key": "param",
                    "supported": True,
                    "status": "failed",
                },
            ]
        },
        skipped_scenarios=skipped,
    )

    assert [scenario.scenario_id for scenario in resolved] == ["all-default"]
    assert skipped == [{"scenario_id": "failed-scenario", "reason": "status=failed"}]


def test_filter_significant_scenarios_keeps_network_significant_direct_state() -> None:
    common = {
        "territory": "guadeloupe",
        "hazard": "storm",
        "return_period": "annual",
        "scenario_label": "label",
        "parameter_value": "value",
    }
    df = pd.DataFrame(
        [
            {
                **common,
                "scenario_id": "all-default",
                "parameter_key": None,
                "metric": "impact_eur",
                "value": 1000.0,
            },
            {
                **common,
                "scenario_id": "runoff_coeff-0-1",
                "parameter_key": "runoff_coeff",
                "metric": "impact_eur",
                "value": 1040.0,
            },
            {
                **common,
                "scenario_id": "direct_state_thresholds-10-20-40",
                "parameter_key": "direct_state_thresholds",
                "metric": "impact_eur",
                "value": 1000.0,
            },
            {
                **common,
                "scenario_id": "territory_grid_deg-0-05",
                "parameter_key": "territory_grid_deg",
                "metric": "impact_eur",
                "value": 1000.5,
            },
            {
                **common,
                "scenario_id": "all-default",
                "parameter_key": None,
                "metric": "network_state_pct",
                "return_period": "network_state",
                "service": "elec",
                "network_metric": "non_nominal_pct",
                "value": 40.0,
            },
            {
                **common,
                "scenario_id": "runoff_coeff-0-1",
                "parameter_key": "runoff_coeff",
                "metric": "network_state_pct",
                "return_period": "network_state",
                "service": "elec",
                "network_metric": "non_nominal_pct",
                "value": 40.5,
            },
            {
                **common,
                "scenario_id": "direct_state_thresholds-10-20-40",
                "parameter_key": "direct_state_thresholds",
                "metric": "network_state_pct",
                "return_period": "network_state",
                "service": "elec",
                "network_metric": "non_nominal_pct",
                "value": 43.5,
            },
            {
                **common,
                "scenario_id": "territory_grid_deg-0-05",
                "parameter_key": "territory_grid_deg",
                "metric": "network_state_pct",
                "return_period": "network_state",
                "service": "elec",
                "network_metric": "non_nominal_pct",
                "value": 40.1,
            },
        ]
    )

    with_deltas = add_baseline_deltas(df)
    filtered, report = filter_significant_scenarios(
        with_deltas,
        impact_threshold_pct=3.0,
        network_threshold_pp=3.0,
    )

    assert set(filtered["scenario_id"]) == {
        "all-default",
        "runoff_coeff-0-1",
        "direct_state_thresholds-10-20-40",
    }
    assert "direct_state_thresholds-10-20-40" in report["selected_scenario_ids"]
    assert {
        item["scenario_id"]
        for item in report["excluded_scenarios"]
    } == {"territory_grid_deg-0-05"}


def test_summarize_network_state_distribution_handles_nested_service_units() -> None:
    summary = summarize_network_state_distribution(
        {
            "unit-a": {"degraded_share": 0.10, "state": "S1", "asset_count": 40},
            "unit-b": {"degraded_share": 0.30, "state": "S3", "asset_count": 60},
        }
    )

    assert summary == (22.0, 18.0)


def test_build_impact_legend_spec_includes_decrease_and_increase_swatches() -> None:
    handles, labels, title = build_impact_legend_spec()

    assert labels == ["Impact annuel moyen", "Impact RP50", "Impact RP100"]
    assert "diminution | augmentation" in title
    assert len(handles) == 3
    assert all(len(handle) == 2 for handle in handles)


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

    extended_dir = tmp_path / "tornado-portfolio-risk"
    extended_dir.mkdir()
    legacy_extended = extended_dir / "tornado_portfolio_pml_10.png"
    legacy_extended.write_text("legacy", encoding="utf-8")

    clean_legacy_outputs(tmp_path)

    assert not curves_dir.exists()
    assert not legacy_tornado.exists()
    assert not legacy_combined_delta.exists()
    assert combined_tornado.exists()
    assert not legacy_network.exists()
    assert not legacy_extended.exists()


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


def test_plot_delta_annual_tornado_produces_one_output(tmp_path: Path) -> None:
    rows: list[dict[str, object]] = []
    for hazard in ("delta", "storm", "storm_cmcc"):
        rows.append(
            {
                "scenario_id": "all-default",
                "scenario_label": "Default",
                "parameter_key": "param",
                "parameter_value": "default",
                "territory": "guadeloupe",
                "hazard": hazard,
                "metric": "impact_eur",
                "return_period": "annual",
                "value": 100.0,
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
                "metric": "impact_eur",
                "return_period": "annual",
                "value": 110.0,
            }
        )

    df = add_baseline_deltas(pd.DataFrame(rows))
    output_paths = plot_delta_annual_tornado(df, tmp_path)

    assert [path.name for path in output_paths] == ["tornado_guadeloupe_annual_all_hazards.png"]
    assert output_paths[0].exists()


def test_plot_portfolio_risk_tornado_produces_expected_outputs(tmp_path: Path) -> None:
    metadata_source = pd.DataFrame(
        [
            {
                "scenario_id": "all-default",
                "scenario_label": "Default",
                "parameter_key": "",
                "parameter_value": "default",
                "territory": "guadeloupe",
            },
            {
                "scenario_id": "scenario-a",
                "scenario_label": "Scenario A",
                "parameter_key": "param",
                "parameter_value": "1",
                "territory": "guadeloupe",
            },
        ]
    )
    scenario_metadata = build_scenario_metadata(metadata_source)
    rows: list[dict[str, object]] = []
    for scenario_id, multiplier in (("all-default", 1.0), ("scenario-a", 1.25)):
        for hazard in ("storm", "storm_cmcc"):
            rows.append(
                {
                    "scenario_id": scenario_id,
                    "hazard": hazard,
                    "percentile_99_loss_eur": 1000.0 * multiplier,
                    "pml_10_eur": 2000.0 * multiplier,
                    "pml_20_eur": 3000.0 * multiplier,
                    "pml_200_eur": 4000.0 * multiplier,
                    "pml_1000_eur": 5000.0 * multiplier,
                    "tvar_95_eur": 6000.0 * multiplier,
                }
            )

    output_paths = plot_portfolio_risk_tornado(pd.DataFrame(rows), scenario_metadata, "Guadeloupe", tmp_path)

    assert sorted(path.name for path in output_paths) == [
        "tornado_portfolio_percentile_99_loss.png",
        "tornado_portfolio_pml_10.png",
        "tornado_portfolio_pml_1000.png",
        "tornado_portfolio_pml_20.png",
        "tornado_portfolio_pml_200.png",
        "tornado_portfolio_tvar_95.png",
    ]
    assert all(path.exists() for path in output_paths)


def test_plot_social_and_risk_tornadoes_produce_expected_outputs(tmp_path: Path) -> None:
    metadata_source = pd.DataFrame(
        [
            {
                "scenario_id": "all-default",
                "scenario_label": "Default",
                "parameter_key": "",
                "parameter_value": "default",
                "territory": "guadeloupe",
            },
            {
                "scenario_id": "scenario-a",
                "scenario_label": "Scenario A",
                "parameter_key": "param",
                "parameter_value": "1",
                "territory": "guadeloupe",
            },
        ]
    )
    scenario_metadata = build_scenario_metadata(metadata_source)
    rows: list[dict[str, object]] = []
    for scenario_id, shift in (("all-default", 0.0), ("scenario-a", 100.0)):
        rows.append(
            {
                "scenario_id": scenario_id,
                "risk_index_storm": 2.0 + shift / 100.0,
                "risk_index_cmcc": 3.0 + shift / 100.0,
                "social_metrics": {
                    "storm": {
                        "population_without_water_aep": 1000.0 + shift,
                        "population_without_water_eu": 500.0 + shift,
                        "population_with_degraded_elec": 200.0 + shift,
                    },
                    "storm_cmcc": {
                        "population_without_water_aep": 1200.0 + shift,
                        "population_without_water_eu": 700.0 + shift,
                        "population_with_degraded_elec": 300.0 + shift,
                    },
                },
                "social_impact_population_state_distribution": {
                    "storm": {
                        "elec": {"S0": 50.0 + shift, "S1": 25.0 + shift},
                        "water_aep": {"S2": 40.0 + shift, "S3": 60.0 + shift},
                        "water_eu": {"S3": 30.0 + shift},
                    },
                    "storm_cmcc": {
                        "elec": {"S0": 45.0 + shift, "S1": 20.0 + shift},
                        "water_aep": {"S2": 35.0 + shift, "S3": 55.0 + shift},
                        "water_eu": {"S3": 25.0 + shift},
                    },
                },
            }
        )

    territory_df = pd.DataFrame(rows)
    social_outputs = plot_social_metric_tornado(territory_df, scenario_metadata, "Guadeloupe", tmp_path)
    state_outputs = plot_social_state_tornado(territory_df, scenario_metadata, "Guadeloupe", tmp_path)
    risk_outputs = plot_risk_index_tornado(territory_df, scenario_metadata, "Guadeloupe", tmp_path)

    assert sorted(path.name for path in social_outputs) == [
        "tornado_social_degraded_elec.png",
        "tornado_social_without_water_aep.png",
        "tornado_social_without_water_eu.png",
    ]
    assert sorted(path.name for path in state_outputs) == [
        "tornado_social_state_elec_s0.png",
        "tornado_social_state_elec_s1.png",
        "tornado_social_state_water_aep_s2.png",
        "tornado_social_state_water_aep_s3.png",
        "tornado_social_state_water_eu_s3.png",
    ]
    assert sorted(path.name for path in risk_outputs) == [
        "tornado_risk_index_max.png",
        "tornado_risk_index_mean.png",
    ]
    assert all(path.exists() for path in social_outputs + state_outputs + risk_outputs)


def test_plot_super_impact_monetary_tornado_filters_to_scenarios_above_two_percent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    rows: list[dict[str, object]] = []
    for hazard in ("storm", "storm_cmcc"):
        for return_period in ("annual", "rp50", "rp100"):
            rows.append(
                {
                    "scenario_id": "all-default",
                    "scenario_label": "Default",
                    "parameter_key": "param",
                    "parameter_value": "default",
                    "territory": "guadeloupe",
                    "hazard": hazard,
                    "metric": "impact_eur",
                    "return_period": return_period,
                    "value": 100.0,
                }
            )
    for scenario_id, multiplier in (("scenario-low", 1.01), ("scenario-high", 1.05)):
        for hazard in ("storm", "storm_cmcc"):
            for return_period in ("annual", "rp50", "rp100"):
                rows.append(
                    {
                        "scenario_id": scenario_id,
                        "scenario_label": scenario_id,
                        "parameter_key": "param",
                        "parameter_value": scenario_id,
                        "territory": "guadeloupe",
                        "hazard": hazard,
                        "metric": "impact_eur",
                        "return_period": return_period,
                        "value": 100.0 * multiplier,
                    }
                )

    df = add_baseline_deltas(pd.DataFrame(rows))
    captured_labels: list[list[str]] = []
    original = matplotlib.axes.Axes.set_yticklabels

    def spy(self, labels, *args, **kwargs):  # type: ignore[no-untyped-def]
        captured_labels.append(list(labels))
        return original(self, labels, *args, **kwargs)

    monkeypatch.setattr(matplotlib.axes.Axes, "set_yticklabels", spy)

    output_paths = plot_super_impact_monetary_tornado(df, tmp_path)

    assert [path.name for path in output_paths] == ["sensitivity_super_graph_1_impact_monetaire_guadeloupe.png"]
    assert output_paths[0].exists()
    assert captured_labels
    assert captured_labels[0] == ["param = scenario-high"]


def test_plot_super_network_state_tornado_filters_to_scenarios_above_two_points(
    tmp_path: Path,
    monkeypatch,
) -> None:
    rows: list[dict[str, object]] = []
    for hazard in ("storm", "storm_cmcc"):
        for service in ("elec", "water_aep", "water_eu"):
            for network_metric, baseline_value in (
                ("non_nominal_pct", 10.0),
                ("outage_pct", 3.0),
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
                        "scenario_id": "scenario-low",
                        "scenario_label": "Scenario low",
                        "parameter_key": "param",
                        "parameter_value": "low",
                        "territory": "guadeloupe",
                        "hazard": hazard,
                        "metric": "network_state_pct",
                        "return_period": "network_state",
                        "service": service,
                        "network_metric": network_metric,
                        "value": baseline_value + 1.5,
                    }
                )
                rows.append(
                    {
                        "scenario_id": "scenario-high",
                        "scenario_label": "Scenario high",
                        "parameter_key": "param",
                        "parameter_value": "high",
                        "territory": "guadeloupe",
                        "hazard": hazard,
                        "metric": "network_state_pct",
                        "return_period": "network_state",
                        "service": service,
                        "network_metric": network_metric,
                        "value": baseline_value + 3.0,
                    }
                )

    df = add_baseline_deltas(pd.DataFrame(rows))
    captured_labels: list[list[str]] = []
    original = matplotlib.axes.Axes.set_yticklabels

    def spy(self, labels, *args, **kwargs):  # type: ignore[no-untyped-def]
        captured_labels.append(list(labels))
        return original(self, labels, *args, **kwargs)

    monkeypatch.setattr(matplotlib.axes.Axes, "set_yticklabels", spy)

    output_paths = plot_super_network_state_tornado(df, tmp_path)

    assert [path.name for path in output_paths] == ["sensitivity_super_graph_2_pct_reseaux_guadeloupe.png"]
    assert output_paths[0].exists()
    assert captured_labels
    assert captured_labels[0] == ["param = high"]


def test_plot_super_social_state_tornado_splits_services_and_filters_significant_scenarios(
    tmp_path: Path,
    monkeypatch,
) -> None:
    metadata_source = pd.DataFrame(
        [
            {
                "scenario_id": "all-default",
                "scenario_label": "Default",
                "parameter_key": "",
                "parameter_value": "default",
                "territory": "guadeloupe",
            },
            {
                "scenario_id": "scenario-low",
                "scenario_label": "Scenario low",
                "parameter_key": "param",
                "parameter_value": "low",
                "territory": "guadeloupe",
            },
            {
                "scenario_id": "scenario-high",
                "scenario_label": "Scenario high",
                "parameter_key": "param",
                "parameter_value": "high",
                "territory": "guadeloupe",
            },
        ]
    )
    scenario_metadata = build_scenario_metadata(metadata_source)
    rows = [
        {
            "scenario_id": "all-default",
            "territory": "guadeloupe",
            "social_impact_population_state_distribution": {
                "storm": {
                    "elec": {"S1": 100.0, "S2": 60.0, "S3": 20.0},
                    "water_aep": {"S1": 70.0, "S2": 50.0, "S3": 30.0},
                    "water_eu": {"S1": 40.0, "S2": 25.0, "S3": 10.0},
                },
                "storm_cmcc": {
                    "elec": {"S1": 110.0, "S2": 70.0, "S3": 30.0},
                    "water_aep": {"S1": 80.0, "S2": 55.0, "S3": 35.0},
                    "water_eu": {"S1": 45.0, "S2": 28.0, "S3": 12.0},
                },
            },
        },
        {
            "scenario_id": "scenario-low",
            "territory": "guadeloupe",
            "social_impact_population_state_distribution": {
                "storm": {
                    "elec": {"S1": 101.0, "S2": 60.0, "S3": 20.0},
                    "water_aep": {"S1": 70.0, "S2": 50.0, "S3": 30.0},
                    "water_eu": {"S1": 40.0, "S2": 25.0, "S3": 10.0},
                },
                "storm_cmcc": {
                    "elec": {"S1": 111.0, "S2": 70.0, "S3": 30.0},
                    "water_aep": {"S1": 80.0, "S2": 55.0, "S3": 35.0},
                    "water_eu": {"S1": 45.0, "S2": 28.0, "S3": 12.0},
                },
            },
        },
        {
            "scenario_id": "scenario-high",
            "territory": "guadeloupe",
            "social_impact_population_state_distribution": {
                "storm": {
                    "elec": {"S1": 110.0, "S2": 66.0, "S3": 24.0},
                    "water_aep": {"S1": 77.0, "S2": 55.0, "S3": 36.0},
                    "water_eu": {"S1": 44.0, "S2": 30.0, "S3": 12.0},
                },
                "storm_cmcc": {
                    "elec": {"S1": 121.0, "S2": 77.0, "S3": 36.0},
                    "water_aep": {"S1": 88.0, "S2": 61.0, "S3": 42.0},
                    "water_eu": {"S1": 50.0, "S2": 31.0, "S3": 15.0},
                },
            },
        },
    ]

    captured_labels: list[list[str]] = []
    original = matplotlib.axes.Axes.set_yticklabels

    def spy(self, labels, *args, **kwargs):  # type: ignore[no-untyped-def]
        captured_labels.append(list(labels))
        return original(self, labels, *args, **kwargs)

    monkeypatch.setattr(matplotlib.axes.Axes, "set_yticklabels", spy)

    output_paths = plot_super_social_state_tornado(pd.DataFrame(rows), scenario_metadata, "Guadeloupe", tmp_path)

    assert [path.name for path in output_paths] == [
        "sensitivity_super_graph_3_social_states_aep_guadeloupe.png",
        "sensitivity_super_graph_3_social_states_eu_guadeloupe.png",
        "sensitivity_super_graph_3_social_states_elec_guadeloupe.png",
    ]
    assert all(path.exists() for path in output_paths)
    assert captured_labels
    assert ["param = high"] in captured_labels
