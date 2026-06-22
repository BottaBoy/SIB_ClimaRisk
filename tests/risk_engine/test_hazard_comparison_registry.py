from __future__ import annotations

import json
from pathlib import Path

from backend.app.risk_engine.hazard_comparison_registry import (
    DEFAULT_HAZARD_COMPARISON_REGISTRY_PATH,
    load_hazard_comparison_registry,
    validate_hazard_comparison_registry,
)


def test_load_hazard_comparison_registry_exposes_expected_perimeter() -> None:
    registry = load_hazard_comparison_registry()

    assert registry.path == DEFAULT_HAZARD_COMPARISON_REGISTRY_PATH
    assert registry.included_ids == (
        "guadeloupe",
        "martinique",
        "saint_barthelemy",
        "saint_martin",
        "saint_pierre_et_miquelon",
        "la_reunion",
        "mayotte",
        "nouvelle_caledonie",
        "guyane",
    )
    assert registry.excluded_ids == (
        "polynesie_francaise",
        "wallis_et_futuna",
    )


def test_validate_hazard_comparison_registry_schema_is_consistent_without_filesystem_checks() -> None:
    validation = validate_hazard_comparison_registry(check_filesystem=False)

    assert validation.errors == ()
    assert validation.warnings == ()


def test_hazard_comparison_registry_tracks_new_population_normalization_paths() -> None:
    registry = load_hazard_comparison_registry()

    guyane_population = registry.territories["guyane"]["population"]["path"]
    saint_bart_population = registry.territories["saint_barthelemy"]["population"]["path"]

    assert str(guyane_population).endswith("guy_pop_2020_CN_100m_R2025A_v1 (1).tif")
    assert str(saint_bart_population).endswith("blm_pop_2020_CN_100m_R2025A_v1.tif")


def test_hazard_comparison_registry_freezes_guyane_bbox_to_french_guiana_hazard_sources() -> None:
    registry = load_hazard_comparison_registry()

    bbox = registry.territories["guyane"]["comparison_bbox_hint"]

    assert bbox == {
        "lon_min": -55.104028,
        "lat_min": 1.613472,
        "lon_max": -51.148194,
        "lat_max": 6.255417,
    }


def test_validate_hazard_comparison_registry_detects_inconsistent_ready_topography(tmp_path: Path) -> None:
    registry_path = tmp_path / "territories.json"
    payload = {
        "meta": {
            "included_territories": ["demo"],
            "excluded_territories": [],
        },
        "shared_sources": {
            "admin_boundaries_adm0_path": str(tmp_path / "adm0.geojson"),
            "copernicus_topography_dir": str(tmp_path / "copernicus"),
            "raw_track_catalogs": {
                "storm_dir": str(tmp_path / "storm"),
                "storm_cmcc_dir": str(tmp_path / "storm_cmcc"),
                "patterns_by_basin": {
                    "NA": {"storm": "na.txt", "storm_cmcc": "na_cmcc.txt"},
                    "SI": {"storm": "si.txt", "storm_cmcc": "si_cmcc.txt"},
                    "SP": {"storm": "sp.txt", "storm_cmcc": "sp_cmcc.txt"},
                },
            },
        },
        "territories": {
            "demo": {
                "label": "Demo",
                "include_in_comparison": True,
                "aliases": ["demo"],
                "storm_basin_code": "NA",
                "comparison_bbox_hint": {
                    "lon_min": 0.0,
                    "lat_min": 0.0,
                    "lon_max": 1.0,
                    "lat_max": 1.0,
                },
                "admin_mask": {
                    "adm0_path": str(tmp_path / "adm0.geojson"),
                    "mode": "shared_adm0_plus_bbox_hint",
                },
                "topography": {
                    "canonical_copernicus_path": str(tmp_path / "copernicus" / "Demo_COP30.tif"),
                    "copernicus_archive_path": str(tmp_path / "copernicus" / "Demo_rasters_COP30.tar.gz"),
                    "lot0_status": "ready",
                    "exists_now": True,
                },
                "landslide": {
                    "earthquake_path": str(tmp_path / "ls_eq.tif"),
                    "precip_current_path": str(tmp_path / "ls_cur.tif"),
                    "precip_ssp585_path": str(tmp_path / "ls_585.tif"),
                    "exists_now": True,
                },
                "population": {
                    "path": str(tmp_path / "pop.tif"),
                    "required_for_hazard_only": False,
                    "exists_now": True,
                },
            }
        },
    }
    registry_path.write_text(json.dumps(payload), encoding="utf-8")

    validation = validate_hazard_comparison_registry(registry_path, check_filesystem=True)

    assert any("topography marked ready but file is missing" in error for error in validation.errors)
