from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pytest
import pyarrow as pa
import pyarrow.parquet as pq


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from scripts import build_hazard_comparison_visual_pack as visual_pack


NA_TERRITORIES = (
    ("guadeloupe", "Guadeloupe", -61.20, 15.90),
    ("martinique", "Martinique", -61.00, 14.70),
    ("saint_barthelemy", "Saint-Barthélemy", -62.85, 17.90),
    ("saint_martin", "Saint-Martin", -63.02, 18.08),
    ("saint_pierre_et_miquelon", "Saint-Pierre-et-Miquelon", -56.20, 46.85),
    ("guyane", "Guyane", -53.60, 4.20),
)
SI_TERRITORIES = (
    ("la_reunion", "La Réunion", 55.52, -21.10),
    ("mayotte", "Mayotte", 45.18, -12.82),
)
SP_TERRITORIES = (
    ("nouvelle_caledonie", "Nouvelle-Calédonie", 166.45, -22.25),
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _territory_entry(label: str, basin_code: str, lon: float, lat: float) -> dict:
    return {
        "label": label,
        "include_in_comparison": True,
        "aliases": [label.lower().replace(" ", "_")],
        "storm_basin_code": basin_code,
        "comparison_bbox_hint": {
            "lon_min": lon - 0.05,
            "lat_min": lat - 0.05,
            "lon_max": lon + 0.05,
            "lat_max": lat + 0.05,
        },
    }


def _registry_payload() -> dict:
    territories: dict[str, dict] = {}
    for territory_id, label, lon, lat in NA_TERRITORIES:
        territories[territory_id] = _territory_entry(label, "NA", lon, lat)
    for territory_id, label, lon, lat in SI_TERRITORIES:
        territories[territory_id] = _territory_entry(label, "SI", lon, lat)
    for territory_id, label, lon, lat in SP_TERRITORIES:
        territories[territory_id] = _territory_entry(label, "SP", lon, lat)
    return {
        "meta": {
            "included_territories": list(visual_pack.TERRITORY_ORDER),
            "excluded_territories": [],
        },
        "shared_sources": {
            "raw_track_catalogs": {
                "patterns_by_basin": {
                    "NA": {
                        "storm": "STORM_DATA_IBTRACS_NA_1000_YEARS_*.txt",
                        "storm_cmcc": "STORM_DATA_CMCC-CM2-VHR4_NA_1000_YEARS_*_IBTRACSDELTA.txt",
                    },
                    "SI": {
                        "storm": "STORM_DATA_IBTRACS_SI_1000_YEARS_*.txt",
                        "storm_cmcc": "STORM_DATA_CMCC-CM2-VHR4_SI_1000_YEARS_*_IBTRACSDELTA.txt",
                    },
                    "SP": {
                        "storm": "STORM_DATA_IBTRACS_SP_1000_YEARS_*.txt",
                        "storm_cmcc": "STORM_DATA_CMCC-CM2-VHR4_SP_1000_YEARS_*_IBTRACSDELTA.txt",
                    },
                }
            }
        },
        "territories": territories,
    }


def _storm_row(year: int, basin_id: int, lat: float, lon: float, wind_max: float, tc_number: int) -> str:
    values = [
        year,
        8,
        tc_number,
        0,
        basin_id,
        lat,
        lon,
        990.0,
        wind_max,
        25.0,
        1,
        0,
        50.0,
    ]
    return ",".join(str(value) for value in values)


def _write_raw_storm_sources(storm_dir: Path, storm_cmcc_dir: Path) -> None:
    storm_dir.mkdir(parents=True, exist_ok=True)
    storm_cmcc_dir.mkdir(parents=True, exist_ok=True)
    basin_rows = {
        "na": [
            _storm_row(0, 1, 15.9, 299.0, 28.0, 1),
            _storm_row(1, 1, 17.9, 297.1, 31.0, 2),
        ],
        "si": [
            _storm_row(0, 3, -21.1, 55.5, 26.0, 1),
            _storm_row(1, 3, -12.8, 45.2, 29.0, 2),
        ],
        "sp": [
            _storm_row(0, 4, -22.3, 166.4, 32.0, 1),
            _storm_row(1, 4, -21.9, 167.0, 34.0, 2),
        ],
    }
    basin_rows_cmcc = {
        "na": [
            _storm_row(0, 1, 15.9, 299.0, 30.0, 1),
            _storm_row(1, 1, 17.9, 297.1, 33.0, 2),
        ],
        "si": [
            _storm_row(0, 3, -21.1, 55.5, 28.0, 1),
            _storm_row(1, 3, -12.8, 45.2, 31.0, 2),
        ],
        "sp": [
            _storm_row(0, 4, -22.3, 166.4, 34.0, 1),
            _storm_row(1, 4, -21.9, 167.0, 36.0, 2),
        ],
    }
    for basin_code, rows in basin_rows.items():
        (storm_dir / f"STORM_DATA_IBTRACS_{basin_code.upper()}_1000_YEARS_0.txt").write_text(
            "\n".join(rows) + "\n",
            encoding="utf-8",
        )
    for basin_code, rows in basin_rows_cmcc.items():
        (storm_cmcc_dir / f"STORM_DATA_CMCC-CM2-VHR4_{basin_code.upper()}_1000_YEARS_0_IBTRACSDELTA.txt").write_text(
            "\n".join(rows) + "\n",
            encoding="utf-8",
        )


def _catalog_rows(territories: tuple[tuple[str, str, float, float], ...], *, provider_offset: float) -> list[dict]:
    rows: list[dict] = []
    for index, (_territory_id, _label, lon, lat) in enumerate(territories, start=1):
        for year in range(3):
            raw_lon = lon + 360.0 if lon < 0.0 else lon
            rows.append(
                {
                    "Year": year,
                    "lat": lat,
                    "lon": raw_lon,
                    "wind_max": 20.0 + provider_offset + float(index * 2) + float(year),
                    "track_id": f"track_{index}_{year}",
                }
            )
    return rows


def _write_catalog_parquet(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pydict(
        {
            "Year": [int(row["Year"]) for row in rows],
            "lat": [float(row["lat"]) for row in rows],
            "lon": [float(row["lon"]) for row in rows],
            "wind_max": [float(row["wind_max"]) for row in rows],
            "track_id": [str(row["track_id"]) for row in rows],
        }
    )
    pq.write_table(table, path)


def _write_catalog_sources(catalog_root: Path) -> None:
    _write_catalog_parquet(catalog_root / "na" / "storm_tracks.parquet", _catalog_rows(NA_TERRITORIES, provider_offset=0.0))
    _write_catalog_parquet(catalog_root / "na" / "storm_cmcc_tracks.parquet", _catalog_rows(NA_TERRITORIES, provider_offset=4.0))
    _write_catalog_parquet(catalog_root / "si" / "storm_tracks.parquet", _catalog_rows(SI_TERRITORIES, provider_offset=1.0))
    _write_catalog_parquet(catalog_root / "si" / "storm_cmcc_tracks.parquet", _catalog_rows(SI_TERRITORIES, provider_offset=5.0))
    _write_catalog_parquet(catalog_root / "sp" / "storm_tracks.parquet", _catalog_rows(SP_TERRITORIES, provider_offset=2.0))
    _write_catalog_parquet(catalog_root / "sp" / "storm_cmcc_tracks.parquet", _catalog_rows(SP_TERRITORIES, provider_offset=6.0))


def test_resolve_ordered_territory_specs_uses_expected_order():
    payload = _registry_payload()

    specs = visual_pack._resolve_ordered_territory_specs(payload)

    assert [spec.territory_id for spec in specs] == list(visual_pack.TERRITORY_ORDER)
    assert [spec.basin_code for spec in specs] == ["na", "na", "na", "na", "na", "na", "si", "si", "sp"]


def test_normalize_longitudes_gt_180():
    raw = np.array([299.0, 181.5, 179.0, -61.2], dtype=float)

    normalized = visual_pack._normalize_longitudes(raw)

    assert np.allclose(normalized, np.array([-61.0, -178.5, 179.0, -61.2], dtype=float))


def test_resolve_basin_display_spec_wraps_dateline_to_interest_window():
    payload = {
        "meta": {"grid_cell_deg": 0.05},
        "storm": {
            "cells": [
                {"lat": -22.0, "lon": -179.875, "mean_wind_mps": 30.0},
                {"lat": -22.0, "lon": 180.025, "mean_wind_mps": 31.0},
            ]
        },
        "storm_cmcc": {
            "cells": [
                {"lat": -22.0, "lon": -179.875, "mean_wind_mps": 32.0},
                {"lat": -22.0, "lon": 180.025, "mean_wind_mps": 33.0},
            ]
        },
    }

    display_spec = visual_pack._resolve_basin_display_spec(payload, 0.05)

    assert display_spec.wrapped_dateline is True
    assert display_spec.east - display_spec.west < 1.0
    assert min(cell["lon"] for cell in display_spec.display_cells_by_provider["storm"]) >= 180.0


def test_resolve_basin_display_spec_keeps_na_unwrapped():
    payload = {
        "meta": {"grid_cell_deg": 0.05},
        "storm": {
            "cells": [
                {"lat": 10.0, "lon": -104.875, "mean_wind_mps": 30.0},
                {"lat": 10.0, "lon": -1.125, "mean_wind_mps": 31.0},
            ]
        },
        "storm_cmcc": {
            "cells": [
                {"lat": 10.0, "lon": -104.875, "mean_wind_mps": 32.0},
                {"lat": 10.0, "lon": -1.125, "mean_wind_mps": 33.0},
            ]
        },
    }

    display_spec = visual_pack._resolve_basin_display_spec(payload, 0.05)

    assert display_spec.wrapped_dateline is False
    assert display_spec.west < 0.0
    assert display_spec.east < 0.0


def test_compute_histogram_payloads_builds_shared_axes():
    annual_maxima = {
        "guadeloupe": {"storm": [20.0, 22.0, 24.0], "storm_cmcc": [23.0, 25.0, 27.0]},
        "martinique": {"storm": [18.0, 19.0, 21.0], "storm_cmcc": [21.0, 22.0, 24.0]},
    }

    payload = visual_pack._compute_histogram_payloads(annual_maxima, bins_count=5, bin_width_kmh=10.0)

    assert payload["x_limits"][0] < payload["x_limits"][1]
    assert payload["y_limit"] > 0.0
    assert len(payload["edges"]) == 5
    assert len(payload["territories"]["guadeloupe"]["storm"]) == len(payload["centers"])
    assert len(payload["territories"]["martinique"]["storm_cmcc"]) == len(payload["centers"])


def test_compute_histogram_payloads_can_focus_on_high_winds():
    annual_maxima = {
        "guadeloupe": {"storm": [40.0, 60.0, 70.0], "storm_cmcc": [45.0, 58.0, 75.0]},
    }

    payload = visual_pack._compute_histogram_payloads(
        annual_maxima,
        bins_count=3,
        bin_width_kmh=20.0,
        min_speed_kmh=200.0,
    )

    assert payload["x_limits"] == (200.0, 280.0)
    assert payload["min_speed_kmh"] == 200.0
    assert payload["territories"]["guadeloupe"]["storm"] == pytest.approx([100.0 / 3.0, 0.0, 100.0 / 3.0, 0.0])
    assert payload["territories"]["guadeloupe"]["storm_cmcc"] == pytest.approx([100.0 / 3.0, 0.0, 0.0, 100.0 / 3.0])


def test_compute_histogram_payloads_high_wind_focus_without_matching_values_returns_empty_bins():
    annual_maxima = {
        "guadeloupe": {"storm": [20.0, 22.0, 24.0], "storm_cmcc": [23.0, 25.0, 27.0]},
    }

    payload = visual_pack._compute_histogram_payloads(
        annual_maxima,
        bins_count=4,
        bin_width_kmh=10.0,
        min_speed_kmh=200.0,
    )

    assert payload["x_limits"] == (200.0, 210.0)
    assert payload["y_limit"] == 1.0
    assert payload["territories"]["guadeloupe"]["storm"] == [0.0]
    assert payload["territories"]["guadeloupe"]["storm_cmcc"] == [0.0]


def test_build_territory_annual_maxima_returns_year_and_track_counts(tmp_path):
    catalog_root = tmp_path / "catalogs"
    _write_catalog_sources(catalog_root)
    specs = visual_pack._resolve_ordered_territory_specs(_registry_payload())

    annual_maxima, territory_counts, filtered_territory_counts = visual_pack._build_territory_annual_maxima(
        territory_specs=specs,
        catalog_root=catalog_root,
        min_speed_kmh=200.0,
    )

    assert annual_maxima["guadeloupe"]["storm"] == [22.0, 23.0, 24.0]
    assert territory_counts["guadeloupe"]["storm"] == {"year_count": 3, "track_count": 3}
    assert territory_counts["guadeloupe"]["storm_cmcc"] == {"year_count": 3, "track_count": 3}
    assert filtered_territory_counts["guadeloupe"]["storm"] == {"year_count": 0, "track_count": 0}
    assert filtered_territory_counts["guadeloupe"]["storm_cmcc"] == {"year_count": 0, "track_count": 0}


def test_build_territory_annual_maxima_returns_filtered_counts_for_high_wind_focus(tmp_path):
    catalog_root = tmp_path / "catalogs"
    specs = visual_pack._resolve_ordered_territory_specs(_registry_payload())
    guadeloupe = next(spec for spec in specs if spec.territory_id == "guadeloupe")

    _write_catalog_parquet(
        catalog_root / "na" / "storm_tracks.parquet",
        [
            {"Year": 0, "lat": 15.9, "lon": 298.8, "wind_max": 40.0, "track_id": "track_low"},
            {"Year": 0, "lat": 15.9, "lon": 298.8, "wind_max": 60.0, "track_id": "track_a"},
            {"Year": 1, "lat": 15.9, "lon": 298.8, "wind_max": 58.0, "track_id": "track_b"},
            {"Year": 2, "lat": 15.9, "lon": 298.8, "wind_max": 30.0, "track_id": "track_c"},
            {"Year": 2, "lat": 15.9, "lon": 298.8, "wind_max": 65.0, "track_id": "track_d"},
        ],
    )
    _write_catalog_parquet(
        catalog_root / "na" / "storm_cmcc_tracks.parquet",
        [
            {"Year": 0, "lat": 15.9, "lon": 298.8, "wind_max": 45.0, "track_id": "cmcc_low"},
            {"Year": 0, "lat": 15.9, "lon": 298.8, "wind_max": 57.0, "track_id": "cmcc_a"},
            {"Year": 2, "lat": 15.9, "lon": 298.8, "wind_max": 59.0, "track_id": "cmcc_b"},
        ],
    )
    _write_catalog_parquet(catalog_root / "si" / "storm_tracks.parquet", [])
    _write_catalog_parquet(catalog_root / "si" / "storm_cmcc_tracks.parquet", [])
    _write_catalog_parquet(catalog_root / "sp" / "storm_tracks.parquet", [])
    _write_catalog_parquet(catalog_root / "sp" / "storm_cmcc_tracks.parquet", [])

    annual_maxima, territory_counts, filtered_territory_counts = visual_pack._build_territory_annual_maxima(
        territory_specs=[guadeloupe],
        catalog_root=catalog_root,
        min_speed_kmh=200.0,
    )

    assert annual_maxima["guadeloupe"]["storm"] == [60.0, 58.0, 65.0]
    assert territory_counts["guadeloupe"]["storm"] == {"year_count": 3, "track_count": 5}
    assert filtered_territory_counts["guadeloupe"]["storm"] == {"year_count": 3, "track_count": 3}
    assert filtered_territory_counts["guadeloupe"]["storm_cmcc"] == {"year_count": 2, "track_count": 2}


def test_basin_map_scale_is_fixed_and_expressed_in_kmh():
    vmin_mps, vmax_mps = visual_pack._resolve_global_basin_map_scale()
    ticks = visual_pack._build_basin_colorbar_ticks(vmin_mps, vmax_mps)

    assert (vmin_mps, vmax_mps) == (3.30, 98.5)
    assert ticks[0] == vmin_mps
    assert ticks[-1] == vmax_mps
    assert visual_pack._format_speed_kmh(vmin_mps) == "11.9"
    assert visual_pack._format_speed_kmh(vmax_mps) == "354.6"


def test_build_territory_supergraph_figure_avoids_point_annotations():
    specs = visual_pack._resolve_ordered_territory_specs(_registry_payload())
    annual_maxima = {
        spec.territory_id: {
            "storm": [20.0, 21.0, 22.0],
            "storm_cmcc": [23.0, 24.0, 25.0],
        }
        for spec in specs
    }
    territory_counts = {
        spec.territory_id: {
            "storm": {"year_count": 3, "track_count": 2},
            "storm_cmcc": {"year_count": 3, "track_count": 4},
        }
        for spec in specs
    }
    territory_counts["nouvelle_caledonie"]["storm"] = {"year_count": 3, "track_count": 20448}
    territory_counts["nouvelle_caledonie"]["storm_cmcc"] = {"year_count": 3, "track_count": 21307}
    histogram_payload = visual_pack._compute_histogram_payloads(annual_maxima, bins_count=6, bin_width_kmh=None)

    fig = visual_pack._build_territory_supergraph_figure(
        specs,
        histogram_payload,
        territory_counts,
        title="Vent max par année simulée - distribution des maxima annuels",
    )
    axes = list(np.asarray(fig.axes[:9]).reshape(-1))
    track_indicator_axes = [child for ax in axes for child in ax.child_axes]

    assert len(axes) == 9
    assert all(len(ax.texts) == 0 for ax in axes)
    assert "Guadeloupe (3/3 années & 2/4 tracks)" == axes[0].get_title()
    assert len(track_indicator_axes) == 9
    assert track_indicator_axes[0].get_xticks().tolist() == [0, 1500]
    assert track_indicator_axes[-1].get_xticks().tolist() == [0, 21307]
    assert any(text.get_text() == "Tracks utilisés" for text in track_indicator_axes[0].texts)
    assert any(text.get_text() == "2" for text in track_indicator_axes[0].texts)
    assert any(text.get_text() == "4" for text in track_indicator_axes[0].texts)
    assert any(text.get_text() == "21 307" for text in track_indicator_axes[-1].texts)
    legend = fig.legends[0]
    assert [text.get_text() for text in legend.get_texts()] == ["STORM", "STORM_CMCC"]
    visual_pack.plt.close(fig)


def test_smoke_main_writes_expected_pack(tmp_path, monkeypatch):
    registry_path = _write_json(tmp_path / "territories.json", _registry_payload())
    storm_dir = tmp_path / "storm"
    storm_cmcc_dir = tmp_path / "storm_cmcc"
    catalog_root = tmp_path / "catalogs"
    output_root = tmp_path / "pack"
    _write_raw_storm_sources(storm_dir, storm_cmcc_dir)
    _write_catalog_sources(catalog_root)
    monkeypatch.setattr(visual_pack, "ccrs", None)

    exit_code = visual_pack.main(
        [
            "--registry-path",
            str(registry_path),
            "--catalog-root",
            str(catalog_root),
            "--storm-dir",
            str(storm_dir),
            "--storm-cmcc-dir",
            str(storm_cmcc_dir),
            "--out-dir",
            str(output_root),
            "--cell-deg",
            "0.1",
            "--bin-width-kmh",
            "12",
        ]
    )

    maps_dir = output_root / "maps"
    charts_dir = output_root / "charts"
    manifest_path = output_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert manifest_path.exists()
    assert len(list(maps_dir.glob("*.png"))) == 13
    assert (charts_dir / "territories_vent_max_par_annee_supergraph.png").exists()
    assert (charts_dir / "territories_vent_max_par_annee_supergraph_sup_200kmh.png").exists()
    assert (maps_dir / "all_basins_rp100_storm_vs_storm_cmcc.png").exists()
    assert manifest["basins"]["sp"]["map_outputs"]["event_max"].endswith("sp_event_max_storm_vs_storm_cmcc.png")
    assert manifest["combined_map_outputs"]["rp100"].endswith("all_basins_rp100_storm_vs_storm_cmcc.png")
    assert manifest["territories"]["saint_martin"]["annual_maxima_count"]["storm"] == 3
    assert manifest["territories"]["nouvelle_caledonie"]["annual_maxima_count"]["storm_cmcc"] == 3
    assert manifest["territories"]["saint_martin"]["track_count"]["storm"] == 3
    assert manifest["territories"]["nouvelle_caledonie"]["track_count"]["storm_cmcc"] == 3
    assert manifest["parameters"]["map_scale_mps"] == [3.3, 98.5]
    assert manifest["parameters"]["map_scale_kmh"] == [11.9, 354.6]
    assert manifest["parameters"]["high_wind_focus_threshold_kmh"] == 200.0
    assert manifest["high_wind_focus_histogram"]["threshold_kmh"] == 200.0
    assert manifest["high_wind_focus_histogram"]["supergraph_path"].endswith(
        "charts/territories_vent_max_par_annee_supergraph_sup_200kmh.png"
    )
    assert manifest["outputs"]["charts"][-1].endswith("territories_vent_max_par_annee_supergraph_sup_200kmh.png")
