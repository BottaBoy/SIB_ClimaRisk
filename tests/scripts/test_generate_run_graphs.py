from pathlib import Path
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
    assert graph.png_payload["categories"] == ["Annual EAI", "PML100", "PML1000", "TVaR95", "P99"]


def test_load_auxiliary_artifacts_resolves_archived_inputs(tmp_path, monkeypatch):
    run_root = tmp_path / "runs" / "20260527_072457" / "territories" / "guadeloupe" / "web" / "data"
    run_root.mkdir(parents=True)
    (run_root / "guadeloupe-page7-analysis.json").write_text('{"hazard": {}, "impact": {}, "exposition": {}}', encoding="utf-8")
    (run_root / "guadeloupe-wind-maps.json").write_text('{"meta": {}, "storm": {}, "storm_cmcc": {}}', encoding="utf-8")
    (run_root / "guadeloupe-landslide-maps.json").write_text('{"meta": {}, "storm": {}, "storm_cmcc": {}}', encoding="utf-8")
    (run_root / "guadeloupe-network-states.geojson").write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")
    (run_root / "guadeloupe-water-infra.geojson").write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")
    monkeypatch.setattr(generate_run_graphs, "RUN_OUTPUTS_DIR", tmp_path / "runs")

    bundle = generate_run_graphs.TerritoryPayload(
        territory="guadeloupe",
        payload_path=str(run_root / "guadeloupe-complete-analysis.json"),
        payload={"portfolio_results": {}},
        source_kind="archived",
    )

    artifacts = generate_run_graphs._load_auxiliary_artifacts(_run_record(), bundle)

    assert artifacts.page7_analysis is not None
    assert artifacts.case_study_analysis is not None
    assert artifacts.wind_maps is not None
    assert artifacts.landslide_maps is not None
    assert artifacts.network_states_path is not None
    assert artifacts.water_infra_path is not None


def test_render_integrated_vincennes_assets_generates_outputs_and_warnings(tmp_path, monkeypatch):
    output_dir = tmp_path / "graphs"
    stale_chart = output_dir / "charts" / "stale.png"
    stale_chart.parent.mkdir(parents=True)
    stale_chart.write_text("old", encoding="utf-8")

    record = generate_run_graphs.RunRecord(
        run_id="20260615_191554",
        status="success",
        created_at=None,
        updated_at=None,
        territories=["saint-barthelemy"],
        dynamic_max_tracks=None,
        memory_budget_gb=None,
        manifest_path="/tmp/manifest.json",
        manifest={"territories": {"saint-barthelemy": {}}},
        archived_ready_count=1,
    )
    payloads = {
        "saint-barthelemy": generate_run_graphs.TerritoryPayload(
            territory="saint-barthelemy",
            payload_path="/tmp/saint-barthelemy-complete-analysis.json",
            payload={},
            source_kind="archived",
        )
    }

    artifacts = generate_run_graphs.AuxiliaryArtifacts(
        territory="saint-barthelemy",
        complete_analysis=generate_run_graphs.ArchivedArtifact("/tmp/complete.json", {}),
        page7_analysis=None,
        case_study_analysis=None,
        wind_maps=None,
        landslide_maps=None,
        network_states_path=None,
        water_infra_path=None,
    )

    monkeypatch.setattr(generate_run_graphs, "_load_auxiliary_artifacts", lambda record, bundle: artifacts)
    monkeypatch.setattr(generate_run_graphs, "_load_matplotlib", lambda: (None, object()))

    def _fake_render(_plt, output_path, payload):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(str(payload.get("title") or "ok"), encoding="utf-8")

    def _fake_csv(output_path, headers, rows):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(",".join(headers) + "\n", encoding="utf-8")

    monkeypatch.setattr(generate_run_graphs, "_render_auxiliary_output", _fake_render)
    monkeypatch.setattr(generate_run_graphs, "_write_csv_table", _fake_csv)
    monkeypatch.setattr(
        generate_run_graphs,
        "_build_wind_hist_payload",
        lambda artifacts, hist_key, title: {"type": "grouped_bar", "title": title, "categories": ["1"], "series": [{"name": "x", "values": [1], "color": "#000"}]},
    )
    monkeypatch.setattr(generate_run_graphs, "_build_damage_scenario_payload", lambda *args, **kwargs: None)
    monkeypatch.setattr(generate_run_graphs, "_build_total_damage_by_return_period_payload", lambda *args, **kwargs: None)
    monkeypatch.setattr(generate_run_graphs, "_build_network_state_chart_payload", lambda *args, **kwargs: None)
    monkeypatch.setattr(generate_run_graphs, "_build_network_state_distribution_payload", lambda *args, **kwargs: None)
    monkeypatch.setattr(generate_run_graphs, "_build_hazard_comparison_csv_rows", lambda artifacts: (["indicator", "storm"], [["A", "1"]]))
    monkeypatch.setattr(generate_run_graphs, "_build_impact_table_payload", lambda *args, **kwargs: None)
    monkeypatch.setattr(generate_run_graphs, "_build_exposure_network_table_payload", lambda *args, **kwargs: None)
    monkeypatch.setattr(generate_run_graphs, "_build_exposure_ouvrage_table_payload", lambda *args, **kwargs: None)
    monkeypatch.setattr(generate_run_graphs, "_build_hazard_comparison_table_payload", lambda *args, **kwargs: None)
    monkeypatch.setattr(generate_run_graphs, "_build_social_impact_table_payload", lambda *args, **kwargs: None)
    monkeypatch.setattr(generate_run_graphs, "_build_population_coverage_table_payload", lambda *args, **kwargs: None)
    monkeypatch.setattr(generate_run_graphs, "_build_hazard_cell_points", lambda *args, **kwargs: [])
    monkeypatch.setattr(generate_run_graphs, "_build_landslide_points", lambda *args, **kwargs: [])

    paths, warnings = generate_run_graphs._render_integrated_vincennes_assets(record, payloads, output_dir)

    relative_paths = sorted(Path(path).relative_to(output_dir).as_posix() for path in paths)
    assert "charts/saint-barthelemy_vent_max_par_annee.png" in relative_paths
    assert "charts/saint-barthelemy_vent_max_par_evenement.png" in relative_paths
    assert "tables/saint-barthelemy_comparaison_aleas.csv" in relative_paths
    assert not stale_chart.exists()
    assert any("degats_eau_par_scenario_labels" in warning for warning in warnings)


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


def test_build_wind_hist_payload_uses_line_annotations_without_zero_labels() -> None:
    artifacts = generate_run_graphs.AuxiliaryArtifacts(
        territory="saint-barthelemy",
        complete_analysis=generate_run_graphs.ArchivedArtifact("/tmp/complete.json", {}),
        page7_analysis=generate_run_graphs.ArchivedArtifact(
            "/tmp/page7.json",
            {
                "hazard": {
                    "wind_histograms": {
                        "storm": {"track_max_hist": {"bins_mps": [60.0, 61.0], "percent": [0.0, 5.0]}},
                        "storm_cmcc": {"track_max_hist": {"bins_mps": [60.0, 61.0], "percent": [1.5, 0.0]}},
                    }
                }
            },
        ),
        case_study_analysis=None,
        wind_maps=None,
        landslide_maps=None,
        network_states_path=None,
        water_infra_path=None,
    )

    payload = generate_run_graphs._build_wind_hist_payload(artifacts, "track_max_hist", "Vent max")

    assert payload is not None
    assert payload["type"] == "line"
    assert payload["xlabel"] == "Vent maximum (km/h)"
    assert payload["series"][0]["x"] == [216.0, 219.6]
    assert payload["series"][0]["annotations"] == ["", "5 %"]
    assert payload["series"][1]["annotations"] == ["1.5 %", ""]


def test_build_network_state_chart_payload_uses_percentages(monkeypatch: pytest.MonkeyPatch) -> None:
    artifacts = generate_run_graphs.AuxiliaryArtifacts(
        territory="guadeloupe",
        complete_analysis=generate_run_graphs.ArchivedArtifact("/tmp/complete.json", {}),
        page7_analysis=None,
        case_study_analysis=None,
        wind_maps=None,
        landslide_maps=None,
        network_states_path="/tmp/network.geojson",
        water_infra_path=None,
    )

    counts_by_hazard = {
        "storm": {"S0": 2, "S1": 1, "S2": 1, "S3": 0},
        "storm_cmcc": {"S0": 1, "S1": 1, "S2": 0, "S3": 2},
    }

    def _fake_state_counts(_artifacts, **kwargs):
        return counts_by_hazard[kwargs["hazard"]]

    monkeypatch.setattr(generate_run_graphs, "_state_counts_for_metric", _fake_state_counts)

    payload = generate_run_graphs._build_network_state_chart_payload(artifacts, "aep", "p99", "Etat")

    assert payload is not None
    assert payload["ylabel"] == "% des reseaux"
    assert payload["series"][0]["color"] == "#68b66e"
    assert payload["series"][0]["name"] == "Opérationnel (S0)"
    assert payload["series"][0]["values"] == [50.0, 25.0]
    assert payload["series"][3]["name"] == "Hors service (S3)"
    assert payload["series"][3]["color"] == "#000000"
    assert payload["series"][3]["values"] == [0.0, 50.0]


def test_build_damage_scenario_payload_adds_damage_share_labels() -> None:
    artifacts = generate_run_graphs.AuxiliaryArtifacts(
        territory="guadeloupe",
        complete_analysis=generate_run_graphs.ArchivedArtifact("/tmp/complete.json", {}),
        page7_analysis=generate_run_graphs.ArchivedArtifact(
            "/tmp/page7.json",
            {
                "impact": {
                    "damage_breakdown_by_scenario": {
                        "annual": {
                            "storm": [
                                {"class_key": "eau_aep", "class_label": "Eau AEP", "exposure_eur": 1_000.0, "damage_eur": 250.0},
                                {"class_key": "eau_eu", "class_label": "Eau EU", "exposure_eur": 500.0, "damage_eur": 50.0},
                            ],
                            "storm_cmcc": [
                                {"class_key": "eau_aep", "class_label": "Eau AEP", "exposure_eur": 1_000.0, "damage_eur": 300.0},
                                {"class_key": "eau_eu", "class_label": "Eau EU", "exposure_eur": 500.0, "damage_eur": 25.0},
                            ],
                        }
                    }
                }
            },
        ),
        case_study_analysis=None,
        wind_maps=None,
        landslide_maps=None,
        network_states_path=None,
        water_infra_path=None,
    )

    payload = generate_run_graphs._build_damage_scenario_payload(artifacts, "water", "Degats eau")

    assert payload is not None
    assert payload["label_texts"][0][0] == "250.00 EUR\n(25.00% valeur)"
    assert payload["label_texts"][1][1] == "25.00 EUR\n(5.00% valeur)"


def test_build_total_damage_by_return_period_payload_adds_family_share_labels() -> None:
    artifacts = generate_run_graphs.AuxiliaryArtifacts(
        territory="guadeloupe",
        complete_analysis=generate_run_graphs.ArchivedArtifact("/tmp/complete.json", {}),
        page7_analysis=generate_run_graphs.ArchivedArtifact(
            "/tmp/page7.json",
            {
                "impact": {
                    "damage_breakdown_by_scenario": {
                        "annual": {
                            "storm": [{"class_key": "eau_aep", "damage_eur": 35.0}],
                            "storm_cmcc": [{"class_key": "eau_aep", "damage_eur": 17.5}],
                        },
                        "rp50": {
                            "storm": [{"class_key": "eau_aep", "damage_eur": 70.0}],
                            "storm_cmcc": [{"class_key": "eau_aep", "damage_eur": 35.0}],
                        },
                        "rp100": {
                            "storm": [{"class_key": "eau_aep", "damage_eur": 140.0}],
                            "storm_cmcc": [{"class_key": "eau_aep", "damage_eur": 70.0}],
                        },
                        "p99": {
                            "storm": [{"class_key": "eau_aep", "damage_eur": 280.0}],
                            "storm_cmcc": [{"class_key": "eau_aep", "damage_eur": 140.0}],
                        },
                    }
                },
                "exposition": {
                    "total_value_by_type_eur": {
                        "eau_aep": 700.0,
                        "eau_eu": 700.0,
                    }
                },
            },
        ),
        case_study_analysis=None,
        wind_maps=None,
        landslide_maps=None,
        network_states_path=None,
        water_infra_path=None,
    )

    payload = generate_run_graphs._build_total_damage_by_return_period_payload(artifacts, "water", "Degats eau")

    assert payload is not None
    assert payload["label_texts"][0][0] == "35.00 EUR\n(2.50% valeur)"
    assert payload["label_texts"][0][3] == "280.00 EUR\n(20.00% valeur)"
    assert payload["label_texts"][1][1] == "35.00 EUR\n(2.50% valeur)"


def test_resolve_grouped_bar_ymax_adds_headroom_for_multiline_labels() -> None:
    payload = {
        "show_labels": True,
        "series": [
            {"values": [100.0]},
            {"values": [80.0]},
        ],
        "label_texts": [["100.00 EUR\n(10.00% valeur)"], ["80.00 EUR\n(8.00% valeur)"]],
    }

    ymax = generate_run_graphs._resolve_grouped_bar_ymax(payload)

    assert ymax > 120.0


def test_network_filter_config_supports_aggregated_electric_grid() -> None:
    layer_keys, network_kinds = generate_run_graphs._network_filter_config("elec")

    assert layer_keys is not None
    assert "elec_grid_0p1deg" in layer_keys
    assert "elec_bt_aerien" in layer_keys
    assert network_kinds is None


def test_build_annual_fec_graph_combines_selected_hazards(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_curve(_record, _territory, _payload, hazard):
        if hazard == "storm":
            return [10.0, 100.0], [1_000.0, 5_000.0], [], None
        return [10.0, 100.0], [2_000.0, 6_000.0], [], None

    monkeypatch.setattr(generate_run_graphs, "_resolve_annual_fec_curve", _fake_curve)
    monkeypatch.setattr(generate_run_graphs, "_resolve_total_exposure_value", lambda *_args, **_kwargs: 10_000.0)

    graph = generate_run_graphs.build_annual_fec_graph(
        _run_record(),
        "guadeloupe",
        {"portfolio_results": {}},
        ["storm", "storm_cmcc"],
    )

    assert graph is not None
    assert graph.graph_id == "annual_fec_by_territory_hazard__guadeloupe"
    assert graph.hazard is None
    assert graph.png_payload is not None
    assert len(graph.png_payload["series"]) == 2
    assert graph.png_payload["series"][0]["name"] == "STORM"
    assert graph.png_payload["series"][1]["name"] == "STORM_CMCC"


def test_adaptive_geo_linewidth_keeps_base_width_for_lines() -> None:
    class _Frame:
        total_bounds = [0.0, 0.0, 1000.0, 1000.0]
        geom_type = ["LineString"]

    assert generate_run_graphs._adaptive_geo_linewidth(_Frame(), base_width=1.4) == 1.4


def test_adaptive_geo_linewidth_reduces_for_tight_polygon_extent() -> None:
    class _Frame:
        total_bounds = [0.0, 0.0, 1000.0, 1000.0]
        geom_type = ["Polygon"]

    assert generate_run_graphs._adaptive_geo_linewidth(_Frame(), base_width=1.4) == 0.22


def test_swap_state_surfaces_for_source_lines_prefers_matching_line_geometries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import LineString, Polygon

    state_gdf = gpd.GeoDataFrame(
        {
            "feature_id": ["EU_1"],
            "state_p99_storm": ["S2"],
        },
        geometry=[Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])],
        crs="EPSG:3857",
    )
    source_gdf = gpd.GeoDataFrame(
        {
            "feature_id": ["EU_1"],
            "infra_type": ["eu_cana"],
        },
        geometry=[LineString([(0, 0), (2, 0)])],
        crs="EPSG:3857",
    )

    monkeypatch.setattr(generate_run_graphs, "_load_geodataframe_cached", lambda _path: source_gdf.copy())

    swapped = generate_run_graphs._swap_state_surfaces_for_source_lines(
        state_gdf,
        {
            "state_column": "state_p99_storm",
            "source_geojson_path": "/tmp/source.geojson",
            "filter_values": ["eau_eu"],
        },
    )

    assert list(swapped.geom_type) == ["LineString"]
    assert list(swapped["feature_id"]) == ["EU_1"]
    assert list(swapped["state_p99_storm"]) == ["S2"]


def test_swap_state_surfaces_for_source_lines_accepts_aggregated_electric_grid_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import LineString, Polygon

    state_gdf = gpd.GeoDataFrame(
        {
            "feature_id": ["cell-1"],
            "state_p99_storm": ["S1"],
        },
        geometry=[Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])],
        crs="EPSG:3857",
    )
    source_gdf = gpd.GeoDataFrame(
        {
            "feature_id": ["line-1"],
            "infra_type": ["elec_bt_aerien"],
        },
        geometry=[LineString([(0, 0), (2, 0)])],
        crs="EPSG:3857",
    )

    monkeypatch.setattr(generate_run_graphs, "_load_geodataframe_cached", lambda _path: source_gdf.copy())

    swapped = generate_run_graphs._swap_state_surfaces_for_source_lines(
        state_gdf,
        {
            "state_column": "state_p99_storm",
            "source_geojson_path": "/tmp/source.geojson",
            "filter_values": ["elec_grid_0p1deg"],
        },
    )

    assert list(swapped.geom_type) == ["LineString"]
    assert list(swapped["feature_id"]) == ["line-1"]
    assert list(swapped["state_p99_storm"]) == ["S1"]


def test_build_network_state_matrix_payload_aggregates_electric_air_and_underground() -> None:
    def _row(
        class_key: str,
        storm_pct: dict[str, float],
        cmcc_pct: dict[str, float],
        exposure: float,
    ) -> dict[str, object]:
        return {
            "class_key": class_key,
            "class_label": class_key,
            "storm": {"state_pct": storm_pct, "exposure_eur": exposure},
            "storm_cmcc": {"state_pct": cmcc_pct, "exposure_eur": exposure},
        }

    scenario_rows = [
        _row("eau_aep", {"S0": 100.0, "S1": 0.0, "S2": 0.0, "S3": 0.0}, {"S0": 90.0, "S1": 10.0, "S2": 0.0, "S3": 0.0}, 400.0),
        _row("eau_eu", {"S0": 80.0, "S1": 20.0, "S2": 0.0, "S3": 0.0}, {"S0": 70.0, "S1": 30.0, "S2": 0.0, "S3": 0.0}, 300.0),
        _row("elec_bt_aerien", {"S0": 100.0, "S1": 0.0, "S2": 0.0, "S3": 0.0}, {"S0": 50.0, "S1": 50.0, "S2": 0.0, "S3": 0.0}, 100.0),
        _row("elec_hta_aerien", {"S0": 0.0, "S1": 100.0, "S2": 0.0, "S3": 0.0}, {"S0": 0.0, "S1": 0.0, "S2": 100.0, "S3": 0.0}, 50.0),
        _row("elec_bt_souterrain", {"S0": 60.0, "S1": 40.0, "S2": 0.0, "S3": 0.0}, {"S0": 40.0, "S1": 60.0, "S2": 0.0, "S3": 0.0}, 80.0),
        _row("elec_hta_souterrain", {"S0": 20.0, "S1": 80.0, "S2": 0.0, "S3": 0.0}, {"S0": 0.0, "S1": 100.0, "S2": 0.0, "S3": 0.0}, 40.0),
    ]
    artifacts = generate_run_graphs.AuxiliaryArtifacts(
        territory="guadeloupe",
        complete_analysis=generate_run_graphs.ArchivedArtifact("/tmp/complete.json", {}),
        page7_analysis=generate_run_graphs.ArchivedArtifact(
            "/tmp/page7.json",
            {
                "impact": {
                    "state_damage_tables": {
                        "annual": scenario_rows,
                        "rp50": scenario_rows,
                        "rp100": scenario_rows,
                        "p99": scenario_rows,
                    }
                },
                "exposition": {
                    "lengths_km": {
                        "elec_bt_aerien": 3.0,
                        "elec_hta_aerien": 1.0,
                        "elec_bt_souterrain": 2.0,
                        "elec_hta_souterrain": 1.0,
                    }
                },
            },
        ),
        case_study_analysis=None,
        wind_maps=None,
        landslide_maps=None,
        network_states_path=None,
        water_infra_path=None,
    )

    payload = generate_run_graphs._build_network_state_matrix_payload(artifacts, "storm", "Matrice")

    assert payload is not None
    assert payload["row_titles"] == ["Annuel", "RP50", "RP100", "P99"]
    assert payload["column_titles"][2] == "Etats reseaux elec aerien"
    assert payload["cells"][0][2]["S0"] == pytest.approx(75.0)
    assert payload["cells"][0][2]["S1"] == pytest.approx(25.0)
    assert payload["cells"][0][3]["S0"] == pytest.approx(46.667, rel=1e-4)
    assert payload["cells"][0][3]["S1"] == pytest.approx(53.333, rel=1e-4)
    assert "Opérationnel (S0)" in payload["note"]
    assert "Hors service (S3)" in payload["note"]


def test_thin_zoomed_surface_network_geometries_reduces_polygon_area() -> None:
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import Polygon

    gdf = gpd.GeoDataFrame(
        {"feature_id": ["EU_1"]},
        geometry=[Polygon([(0, 0), (200, 0), (200, 120), (0, 120)])],
        crs="EPSG:3857",
    )

    thinned = generate_run_graphs._thin_zoomed_surface_network_geometries(gdf)

    assert float(thinned.area.sum()) < float(gdf.area.sum())


def test_normalize_territory_supports_saint_barthelemy_aliases() -> None:
    assert generate_run_graphs._normalize_territory("stb") == "saint-barthelemy"
    assert generate_run_graphs._normalize_territory("blm") == "saint-barthelemy"
