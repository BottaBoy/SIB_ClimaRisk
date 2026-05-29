from pathlib import Path
import importlib.util

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import Point


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "outputs" / "Graphs" / "presentation-vincennes" / "export_assets.py"

spec = importlib.util.spec_from_file_location("presentation_vincennes_export_assets", MODULE_PATH)
assert spec is not None and spec.loader is not None
export_assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export_assets)


def test_annotate_peak_skips_displayed_zero_values() -> None:
    fig, ax = export_assets.plt.subplots()

    export_assets.annotate_peak(ax, np.array([121.0, 122.0]), np.array([0.0, 5.0]), "#0083CB", 10)

    assert len(ax.texts) == 1
    assert ax.texts[0].get_text() == "5 %"
    export_assets.plt.close(fig)


def test_select_network_state_features_aggregates_electric_layers() -> None:
    gdf = gpd.GeoDataFrame(
        {
            "layer_key": ["eau_aep", "elec_bt_souterrain", "elec_hta_aerien"],
            "geometry": [Point(0, 0), Point(1, 1), Point(2, 2)],
        },
        crs="EPSG:4326",
    )

    selected = export_assets.select_network_state_features(gdf, "elec")

    assert selected["layer_key"].tolist() == ["elec_bt_souterrain", "elec_hta_aerien"]


def test_resolve_map_view_bounds_prefers_reference_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = gpd.GeoDataFrame({"geometry": [Point(1, 1)]}, crs="EPSG:3857")

    monkeypatch.setattr(export_assets, "territory_reference_map_bounds", lambda territory: (10.0, 20.0, 30.0, 40.0))

    bounds = export_assets.resolve_map_view_bounds("guadeloupe", frame, pad_ratio=0.04)

    assert bounds == (10.0, 20.0, 30.0, 40.0)


def test_iter_network_state_map_exports_covers_requested_files() -> None:
    exports = export_assets.iter_network_state_map_exports(["guadeloupe", "martinique"])
    file_names = {item["file_name"] for item in exports}

    assert len(exports) == 12
    assert "guadeloupe_etat_reseaux_aep_retour_100_ans.png" in file_names
    assert "guadeloupe_etat_reseaux_eu_climat_actuel_p99.png" in file_names
    assert "guadeloupe_etat_reseaux_elec_retour_100_ans.png" in file_names
    assert "martinique_etat_reseaux_aep_climat_actuel_p99.png" in file_names
    assert "martinique_etat_reseaux_eu_retour_100_ans.png" in file_names
    assert "martinique_etat_reseaux_elec_climat_actuel_p99.png" in file_names


def test_expected_relative_outputs_validation_layout_focuses_layout_review_set() -> None:
    outputs = export_assets.expected_relative_outputs(export_assets.EXPORT_PROFILE_VALIDATION_LAYOUT, ["guadeloupe"])

    assert len(outputs) == 13
    assert "charts/guadeloupe_vent_max_par_annee.png" in outputs
    assert "charts/guadeloupe_vent_max_par_evenement.png" in outputs
    assert "maps/guadeloupe_etat_reseaux_eu_retour_100_ans.png" in outputs
    assert "maps/guadeloupe_etat_reseaux_elec_climat_actuel_p99.png" in outputs
    assert "maps/guadeloupe_mouvements_de_terrain_rp100.png" in outputs
    assert "charts/guadeloupe_degats_eau_par_scenario_labels.png" not in outputs
    assert "tables/guadeloupe_comparaison_aleas.csv" not in outputs


def test_forbidden_relative_outputs_validation_layout_covers_removed_maps() -> None:
    outputs = export_assets.forbidden_relative_outputs(export_assets.EXPORT_PROFILE_VALIDATION_LAYOUT, ["guadeloupe", "martinique"])

    assert "maps/bassin_na_visualisation_alea_zone_complete.png" in outputs
    assert "maps/guadeloupe_aep_canalisations.png" in outputs
    assert "maps/martinique_haute_tension_souterrain.png" in outputs


def test_validate_generated_outputs_reports_missing_and_forbidden_files(tmp_path: Path) -> None:
    original_output_root = export_assets.OUTPUT_ROOT
    try:
        export_assets.configure_output_root(tmp_path)
        export_assets.ensure_dirs()
        (export_assets.CHART_DIR / "guadeloupe_vent_max_par_annee.png").write_text("ok", encoding="utf-8")
        (export_assets.MAP_DIR / "guadeloupe_aep_canalisations.png").write_text("stale", encoding="utf-8")

        with pytest.raises(RuntimeError) as exc:
            export_assets.validate_generated_outputs(export_assets.EXPORT_PROFILE_VALIDATION_LAYOUT, ["guadeloupe"])

        message = str(exc.value)
        assert "Missing generated files:" in message
        assert "Forbidden files still present:" in message
        assert "maps/guadeloupe_aep_canalisations.png" in message
        assert "charts/guadeloupe_vent_max_par_evenement.png" in message
    finally:
        export_assets.configure_output_root(original_output_root)