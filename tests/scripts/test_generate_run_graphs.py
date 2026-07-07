import json
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
    assert graph.png_payload["categories"] == ["EAI annuel", "PML100", "PML1000", "TVaR95", "P99"]


def test_build_pml_ladder_graph_combines_storm_and_cmcc():
    payload = {
        "portfolio_results": {
            "storm": {
                "pml_10_eur": 10.0,
                "pml_20_eur": 20.0,
                "pml_50_eur": 50.0,
                "pml_100_eur": 100.0,
                "pml_200_eur": 200.0,
                "pml_1000_eur": 1000.0,
            },
            "storm_cmcc": {
                "pml_10_eur": 12.0,
                "pml_20_eur": 22.0,
                "pml_50_eur": 55.0,
                "pml_100_eur": 110.0,
                "pml_200_eur": 220.0,
                "pml_1000_eur": 1110.0,
            },
        }
    }

    graph = generate_run_graphs.build_pml_ladder_graph("guadeloupe", payload, ["storm", "storm_cmcc"])

    assert graph is not None
    assert graph.hazard is None
    assert graph.png_payload["type"] == "grouped_bar"
    assert [series["name"] for series in graph.png_payload["series"]] == ["STORM", "STORM_CMCC"]


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
    assert artifacts.population_overlays is not None
    assert artifacts.population_raster_path is not None
    assert artifacts.hydraulic_zones_path is not None


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
        lambda artifacts, hist_key, title, point_divisor=1: {"type": "grouped_bar", "title": title, "categories": ["1"], "series": [{"name": "x", "values": [1], "color": "#000"}]},
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
    assert "charts/saint-barthelemy_vent_max_par_annee_1_point_sur_2.png" in relative_paths
    assert "charts/saint-barthelemy_vent_max_par_evenement_1_point_sur_2.png" in relative_paths
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
        str(output_dir / "Population" / "carte_population_guadeloupe.png"),
        str(output_dir / "Population" / "matrice_population_etats_reseaux_storm.png"),
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
        "chart": 3,
        "map": 2,
        "table": 1,
    }
    assert generate_run_graphs._count_generated_outputs(records, "family") == {
        "alea": 2,
        "exposition": 1,
        "impact": 2,
        "synthese": 1,
    }


def test_build_population_output_specs_returns_guadeloupe_pack(monkeypatch):
    artifacts = generate_run_graphs.AuxiliaryArtifacts(
        territory="guadeloupe",
        complete_analysis=generate_run_graphs.ArchivedArtifact("/tmp/complete.json", {"territory_results": []}),
        page7_analysis=None,
        case_study_analysis=None,
        wind_maps=None,
        landslide_maps=None,
        network_states_path="/tmp/network.geojson",
        water_infra_path="/tmp/water.geojson",
        population_overlays=generate_run_graphs.ArchivedArtifact("/tmp/population-overlays.json", {"territories": []}),
        population_raster_path="/tmp/glp.tif",
        hydraulic_zones_path="/tmp/hydraulic.gpkg",
    )
    monkeypatch.setattr(generate_run_graphs, "_build_population_overlay_map_payload", lambda *args, **kwargs: {"type": "raster_overlay_map", "title": "population"})
    monkeypatch.setattr(generate_run_graphs, "_build_population_hotspot_superplot_payload", lambda *args, **kwargs: {"type": "choropleth_map_grid", "title": kwargs.get("title") or args[1]})
    monkeypatch.setattr(generate_run_graphs, "_build_hydraulic_population_importance_payload", lambda *args, **kwargs: {"type": "choropleth_map", "title": kwargs.get("title") or args[1]})
    monkeypatch.setattr(generate_run_graphs, "_build_population_state_matrix_payload", lambda *args, **kwargs: {"type": "population_state_matrix", "title": kwargs.get("title") or args[2]})

    specs = generate_run_graphs._build_population_output_specs(artifacts)

    assert [name for name, _payload in specs] == [
        "carte_population_guadeloupe.png",
        "superplot_hotspots_population_affectee.png",
        "importance_zonages_hydrauliques_aep.png",
        "matrice_population_etats_reseaux_storm.png",
        "matrice_population_etats_reseaux_storm_cmcc.png",
    ]


def test_build_population_hotspot_superplot_payload_matches_total_affected_population(monkeypatch):
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import Point

    artifacts = generate_run_graphs.AuxiliaryArtifacts(
        territory="guadeloupe",
        complete_analysis=generate_run_graphs.ArchivedArtifact(
            "/tmp/complete.json",
            {
                "territory_results": [
                    {"territory_id": "cell-+16.20_-61.60", "population_total": 100.0},
                    {"territory_id": "cell-+16.40_-61.40", "population_total": 50.0},
                ]
            },
        ),
        page7_analysis=None,
        case_study_analysis=None,
        wind_maps=None,
        landslide_maps=None,
        network_states_path="/tmp/network.geojson",
        water_infra_path=None,
        population_overlays=generate_run_graphs.ArchivedArtifact(
            "/tmp/population-overlays.json",
            {"territories": [{"code": "glp", "bounds": {"west": -61.7, "east": -61.3, "south": 16.1, "north": 16.5}}]},
        ),
        population_raster_path="/tmp/glp.tif",
    )
    features = gpd.GeoDataFrame(
        [
            {
                "feature_id": "aep-zone-1",
                "layer_key": "eau_aep",
                "state_annual_storm": "S0",
                "state_rp50_storm": "S0",
                "state_rp100_storm": "S3",
                "state_p99_storm": "S0",
                "state_annual_storm_cmcc": "S0",
                "state_rp50_storm_cmcc": "S0",
                "state_rp100_storm_cmcc": "S1",
                "state_p99_storm_cmcc": "S0",
                "geometry": Point(-61.60, 16.20).buffer(0.03),
            },
            {
                "feature_id": "elec-line-1",
                "layer_key": "elec_bt_aerien",
                "state_annual_storm": "S0",
                "state_rp50_storm": "S0",
                "state_rp100_storm": "S2",
                "state_p99_storm": "S0",
                "state_annual_storm_cmcc": "S0",
                "state_rp50_storm_cmcc": "S0",
                "state_rp100_storm_cmcc": "S2",
                "state_p99_storm_cmcc": "S0",
                "geometry": Point(-61.40, 16.40).buffer(0.03),
            },
        ],
        geometry="geometry",
        crs="EPSG:4326",
    )
    hotspot_grid = gpd.GeoDataFrame(
        [
            {"grid_cell_id": "cell-+16.20_-61.60", "population_total": 100.0, "geometry": Point(-61.60, 16.20).buffer(0.01)},
            {"grid_cell_id": "cell-+16.40_-61.40", "population_total": 50.0, "geometry": Point(-61.40, 16.40).buffer(0.01)},
        ],
        geometry="geometry",
        crs="EPSG:4326",
    )
    monkeypatch.setattr(generate_run_graphs, "_load_geodataframe_cached", lambda path: features.copy())
    monkeypatch.setattr(generate_run_graphs, "_build_population_grid_geodataframe", lambda *args, **kwargs: hotspot_grid.copy())

    hotspot_payload = generate_run_graphs._build_population_hotspot_superplot_payload(
        artifacts,
        "Guadeloupe - Hotspots",
    )
    matrix_payload = generate_run_graphs._build_population_state_matrix_payload(
        artifacts,
        "storm",
        "Guadeloupe - Matrice",
    )

    assert hotspot_payload is not None
    assert matrix_payload is not None
    rp100_storm_gdf = hotspot_payload["cells"][0][2]["gdf"]
    assert rp100_storm_gdf["affected_population"].sum() == pytest.approx(150.0)
    first_cell = matrix_payload["cells"][2][0]
    assert sum(first_cell.values()) == pytest.approx(100.0, abs=1e-6)


def test_hydraulic_population_importance_propagates_zone_uid(monkeypatch):
    gpd = pytest.importorskip("geopandas")
    np = pytest.importorskip("numpy")
    from types import SimpleNamespace
    from shapely.geometry import Polygon

    zones = gpd.GeoDataFrame(
        [
            {"zone_uid": "A", "network_kind": "AEP", "geometry": Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])},
            {"zone_uid": "A", "network_kind": "AEP", "geometry": Polygon([(1, 0), (2, 0), (2, 1), (1, 1)])},
            {"zone_uid": "B", "network_kind": "AEP", "geometry": Polygon([(0, 1), (1, 1), (1, 2), (0, 2)])},
        ],
        geometry="geometry",
        crs="EPSG:4326",
    )
    artifacts = generate_run_graphs.AuxiliaryArtifacts(
        territory="guadeloupe",
        complete_analysis=generate_run_graphs.ArchivedArtifact("/tmp/complete.json", {"territory_results": []}),
        page7_analysis=None,
        case_study_analysis=None,
        wind_maps=None,
        landslide_maps=None,
        network_states_path=None,
        water_infra_path=None,
        population_raster_path="/tmp/glp.tif",
        hydraulic_zones_path="/tmp/hydraulic.gpkg",
    )

    class _FakeSrc:
        nodata = None
        crs = "EPSG:4326"

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _FakeRasterio:
        def __init__(self):
            self.calls = 0

        def open(self, path):
            return _FakeSrc()

        def _mask(self, src, geometries, crop=True, filled=False):
            self.calls += 1
            value = 10.0 if self.calls == 1 else 20.0
            return np.ma.array([[[value]]]), None

    fake_rasterio = _FakeRasterio()
    monkeypatch.setattr(generate_run_graphs, "_load_geodataframe_layer_cached", lambda path, layer=None: zones.copy())
    monkeypatch.setattr(generate_run_graphs, "_load_rasterio", lambda: SimpleNamespace(open=fake_rasterio.open, mask=SimpleNamespace(mask=fake_rasterio._mask)))

    payload = generate_run_graphs._build_hydraulic_population_importance_payload(
        artifacts,
        "Guadeloupe - Hydro",
    )

    assert payload is not None
    values = payload["gdf"].groupby("zone_uid")["dependent_population"].unique().to_dict()
    assert values["A"].tolist() == [10.0]
    assert values["B"].tolist() == [20.0]


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
    assert payload["legacy_line_layout"] is True
    assert payload["series"][0]["x"] == [216.0, 219.6]
    assert payload["series"][0]["annotations"] == ["", "5 %"]
    assert payload["series"][1]["annotations"] == ["1.5 %", ""]


def test_build_wind_hist_payload_downsamples_to_one_point_out_of_two() -> None:
    artifacts = generate_run_graphs.AuxiliaryArtifacts(
        territory="guadeloupe",
        complete_analysis=generate_run_graphs.ArchivedArtifact("/tmp/complete.json", {}),
        page7_analysis=generate_run_graphs.ArchivedArtifact(
            "/tmp/page7.json",
            {
                "hazard": {
                    "wind_histograms": {
                        "storm": {"track_max_hist": {"bins_mps": [60.0, 61.0, 62.0, 63.0, 64.0, 65.0], "percent": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]}},
                        "storm_cmcc": {"track_max_hist": {"bins_mps": [60.0, 61.0, 62.0, 63.0, 64.0, 65.0], "percent": [6.0, 5.0, 4.0, 3.0, 2.0, 1.0]}},
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

    payload = generate_run_graphs._build_wind_hist_payload(
        artifacts,
        "track_max_hist",
        "Vent max",
        point_divisor=2,
    )

    assert payload is not None
    assert payload["series"][0]["x"] == [216.0, 223.2, 234.0]
    assert payload["series"][0]["y"] == [1.0, 3.0, 6.0]
    assert payload["series"][0]["annotations"] == ["1 %", "3 %", "6 %"]
    assert payload["series"][1]["y"] == [6.0, 4.0, 1.0]
    assert "un point sur deux" in payload["note"]


def test_build_hazard_supergraph_payload_uses_blue_red_wind_scale() -> None:
    artifacts = generate_run_graphs.AuxiliaryArtifacts(
        territory="guadeloupe",
        complete_analysis=generate_run_graphs.ArchivedArtifact("/tmp/complete.json", {}),
        page7_analysis=None,
        case_study_analysis=None,
        wind_maps=generate_run_graphs.ArchivedArtifact(
            "/tmp/wind.json",
            {
                "storm": {
                    "cells": [
                        {
                            "lat": 16.2,
                            "lon": -61.5,
                            "rp50_wind_mps": 35.0,
                            "rp100_wind_mps": 42.0,
                            "rp50_rain_mm": 120.0,
                            "rp100_rain_mm": 180.0,
                            "rp50_surge_m": 1.2,
                            "rp100_surge_m": 2.0,
                        }
                    ]
                }
            },
        ),
        landslide_maps=generate_run_graphs.ArchivedArtifact(
            "/tmp/landslide.json",
            {"storm": {"cells": [{"lat": 16.2, "lon": -61.5, "mean_landslide_score": 0.7}]}},
        ),
        network_states_path=None,
        water_infra_path=None,
    )

    map_payloads = generate_run_graphs._build_hazard_scatter_map_payloads(artifacts, "guadeloupe")
    supergraph = generate_run_graphs._build_guadeloupe_hazard_supergraph_payload(artifacts, "guadeloupe")

    assert map_payloads["wind_rp100"]["cmap_colors"] == generate_run_graphs.WIND_MAP_COLORS
    assert map_payloads["wind_rp100"]["colorbar_label"] == "Vent RP100 (km/h)"
    assert map_payloads["wind_rp100"]["points"][0]["value"] == pytest.approx(151.2)
    assert supergraph is not None
    assert supergraph["type"] == "scatter_map_grid"
    assert [row["label"] for row in supergraph["rows"]] == ["RP50", "RP100"]
    assert [column["label"] for column in supergraph["columns"]] == [
        "Vent",
        "Pluie",
        "Inondation cotiere",
        "Mouvements de terrain",
    ]
    assert "note" not in supergraph
    assert supergraph["columns"][0]["colorbar_label"] == "Vent (km/h)"
    assert supergraph["cells"][0][0]["vmin"] == pytest.approx(120.96)
    assert supergraph["cells"][0][0]["vmax"] == pytest.approx(156.24)


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
    assert payload["label_strategy"] == "grouped_bar_full_labels"
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
    assert payload["label_strategy"] == "grouped_bar_full_labels"
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
    assert graph.png_payload["legacy_line_layout"] is True
    assert graph.png_payload["series"][0]["annotations"][0] == "10y\\n1.00 k EUR\\n10.00%"


def test_build_lifetime_fec_graph_marks_priority_points(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        generate_run_graphs,
        "_extract_graph_block",
        lambda *_args, **_kwargs: {
            "series": [
                {
                    "name": "30 ans",
                    "return_period_years": [10, 20, 50, 100, 200, 1000],
                    "damage_eur": [100.0, 200.0, 300.0, 400.0, 500.0, 800.0],
                }
            ]
        },
    )
    monkeypatch.setattr(
        generate_run_graphs,
        "_resolve_annual_fec_curve",
        lambda *_args, **_kwargs: ([10.0, 20.0, 50.0, 100.0, 200.0, 1000.0], [100.0, 200.0, 300.0, 400.0, 500.0, 800.0], [], None),
    )

    graph = generate_run_graphs.build_lifetime_fec_graph(
        _run_record(),
        "guadeloupe",
        {"portfolio_results": {}},
        "storm",
    )

    assert graph is not None
    assert graph.png_payload["legacy_line_layout"] is True
    assert "annotations" not in graph.png_payload["series"][0]


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


def test_main_supports_targeted_cyclone_run_family(monkeypatch, tmp_path) -> None:
    run_id = "targeted_cyclone_20260623_120000"
    run_root = tmp_path / "targeted-runs" / run_id / "territories" / "saint-barthelemy" / "web" / "data"
    run_root.mkdir(parents=True)
    payload = {
        "meta": {
            "run_family": "targeted-cyclone",
            "report_semantics": "event",
            "hazards": ["STORM"],
            "selected_cyclones": [
                {
                    "preset_id": "irma-2017",
                    "storm_id": "2017242N16333",
                    "name": "IRMA",
                    "season": 2017,
                    "basin": "NA",
                    "transposition": {"lat_shift": 6.9, "lon_shift": -11.8},
                }
            ],
        },
        "portfolio_results": {
            "event_summary": {
                "storm_top_events": [
                    {
                        "event_id": "2017242N16333",
                        "event_name": "IRMA (transposed saint-barthelemy)",
                        "loss_eur": 120.0,
                        "frequency_annual": 1.0,
                        "return_period_years_approx": 1.0,
                    }
                ],
            },
            "storm": {
                "eai_eur": 100.0,
                "eai_direct_eur": 70.0,
                "eai_indirect_eur": 30.0,
                "max_event_loss_eur": 120.0,
                "tvar_95_eur": 125.0,
            }
        },
    }
    (run_root / "saint-barthelemy-complete-analysis.json").write_text(json.dumps(payload), encoding="utf-8")
    manifest = {
        "run_id": run_id,
        "run_family": "targeted-cyclone",
        "status": "success",
        "territories": {
            "saint-barthelemy": {
                "status": "complete",
                "archived_complete_analysis_path": str(run_root / "saint-barthelemy-complete-analysis.json"),
                "phases": {
                    "export": {
                        "archived_output_file": str(run_root / "saint-barthelemy-complete-analysis.json"),
                    }
                },
            }
        },
        "parameters": {
            "run_family": "targeted-cyclone",
            "territories": ["saint-barthelemy"],
        },
    }
    manifest_path = tmp_path / "targeted-runs" / run_id / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    monkeypatch.setitem(generate_run_graphs.RUN_FAMILY_OUTPUT_DIRS, "targeted-cyclone", tmp_path / "targeted-runs")
    monkeypatch.setattr(generate_run_graphs, "_resolve_output_root", lambda _value: (tmp_path / "graphs", None))
    monkeypatch.setattr(generate_run_graphs, "_load_matplotlib", lambda: (None, object()))

    def _fake_render_png(graphs, png_dir):
        png_dir.mkdir(parents=True, exist_ok=True)
        output_path = png_dir / "targeted-event-scorecard.png"
        output_path.write_text("png", encoding="utf-8")
        return [str(output_path)]

    monkeypatch.setattr(generate_run_graphs, "render_png_graphs", _fake_render_png)

    exit_code = generate_run_graphs.main(
        [
            "--run-family",
            "targeted-cyclone",
            "--run-id",
            run_id,
            "--formats",
            "png",
            "--output-dir",
            str(tmp_path / "graphs"),
        ]
    )

    assert exit_code == 0
    graph_manifest = tmp_path / "graphs" / run_id / "graphs-manifest.json"
    assert graph_manifest.exists()
    manifest_payload = json.loads(graph_manifest.read_text(encoding="utf-8"))
    assert manifest_payload["run_family"] == "targeted-cyclone"
    assert "tables/saint-barthelemy_cyclones_selection.csv" in {
        Path(path).relative_to(tmp_path / "graphs" / run_id).as_posix()
        for path in manifest_payload["auxiliary_output_paths"]
    }


def test_render_targeted_event_assets_generates_trajectory_map(tmp_path, monkeypatch) -> None:
    run_id = "targeted_cyclone_20260623_130000"
    run_root = tmp_path / "targeted-runs" / run_id / "territories" / "saint-barthelemy" / "web" / "data"
    run_root.mkdir(parents=True)
    segment_geojson_path = run_root / "saint-barthelemy-targeted-cyclone-segments.geojson"
    segment_geojson_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "saffir_simpson_category": 4,
                            "saffir_simpson_label": "Cat 4",
                        },
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[-62.8, 17.9], [-62.7, 18.0]],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    bundle = generate_run_graphs.TerritoryPayload(
        territory="saint-barthelemy",
        payload_path=str(run_root / "saint-barthelemy-complete-analysis.json"),
        payload={
            "meta": {
                "selected_cyclones": [],
                "targeted_cyclone_track_segments_geojson": str(segment_geojson_path),
            },
            "portfolio_results": {},
        },
        source_kind="archived",
    )
    monkeypatch.setattr(generate_run_graphs, "_load_matplotlib", lambda: (None, object()))

    def _fake_render(_plt, output_path, payload):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload.get("title") or "ok", encoding="utf-8")

    monkeypatch.setattr(generate_run_graphs, "_render_auxiliary_output", _fake_render)

    paths, warnings = generate_run_graphs._render_targeted_event_assets(
        record=generate_run_graphs.RunRecord(
            run_id=run_id,
            status="success",
            created_at=None,
            updated_at=None,
            territories=["saint-barthelemy"],
            dynamic_max_tracks=None,
            memory_budget_gb=None,
            manifest_path=str(tmp_path / "targeted-runs" / run_id / "manifest.json"),
            manifest={"territories": {"saint-barthelemy": {}}},
            archived_ready_count=1,
            run_family="targeted-cyclone",
        ),
        payloads={"saint-barthelemy": bundle},
        output_dir=tmp_path / "graphs" / run_id,
    )

    assert not warnings
    assert "maps/saint-barthelemy_trajectoire_cyclone_saffir_simpson.png" in {
        Path(path).relative_to(tmp_path / "graphs" / run_id).as_posix() for path in paths
    }
