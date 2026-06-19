from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from backend.app import config as risk_config
from backend.app.risk_engine import hazard_comparison_engine
from backend.app.risk_engine.hazard_comparison_engine import (
    build_hazard_comparison_execution_plan,
    materialize_hazard_comparison_hazards,
    materialize_hazard_comparison_exports,
    materialize_hazard_comparison_metrics,
    materialize_hazard_comparison_report,
    validate_hazard_comparison_scenarios,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _catalog_payload(root: Path) -> dict:
    catalogs: dict[str, dict[str, dict[str, object]]] = {}
    for basin_code, basin_id in (("NA", 1), ("SI", 3), ("SP", 4)):
        basin_dir = root / basin_code.lower()
        catalogs[basin_code] = {}
        for provider in ("storm", "storm_cmcc"):
            parquet_path = basin_dir / f"{provider}.parquet"
            manifest_path = basin_dir / f"{provider}.manifest.json"
            parquet_path.parent.mkdir(parents=True, exist_ok=True)
            parquet_path.write_text("parquet-placeholder", encoding="utf-8")
            _write_json(
                manifest_path,
                {
                    "basin_code": basin_code,
                    "basin_id": basin_id,
                    "provider": provider,
                    "row_count": 10,
                    "track_count": 2,
                    "track_identity_version": 2,
                    "years_covered": 1000,
                    "year_min": 0,
                    "year_max": 999,
                    "source_files": [],
                },
            )
            catalogs[basin_code][provider] = {
                "provider": provider,
                "provider_label": provider.upper(),
                "basin_id": basin_id,
                "parquet_path": str(parquet_path),
                "manifest_path": str(manifest_path),
                "wind_unit_in": "m/s",
                "radius_unit_in": "km",
                "timestep_hours": 3,
            }
    return {
        "meta": {"catalog_version": 1},
        "catalogs": catalogs,
    }


def _scenario_payload() -> dict:
    return {
        "meta": {"scenario_version": 1},
        "scenarios": {
            "storm": {
                "label": "STORM",
                "track_catalog_provider": "storm",
                "components": {
                    "wind": {"enabled": True, "source": "track_catalog", "hazard_class": "TC"},
                    "rain": {"enabled": True, "source": "track_catalog", "hazard_class": "TCRain"},
                    "surge": {
                        "enabled": True,
                        "source": "track_catalog",
                        "hazard_class": "TCSurgeBathtub",
                        "topography_source": "canonical_copernicus",
                    },
                    "landslide": {
                        "enabled": True,
                        "source": "native_raster_pair",
                        "hazard_class": "LS",
                        "combination_mode": "concatenate_native_hazards",
                        "raster_fields": ["earthquake_path", "precip_current_path"],
                    },
                },
            },
            "storm_cmcc": {
                "label": "STORM_CMCC",
                "track_catalog_provider": "storm_cmcc",
                "components": {
                    "wind": {"enabled": True, "source": "track_catalog", "hazard_class": "TC"},
                    "rain": {"enabled": True, "source": "track_catalog", "hazard_class": "TCRain"},
                    "surge": {
                        "enabled": True,
                        "source": "track_catalog",
                        "hazard_class": "TCSurgeBathtub",
                        "topography_source": "canonical_copernicus",
                    },
                    "landslide": {
                        "enabled": True,
                        "source": "native_raster_pair",
                        "hazard_class": "LS",
                        "combination_mode": "concatenate_native_hazards",
                        "raster_fields": ["earthquake_path", "precip_ssp585_path"],
                    },
                },
            },
        },
    }


def _registry_payload(tmp_path: Path, *, territory_id: str, topo_path: Path) -> dict:
    adm0_path = tmp_path / "adm0.geojson"
    adm0_path.write_text("{}", encoding="utf-8")
    landslide_root = tmp_path / "landslide"
    landslide_root.mkdir(parents=True, exist_ok=True)
    for name in ("eq.tif", "cur.tif", "ssp585.tif"):
        (landslide_root / name).write_text(name, encoding="utf-8")
    population_path = tmp_path / "population.tif"
    population_path.write_text("population", encoding="utf-8")

    return {
        "meta": {
            "included_territories": [territory_id],
            "excluded_territories": [],
        },
        "shared_sources": {
            "admin_boundaries_adm0_path": str(adm0_path),
            "copernicus_topography_dir": str(topo_path.parent),
            "raw_track_catalogs": {
                "storm_dir": str(tmp_path / "storm"),
                "storm_cmcc_dir": str(tmp_path / "storm_cmcc"),
                "patterns_by_basin": {
                    "NA": {"storm": "na*.txt", "storm_cmcc": "na_cmcc*.txt"},
                    "SI": {"storm": "si*.txt", "storm_cmcc": "si_cmcc*.txt"},
                    "SP": {"storm": "sp*.txt", "storm_cmcc": "sp_cmcc*.txt"},
                },
            },
        },
        "territories": {
            territory_id: {
                "label": territory_id.capitalize(),
                "include_in_comparison": True,
                "aliases": [territory_id],
                "storm_basin_code": "NA",
                "comparison_bbox_hint": {
                    "lon_min": -61.2,
                    "lat_min": 15.9,
                    "lon_max": -61.0,
                    "lat_max": 16.1,
                },
                "admin_mask": {
                    "adm0_path": str(adm0_path),
                    "mode": "shared_adm0_plus_bbox_hint",
                },
                "topography": {
                    "canonical_copernicus_path": str(topo_path),
                    "copernicus_archive_path": str(tmp_path / "Demo_rasters_COP30.tar.gz"),
                    "lot0_status": "ready",
                    "exists_now": True,
                },
                "landslide": {
                    "earthquake_path": str(landslide_root / "eq.tif"),
                    "precip_current_path": str(landslide_root / "cur.tif"),
                    "precip_ssp585_path": str(landslide_root / "ssp585.tif"),
                    "exists_now": True,
                },
                "population": {
                    "path": str(population_path),
                    "required_for_hazard_only": False,
                    "exists_now": True,
                },
            }
        },
    }


def test_validate_hazard_comparison_scenarios_default_config_is_consistent() -> None:
    validation = validate_hazard_comparison_scenarios()

    assert validation.errors == ()
    assert validation.scenario_ids == ("storm", "storm_cmcc")


def test_build_execution_plan_resolves_catalogs_and_component_inputs(tmp_path: Path) -> None:
    topo_path = tmp_path / "copernicus" / "Demo_COP30.tif"
    topo_path.parent.mkdir(parents=True, exist_ok=True)
    topo_path.write_text("topography", encoding="utf-8")

    registry_path = _write_json(tmp_path / "territories.json", _registry_payload(tmp_path, territory_id="demo", topo_path=topo_path))
    catalogs_path = _write_json(tmp_path / "catalogs.json", _catalog_payload(tmp_path / "catalogs"))
    scenarios_path = _write_json(tmp_path / "scenarios.json", _scenario_payload())

    payload = build_hazard_comparison_execution_plan(
        run_id="20260522_000000",
        output_root=tmp_path / "runs",
        registry_path=registry_path,
        catalogs_path=catalogs_path,
        scenarios_path=scenarios_path,
    )

    territory = payload["territories"]["demo"]
    storm = territory["scenarios"]["storm"]
    storm_cmcc = territory["scenarios"]["storm_cmcc"]

    assert payload["selected_territories"] == ["demo"]
    assert payload["selected_scenarios"] == ["storm", "storm_cmcc"]
    assert territory["status"] == "ready"
    assert storm["catalog"]["track_count"] == 2
    assert storm["components"]["surge"]["topography"]["path"] == str(topo_path)
    assert [item["field"] for item in storm["components"]["landslide"]["input_rasters"]] == [
        "earthquake_path",
        "precip_current_path",
    ]
    assert [item["field"] for item in storm_cmcc["components"]["landslide"]["input_rasters"]] == [
        "earthquake_path",
        "precip_ssp585_path",
    ]
    assert storm["components"]["wind"]["planned_output_path"].endswith("/territories/demo/hazards/storm/wind.h5")


def test_build_execution_plan_rejects_guadeloupe_topography_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    canonical_topo_path = tmp_path / "copernicus" / "Guadeloupe_COP30.tif"
    resolved_topo_path = tmp_path / "other" / "Guadeloupe_COP30.tif"
    canonical_topo_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_topo_path.parent.mkdir(parents=True, exist_ok=True)
    canonical_topo_path.write_text("canonical", encoding="utf-8")
    resolved_topo_path.write_text("resolved", encoding="utf-8")

    registry_path = _write_json(
        tmp_path / "territories.json",
        _registry_payload(tmp_path, territory_id="guadeloupe", topo_path=canonical_topo_path),
    )
    catalogs_path = _write_json(tmp_path / "catalogs.json", _catalog_payload(tmp_path / "catalogs"))
    scenarios_path = _write_json(tmp_path / "scenarios.json", _scenario_payload())

    monkeypatch.setattr(risk_config, "_DEFAULT_SURGE_TOPO_BY_TERRITORY", {"guadeloupe": resolved_topo_path})

    with pytest.raises(ValueError, match="resolve_surge_topo_path_for_territory returned"):
        build_hazard_comparison_execution_plan(
            run_id="20260522_000000",
            output_root=tmp_path / "runs",
            registry_path=registry_path,
            catalogs_path=catalogs_path,
            scenarios_path=scenarios_path,
        )


def test_build_execution_plan_corrects_legacy_manifest_track_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    topo_path = tmp_path / "copernicus" / "Demo_COP30.tif"
    topo_path.parent.mkdir(parents=True, exist_ok=True)
    topo_path.write_text("topography", encoding="utf-8")
    support_catalogs = _catalog_payload(tmp_path / "support_catalogs")

    parquet_path = tmp_path / "catalogs" / "na" / "storm.parquet"
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "Year": [0, 0, 1, 1],
            "track_id": ["storm:NA:0:10", "storm:NA:0:10", "storm:NA:1:10", "storm:NA:1:10"],
            "Basin ID": [1, 1, 1, 1],
            "lat": [15.0, 15.1, 15.0, 15.1],
            "lon": [-61.0, -61.1, -61.0, -61.1],
        }
    ).to_parquet(parquet_path, index=False)
    cmcc_parquet_path = tmp_path / "catalogs" / "na" / "storm_cmcc.parquet"
    pd.DataFrame(
        {
            "Year": [0, 0],
            "track_id": ["storm_cmcc:NA:0:20", "storm_cmcc:NA:0:20"],
            "Basin ID": [1, 1],
            "lat": [15.0, 15.1],
            "lon": [-61.0, -61.1],
        }
    ).to_parquet(cmcc_parquet_path, index=False)

    catalogs_payload = {
        "meta": {"catalog_version": 1},
        "catalogs": {
            "NA": {
                "storm": {
                    "provider": "storm",
                    "provider_label": "STORM",
                    "basin_id": 1,
                    "parquet_path": str(parquet_path),
                    "manifest_path": str(_write_json(tmp_path / "catalogs" / "na" / "storm.manifest.json", {
                        "basin_code": "NA",
                        "basin_id": 1,
                        "provider": "storm",
                        "row_count": 4,
                        "track_count": 1,
                        "years_covered": 2,
                        "year_min": 0,
                        "year_max": 1,
                        "source_files": [],
                    })),
                },
                "storm_cmcc": {
                    "provider": "storm_cmcc",
                    "provider_label": "STORM_CMCC",
                    "basin_id": 1,
                    "parquet_path": str(cmcc_parquet_path),
                    "manifest_path": str(_write_json(tmp_path / "catalogs" / "na" / "storm_cmcc.manifest.json", {
                        "basin_code": "NA",
                        "basin_id": 1,
                        "provider": "storm_cmcc",
                        "row_count": 2,
                        "track_count": 1,
                        "years_covered": 1,
                        "year_min": 0,
                        "year_max": 0,
                        "source_files": [],
                    })),
                },
            },
                "SI": support_catalogs["catalogs"]["SI"],
                "SP": support_catalogs["catalogs"]["SP"],
        },
    }
    registry_path = _write_json(tmp_path / "territories.json", _registry_payload(tmp_path, territory_id="demo", topo_path=topo_path))
    catalogs_path = _write_json(tmp_path / "catalogs.json", catalogs_payload)
    scenarios_path = _write_json(tmp_path / "scenarios.json", _scenario_payload())

    monkeypatch.setattr(risk_config, "_DEFAULT_SURGE_TOPO_BY_TERRITORY", {})

    payload = build_hazard_comparison_execution_plan(
        run_id="20260522_000010",
        output_root=tmp_path / "runs",
        registry_path=registry_path,
        catalogs_path=catalogs_path,
        scenarios_path=scenarios_path,
    )

    assert payload["territories"]["demo"]["scenarios"]["storm"]["catalog"]["track_count"] == 2
    assert payload["territories"]["demo"]["scenarios"]["storm"]["catalog"]["track_count_corrected_from_catalog"] is True


class _FakeHazard:
    haz_type = "FAKE"
    units = "unit"

    def __init__(self, label: str, *, event_count: int = 2, centroid_count: int = 4):
        self.label = str(label)
        self.event_id = list(range(event_count))
        self.event_name = [f"{self.label}_{idx}" for idx in range(event_count)]
        self.centroids = SimpleNamespace(size=int(centroid_count), lat=[0.0] * int(centroid_count), lon=[0.0] * int(centroid_count))
        self.intensity = SimpleNamespace(nnz=int(event_count * centroid_count))

    def write_hdf5(self, path: str) -> None:
        Path(path).write_text(f"hazard:{self.label}", encoding="utf-8")

    @classmethod
    def concat(cls, hazards: list["_FakeHazard"]) -> "_FakeHazard":
        event_count = sum(len(getattr(item, "event_id", [])) for item in hazards)
        centroid_count = max((getattr(getattr(item, "centroids", None), "size", 0) for item in hazards), default=0)
        return cls("concat", event_count=event_count, centroid_count=centroid_count)


class _FakeRainClass:
    @staticmethod
    def from_tracks(*args, **kwargs):
        return _FakeHazard("rain")


class _AppendOnlyHazard:
    haz_type = "LS"
    units = ""

    def __init__(self):
        self.event_id = []
        self.event_name = []
        self.centroids = SimpleNamespace(size=0, lat=[], lon=[])
        self.intensity = SimpleNamespace(nnz=0)

    def populate(self, label: str, *, event_count: int = 2, centroid_count: int = 4) -> "_AppendOnlyHazard":
        self.event_id = list(range(event_count))
        self.event_name = [f"{label}_{idx}" for idx in range(event_count)]
        self.centroids = SimpleNamespace(size=int(centroid_count), lat=[0.0] * int(centroid_count), lon=[0.0] * int(centroid_count))
        self.intensity = SimpleNamespace(nnz=int(event_count * centroid_count))
        return self

    def append(self, *hazards: "_AppendOnlyHazard") -> None:
        event_count = sum(len(getattr(item, "event_id", [])) for item in hazards)
        centroid_count = max((getattr(getattr(item, "centroids", None), "size", 0) for item in hazards), default=0)
        intensity_nnz = sum(int(getattr(getattr(item, "intensity", None), "nnz", 0) or 0) for item in hazards)
        self.event_id = list(range(event_count))
        self.event_name = [f"combined_{idx}" for idx in range(event_count)]
        self.centroids = SimpleNamespace(size=int(centroid_count), lat=[0.0] * int(centroid_count), lon=[0.0] * int(centroid_count))
        self.intensity = SimpleNamespace(nnz=int(intensity_nnz))

    def write_hdf5(self, path: str) -> None:
        Path(path).write_text("hazard:append-only", encoding="utf-8")

    @classmethod
    def concat(cls, hazards: list["_AppendOnlyHazard"]) -> "_AppendOnlyHazard":
        raise AssertionError("append path should be used for append-only landslide hazards")


def test_materialize_hazard_comparison_hazards_builds_component_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    topo_path = tmp_path / "copernicus" / "Demo_COP30.tif"
    topo_path.parent.mkdir(parents=True, exist_ok=True)
    topo_path.write_text("topography", encoding="utf-8")

    registry_path = _write_json(tmp_path / "territories.json", _registry_payload(tmp_path, territory_id="demo", topo_path=topo_path))
    catalogs_path = _write_json(tmp_path / "catalogs.json", _catalog_payload(tmp_path / "catalogs"))
    scenarios_path = _write_json(tmp_path / "scenarios.json", _scenario_payload())
    plan = build_hazard_comparison_execution_plan(
        run_id="20260522_000000",
        output_root=tmp_path / "runs",
        registry_path=registry_path,
        catalogs_path=catalogs_path,
        scenarios_path=scenarios_path,
    )

    landslide_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        hazard_comparison_engine,
        "_require_phase3_runtime",
        lambda: {"np": SimpleNamespace(), "Hazard": _FakeHazard, "TCRain": _FakeRainClass, "TCSurgeBathtub": object()},
    )
    monkeypatch.setattr(
        hazard_comparison_engine,
        "load_settings",
        lambda: SimpleNamespace(
            territory_grid_deg=0.2,
            hazard_dynamic_max_tracks=12,
            storm_wind_unit_in="m/s",
            storm_convert_10min_to_1min=True,
            storm_radius_unit_in="km",
            storm_env_pressure_hpa=1010.0,
            hazard_rain_model="R-CLIPER",
            hazard_rain_max_dist_inland_km=2000.0,
            landslide_corr_fact=500.0,
            landslide_n_years=200,
            landslide_dist="poisson",
        ),
    )
    monkeypatch.setattr(
        hazard_comparison_engine,
        "load_storm_hazards_from_parquet_for_points",
        lambda **kwargs: SimpleNamespace(source="dynamic_parquet"),
    )
    monkeypatch.setattr(
        hazard_comparison_engine,
        "resolve_hazard_bundle_tracks",
        lambda bundle, hazard_key: SimpleNamespace(data=[{"track_id": hazard_key}] * 3),
    )
    monkeypatch.setattr(hazard_comparison_engine, "release_hazard_bundle_tracks", lambda bundle, hazard_key: None)
    monkeypatch.setattr(
        hazard_comparison_engine,
        "_build_centroids_from_points",
        lambda point_coords: SimpleNamespace(size=len(list(point_coords)), lat=[0.0], lon=[0.0]),
    )
    monkeypatch.setattr(hazard_comparison_engine, "_build_hazard_from_tracks", lambda tracks, centroids: _FakeHazard("wind"))
    monkeypatch.setattr(hazard_comparison_engine, "_normalize_frequency_on_copy", lambda hazard_obj, years: hazard_obj)
    monkeypatch.setattr(
        hazard_comparison_engine,
        "_prepare_phase3_surge_topography",
        lambda topo_path, point_records, hazard_source: Path(topo_path),
    )
    monkeypatch.setattr(
        hazard_comparison_engine,
        "_build_surge_hazard",
        lambda *args, **kwargs: (_FakeHazard("surge"), {"fraction_mode": "pointwise", "reason": "dynamic"}),
    )
    monkeypatch.setattr(
        hazard_comparison_engine,
        "build_landslide_hazard_from_prob",
        lambda **kwargs: landslide_calls.append(dict(kwargs)) or _FakeHazard(Path(kwargs["path_sourcefile"]).stem),
    )

    payload = materialize_hazard_comparison_hazards(plan, dynamic_max_tracks=7)

    territory = payload["territories"]["demo"]
    storm = territory["scenarios"]["storm"]

    assert payload["status"] == "complete"
    assert payload["contracts"]["effective_dynamic_max_tracks"] == 7
    assert territory["status"] == "complete"
    assert territory["phases"]["phase3_hazard_build"]["status"] == "complete"
    assert storm["status"] == "complete"
    assert storm["components"]["wind"]["status"] == "complete"
    assert storm["components"]["rain"]["status"] == "complete"
    assert storm["components"]["surge"]["status"] == "complete"
    assert storm["components"]["landslide"]["status"] == "complete"
    assert Path(storm["components"]["wind"]["hazard"]["output"]["path"]).exists()
    assert Path(storm["components"]["landslide"]["hazard"]["output"]["path"]).exists()
    assert len(storm["components"]["landslide"]["input_hazards"]) == 2
    assert len(landslide_calls) == 4
    assert all(call.get("target_centroids") is not None for call in landslide_calls)


def test_materialize_hazard_comparison_hazards_resumes_existing_wind_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topo_path = tmp_path / "copernicus" / "Demo_COP30.tif"
    topo_path.parent.mkdir(parents=True, exist_ok=True)
    topo_path.write_text("topography", encoding="utf-8")

    registry_path = _write_json(tmp_path / "territories.json", _registry_payload(tmp_path, territory_id="demo", topo_path=topo_path))
    catalogs_path = _write_json(tmp_path / "catalogs.json", _catalog_payload(tmp_path / "catalogs"))
    scenarios_path = _write_json(tmp_path / "scenarios.json", _scenario_payload())
    plan = build_hazard_comparison_execution_plan(
        run_id="20260522_000000",
        output_root=tmp_path / "runs",
        registry_path=registry_path,
        catalogs_path=catalogs_path,
        scenarios_path=scenarios_path,
    )

    wind_output = Path(
        plan["territories"]["demo"]["scenarios"]["storm"]["components"]["wind"]["planned_output_path"]
    )
    wind_output.parent.mkdir(parents=True, exist_ok=True)
    wind_output.write_text("already-complete", encoding="utf-8")

    build_calls: list[str] = []

    monkeypatch.setattr(
        hazard_comparison_engine,
        "_require_phase3_runtime",
        lambda: {"np": SimpleNamespace(), "Hazard": _FakeHazard, "TCRain": _FakeRainClass, "TCSurgeBathtub": object()},
    )
    monkeypatch.setattr(
        hazard_comparison_engine,
        "load_settings",
        lambda: SimpleNamespace(
            territory_grid_deg=0.2,
            surge_grid_deg=0.2,
            hazard_dynamic_max_tracks=12,
            storm_wind_unit_in="m/s",
            storm_convert_10min_to_1min=True,
            storm_radius_unit_in="km",
            storm_env_pressure_hpa=1010.0,
            hazard_rain_model="R-CLIPER",
            hazard_rain_max_dist_inland_km=2000.0,
            landslide_corr_fact=500.0,
            landslide_n_years=200,
            landslide_dist="poisson",
        ),
    )
    monkeypatch.setattr(
        hazard_comparison_engine,
        "load_storm_hazards_from_parquet_for_points",
        lambda **kwargs: SimpleNamespace(source="dynamic_parquet"),
    )
    monkeypatch.setattr(
        hazard_comparison_engine,
        "resolve_hazard_bundle_tracks",
        lambda bundle, hazard_key: SimpleNamespace(data=[{"track_id": hazard_key}] * 3),
    )
    monkeypatch.setattr(hazard_comparison_engine, "release_hazard_bundle_tracks", lambda bundle, hazard_key: None)
    monkeypatch.setattr(
        hazard_comparison_engine,
        "_build_centroids_from_points",
        lambda point_coords: SimpleNamespace(size=len(list(point_coords)), lat=[0.0], lon=[0.0]),
    )
    monkeypatch.setattr(
        hazard_comparison_engine,
        "_load_hazard_from_hdf5",
        lambda hazard_cls, path: _FakeHazard(f"resumed-{Path(path).stem}"),
    )
    monkeypatch.setattr(
        hazard_comparison_engine,
        "_build_hazard_from_tracks",
        lambda tracks, centroids: build_calls.append(str((tracks.data or [{}])[0].get("track_id"))) or _FakeHazard("wind"),
    )
    monkeypatch.setattr(hazard_comparison_engine, "_normalize_frequency_on_copy", lambda hazard_obj, years: hazard_obj)
    monkeypatch.setattr(
        hazard_comparison_engine,
        "_prepare_phase3_surge_topography",
        lambda topo_path, point_records, hazard_source: Path(topo_path),
    )
    monkeypatch.setattr(
        hazard_comparison_engine,
        "_build_surge_hazard",
        lambda *args, **kwargs: (_FakeHazard("surge"), {"fraction_mode": "pointwise", "reason": "dynamic"}),
    )
    monkeypatch.setattr(
        hazard_comparison_engine,
        "build_landslide_hazard_from_prob",
        lambda **kwargs: _FakeHazard(Path(kwargs["path_sourcefile"]).stem),
    )

    payload = materialize_hazard_comparison_hazards(plan, dynamic_max_tracks=7, resume_enabled=True)

    storm = payload["territories"]["demo"]["scenarios"]["storm"]
    assert payload["status"] == "complete"
    assert storm["components"]["wind"]["status"] == "complete"
    assert storm["components"]["wind"]["resumed"] is True
    assert storm["components"]["wind"]["hazard"]["output"]["path"] == str(wind_output)
    assert build_calls == ["storm_cmcc"]


def test_materialize_hazard_comparison_hazards_uses_dedicated_surge_grid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topo_path = tmp_path / "copernicus" / "Demo_COP30.tif"
    topo_path.parent.mkdir(parents=True, exist_ok=True)
    topo_path.write_text("topography", encoding="utf-8")

    registry_path = _write_json(tmp_path / "territories.json", _registry_payload(tmp_path, territory_id="demo", topo_path=topo_path))
    catalogs_path = _write_json(tmp_path / "catalogs.json", _catalog_payload(tmp_path / "catalogs"))
    scenarios_path = _write_json(tmp_path / "scenarios.json", _scenario_payload())
    plan = build_hazard_comparison_execution_plan(
        run_id="20260522_000000",
        output_root=tmp_path / "runs",
        registry_path=registry_path,
        catalogs_path=catalogs_path,
        scenarios_path=scenarios_path,
    )

    grid_steps: list[float] = []
    surge_wind_centroid_sizes: list[int] = []

    monkeypatch.setattr(
        hazard_comparison_engine,
        "_require_phase3_runtime",
        lambda: {"np": SimpleNamespace(), "Hazard": _FakeHazard, "TCRain": _FakeRainClass, "TCSurgeBathtub": object()},
    )
    monkeypatch.setattr(
        hazard_comparison_engine,
        "load_settings",
        lambda: SimpleNamespace(
            territory_grid_deg=0.2,
            surge_grid_deg=0.02,
            hazard_dynamic_max_tracks=12,
            storm_wind_unit_in="m/s",
            storm_convert_10min_to_1min=True,
            storm_radius_unit_in="km",
            storm_env_pressure_hpa=1010.0,
            hazard_rain_model="R-CLIPER",
            hazard_rain_max_dist_inland_km=2000.0,
            landslide_corr_fact=500.0,
            landslide_n_years=200,
            landslide_dist="poisson",
        ),
    )
    monkeypatch.setattr(
        hazard_comparison_engine,
        "_build_point_records_from_bbox",
        lambda bbox, *, grid_step_deg: grid_steps.append(float(grid_step_deg)) or (
            [{"lat": 16.0, "lon": -61.1}, {"lat": 16.02, "lon": -61.08}]
            if float(grid_step_deg) == pytest.approx(0.02)
            else [{"lat": 16.0, "lon": -61.1}]
        ),
    )
    monkeypatch.setattr(
        hazard_comparison_engine,
        "load_storm_hazards_from_parquet_for_points",
        lambda **kwargs: SimpleNamespace(source="dynamic_parquet"),
    )
    monkeypatch.setattr(
        hazard_comparison_engine,
        "resolve_hazard_bundle_tracks",
        lambda bundle, hazard_key: SimpleNamespace(data=[{"track_id": hazard_key}] * 3),
    )
    monkeypatch.setattr(hazard_comparison_engine, "release_hazard_bundle_tracks", lambda bundle, hazard_key: None)
    monkeypatch.setattr(
        hazard_comparison_engine,
        "_build_centroids_from_points",
        lambda point_coords: SimpleNamespace(
            size=len(list(point_coords)),
            lat=[0.0] * len(list(point_coords)),
            lon=[0.0] * len(list(point_coords)),
        ),
    )
    monkeypatch.setattr(
        hazard_comparison_engine,
        "_build_hazard_from_tracks",
        lambda tracks, centroids: _FakeHazard("wind", centroid_count=int(centroids.size)),
    )
    monkeypatch.setattr(hazard_comparison_engine, "_normalize_frequency_on_copy", lambda hazard_obj, years: hazard_obj)
    monkeypatch.setattr(
        hazard_comparison_engine,
        "_prepare_phase3_surge_topography",
        lambda topo_path, point_records, hazard_source: Path(topo_path),
    )
    monkeypatch.setattr(
        hazard_comparison_engine,
        "_build_surge_hazard",
        lambda *args, **kwargs: (
            surge_wind_centroid_sizes.append(int(kwargs["wind_hazard"].centroids.size))
            or _FakeHazard("surge", centroid_count=int(kwargs["wind_hazard"].centroids.size)),
            {"fraction_mode": "pointwise", "reason": "dynamic"},
        ),
    )
    monkeypatch.setattr(
        hazard_comparison_engine,
        "build_landslide_hazard_from_prob",
        lambda **kwargs: _FakeHazard(Path(kwargs["path_sourcefile"]).stem),
    )

    payload = materialize_hazard_comparison_hazards(plan, dynamic_max_tracks=7)

    territory = payload["territories"]["demo"]
    storm = territory["scenarios"]["storm"]

    assert grid_steps == [0.2, 0.02]
    assert territory["phases"]["phase3_hazard_build"]["grid_point_count"] == 1
    assert territory["phases"]["phase3_hazard_build"]["surge_grid_point_count"] == 2
    assert storm["grid_point_count"] == 1
    assert storm["surge_grid_point_count"] == 2
    assert surge_wind_centroid_sizes == [2, 2]


def test_materialize_hazard_comparison_hazards_concatenates_append_only_landslides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topo_path = tmp_path / "copernicus" / "Demo_COP30.tif"
    topo_path.parent.mkdir(parents=True, exist_ok=True)
    topo_path.write_text("topography", encoding="utf-8")

    registry_path = _write_json(tmp_path / "territories.json", _registry_payload(tmp_path, territory_id="demo", topo_path=topo_path))
    catalogs_path = _write_json(tmp_path / "catalogs.json", _catalog_payload(tmp_path / "catalogs"))
    scenarios_path = _write_json(tmp_path / "scenarios.json", _scenario_payload())
    plan = build_hazard_comparison_execution_plan(
        run_id="20260522_000000",
        output_root=tmp_path / "runs",
        registry_path=registry_path,
        catalogs_path=catalogs_path,
        scenarios_path=scenarios_path,
    )

    monkeypatch.setattr(
        hazard_comparison_engine,
        "_require_phase3_runtime",
        lambda: {"np": SimpleNamespace(), "Hazard": _FakeHazard, "TCRain": _FakeRainClass, "TCSurgeBathtub": object()},
    )
    monkeypatch.setattr(
        hazard_comparison_engine,
        "load_settings",
        lambda: SimpleNamespace(
            territory_grid_deg=0.2,
            hazard_dynamic_max_tracks=12,
            storm_wind_unit_in="m/s",
            storm_convert_10min_to_1min=True,
            storm_radius_unit_in="km",
            storm_env_pressure_hpa=1010.0,
            hazard_rain_model="R-CLIPER",
            hazard_rain_max_dist_inland_km=2000.0,
            landslide_corr_fact=500.0,
            landslide_n_years=200,
            landslide_dist="poisson",
        ),
    )
    monkeypatch.setattr(
        hazard_comparison_engine,
        "load_storm_hazards_from_parquet_for_points",
        lambda **kwargs: SimpleNamespace(source="dynamic_parquet"),
    )
    monkeypatch.setattr(
        hazard_comparison_engine,
        "resolve_hazard_bundle_tracks",
        lambda bundle, hazard_key: SimpleNamespace(data=[{"track_id": hazard_key}] * 3),
    )
    monkeypatch.setattr(hazard_comparison_engine, "release_hazard_bundle_tracks", lambda bundle, hazard_key: None)
    monkeypatch.setattr(
        hazard_comparison_engine,
        "_build_centroids_from_points",
        lambda point_coords: SimpleNamespace(size=len(list(point_coords)), lat=[0.0], lon=[0.0]),
    )
    monkeypatch.setattr(hazard_comparison_engine, "_build_hazard_from_tracks", lambda tracks, centroids: _FakeHazard("wind"))
    monkeypatch.setattr(hazard_comparison_engine, "_normalize_frequency_on_copy", lambda hazard_obj, years: hazard_obj)
    monkeypatch.setattr(
        hazard_comparison_engine,
        "_prepare_phase3_surge_topography",
        lambda topo_path, point_records, hazard_source: Path(topo_path),
    )
    monkeypatch.setattr(
        hazard_comparison_engine,
        "_build_surge_hazard",
        lambda *args, **kwargs: (_FakeHazard("surge"), {"fraction_mode": "pointwise", "reason": "dynamic"}),
    )
    monkeypatch.setattr(
        hazard_comparison_engine,
        "build_landslide_hazard_from_prob",
        lambda **kwargs: _AppendOnlyHazard().populate(Path(kwargs["path_sourcefile"]).stem, event_count=2),
    )

    payload = materialize_hazard_comparison_hazards(plan, dynamic_max_tracks=7)

    landslide = payload["territories"]["demo"]["scenarios"]["storm"]["components"]["landslide"]

    assert landslide["status"] == "complete"
    assert landslide["hazard"]["event_count"] == 4
    assert len(landslide["input_hazards"]) == 2


def test_hazard_summary_counts_numpy_event_ids(tmp_path: Path) -> None:
    output_path = tmp_path / "hazard.h5"
    output_path.write_text("hazard", encoding="utf-8")

    hazard = SimpleNamespace(
        haz_type="TC",
        units="m/s",
        event_id=np.array([10, 20, 30]),
        centroids=SimpleNamespace(size=5, lat=np.array([0.0] * 5), lon=np.array([0.0] * 5)),
        intensity=SimpleNamespace(nnz=7),
    )

    summary = hazard_comparison_engine._hazard_summary(hazard, output_path=output_path)

    assert summary["event_count"] == 3
    assert summary["centroid_count"] == 5


def test_prepare_phase3_surge_topography_skips_crop_for_dynamic_parquet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topo_path = tmp_path / "demo.tif"
    topo_path.write_text("topography", encoding="utf-8")
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        hazard_comparison_engine,
        "_prepare_topo_raster_with_crs",
        lambda path: calls.append(("with_crs", Path(path))) or Path(path),
    )
    monkeypatch.setattr(
        hazard_comparison_engine,
        "_prepare_topo_raster_for_exposure",
        lambda path, point_records: calls.append(("for_exposure", len(list(point_records)))) or Path(path),
    )

    prepared = hazard_comparison_engine._prepare_phase3_surge_topography(
        topo_path,
        point_records=[{"lat": 5.0, "lon": -52.0}],
        hazard_source="dynamic_parquet",
    )

    assert prepared == topo_path
    assert calls == [("with_crs", topo_path)]


def test_prepare_phase3_surge_topography_keeps_crop_for_non_dynamic_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topo_path = tmp_path / "demo.tif"
    topo_path.write_text("topography", encoding="utf-8")
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        hazard_comparison_engine,
        "_prepare_topo_raster_with_crs",
        lambda path: calls.append(("with_crs", Path(path))) or Path(path),
    )
    monkeypatch.setattr(
        hazard_comparison_engine,
        "_prepare_topo_raster_for_exposure",
        lambda path, point_records: calls.append(("for_exposure", len(list(point_records)))) or Path(path),
    )

    prepared = hazard_comparison_engine._prepare_phase3_surge_topography(
        topo_path,
        point_records=[{"lat": 5.0, "lon": -52.0}],
        hazard_source="precomputed_hdf5",
    )

    assert prepared == topo_path
    assert calls == [("for_exposure", 1)]


class _FakePhase4HazardClass:
    registry: dict[str, object] = {}

    @classmethod
    def from_hdf5(cls, path: str):
        return cls.registry[str(path)]


def test_materialize_hazard_comparison_metrics_extracts_component_metrics_and_deltas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topo_path = tmp_path / "copernicus" / "Demo_COP30.tif"
    topo_path.parent.mkdir(parents=True, exist_ok=True)
    topo_path.write_text("topography", encoding="utf-8")

    registry_path = _write_json(tmp_path / "territories.json", _registry_payload(tmp_path, territory_id="demo", topo_path=topo_path))
    catalogs_path = _write_json(tmp_path / "catalogs.json", _catalog_payload(tmp_path / "catalogs"))
    scenarios_path = _write_json(tmp_path / "scenarios.json", _scenario_payload())
    plan = build_hazard_comparison_execution_plan(
        run_id="20260522_000000",
        output_root=tmp_path / "runs",
        registry_path=registry_path,
        catalogs_path=catalogs_path,
        scenarios_path=scenarios_path,
    )

    monkeypatch.setattr(
        hazard_comparison_engine,
        "_require_phase3_runtime",
        lambda: {"np": SimpleNamespace(), "Hazard": _FakeHazard, "TCRain": _FakeRainClass, "TCSurgeBathtub": object()},
    )
    monkeypatch.setattr(
        hazard_comparison_engine,
        "load_settings",
        lambda: SimpleNamespace(
            territory_grid_deg=0.2,
            hazard_dynamic_max_tracks=12,
            storm_wind_unit_in="m/s",
            storm_convert_10min_to_1min=True,
            storm_radius_unit_in="km",
            storm_env_pressure_hpa=1010.0,
            hazard_rain_model="R-CLIPER",
            hazard_rain_max_dist_inland_km=2000.0,
            landslide_corr_fact=500.0,
            landslide_n_years=200,
            landslide_dist="poisson",
        ),
    )
    monkeypatch.setattr(
        hazard_comparison_engine,
        "load_storm_hazards_from_parquet_for_points",
        lambda **kwargs: SimpleNamespace(source="dynamic_parquet"),
    )
    monkeypatch.setattr(
        hazard_comparison_engine,
        "resolve_hazard_bundle_tracks",
        lambda bundle, hazard_key: SimpleNamespace(data=[{"track_id": hazard_key}] * 3),
    )
    monkeypatch.setattr(hazard_comparison_engine, "release_hazard_bundle_tracks", lambda bundle, hazard_key: None)
    monkeypatch.setattr(
        hazard_comparison_engine,
        "_build_centroids_from_points",
        lambda point_coords: SimpleNamespace(size=len(list(point_coords)), lat=[0.0], lon=[0.0]),
    )
    monkeypatch.setattr(hazard_comparison_engine, "_build_hazard_from_tracks", lambda tracks, centroids: _FakeHazard("wind"))
    monkeypatch.setattr(hazard_comparison_engine, "_normalize_frequency_on_copy", lambda hazard_obj, years: hazard_obj)
    monkeypatch.setattr(
        hazard_comparison_engine,
        "_prepare_phase3_surge_topography",
        lambda topo_path, point_records, hazard_source: Path(topo_path),
    )
    monkeypatch.setattr(
        hazard_comparison_engine,
        "_build_surge_hazard",
        lambda *args, **kwargs: (_FakeHazard("surge"), {"fraction_mode": "pointwise", "reason": "dynamic"}),
    )
    monkeypatch.setattr(
        hazard_comparison_engine,
        "build_landslide_hazard_from_prob",
        lambda **kwargs: _FakeHazard(Path(kwargs["path_sourcefile"]).stem),
    )

    phase3_payload = materialize_hazard_comparison_hazards(plan, dynamic_max_tracks=7)

    fake_registry: dict[str, object] = {}
    for scenario_id, intensity_scale in (("storm", 1.0), ("storm_cmcc", 2.0)):
        scenario = phase3_payload["territories"]["demo"]["scenarios"][scenario_id]
        for component_id, units in (("wind", "m/s"), ("rain", "mm"), ("surge", "m"), ("landslide", "")):
            output_path = scenario["components"][component_id]["hazard"]["output"]["path"]
            intensity = sparse.csr_matrix(
                np.array(
                    [
                        [0.0, 1.0 * intensity_scale, 2.0 * intensity_scale],
                        [3.0 * intensity_scale, 0.0, 0.0],
                    ]
                )
            )
            fake_registry[str(output_path)] = SimpleNamespace(
                haz_type=component_id.upper(),
                units=units,
                event_id=np.array([1, 2]),
                frequency=np.array([0.1, 0.2]),
                centroids=SimpleNamespace(size=3, lat=np.array([0.0, 0.1, 0.2]), lon=np.array([0.0, 0.1, 0.2])),
                intensity=intensity,
            )

    _FakePhase4HazardClass.registry = fake_registry
    monkeypatch.setattr(
        hazard_comparison_engine,
        "_require_phase4_runtime",
        lambda: {"np": np, "Hazard": _FakePhase4HazardClass},
    )

    payload = materialize_hazard_comparison_metrics(phase3_payload)

    metrics_path = Path(payload["comparison_metrics"]["path"])
    territory_metrics = payload["territories"]["demo"]["comparison_metrics"]
    wind_metrics = territory_metrics["scenarios"]["storm"]["components"]["wind"]
    wind_delta = territory_metrics["storm_vs_storm_cmcc"]["components"]["wind"]["metrics"]["intensity_max"]
    wind_return_periods = wind_metrics["intensity_max_return_periods"]

    assert payload["status"] == "complete"
    assert payload["mode"] == "phase4_metric_extraction"
    assert payload["territories"]["demo"]["phases"]["phase4_metric_extraction"]["status"] == "complete"
    assert payload["territories"]["demo"]["comparison_metrics"]["status"] == "complete"
    assert metrics_path.exists()
    assert wind_metrics["event_count"] == 2
    assert wind_metrics["positive_centroid_fraction"] == pytest.approx(1.0)
    assert wind_return_periods["return_periods"] == list(hazard_comparison_engine.RETURN_PERIODS)
    assert wind_return_periods["values"] == pytest.approx([3.0] * len(hazard_comparison_engine.RETURN_PERIODS))
    assert wind_delta["storm"] == pytest.approx(3.0)
    assert wind_delta["storm_cmcc"] == pytest.approx(6.0)
    assert wind_delta["delta_cmcc_minus_storm"] == pytest.approx(3.0)


def test_materialize_hazard_comparison_exports_writes_tables_and_charts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "runs" / "20260522_000002"
    metrics_path = run_dir / "comparison-metrics.json"
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_document = {
        "run_id": "20260522_000002",
        "generated_at": "2026-05-22T00:00:00Z",
        "status": "complete",
        "pairwise_comparison": "storm_vs_storm_cmcc",
        "component_order": ["wind", "rain"],
        "metric_keys": list(hazard_comparison_engine._COMPARISON_DELTA_METRIC_KEYS),
        "territories": {
            "demo": {
                "label": "Demo",
                "status": "complete",
                "scenarios": {
                    "storm": {
                        "status": "complete",
                        "component_order": ["wind", "rain"],
                        "components": {
                            "wind": {
                                "haz_type": "TC",
                                "units": "m/s",
                                "event_count": 2,
                                "frequency_sum_annual": 0.2,
                                "positive_centroid_fraction": 0.5,
                                "intensity_max": 10.0,
                                "intensity_max_return_periods": {"return_periods": [10, 20, 50], "values": [10.0, 10.5, 11.0]},
                                "intensity_mean_positive": 5.0,
                                "intensity_p95_positive": 9.0,
                                "event_footprint_mean_fraction": 0.3,
                                "event_footprint_p95_fraction": 0.4,
                                "event_footprint_max_fraction": 0.5,
                            },
                            "rain": {
                                "haz_type": "TR",
                                "units": "mm",
                                "event_count": 2,
                                "frequency_sum_annual": 0.2,
                                "positive_centroid_fraction": 1.0,
                                "intensity_max": 30.0,
                                "intensity_max_return_periods": {"return_periods": [10, 20, 50], "values": [30.0, 32.0, 34.0]},
                                "intensity_mean_positive": 20.0,
                                "intensity_p95_positive": 28.0,
                                "event_footprint_mean_fraction": 0.8,
                                "event_footprint_p95_fraction": 0.9,
                                "event_footprint_max_fraction": 1.0,
                            },
                        },
                    },
                    "storm_cmcc": {
                        "status": "complete",
                        "component_order": ["wind", "rain"],
                        "components": {
                            "wind": {
                                "haz_type": "TC",
                                "units": "m/s",
                                "event_count": 2,
                                "frequency_sum_annual": 0.2,
                                "positive_centroid_fraction": 0.75,
                                "intensity_max": 15.0,
                                "intensity_max_return_periods": {"return_periods": [10, 20, 50], "values": [15.0, 16.0, 17.0]},
                                "intensity_mean_positive": 6.0,
                                "intensity_p95_positive": 12.0,
                                "event_footprint_mean_fraction": 0.35,
                                "event_footprint_p95_fraction": 0.45,
                                "event_footprint_max_fraction": 0.55,
                            },
                            "rain": {
                                "haz_type": "TR",
                                "units": "mm",
                                "event_count": 2,
                                "frequency_sum_annual": 0.2,
                                "positive_centroid_fraction": 0.9,
                                "intensity_max": 36.0,
                                "intensity_max_return_periods": {"return_periods": [10, 20, 50], "values": [36.0, 38.0, 40.0]},
                                "intensity_mean_positive": 24.0,
                                "intensity_p95_positive": 30.0,
                                "event_footprint_mean_fraction": 0.7,
                                "event_footprint_p95_fraction": 0.8,
                                "event_footprint_max_fraction": 0.95,
                            },
                        },
                    },
                },
                "storm_vs_storm_cmcc": {
                    "status": "complete",
                    "components": {
                        "wind": {
                            "status": "complete",
                            "haz_type": "TC",
                            "units": "m/s",
                            "metrics": {
                                key: {"storm": 1.0, "storm_cmcc": 2.0, "delta_cmcc_minus_storm": 1.0, "ratio_cmcc_over_storm": 2.0}
                                for key in hazard_comparison_engine._COMPARISON_DELTA_METRIC_KEYS
                            },
                        },
                        "rain": {
                            "status": "complete",
                            "haz_type": "TR",
                            "units": "mm",
                            "metrics": {
                                key: {"storm": 3.0, "storm_cmcc": 4.0, "delta_cmcc_minus_storm": 1.0, "ratio_cmcc_over_storm": 1.333333}
                                for key in hazard_comparison_engine._COMPARISON_DELTA_METRIC_KEYS
                            },
                        },
                    },
                },
            }
        },
    }
    metrics_path.write_text(json.dumps(metrics_document, ensure_ascii=False, indent=2), encoding="utf-8")
    payload = {
        "run_id": "20260522_000002",
        "run_dir": str(run_dir),
        "output_root": str(tmp_path / "runs"),
        "territories": {"demo": {"label": "Demo", "status": "complete", "phases": {}}},
        "comparison_metrics": {"status": "complete", "path": str(metrics_path)},
    }

    monkeypatch.setattr(hazard_comparison_engine, "_require_phase5_runtime", lambda: {"plt": object()})
    monkeypatch.setattr(
        hazard_comparison_engine,
        "_render_phase5_metric_chart",
        lambda plt, payload, output_path: output_path.write_text("png", encoding="utf-8"),
    )

    exported = materialize_hazard_comparison_exports(payload)

    summary_path = Path(exported["comparison_exports"]["summary_path"])
    tables_dir = summary_path.parent / "tables"
    charts_dir = summary_path.parent / "charts"

    assert exported["status"] == "complete"
    assert exported["mode"] == "phase5_export_artifacts"
    assert exported["territories"]["demo"]["phases"]["phase5_export_artifacts"]["status"] == "complete"
    assert summary_path.exists()
    assert (tables_dir / "component-metrics-long.csv").exists()
    assert (tables_dir / "storm-vs-storm_cmcc-deltas.csv").exists()
    assert (tables_dir / "component-comparison-wide.csv").exists()
    assert len(list(charts_dir.glob("*.png"))) == 10
    assert json.loads((charts_dir / "wind__intensity_max.json").read_text(encoding="utf-8"))["units"] == "km/h"
    assert json.loads((charts_dir / "wind__intensity_max_return_periods__storm.json").read_text(encoding="utf-8"))["show_value_labels"] is False
    assert exported["comparison_exports"]["chart_count"] == 10


def test_materialize_hazard_comparison_report_writes_html_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "runs" / "20260522_000003"
    metrics_path = run_dir / "comparison-metrics.json"
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_document = {
        "run_id": "20260522_000003",
        "generated_at": "2026-05-22T00:00:00Z",
        "status": "complete",
        "pairwise_comparison": "storm_vs_storm_cmcc",
        "component_order": ["wind"],
        "metric_keys": list(hazard_comparison_engine._COMPARISON_DELTA_METRIC_KEYS),
        "territories": {
            "demo": {
                "label": "Demo",
                "status": "complete",
                "scenarios": {
                    "storm": {
                        "status": "complete",
                        "components": {
                            "wind": {
                                "haz_type": "TC",
                                "units": "m/s",
                                "event_count": 2,
                                "frequency_sum_annual": 0.2,
                                "positive_centroid_fraction": 0.5,
                                "intensity_max": 10.0,
                                "intensity_mean_positive": 5.0,
                                "intensity_p95_positive": 9.0,
                                "event_footprint_mean_fraction": 0.3,
                                "event_footprint_p95_fraction": 0.4,
                                "event_footprint_max_fraction": 0.5,
                            }
                        },
                    },
                    "storm_cmcc": {
                        "status": "complete",
                        "components": {
                            "wind": {
                                "haz_type": "TC",
                                "units": "m/s",
                                "event_count": 2,
                                "frequency_sum_annual": 0.2,
                                "positive_centroid_fraction": 0.75,
                                "intensity_max": 15.0,
                                "intensity_mean_positive": 6.0,
                                "intensity_p95_positive": 12.0,
                                "event_footprint_mean_fraction": 0.35,
                                "event_footprint_p95_fraction": 0.45,
                                "event_footprint_max_fraction": 0.55,
                            }
                        },
                    },
                },
                "storm_vs_storm_cmcc": {
                    "status": "complete",
                    "components": {
                        "wind": {
                            "status": "complete",
                            "haz_type": "TC",
                            "units": "m/s",
                            "metrics": {
                                key: {"storm": 1.0, "storm_cmcc": 2.0, "delta_cmcc_minus_storm": 1.0, "ratio_cmcc_over_storm": 2.0}
                                for key in hazard_comparison_engine._COMPARISON_DELTA_METRIC_KEYS
                            },
                        }
                    },
                },
            }
        },
    }
    metrics_path.write_text(json.dumps(metrics_document, ensure_ascii=False, indent=2), encoding="utf-8")
    payload = {
        "run_id": "20260522_000003",
        "run_dir": str(run_dir),
        "output_root": str(tmp_path / "runs"),
        "territories": {"demo": {"label": "Demo", "status": "complete", "phases": {}}},
        "comparison_metrics": {"status": "complete", "path": str(metrics_path)},
    }

    monkeypatch.setattr(hazard_comparison_engine, "_require_phase5_runtime", lambda: {"plt": object()})
    monkeypatch.setattr(
        hazard_comparison_engine,
        "_render_phase5_metric_chart",
        lambda plt, payload, output_path: output_path.write_text("png", encoding="utf-8"),
    )

    exported = materialize_hazard_comparison_exports(payload)
    reported = materialize_hazard_comparison_report(exported)

    index_path = Path(reported["comparison_report"]["index_path"])
    html_text = index_path.read_text(encoding="utf-8")

    assert reported["status"] == "complete"
    assert reported["mode"] == "phase6_html_report"
    assert reported["territories"]["demo"]["phases"]["phase6_html_report"]["status"] == "complete"
    assert index_path.exists()
    assert "Hazard Comparison Report" in html_text
    assert "Top Absolute Deltas" in html_text
    assert "wind__intensity_max.png" in html_text
