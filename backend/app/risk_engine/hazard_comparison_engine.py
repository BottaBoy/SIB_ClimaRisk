from __future__ import annotations

import csv
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import html
import json
import math
import os
from pathlib import Path
from typing import Any, Callable

from ..config import load_settings, resolve_surge_topo_path_for_territory
from .climada_engine import (
    RETURN_PERIODS,
    _build_surge_hazard,
    _normalize_frequency_on_copy,
    _prepare_topo_raster_for_exposure,
    _prepare_topo_raster_with_crs,
)
from .errors import DependencyMissingError
from .hazard_loader import (
    BasinCoverage,
    _build_centroids_from_points,
    _build_hazard_from_tracks,
    load_storm_hazards_from_parquet_for_points,
    release_hazard_bundle_tracks,
    resolve_hazard_bundle_tracks,
)
from .hazard_comparison_registry import (
    DEFAULT_HAZARD_COMPARISON_REGISTRY_PATH,
    load_hazard_comparison_registry,
    validate_hazard_comparison_registry,
)
from .climada_petals_loader import load_climada_petals_hazard_symbols
from .landslide_engine import build_landslide_hazard_from_prob
from .png_label_layout import grouped_bar_figure_size, place_grouped_bar_labels, text_line_count


UTC = timezone.utc
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_HAZARD_COMPARISON_SCENARIOS_PATH = REPO_ROOT / "config" / "hazard-comparison" / "scenarios.json"
DEFAULT_HAZARD_COMPARISON_CATALOGS_PATH = REPO_ROOT / "config" / "hazard-comparison" / "catalogs.json"
DEFAULT_HAZARD_COMPARISON_RUNS_ROOT = REPO_ROOT / "outputs" / "hazard-comparison-runs"

_ALLOWED_COMPONENTS = ("wind", "rain", "surge", "landslide")
_ALLOWED_TRACK_PROVIDERS = {"storm", "storm_cmcc"}
_ALLOWED_LANDSLIDE_FIELDS = {"earthquake_path", "precip_current_path", "precip_ssp585_path"}
_EXPECTED_BASIN_IDS = {"NA": 1, "SI": 3, "SP": 4}
_DEFAULT_SURGE_GRID_DEG = 0.02
_COMPARISON_DELTA_METRIC_KEYS = (
    "event_count",
    "frequency_sum_annual",
    "positive_centroid_fraction",
    "intensity_max",
    "intensity_mean_positive",
    "intensity_p95_positive",
    "event_footprint_mean_fraction",
    "event_footprint_p95_fraction",
    "event_footprint_max_fraction",
)
_PHASE5_PLOT_METRIC_KEYS = (
    "intensity_max",
    "positive_centroid_fraction",
    "event_footprint_p95_fraction",
)
_PHASE5_RETURN_PERIOD_METRIC_KEY = "intensity_max_return_periods"
_COMPONENT_LABELS = {
    "wind": "Vent",
    "rain": "Pluie",
    "surge": "Submersion cotiere",
    "landslide": "Mouvement de terrain",
}
_PHASE5_METRIC_LABELS = {
    "event_count": "Nombre d'evenements",
    "frequency_sum_annual": "Frequence annuelle cumulee",
    "positive_centroid_fraction": "Part des centroides positifs",
    "intensity_max": "Intensite maximale",
    "intensity_max_return_periods": "Intensite maximale par temps de retour",
    "intensity_mean_positive": "Intensite moyenne positive",
    "intensity_p95_positive": "Intensite positive P95",
    "event_footprint_mean_fraction": "Part moyenne d'emprise evenementielle",
    "event_footprint_p95_fraction": "Part P95 d'emprise evenementielle",
    "event_footprint_max_fraction": "Part maximale d'emprise evenementielle",
}
_PHASE5_GEOGRAPHIC_GROUP_LABELS = {
    "antilles": "Antilles",
    "guyane": "Guyane",
    "saint_pierre_miquelon": "Saint-Pierre-et-Miquelon",
    "ocean_indien": "Ocean Indien",
    "ocean_pacifique": "Ocean Pacifique",
    "na_autres": "NA autres",
}
_PHASE5_TERRITORY_GROUP_OVERRIDES = {
    "guadeloupe": "antilles",
    "martinique": "antilles",
    "saint_barthelemy": "antilles",
    "saint_martin": "antilles",
    "guyane": "guyane",
    "saint_pierre_et_miquelon": "saint_pierre_miquelon",
    "la_reunion": "ocean_indien",
    "mayotte": "ocean_indien",
    "nouvelle_caledonie": "ocean_pacifique",
}
_PHASE5_GROUP_COLOR_FAMILIES = {
    "antilles": ("#0f766e", "#15803d", "#0d9488", "#2f855a"),
    "guyane": ("#166534", "#15803d"),
    "saint_pierre_miquelon": ("#64748b", "#475569"),
    "ocean_indien": ("#ea580c", "#f97316", "#fb7185"),
    "ocean_pacifique": ("#2563eb", "#4f46e5", "#1d4ed8"),
    "na_autres": ("#475569", "#334155"),
}
_PHASE5_GROUP_LABEL_COLORS = {
    "antilles": "#0f766e",
    "guyane": "#166534",
    "saint_pierre_miquelon": "#475569",
    "ocean_indien": "#c2410c",
    "ocean_pacifique": "#3730a3",
    "na_autres": "#334155",
}
_PHASE5_GROUP_BACKGROUND_COLORS = {
    "antilles": "#dff7f2",
    "guyane": "#dcfce7",
    "saint_pierre_miquelon": "#e2e8f0",
    "ocean_indien": "#ffedd5",
    "ocean_pacifique": "#dbeafe",
    "na_autres": "#e5e7eb",
}
_PHASE5_GROUP_HATCHES = {
    "antilles": "//",
    "guyane": "..",
    "saint_pierre_miquelon": "xx",
    "ocean_indien": "\\\\",
    "ocean_pacifique": "oo",
    "na_autres": "--",
}


@dataclass(frozen=True)
class HazardComparisonScenarioSet:
    path: Path
    payload: dict[str, Any]

    @property
    def meta(self) -> dict[str, Any]:
        return dict(self.payload.get("meta") or {})

    @property
    def scenarios(self) -> dict[str, dict[str, Any]]:
        raw = self.payload.get("scenarios") or {}
        return {
            str(key): dict(value)
            for key, value in raw.items()
            if isinstance(value, dict)
        }

    @property
    def scenario_ids(self) -> tuple[str, ...]:
        return tuple(self.scenarios.keys())


@dataclass(frozen=True)
class HazardComparisonScenarioValidation:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    scenario_ids: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    def raise_for_errors(self) -> None:
        if self.errors:
            raise ValueError("Invalid hazard comparison scenarios:\n- " + "\n- ".join(self.errors))


@dataclass(frozen=True)
class HazardComparisonCatalogValidation:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    catalog_keys: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    def raise_for_errors(self) -> None:
        if self.errors:
            raise ValueError("Invalid hazard comparison catalogs:\n- " + "\n- ".join(self.errors))


class HazardComparisonExecutionError(RuntimeError):
    def __init__(self, message: str, *, payload: dict[str, Any]):
        super().__init__(message)
        self.payload = payload


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _emit_progress(progress_callback: Callable[[dict[str, Any]], None] | None, payload: dict[str, Any]) -> None:
    if progress_callback is None:
        return
    progress_callback(dict(payload))


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object at {path}")
    return payload


def _write_json_object(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)


def load_hazard_comparison_scenarios(path: Path | None = None) -> HazardComparisonScenarioSet:
    resolved = Path(path or DEFAULT_HAZARD_COMPARISON_SCENARIOS_PATH)
    payload = _read_json_object(resolved)
    return HazardComparisonScenarioSet(path=resolved, payload=payload)


def validate_hazard_comparison_scenarios(path: Path | None = None) -> HazardComparisonScenarioValidation:
    scenario_set = load_hazard_comparison_scenarios(path)
    errors: list[str] = []
    warnings: list[str] = []

    if not scenario_set.scenarios:
        errors.append("scenarios map is empty")

    for scenario_id, entry in scenario_set.scenarios.items():
        label = str(entry.get("label") or "").strip()
        if not label:
            errors.append(f"{scenario_id}: missing label")

        provider = str(entry.get("track_catalog_provider") or "").strip().lower()
        if provider not in _ALLOWED_TRACK_PROVIDERS:
            errors.append(f"{scenario_id}: unsupported track_catalog_provider '{provider}'")

        components = entry.get("components")
        if not isinstance(components, dict):
            errors.append(f"{scenario_id}: components must be an object")
            continue

        component_ids = tuple(str(value) for value in components.keys())
        missing_components = [component_id for component_id in _ALLOWED_COMPONENTS if component_id not in component_ids]
        unexpected_components = [component_id for component_id in component_ids if component_id not in _ALLOWED_COMPONENTS]
        if missing_components:
            errors.append(f"{scenario_id}: missing components {missing_components}")
        if unexpected_components:
            errors.append(f"{scenario_id}: unexpected components {unexpected_components}")

        for component_id in _ALLOWED_COMPONENTS:
            component = components.get(component_id)
            if not isinstance(component, dict):
                continue
            if not bool(component.get("enabled")):
                errors.append(f"{scenario_id}/{component_id}: component must stay enabled in fail-closed mode")

            source = str(component.get("source") or "").strip()
            if component_id in {"wind", "rain", "surge"} and source != "track_catalog":
                errors.append(f"{scenario_id}/{component_id}: source must be 'track_catalog'")
            if component_id == "surge":
                topography_source = str(component.get("topography_source") or "").strip()
                if topography_source != "canonical_copernicus":
                    errors.append(
                        f"{scenario_id}/surge: topography_source must be 'canonical_copernicus', got '{topography_source}'"
                    )
            if component_id == "landslide":
                if source != "native_raster_pair":
                    errors.append(f"{scenario_id}/landslide: source must be 'native_raster_pair'")
                combination_mode = str(component.get("combination_mode") or "").strip()
                if combination_mode != "concatenate_native_hazards":
                    errors.append(
                        f"{scenario_id}/landslide: combination_mode must be 'concatenate_native_hazards', got '{combination_mode}'"
                    )
                raster_fields = component.get("raster_fields")
                if not isinstance(raster_fields, list) or len(raster_fields) != 2:
                    errors.append(f"{scenario_id}/landslide: raster_fields must contain exactly 2 entries")
                else:
                    normalized_fields = [str(value).strip() for value in raster_fields]
                    if len(set(normalized_fields)) != 2:
                        errors.append(f"{scenario_id}/landslide: raster_fields must be unique")
                    unknown_fields = [value for value in normalized_fields if value not in _ALLOWED_LANDSLIDE_FIELDS]
                    if unknown_fields:
                        errors.append(f"{scenario_id}/landslide: unknown raster fields {unknown_fields}")
                    if "earthquake_path" not in normalized_fields:
                        errors.append(f"{scenario_id}/landslide: raster_fields must include earthquake_path")
                    if provider == "storm" and "precip_current_path" not in normalized_fields:
                        errors.append(
                            f"{scenario_id}/landslide: STORM scenarios must include precip_current_path"
                        )
                    if provider == "storm_cmcc" and "precip_ssp585_path" not in normalized_fields:
                        errors.append(
                            f"{scenario_id}/landslide: STORM_CMCC scenarios must include precip_ssp585_path"
                        )

    return HazardComparisonScenarioValidation(
        errors=tuple(errors),
        warnings=tuple(warnings),
        scenario_ids=scenario_set.scenario_ids,
    )


def _load_catalog_index(path: Path | None = None) -> dict[tuple[str, str], dict[str, Any]]:
    resolved = Path(path or DEFAULT_HAZARD_COMPARISON_CATALOGS_PATH)
    payload = _read_json_object(resolved)
    catalogs = payload.get("catalogs") if isinstance(payload.get("catalogs"), dict) else {}
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for basin_code, basin_entry in catalogs.items():
        if not isinstance(basin_entry, dict):
            continue
        for provider, entry in basin_entry.items():
            if isinstance(entry, dict):
                index[(str(basin_code).upper(), str(provider).lower())] = dict(entry)
    return index


def _catalog_manifest_payload(path: Path) -> dict[str, Any]:
    payload = _read_json_object(path)
    return payload


def _count_catalog_track_instances(parquet_path: Path) -> int:
    try:
        import pandas as pd
    except Exception as exc:  # pragma: no cover - optional in narrow preflight contexts
        raise DependencyMissingError("Pandas is required to count year-aware track instances from comparison catalogs") from exc

    df = pd.read_parquet(parquet_path, columns=["Year", "track_id"])
    missing = sorted({"Year", "track_id"} - set(df.columns))
    if missing:
        raise ValueError(f"Missing required catalog columns in {parquet_path}: {missing}")
    return int(df[["Year", "track_id"]].drop_duplicates().shape[0])


def _resolved_catalog_track_count(manifest: dict[str, Any], parquet_path: Path) -> tuple[int, bool]:
    track_count = int(manifest.get("track_count") or 0)
    track_identity_version = int(manifest.get("track_identity_version") or 1)
    if track_identity_version >= 2:
        return track_count, False
    return _count_catalog_track_instances(parquet_path), True


def validate_hazard_comparison_catalogs(
    path: Path | None = None,
    *,
    check_filesystem: bool = True,
) -> HazardComparisonCatalogValidation:
    errors: list[str] = []
    warnings: list[str] = []
    index = _load_catalog_index(path)

    for basin_code, basin_id in _EXPECTED_BASIN_IDS.items():
        for provider in sorted(_ALLOWED_TRACK_PROVIDERS):
            entry = index.get((basin_code, provider))
            if entry is None:
                errors.append(f"missing catalog entry for {basin_code}/{provider}")
                continue

            actual_basin_id = int(entry.get("basin_id") or 0)
            if actual_basin_id != basin_id:
                errors.append(
                    f"{basin_code}/{provider}: expected basin_id={basin_id}, got {actual_basin_id}"
                )

            parquet_path = Path(str(entry.get("parquet_path") or ""))
            manifest_path = Path(str(entry.get("manifest_path") or ""))
            if check_filesystem and not parquet_path.exists():
                errors.append(f"{basin_code}/{provider}: parquet catalog not found: {parquet_path}")
            if check_filesystem and not manifest_path.exists():
                errors.append(f"{basin_code}/{provider}: catalog manifest not found: {manifest_path}")
            if check_filesystem and manifest_path.exists():
                manifest = _catalog_manifest_payload(manifest_path)
                row_count = int(manifest.get("row_count") or 0)
                try:
                    track_count, track_count_corrected = _resolved_catalog_track_count(manifest, parquet_path)
                except Exception as exc:
                    errors.append(f"{basin_code}/{provider}: could not resolve year-aware track_count: {exc}")
                    track_count = int(manifest.get("track_count") or 0)
                    track_count_corrected = False
                if row_count <= 0:
                    errors.append(f"{basin_code}/{provider}: manifest row_count must be > 0")
                if track_count <= 0:
                    errors.append(f"{basin_code}/{provider}: manifest track_count must be > 0")
                if track_count_corrected:
                    warnings.append(
                        f"{basin_code}/{provider}: legacy manifest track_count was corrected from parquet using year-aware track identity"
                    )
                manifest_basin_code = str(manifest.get("basin_code") or "").upper()
                manifest_provider = str(manifest.get("provider") or "").lower()
                if manifest_basin_code != basin_code:
                    errors.append(
                        f"{basin_code}/{provider}: manifest basin_code mismatch ({manifest_basin_code})"
                    )
                if manifest_provider != provider:
                    errors.append(
                        f"{basin_code}/{provider}: manifest provider mismatch ({manifest_provider})"
                    )

    return HazardComparisonCatalogValidation(
        errors=tuple(errors),
        warnings=tuple(warnings),
        catalog_keys=tuple(sorted(f"{basin}/{provider}" for basin, provider in index.keys())),
    )


def _resolve_selected_territory_ids(
    registry: Any,
    territory_ids: tuple[str, ...] | None,
) -> tuple[str, ...]:
    if not territory_ids:
        return registry.included_ids

    alias_to_id: dict[str, str] = {}
    for territory_id, entry in registry.territories.items():
        alias_to_id[str(territory_id)] = str(territory_id)
        aliases = entry.get("aliases") if isinstance(entry.get("aliases"), list) else []
        for alias in aliases:
            alias_to_id[str(alias).strip().lower()] = str(territory_id)

    resolved_ids: list[str] = []
    for raw in territory_ids:
        normalized = alias_to_id.get(str(raw).strip().lower())
        if normalized is None:
            raise ValueError(f"Unknown comparison territory selection: {raw}")
        if normalized not in registry.included_ids:
            raise ValueError(f"Excluded territory cannot be selected for comparison: {raw}")
        if normalized not in resolved_ids:
            resolved_ids.append(normalized)
    return tuple(resolved_ids)


def _resolve_selected_scenario_ids(
    scenario_set: HazardComparisonScenarioSet,
    scenario_ids: tuple[str, ...] | None,
) -> tuple[str, ...]:
    if not scenario_ids:
        return scenario_set.scenario_ids
    resolved_ids: list[str] = []
    for raw in scenario_ids:
        scenario_id = str(raw).strip()
        if scenario_id not in scenario_set.scenario_ids:
            raise ValueError(f"Unknown comparison scenario selection: {raw}")
        if scenario_id not in resolved_ids:
            resolved_ids.append(scenario_id)
    return tuple(resolved_ids)


def _file_details(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path),
        "size_bytes": int(stat.st_size),
        "mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _require_phase3_runtime() -> dict[str, Any]:
    try:
        import numpy as np  # type: ignore
        from climada.hazard import Hazard  # type: ignore
        petals_symbols = {
            **load_climada_petals_hazard_symbols("tc_rainfield", "TCRain"),
            **load_climada_petals_hazard_symbols("tc_surge_bathtub", "TCSurgeBathtub"),
        }
    except Exception as exc:  # pragma: no cover - runtime dependency
        raise DependencyMissingError("CLIMADA Petals runtime dependencies are required for lot 3 hazard generation") from exc
    return {
        "np": np,
        "Hazard": Hazard,
        "TCRain": petals_symbols["TCRain"],
        "TCSurgeBathtub": petals_symbols["TCSurgeBathtub"],
    }


def _require_phase4_runtime() -> dict[str, Any]:
    try:
        import numpy as np  # type: ignore
        from climada.hazard import Hazard  # type: ignore
    except Exception as exc:  # pragma: no cover - runtime dependency
        raise DependencyMissingError("CLIMADA runtime dependencies are required for lot 4 metric extraction") from exc
    return {
        "np": np,
        "Hazard": Hazard,
    }


def _require_phase5_runtime() -> dict[str, Any]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # pragma: no cover - runtime dependency
        raise DependencyMissingError("Matplotlib is required for lot 5 comparison graph exports") from exc
    return {
        "plt": plt,
    }


def _as_1d_float(np: Any, values: Any) -> Any:
    try:
        arr = np.asarray(values, dtype=float).reshape(-1)
    except Exception:
        return np.zeros(0, dtype=float)
    return np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)


def _round_metric(value: Any, *, digits: int = 6) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except Exception:
        return None
    if not math.isfinite(numeric):
        return None
    return round(numeric, digits)


def _write_csv_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row.keys():
            key_str = str(key)
            if key_str in seen:
                continue
            seen.add(key_str)
            fieldnames.append(key_str)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def _metric_label(metric_key: str) -> str:
    return str(_PHASE5_METRIC_LABELS.get(str(metric_key), str(metric_key).replace("_", " ").title()))


def _component_label(component_id: str) -> str:
    normalized = str(component_id or "").strip()
    return str(_COMPONENT_LABELS.get(normalized, normalized.replace("_", " ").title()))


def _metric_is_intensity(metric_key: str) -> bool:
    return str(metric_key).startswith("intensity_")


def _phase5_display_units(component_id: str, units: str, metric_key: str) -> str:
    if str(component_id) == "wind" and _metric_is_intensity(metric_key):
        return "km/h"
    return str(units or "")


def _phase5_display_value(component_id: str, metric_key: str, value: Any) -> float:
    numeric = float(value or 0.0)
    if str(component_id) == "wind" and _metric_is_intensity(metric_key):
        return numeric * 3.6
    return numeric


def _mix_hex_colors(color: str, target: str, ratio: float) -> str:
    source = str(color or "").lstrip("#")
    destination = str(target or "").lstrip("#")
    if len(source) != 6 or len(destination) != 6:
        return str(color or target or "#334155")
    blend_ratio = max(0.0, min(float(ratio), 1.0))
    values = []
    for idx in range(0, 6, 2):
        source_channel = int(source[idx : idx + 2], 16)
        destination_channel = int(destination[idx : idx + 2], 16)
        mixed = int(round(source_channel + ((destination_channel - source_channel) * blend_ratio)))
        values.append(f"{mixed:02x}")
    return "#" + "".join(values)


def _resolve_phase5_geographic_group(territory_id: str, storm_basin_code: str) -> tuple[str, str]:
    group_id = _PHASE5_TERRITORY_GROUP_OVERRIDES.get(str(territory_id or "").strip())
    basin_code = str(storm_basin_code or "").strip().upper()
    if not group_id:
        if basin_code == "SI":
            group_id = "ocean_indien"
        elif basin_code == "SP":
            group_id = "ocean_pacifique"
        elif basin_code == "NA":
            group_id = "na_autres"
        else:
            group_id = "na_autres"
    return group_id, str(_PHASE5_GEOGRAPHIC_GROUP_LABELS.get(group_id, group_id.replace("_", " ").title()))


def _build_phase5_territory_contexts(metrics_document: dict[str, Any]) -> list[dict[str, str]]:
    territories = metrics_document.get("territories") if isinstance(metrics_document.get("territories"), dict) else {}
    group_counts: dict[str, int] = {}
    contexts: list[dict[str, str]] = []
    for territory_id, territory_payload in territories.items():
        if not isinstance(territory_payload, dict):
            continue
        storm_basin_code = str(territory_payload.get("storm_basin_code") or "").strip().upper()
        group_id = str(territory_payload.get("geographic_group_id") or "").strip()
        group_label = str(territory_payload.get("geographic_group_label") or "").strip()
        if not group_id:
            group_id, group_label = _resolve_phase5_geographic_group(str(territory_id), storm_basin_code)
        if not group_label:
            group_label = str(_PHASE5_GEOGRAPHIC_GROUP_LABELS.get(group_id, group_id.replace("_", " ").title()))
        group_index = group_counts.get(group_id, 0)
        group_counts[group_id] = group_index + 1
        palette = _PHASE5_GROUP_COLOR_FAMILIES.get(group_id) or _PHASE5_GROUP_COLOR_FAMILIES["na_autres"]
        fill_color = str(palette[group_index % len(palette)])
        contexts.append(
            {
                "territory_id": str(territory_id),
                "territory_label": str(territory_payload.get("label") or territory_id),
                "storm_basin_code": storm_basin_code,
                "geographic_group_id": group_id,
                "geographic_group_label": group_label,
                "color": fill_color,
                "edgecolor": _mix_hex_colors(fill_color, "#0f172a", 0.28),
                "label_color": str(_PHASE5_GROUP_LABEL_COLORS.get(group_id, fill_color)),
                "background_color": str(_PHASE5_GROUP_BACKGROUND_COLORS.get(group_id, "#e5e7eb")),
                "hatch": str(_PHASE5_GROUP_HATCHES.get(group_id, "--")),
            }
        )
    return contexts


def _resolve_phase5_metrics_document(payload: dict[str, Any]) -> tuple[dict[str, Any], Path]:
    comparison_metrics = payload.get("comparison_metrics") if isinstance(payload.get("comparison_metrics"), dict) else {}
    metrics_path = Path(str(comparison_metrics.get("path") or ""))
    if metrics_path.exists():
        return _read_json_object(metrics_path), metrics_path

    territories_payload = payload.get("territories") if isinstance(payload.get("territories"), dict) else {}
    territories: dict[str, Any] = {}
    for territory_id, territory_payload in territories_payload.items():
        if not isinstance(territory_payload, dict):
            continue
        comparison_payload = territory_payload.get("comparison_metrics") if isinstance(territory_payload.get("comparison_metrics"), dict) else None
        if comparison_payload is None:
            continue
        territories[str(territory_id)] = dict(comparison_payload)
    if not territories:
        raise ValueError("Lot 5 export requires a complete comparison-metrics payload or file path")

    run_dir = Path(
        str(
            payload.get("run_dir")
            or (Path(str(payload.get("output_root") or DEFAULT_HAZARD_COMPARISON_RUNS_ROOT)) / str(payload.get("run_id") or ""))
        )
    )
    metrics_path = run_dir / "comparison-metrics.json"
    document = {
        "run_id": str(payload.get("run_id") or ""),
        "generated_at": _utc_now(),
        "status": str(comparison_metrics.get("status") or "complete"),
        "pairwise_comparison": "storm_vs_storm_cmcc",
        "component_order": list(_ALLOWED_COMPONENTS),
        "metric_keys": list(_COMPARISON_DELTA_METRIC_KEYS),
        "territories": territories,
    }
    _write_json_object(metrics_path, document)
    return document, metrics_path


def _resolve_phase6_export_inputs(payload: dict[str, Any]) -> tuple[dict[str, Any], Path, dict[str, Any], Path]:
    comparison_exports = payload.get("comparison_exports") if isinstance(payload.get("comparison_exports"), dict) else {}
    summary_path_raw = str(comparison_exports.get("summary_path") or "").strip()
    summary_path = Path(summary_path_raw) if summary_path_raw else Path()

    if not summary_path_raw or not summary_path.is_file():
        run_dir = Path(
            str(
                payload.get("run_dir")
                or (Path(str(payload.get("output_root") or DEFAULT_HAZARD_COMPARISON_RUNS_ROOT)) / str(payload.get("run_id") or ""))
            )
        )
        summary_path = run_dir / "comparison-exports" / "summary.json"

    if not summary_path.is_file():
        raise ValueError(f"Lot 6 report requires a lot 5 export summary: {summary_path}")

    summary_document = _read_json_object(summary_path)
    metrics_path_raw = str(summary_document.get("comparison_metrics_path") or "").strip()
    metrics_path = Path(metrics_path_raw) if metrics_path_raw else Path()
    if not metrics_path.is_file():
        raise ValueError(f"Lot 6 report requires the lot 4 comparison metrics JSON referenced by lot 5: {metrics_path}")
    metrics_document = _read_json_object(metrics_path)
    if str(metrics_document.get("status") or "") != "complete":
        raise ValueError(f"Lot 6 report requires a complete comparison-metrics document, got status={metrics_document.get('status')!r}")
    return summary_document, summary_path, metrics_document, metrics_path


def _collect_phase5_export_rows(metrics_document: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    component_rows: list[dict[str, Any]] = []
    comparison_rows: list[dict[str, Any]] = []
    wide_rows: list[dict[str, Any]] = []
    territories = metrics_document.get("territories") if isinstance(metrics_document.get("territories"), dict) else {}
    component_order = [str(value) for value in list(metrics_document.get("component_order") or _ALLOWED_COMPONENTS)]

    for territory_id, territory_payload in territories.items():
        if not isinstance(territory_payload, dict):
            continue
        territory_label = str(territory_payload.get("label") or territory_id)
        scenarios = territory_payload.get("scenarios") if isinstance(territory_payload.get("scenarios"), dict) else {}
        comparison_payload = territory_payload.get("storm_vs_storm_cmcc") if isinstance(territory_payload.get("storm_vs_storm_cmcc"), dict) else {}
        comparison_components = comparison_payload.get("components") if isinstance(comparison_payload.get("components"), dict) else {}

        for scenario_id, scenario_payload in scenarios.items():
            if not isinstance(scenario_payload, dict):
                continue
            components = scenario_payload.get("components") if isinstance(scenario_payload.get("components"), dict) else {}
            for component_id in component_order:
                component_metrics = components.get(component_id)
                if not isinstance(component_metrics, dict):
                    continue
                row = {
                    "run_id": str(metrics_document.get("run_id") or ""),
                    "territory_id": str(territory_id),
                    "territory_label": territory_label,
                    "scenario": str(scenario_id),
                    "component": str(component_id),
                    "haz_type": str(component_metrics.get("haz_type") or ""),
                    "units": str(component_metrics.get("units") or ""),
                }
                for metric_key in _COMPARISON_DELTA_METRIC_KEYS:
                    row[str(metric_key)] = component_metrics.get(metric_key)
                component_rows.append(row)

        for component_id in component_order:
            component_comparison = comparison_components.get(component_id)
            if not isinstance(component_comparison, dict):
                continue
            metrics_payload = component_comparison.get("metrics") if isinstance(component_comparison.get("metrics"), dict) else {}
            wide_row = {
                "run_id": str(metrics_document.get("run_id") or ""),
                "territory_id": str(territory_id),
                "territory_label": territory_label,
                "component": str(component_id),
                "haz_type": str(component_comparison.get("haz_type") or ""),
                "units": str(component_comparison.get("units") or ""),
            }
            for metric_key in _COMPARISON_DELTA_METRIC_KEYS:
                values = metrics_payload.get(metric_key) if isinstance(metrics_payload.get(metric_key), dict) else {}
                row = {
                    "run_id": str(metrics_document.get("run_id") or ""),
                    "territory_id": str(territory_id),
                    "territory_label": territory_label,
                    "component": str(component_id),
                    "haz_type": str(component_comparison.get("haz_type") or ""),
                    "units": str(component_comparison.get("units") or ""),
                    "metric_key": str(metric_key),
                    "metric_label": _metric_label(metric_key),
                    "storm": values.get("storm"),
                    "storm_cmcc": values.get("storm_cmcc"),
                    "delta_cmcc_minus_storm": values.get("delta_cmcc_minus_storm"),
                    "ratio_cmcc_over_storm": values.get("ratio_cmcc_over_storm"),
                }
                comparison_rows.append(row)
                wide_row[f"{metric_key}__storm"] = values.get("storm")
                wide_row[f"{metric_key}__storm_cmcc"] = values.get("storm_cmcc")
                wide_row[f"{metric_key}__delta_cmcc_minus_storm"] = values.get("delta_cmcc_minus_storm")
                wide_row[f"{metric_key}__ratio_cmcc_over_storm"] = values.get("ratio_cmcc_over_storm")
            wide_rows.append(wide_row)

    return component_rows, comparison_rows, wide_rows


def _build_phase5_scalar_chart_payloads(metrics_document: dict[str, Any]) -> list[dict[str, Any]]:
    territories = metrics_document.get("territories") if isinstance(metrics_document.get("territories"), dict) else {}
    if not territories:
        return []
    component_order = [str(value) for value in list(metrics_document.get("component_order") or _ALLOWED_COMPONENTS)]
    territory_contexts = _build_phase5_territory_contexts(metrics_document)

    chart_payloads: list[dict[str, Any]] = []
    for component_id in component_order:
        for metric_key in _PHASE5_PLOT_METRIC_KEYS:
            territory_labels: list[str] = []
            category_styles: list[dict[str, str]] = []
            storm_values: list[float] = []
            cmcc_values: list[float] = []
            units = ""
            haz_type = ""

            for context in territory_contexts:
                territory_id = str(context["territory_id"])
                territory_payload = territories.get(territory_id)
                if not isinstance(territory_payload, dict):
                    continue
                scenarios = territory_payload.get("scenarios") if isinstance(territory_payload.get("scenarios"), dict) else {}
                storm_component = ((scenarios.get("storm") or {}).get("components") or {}).get(component_id)
                cmcc_component = ((scenarios.get("storm_cmcc") or {}).get("components") or {}).get(component_id)
                if not isinstance(storm_component, dict) or not isinstance(cmcc_component, dict):
                    continue

                raw_units = str(storm_component.get("units") or cmcc_component.get("units") or units)
                territory_labels.append(str(context["territory_label"]))
                category_styles.append(
                    {
                        "territory_id": territory_id,
                        "group_id": str(context["geographic_group_id"]),
                        "group_label": str(context["geographic_group_label"]),
                        "label_color": str(context["label_color"]),
                        "background_color": str(context["background_color"]),
                    }
                )
                storm_values.append(_phase5_display_value(component_id, metric_key, storm_component.get(metric_key)))
                cmcc_values.append(_phase5_display_value(component_id, metric_key, cmcc_component.get(metric_key)))
                units = _phase5_display_units(component_id, raw_units, metric_key)
                haz_type = str(storm_component.get("haz_type") or cmcc_component.get("haz_type") or haz_type)

            if not territory_labels:
                continue

            ylabel = _metric_label(metric_key)
            if metric_key == "intensity_max" and units:
                ylabel = f"{ylabel} ({units})"

            chart_payloads.append(
                {
                    "component": str(component_id),
                    "haz_type": haz_type,
                    "metric_key": str(metric_key),
                    "metric_label": _metric_label(metric_key),
                    "units": units,
                    "title": f"{_component_label(component_id)} - {_metric_label(metric_key)}",
                    "ylabel": ylabel,
                    "categories": territory_labels,
                    "series": [
                        {"name": "STORM", "values": storm_values, "color": "#0f766e"},
                        {"name": "STORM_CMCC", "values": cmcc_values, "color": "#b45309"},
                    ],
                    "show_value_labels": True,
                    "value_label_rotation": 0,
                    "value_label_fontsize": 8,
                    "category_styles": category_styles,
                    "group_legend_title": "Groupe geographique",
                    "label_strategy": (
                        "phase5_scalar_grouped_bar_dense_labels"
                        if metric_key in {"positive_centroid_fraction", "event_footprint_p95_fraction"}
                        else None
                    ),
                    "label_fontsize_target": 13,
                    "allow_figure_autoscale": True,
                    "label_lane_gap_pts": 6,
                }
            )
    return chart_payloads


def _build_phase5_return_period_chart_payloads(metrics_document: dict[str, Any]) -> list[dict[str, Any]]:
    territories = metrics_document.get("territories") if isinstance(metrics_document.get("territories"), dict) else {}
    if not territories:
        return []
    component_order = [str(value) for value in list(metrics_document.get("component_order") or _ALLOWED_COMPONENTS)]
    territory_contexts = _build_phase5_territory_contexts(metrics_document)

    chart_payloads: list[dict[str, Any]] = []
    for component_id in component_order:
        for scenario_id, scenario_label in (("storm", "STORM"), ("storm_cmcc", "STORM_CMCC")):
            categories: list[str] = []
            series_payloads: list[dict[str, Any]] = []
            units = ""
            haz_type = ""

            for context in territory_contexts:
                territory_id = str(context["territory_id"])
                territory_payload = territories.get(territory_id)
                if not isinstance(territory_payload, dict):
                    continue
                scenarios = territory_payload.get("scenarios") if isinstance(territory_payload.get("scenarios"), dict) else {}
                component_payload = ((scenarios.get(scenario_id) or {}).get("components") or {}).get(component_id)
                if not isinstance(component_payload, dict):
                    continue

                curve = (
                    component_payload.get(_PHASE5_RETURN_PERIOD_METRIC_KEY)
                    if isinstance(component_payload.get(_PHASE5_RETURN_PERIOD_METRIC_KEY), dict)
                    else {}
                )
                return_periods = [int(value) for value in list(curve.get("return_periods") or [])]
                values = list(curve.get("values") or [])
                if not return_periods or len(return_periods) != len(values):
                    continue

                if not categories:
                    categories = [str(value) for value in return_periods]
                elif len(categories) != len(return_periods):
                    continue

                raw_units = str(component_payload.get("units") or units)
                units = _phase5_display_units(component_id, raw_units, _PHASE5_RETURN_PERIOD_METRIC_KEY) or units
                haz_type = str(component_payload.get("haz_type") or haz_type)
                series_payloads.append(
                    {
                        "name": str(context["territory_label"]),
                        "territory_id": territory_id,
                        "geographic_group_id": str(context["geographic_group_id"]),
                        "values": [
                            _phase5_display_value(component_id, _PHASE5_RETURN_PERIOD_METRIC_KEY, value)
                            for value in values
                        ],
                        "color": str(context["color"]),
                        "edgecolor": str(context["edgecolor"]),
                        "hatch": str(context["hatch"]),
                    }
                )

            if not categories or not series_payloads:
                continue

            metric_label = f"{_metric_label(_PHASE5_RETURN_PERIOD_METRIC_KEY)} ({scenario_label})"
            ylabel = _metric_label(_PHASE5_RETURN_PERIOD_METRIC_KEY)
            if units:
                ylabel = f"{ylabel} ({units})"

            chart_payloads.append(
                {
                    "component": str(component_id),
                    "haz_type": haz_type,
                    "metric_key": f"{_PHASE5_RETURN_PERIOD_METRIC_KEY}__{scenario_id}",
                    "metric_label": metric_label,
                    "units": units,
                    "scenario_id": str(scenario_id),
                    "title": f"{_component_label(component_id)} - {_metric_label(_PHASE5_RETURN_PERIOD_METRIC_KEY)} - {scenario_label}",
                    "xlabel": "Temps de retour (ans)",
                    "ylabel": ylabel,
                    "categories": categories,
                    "series": series_payloads,
                    "show_value_labels": True,
                    "value_label_rotation": 90,
                    "value_label_fontsize": 7,
                    "legend_title": "Territoire",
                }
            )

    return chart_payloads


def _build_phase5_chart_payloads(metrics_document: dict[str, Any]) -> list[dict[str, Any]]:
    return _build_phase5_scalar_chart_payloads(metrics_document) + _build_phase5_return_period_chart_payloads(metrics_document)


def _scaled_phase5_value_label_fontsize(base_fontsize: int | float, *, item_count: int) -> int:
    base_size = max(float(base_fontsize), 1.0)
    scaled = max(base_size * 2.0, base_size + 2.0)
    if item_count >= 18:
        scaled = min(scaled, 14.0)
    else:
        scaled = min(scaled, 16.0)
    return max(9, int(round(scaled)))


def _phase5_label_headroom_ratio(*, label_fontsize: int, rotation: int) -> float:
    font_factor = max(float(label_fontsize) / 8.0, 1.0)
    rotation_factor = 1.35 if rotation else 1.0
    return 0.07 + (0.06 * font_factor * rotation_factor)


def _render_phase5_metric_chart(plt: Any, payload: dict[str, Any], output_path: Path) -> None:
    categories = list(payload.get("categories") or [])
    series = list(payload.get("series") or [])
    category_styles = list(payload.get("category_styles") or [])
    show_value_labels = bool(payload.get("show_value_labels", True))
    strategy = str(payload.get("label_strategy") or "").strip().lower()
    count = max(1, len(series))
    positions = list(range(len(categories)))
    value_label_rotation = int(payload.get("value_label_rotation") or 0)
    value_label_fontsize = int(
        payload.get("label_fontsize_target")
        or _scaled_phase5_value_label_fontsize(
            int(payload.get("value_label_fontsize") or 8),
            item_count=max(len(categories), len(series)),
        )
    )
    dense_label_lines = 1
    if strategy == "phase5_scalar_grouped_bar_dense_labels":
        for series_payload in series:
            for value in list(series_payload.get("values") or []):
                dense_label_lines = max(dense_label_lines, text_line_count(f"{float(value or 0.0):.3g}"))
        width, height = grouped_bar_figure_size(
            category_count=len(categories),
            series_count=len(series),
            label_fontsize=value_label_fontsize,
            max_label_lines=dense_label_lines,
            base_width=max(9.5, float(len(categories)) * 1.45 + float(len(series)) * 0.7),
            base_height=6.1 if show_value_labels else 5.4,
        )
        for _attempt in range(6):
            fig, ax = plt.subplots(figsize=(width, height))
            bar_width = min(0.38, 0.8 / count)
            all_values: list[float] = []
            bar_groups: list[list[Any]] = []
            if len(category_styles) == len(categories):
                for idx, category_style in enumerate(category_styles):
                    ax.axvspan(
                        idx - 0.5,
                        idx + 0.5,
                        facecolor=str(category_style.get("background_color") or "#e5e7eb"),
                        alpha=0.18,
                        zorder=0,
                    )
            for idx, series_payload in enumerate(series):
                values = [float(value or 0.0) for value in list(series_payload.get("values") or [])]
                all_values.extend(values)
                offset = (idx - (count - 1) / 2.0) * bar_width
                bars = ax.bar(
                    [position + offset for position in positions],
                    values,
                    width=bar_width,
                    label=str(series_payload.get("name") or f"series-{idx + 1}"),
                    color=str(series_payload.get("color") or "#334155"),
                    edgecolor=str(series_payload.get("edgecolor") or series_payload.get("color") or "#334155"),
                    linewidth=0.9,
                    hatch=str(series_payload.get("hatch") or ""),
                    zorder=3,
                )
                bar_groups.append(list(bars))
            ax.set_xticks(positions)
            ax.set_xticklabels(categories, rotation=25, ha="right")
            if len(category_styles) == len(categories):
                for tick, category_style in zip(ax.get_xticklabels(), category_styles):
                    tick.set_color(str(category_style.get("label_color") or "#0f172a"))
            if payload.get("xlabel"):
                ax.set_xlabel(str(payload.get("xlabel") or ""))
            ax.set_ylabel(str(payload.get("ylabel") or "Valeur"))
            ax.set_title(str(payload.get("title") or "Comparaison des aleas"))
            max_value = max(all_values) if all_values else 0.0
            top_padding_ratio = (
                _phase5_label_headroom_ratio(label_fontsize=value_label_fontsize, rotation=value_label_rotation)
                if show_value_labels
                else 0.06
            )
            top_padding = max(0.2, max_value * top_padding_ratio)
            ax.set_ylim(0.0, max(1.0, max_value + top_padding))
            ax.grid(axis="y", alpha=0.18, zorder=1)
            ax.margins(x=0.05)
            legend_columns = 1
            if len(series) > 6:
                legend_columns = 3
            elif len(series) > 3:
                legend_columns = 2
            primary_legend = ax.legend(
                title=str(payload.get("legend_title") or "") or None,
                ncol=min(legend_columns, max(1, len(series))),
                fontsize=8 if len(series) > 6 else 9,
                loc="upper left",
            )
            if len(category_styles) == len(categories):
                from matplotlib.patches import Patch

                ax.add_artist(primary_legend)
                group_handles: list[Any] = []
                seen_group_ids: set[str] = set()
                for category_style in category_styles:
                    group_id = str(category_style.get("group_id") or "")
                    if not group_id or group_id in seen_group_ids:
                        continue
                    seen_group_ids.add(group_id)
                    group_handles.append(
                        Patch(
                            facecolor=str(category_style.get("background_color") or "#e5e7eb"),
                            edgecolor=str(category_style.get("label_color") or "#334155"),
                            label=str(category_style.get("group_label") or group_id),
                        )
                    )
                if group_handles:
                    ax.legend(
                        handles=group_handles,
                        title=str(payload.get("group_legend_title") or "Groupe geographique"),
                        loc="upper right",
                        fontsize=8,
                    )
            if show_value_labels:
                label_groups = [
                    [f"{float(value or 0.0):.3g}" for value in list(series_payload.get("values") or [])]
                    for series_payload in series
                ]
                result = place_grouped_bar_labels(
                    ax,
                    bar_groups,
                    label_groups,
                    label_fontsize=value_label_fontsize,
                    lane_gap_pts=float(payload.get("label_lane_gap_pts") or 6.0),
                )
                if result.success:
                    fig.tight_layout()
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    fig.savefig(output_path, dpi=180, bbox_inches="tight")
                    plt.close(fig)
                    return
            else:
                fig.tight_layout()
                output_path.parent.mkdir(parents=True, exist_ok=True)
                fig.savefig(output_path, dpi=180, bbox_inches="tight")
                plt.close(fig)
                return
            plt.close(fig)
            width *= 1.14
            height *= 1.10

    width = max(9.5, float(len(categories)) * 1.45 + float(len(series)) * 0.7)
    fig, ax = plt.subplots(figsize=(width, 6.1 if show_value_labels else 5.4))
    bar_width = min(0.38, 0.8 / count)
    all_values: list[float] = []
    if len(category_styles) == len(categories):
        for idx, category_style in enumerate(category_styles):
            ax.axvspan(
                idx - 0.5,
                idx + 0.5,
                facecolor=str(category_style.get("background_color") or "#e5e7eb"),
                alpha=0.18,
                zorder=0,
            )

    for idx, series_payload in enumerate(series):
        values = [float(value or 0.0) for value in list(series_payload.get("values") or [])]
        all_values.extend(values)
        offset = (idx - (count - 1) / 2.0) * bar_width
        bars = ax.bar(
            [position + offset for position in positions],
            values,
            width=bar_width,
            label=str(series_payload.get("name") or f"series-{idx + 1}"),
            color=str(series_payload.get("color") or "#334155"),
            edgecolor=str(series_payload.get("edgecolor") or series_payload.get("color") or "#334155"),
            linewidth=0.9,
            hatch=str(series_payload.get("hatch") or ""),
            zorder=3,
        )
        if show_value_labels:
            label_offset = max(0.04, (max(all_values) if all_values else 0.0) * 0.02)
            for bar, value in zip(bars, values):
                ax.text(
                    bar.get_x() + bar.get_width() / 2.0,
                    bar.get_height() + label_offset,
                    f"{value:.3g}",
                    ha="center",
                    va="bottom",
                    fontsize=value_label_fontsize,
                    rotation=value_label_rotation,
                    clip_on=True,
                    bbox={"boxstyle": "round,pad=0.18", "facecolor": "white", "edgecolor": "none", "alpha": 0.82},
                )

    ax.set_xticks(positions)
    ax.set_xticklabels(categories, rotation=25, ha="right")
    if len(category_styles) == len(categories):
        for tick, category_style in zip(ax.get_xticklabels(), category_styles):
            tick.set_color(str(category_style.get("label_color") or "#0f172a"))
    if payload.get("xlabel"):
        ax.set_xlabel(str(payload.get("xlabel") or ""))
    ax.set_ylabel(str(payload.get("ylabel") or "Valeur"))
    ax.set_title(str(payload.get("title") or "Comparaison des aleas"))
    max_value = max(all_values) if all_values else 0.0
    top_padding_ratio = (
        _phase5_label_headroom_ratio(label_fontsize=value_label_fontsize, rotation=value_label_rotation)
        if show_value_labels
        else 0.06
    )
    top_padding = max(0.2, max_value * top_padding_ratio)
    ax.set_ylim(0.0, max(1.0, max_value + top_padding))
    ax.grid(axis="y", alpha=0.18, zorder=1)
    ax.margins(x=0.04)
    legend_columns = 1
    if len(series) > 6:
        legend_columns = 3
    elif len(series) > 3:
        legend_columns = 2
    primary_legend = ax.legend(
        title=str(payload.get("legend_title") or "") or None,
        ncol=min(legend_columns, max(1, len(series))),
        fontsize=8 if len(series) > 6 else 9,
        loc="upper left",
    )
    if len(category_styles) == len(categories):
        from matplotlib.patches import Patch

        ax.add_artist(primary_legend)
        group_handles: list[Any] = []
        seen_group_ids: set[str] = set()
        for category_style in category_styles:
            group_id = str(category_style.get("group_id") or "")
            if not group_id or group_id in seen_group_ids:
                continue
            seen_group_ids.add(group_id)
            group_handles.append(
                Patch(
                    facecolor=str(category_style.get("background_color") or "#e5e7eb"),
                    edgecolor=str(category_style.get("label_color") or "#334155"),
                    label=str(category_style.get("group_label") or group_id),
                )
            )
        if group_handles:
            ax.legend(
                handles=group_handles,
                title=str(payload.get("group_legend_title") or "Groupe geographique"),
                loc="upper right",
                fontsize=8,
            )
    ax.margins(x=0.02)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _build_phase6_top_delta_rows(metrics_document: dict[str, Any], *, limit: int = 24) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        territories = metrics_document.get("territories") if isinstance(metrics_document.get("territories"), dict) else {}
        for territory_id, territory_payload in territories.items():
                if not isinstance(territory_payload, dict):
                        continue
                territory_label = str(territory_payload.get("label") or territory_id)
                comparison_payload = territory_payload.get("storm_vs_storm_cmcc") if isinstance(territory_payload.get("storm_vs_storm_cmcc"), dict) else {}
                components = comparison_payload.get("components") if isinstance(comparison_payload.get("components"), dict) else {}
                for component_id, component_payload in components.items():
                        if not isinstance(component_payload, dict):
                                continue
                        metrics_payload = component_payload.get("metrics") if isinstance(component_payload.get("metrics"), dict) else {}
                        for metric_key, values in metrics_payload.items():
                                if not isinstance(values, dict):
                                        continue
                                delta = _round_metric(values.get("delta_cmcc_minus_storm"))
                                if delta is None:
                                        continue
                                rows.append(
                                        {
                                                "territory_id": str(territory_id),
                                                "territory_label": territory_label,
                                                "component": _component_label(str(component_id)),
                                                "metric_key": str(metric_key),
                                                "metric_label": _metric_label(str(metric_key)),
                                                "units": str(component_payload.get("units") or ""),
                                                "storm": _round_metric(values.get("storm")),
                                                "storm_cmcc": _round_metric(values.get("storm_cmcc")),
                                                "delta_cmcc_minus_storm": delta,
                                                "ratio_cmcc_over_storm": _round_metric(values.get("ratio_cmcc_over_storm")),
                                                "abs_delta": abs(float(delta)),
                                        }
                                )
        rows.sort(
                key=lambda row: (
                        -float(row.get("abs_delta") or 0.0),
                        str(row.get("territory_label") or ""),
                        str(row.get("component") or ""),
                        str(row.get("metric_key") or ""),
                )
        )
        return rows[:limit]


def _relative_href(base_dir: Path, target: Path) -> str:
        return os.path.relpath(target, start=base_dir).replace(os.sep, "/")


def _render_phase6_report_html(
        summary_document: dict[str, Any],
        summary_path: Path,
        metrics_document: dict[str, Any],
        metrics_path: Path,
        output_path: Path,
) -> None:
        report_dir = output_path.parent
        table_exports = summary_document.get("table_exports") if isinstance(summary_document.get("table_exports"), dict) else {}
        territories = metrics_document.get("territories") if isinstance(metrics_document.get("territories"), dict) else {}
        territory_labels = [str((payload or {}).get("label") or territory_id) for territory_id, payload in territories.items() if isinstance(payload, dict)]
        top_rows = _build_phase6_top_delta_rows(metrics_document)
        chart_groups: dict[str, list[dict[str, str]]] = {component: [] for component in _ALLOWED_COMPONENTS}
        for chart in list(summary_document.get("charts") or []):
                if not isinstance(chart, dict):
                        continue
                component = str(chart.get("component") or "other")
                image_path = Path(str(chart.get("image_path") or ""))
                payload_file = Path(str(chart.get("payload_path") or ""))
                if not image_path.exists() or not payload_file.exists():
                        continue
                chart_groups.setdefault(component, []).append(
                        {
                                "component": component,
                                "metric_key": str(chart.get("metric_key") or ""),
                                "component_label": _component_label(component),
                                "metric_label": str(chart.get("metric_label") or _metric_label(str(chart.get("metric_key") or ""))),
                                "image_href": _relative_href(report_dir, image_path),
                                "payload_href": _relative_href(report_dir, payload_file),
                        }
                )

        top_rows_html = "".join(
                "<tr>"
                f"<td>{html.escape(str(row['territory_label']))}</td>"
                f"<td>{html.escape(str(row['component']))}</td>"
                f"<td>{html.escape(str(row['metric_label']))}</td>"
                f"<td>{html.escape(str(row['delta_cmcc_minus_storm']))}</td>"
                f"<td>{html.escape(str(row['ratio_cmcc_over_storm']))}</td>"
                f"<td>{html.escape(str(row['units']))}</td>"
                "</tr>"
                for row in top_rows
        )
        if not top_rows_html:
                top_rows_html = '<tr><td colspan="6">Aucun delta de comparaison disponible.</td></tr>'

        table_links_html = "".join(
                f'<li><a href="{html.escape(_relative_href(report_dir, Path(str(path))))}">{html.escape(name)}</a></li>'
                for name, path in table_exports.items()
                if str(path)
        )
        chart_sections_html: list[str] = []
        for component in _ALLOWED_COMPONENTS:
                entries = chart_groups.get(component) or []
                if not entries:
                        continue
                cards_html = "".join(
                        "<article class=\"chart-card\">"
                        f"<h3>{html.escape(entry['metric_label'])}</h3>"
                        f"<a class=\"chart-link\" href=\"{html.escape(entry['image_href'])}\"><img src=\"{html.escape(entry['image_href'])}\" alt=\"{html.escape(entry['component_label'])} {html.escape(entry['metric_label'])}\"></a>"
                        f"<p><a href=\"{html.escape(entry['payload_href'])}\">Charge utile JSON</a></p>"
                        "</article>"
                        for entry in entries
                )
                chart_sections_html.append(
                        "<section class=\"component-section\">"
                        f"<h2>{html.escape(_component_label(component))}</h2>"
                        f"<div class=\"chart-grid\">{cards_html}</div>"
                        "</section>"
                )

        html_text = f"""<!doctype html>
<html lang=\"fr\">
<head>
    <meta charset=\"utf-8\">
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
    <title>Rapport de comparaison des aleas - {html.escape(str(metrics_document.get('run_id') or ''))}</title>
    <style>
        :root {{
            --bg: #f2efe8;
            --ink: #142033;
            --muted: #5d6a78;
            --card: rgba(255,255,255,0.92);
            --line: rgba(20,32,51,0.12);
            --accent: #0f766e;
            --accent-2: #9a3412;
            --shadow: 0 18px 38px rgba(20,32,51,0.12);
        }}
        * {{ box-sizing: border-box; }}
        body {{
            margin: 0;
            color: var(--ink);
            font-family: "Avenir Next", "Segoe UI", sans-serif;
            background:
                radial-gradient(circle at top left, rgba(15,118,110,0.16), transparent 28%),
                radial-gradient(circle at top right, rgba(154,52,18,0.12), transparent 26%),
                linear-gradient(180deg, #f7f4ee 0%, var(--bg) 100%);
        }}
        header {{ padding: 40px 32px 24px; }}
        h1, h2, h3 {{ margin: 0; font-family: "Georgia", "Times New Roman", serif; }}
        header p {{ color: var(--muted); max-width: 1000px; }}
        .shell {{ padding: 0 32px 40px; display: grid; gap: 24px; }}
        .hero, .panel, .component-section {{
            background: var(--card);
            border: 1px solid var(--line);
            border-radius: 24px;
            box-shadow: var(--shadow);
            backdrop-filter: blur(10px);
        }}
        .hero {{ padding: 24px; display: grid; gap: 18px; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 14px; }}
        .stat {{ padding: 16px; border-radius: 18px; background: rgba(20,32,51,0.04); border: 1px solid rgba(20,32,51,0.08); }}
        .stat strong {{ display: block; font-size: 1.6rem; color: var(--accent); }}
        .meta-list, .downloads {{ margin: 0; padding-left: 18px; }}
        .layout {{ display: grid; grid-template-columns: 1.1fr 0.9fr; gap: 24px; align-items: start; }}
        .panel {{ padding: 22px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 14px; }}
        th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
        th {{ font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); }}
        .component-section {{ padding: 22px; display: grid; gap: 18px; }}
        .chart-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 18px; }}
        .chart-card {{ padding: 16px; border-radius: 18px; background: rgba(20,32,51,0.035); border: 1px solid rgba(20,32,51,0.08); }}
        .chart-card img {{ width: 100%; height: auto; display: block; border-radius: 14px; border: 1px solid var(--line); background: #fff; }}
        a {{ color: var(--accent); }}
        a:hover {{ color: var(--accent-2); }}
        .chart-link {{ display: block; margin-top: 12px; }}
        @media (max-width: 980px) {{
            .layout {{ grid-template-columns: 1fr; }}
            header, .shell {{ padding-left: 18px; padding-right: 18px; }}
        }}
    </style>
</head>
<body>
    <header>
        <h1>Rapport de comparaison des aleas</h1>
        <p>Run <strong>{html.escape(str(metrics_document.get('run_id') or ''))}</strong> derive des artefacts d'export du lot 5. Ce rapport est statique et orienté audit : il relie uniquement les sorties persistees des lots 4 et 5.</p>
    </header>
    <main class=\"shell\">
        <section class=\"hero\">
            <div class=\"stats\">
                <div class=\"stat\"><strong>{html.escape(str(summary_document.get('territory_count') or 0))}</strong><span>Territoires</span></div>
                <div class=\"stat\"><strong>{html.escape(str(summary_document.get('chart_count') or 0))}</strong><span>Graphes</span></div>
                <div class=\"stat\"><strong>{html.escape(str(summary_document.get('component_metric_row_count') or 0))}</strong><span>Lignes composant</span></div>
                <div class=\"stat\"><strong>{html.escape(str(summary_document.get('comparison_delta_row_count') or 0))}</strong><span>Lignes delta</span></div>
            </div>
            <div class=\"layout\">
                <section class=\"panel\">
                    <h2>Perimetre</h2>
                    <ul class=\"meta-list\">
                        <li>Territoires : {html.escape(', '.join(territory_labels) if territory_labels else 'n/a')}</li>
                        <li>JSON des metriques : <a href=\"{html.escape(_relative_href(report_dir, metrics_path))}\">comparison-metrics.json</a></li>
                        <li>Resume d'export : <a href=\"{html.escape(_relative_href(report_dir, summary_path))}\">summary.json</a></li>
                    </ul>
                </section>
                <section class=\"panel\">
                    <h2>Telechargements</h2>
                    <ul class=\"downloads\">{table_links_html}</ul>
                </section>
            </div>
        </section>
        <section class=\"panel\">
            <h2>Plus grands deltas absolus</h2>
            <table>
                <thead>
                    <tr><th>Territoire</th><th>Composant</th><th>Metrique</th><th>Delta</th><th>Ratio</th><th>Unites</th></tr>
                </thead>
                <tbody>{top_rows_html}</tbody>
            </table>
        </section>
        {''.join(chart_sections_html)}
    </main>
</body>
</html>
"""
        output_path.write_text(html_text, encoding="utf-8")


def _load_hazard_from_hdf5(hazard_cls: Any, path: Path) -> Any:
    return hazard_cls.from_hdf5(str(path))


def _hazard_positive_intensity_values(np: Any, hazard_obj: Any) -> Any:
    intensity = getattr(hazard_obj, "intensity", None)
    if intensity is None:
        return np.zeros(0, dtype=float)
    data = getattr(intensity, "data", None)
    if data is not None:
        arr = _as_1d_float(np, data)
        return arr[arr > 0.0]
    arr = _as_1d_float(np, intensity)
    return arr[arr > 0.0]


def _hazard_event_nonzero_counts(np: Any, hazard_obj: Any) -> Any:
    intensity = getattr(hazard_obj, "intensity", None)
    event_count = int(_hazard_event_count(hazard_obj))
    if intensity is None:
        return np.zeros(event_count, dtype=int)

    if hasattr(intensity, "tocsr"):
        csr = intensity.tocsr()
        counts = np.asarray(np.diff(csr.indptr), dtype=int).reshape(-1)
    else:
        arr = np.asarray(intensity)
        if arr.ndim == 0:
            counts = np.zeros(event_count, dtype=int)
        else:
            if arr.ndim == 1:
                arr = arr.reshape(1, -1)
            counts = np.count_nonzero(arr > 0.0, axis=1).astype(int)

    if event_count <= 0:
        return counts
    if counts.size == event_count:
        return counts
    if counts.size > event_count:
        return counts[:event_count]
    padded = np.zeros(event_count, dtype=int)
    padded[: counts.size] = counts
    return padded


def _hazard_event_positive_maxima(np: Any, hazard_obj: Any) -> Any:
    intensity = getattr(hazard_obj, "intensity", None)
    event_count = int(_hazard_event_count(hazard_obj))
    if intensity is None or event_count <= 0:
        return np.zeros(max(0, event_count), dtype=float)

    if hasattr(intensity, "tocsr"):
        csr = intensity.tocsr()
        if getattr(csr, "nnz", 0) <= 0:
            return np.zeros(event_count, dtype=float)
        maxima = np.asarray(csr.max(axis=1).toarray(), dtype=float).reshape(-1)
    else:
        arr = np.asarray(intensity, dtype=float)
        if arr.ndim == 0:
            return np.zeros(event_count, dtype=float)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        maxima = np.max(np.where(arr > 0.0, arr, 0.0), axis=1).astype(float)

    if maxima.size == event_count:
        return maxima
    if maxima.size > event_count:
        return maxima[:event_count]
    padded = np.zeros(event_count, dtype=float)
    padded[: maxima.size] = maxima
    return padded


def _compute_return_period_curve(np: Any, values: Any, frequency: Any, return_periods: tuple[int, ...]) -> dict[str, Any]:
    values_arr = _as_1d_float(np, values)
    freq_arr = _as_1d_float(np, frequency)
    size = min(values_arr.size, freq_arr.size)
    if size <= 0:
        return {
            "return_periods": [int(rp) for rp in return_periods],
            "values": [0.0 for _ in return_periods],
        }

    values_arr = values_arr[:size]
    freq_arr = freq_arr[:size]
    valid = (values_arr > 0.0) & (freq_arr > 0.0)
    if not valid.any():
        return {
            "return_periods": [int(rp) for rp in return_periods],
            "values": [0.0 for _ in return_periods],
        }

    values_valid = values_arr[valid]
    freq_valid = freq_arr[valid]
    sort_idxs = np.argsort(values_valid)[::-1]
    exceed_freq = np.cumsum(freq_valid[sort_idxs])
    impact_curve = values_valid[sort_idxs][::-1]
    return_curve = np.divide(
        1.0,
        exceed_freq[::-1],
        out=np.full(exceed_freq.size, np.inf, dtype=float),
        where=exceed_freq[::-1] > 0.0,
    )
    finite = np.isfinite(return_curve) & (return_curve > 0.0)
    if not finite.any():
        return {
            "return_periods": [int(rp) for rp in return_periods],
            "values": [0.0 for _ in return_periods],
        }

    interpolated = np.interp(
        np.asarray(return_periods, dtype=float),
        return_curve[finite],
        impact_curve[finite],
    )
    return {
        "return_periods": [int(rp) for rp in return_periods],
        "values": [
            float(_round_metric(max(0.0, interpolated[idx])) or 0.0)
            for idx, _ in enumerate(return_periods)
        ],
    }


def _hazard_positive_centroid_count(np: Any, hazard_obj: Any) -> int:
    intensity = getattr(hazard_obj, "intensity", None)
    if intensity is None:
        return 0
    if hasattr(intensity, "tocsr"):
        csr = intensity.tocsr()
        if getattr(csr, "nnz", 0) <= 0:
            return 0
        return int(np.unique(np.asarray(csr.indices, dtype=int)).size)

    arr = np.asarray(intensity)
    if arr.ndim == 0:
        return 0
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    return int(np.count_nonzero(np.any(arr > 0.0, axis=0)))


def _prepare_phase3_surge_topography(
    topo_path: Path,
    *,
    point_records: list[dict[str, Any]],
    hazard_source: str | None,
) -> Path:
    source_name = str(hazard_source or "").strip().lower()
    if source_name == "dynamic_parquet":
        # Dynamic comparison surge uses pointwise raster sampling; avoid materializing
        # a large cropped DEM window for wide territories such as Guyane.
        return _prepare_topo_raster_with_crs(topo_path)
    return _prepare_topo_raster_for_exposure(topo_path, point_records=point_records)


def _component_metric_delta(storm_value: Any, cmcc_value: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "storm": storm_value,
        "storm_cmcc": cmcc_value,
        "delta_cmcc_minus_storm": None,
        "ratio_cmcc_over_storm": None,
    }
    try:
        if storm_value is not None and cmcc_value is not None:
            storm_numeric = float(storm_value)
            cmcc_numeric = float(cmcc_value)
            payload["delta_cmcc_minus_storm"] = _round_metric(cmcc_numeric - storm_numeric)
            if storm_numeric != 0.0:
                payload["ratio_cmcc_over_storm"] = _round_metric(cmcc_numeric / storm_numeric)
    except Exception:
        return payload
    return payload


def _build_component_metric_comparison(storm_metrics: dict[str, Any], cmcc_metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "complete",
        "haz_type": str(storm_metrics.get("haz_type") or cmcc_metrics.get("haz_type") or ""),
        "units": str(storm_metrics.get("units") or cmcc_metrics.get("units") or ""),
        "metrics": {
            key: _component_metric_delta(storm_metrics.get(key), cmcc_metrics.get(key))
            for key in _COMPARISON_DELTA_METRIC_KEYS
        },
    }


def _summarize_hazard_comparison_metrics(np: Any, hazard_obj: Any, *, output_path: Path) -> dict[str, Any]:
    event_count = int(_hazard_event_count(hazard_obj))
    centroid_count = int(_hazard_centroid_count(hazard_obj))
    positive_values = _hazard_positive_intensity_values(np, hazard_obj)
    positive_centroid_count = int(_hazard_positive_centroid_count(np, hazard_obj))
    event_nonzero_counts = _hazard_event_nonzero_counts(np, hazard_obj)
    positive_event_counts = event_nonzero_counts[event_nonzero_counts > 0]
    frequency = _as_1d_float(np, getattr(hazard_obj, "frequency", []))
    event_positive_maxima = _hazard_event_positive_maxima(np, hazard_obj)

    return {
        "haz_type": str(getattr(hazard_obj, "haz_type", "") or ""),
        "units": str(getattr(hazard_obj, "units", "") or ""),
        "event_count": int(event_count),
        "centroid_count": int(centroid_count),
        "intensity_nnz": int(getattr(getattr(hazard_obj, "intensity", None), "nnz", 0) or 0),
        "frequency_sum_annual": _round_metric(frequency.sum() if frequency.size else 0.0, digits=8),
        "positive_event_count": int(positive_event_counts.size),
        "positive_event_fraction": _round_metric(
            float(positive_event_counts.size) / float(max(event_count, 1)),
        ),
        "positive_centroid_count": int(positive_centroid_count),
        "positive_centroid_fraction": _round_metric(
            float(positive_centroid_count) / float(max(centroid_count, 1)),
        ),
        "intensity_max": _round_metric(positive_values.max() if positive_values.size else 0.0),
        "intensity_max_return_periods": _compute_return_period_curve(np, event_positive_maxima, frequency, RETURN_PERIODS),
        "intensity_mean_positive": _round_metric(positive_values.mean() if positive_values.size else 0.0),
        "intensity_p95_positive": _round_metric(np.percentile(positive_values, 95) if positive_values.size else 0.0),
        "event_footprint_mean_count": _round_metric(positive_event_counts.mean() if positive_event_counts.size else 0.0),
        "event_footprint_p95_count": _round_metric(
            np.percentile(positive_event_counts, 95) if positive_event_counts.size else 0.0
        ),
        "event_footprint_max_count": int(positive_event_counts.max()) if positive_event_counts.size else 0,
        "event_footprint_mean_fraction": _round_metric(
            (positive_event_counts.mean() / float(max(centroid_count, 1))) if positive_event_counts.size else 0.0
        ),
        "event_footprint_p95_fraction": _round_metric(
            (np.percentile(positive_event_counts, 95) / float(max(centroid_count, 1))) if positive_event_counts.size else 0.0
        ),
        "event_footprint_max_fraction": _round_metric(
            (positive_event_counts.max() / float(max(centroid_count, 1))) if positive_event_counts.size else 0.0
        ),
        "output": _file_details(output_path),
    }


def _aligned_grid_centers(min_coord: float, max_coord: float, step: float) -> list[float]:
    grid_step = max(1e-6, float(step))
    start = math.floor(float(min_coord) / grid_step) * grid_step
    stop = math.ceil(float(max_coord) / grid_step) * grid_step
    centers: list[float] = []
    current = start
    while current <= stop + 1e-9:
        centers.append(round(float(current), 6))
        current += grid_step
    return centers


def _build_point_records_from_bbox(bbox: dict[str, Any], *, grid_step_deg: float) -> list[dict[str, float]]:
    lon_min = float(bbox.get("lon_min"))
    lat_min = float(bbox.get("lat_min"))
    lon_max = float(bbox.get("lon_max"))
    lat_max = float(bbox.get("lat_max"))
    lat_centers = _aligned_grid_centers(lat_min, lat_max, float(grid_step_deg))
    lon_centers = _aligned_grid_centers(lon_min, lon_max, float(grid_step_deg))
    return [
        {
            "lat": float(lat),
            "lon": float(lon),
        }
        for lat in lat_centers
        for lon in lon_centers
    ]


def _single_basin_coverage(basin_code: str) -> tuple[BasinCoverage, ...]:
    basin_id = _EXPECTED_BASIN_IDS.get(str(basin_code).upper())
    if basin_id is None:
        raise ValueError(f"Unsupported comparison basin code: {basin_code}")
    return (
        BasinCoverage(
            basin_id=int(basin_id),
            code=str(basin_code).upper(),
            label=str(basin_code).upper(),
            lat_min=-90.0,
            lat_max=90.0,
            lon_min=-180.0,
            lon_max=180.0,
        ),
    )


def _hazard_event_count(hazard_obj: Any) -> int:
    event_ids = getattr(hazard_obj, "event_id", None)
    if event_ids is None:
        return 0
    try:
        return int(len(event_ids))
    except Exception:
        return 0


def _hazard_centroid_count(hazard_obj: Any) -> int:
    centroids = getattr(hazard_obj, "centroids", None)
    if centroids is None:
        return 0
    try:
        size = getattr(centroids, "size", None)
        if size is not None:
            return int(size)
    except Exception:
        pass
    try:
        return int(len(getattr(centroids, "lat", []) or []))
    except Exception:
        return 0


def _write_hazard_output(hazard_obj: Any, output_path: Path) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    hazard_obj.write_hdf5(str(tmp_path))
    os.replace(tmp_path, output_path)
    return _file_details(output_path)


def _hazard_summary(
    hazard_obj: Any,
    *,
    output_path: Path,
    notes: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    intensity = getattr(hazard_obj, "intensity", None)
    nnz = getattr(intensity, "nnz", None)
    payload = {
        "haz_type": str(getattr(hazard_obj, "haz_type", "") or ""),
        "units": str(getattr(hazard_obj, "units", "") or ""),
        "event_count": int(_hazard_event_count(hazard_obj)),
        "centroid_count": int(_hazard_centroid_count(hazard_obj)),
        "intensity_nnz": int(nnz) if nnz is not None else None,
        "output": _file_details(output_path),
        "notes": list(notes or []),
    }
    if extra:
        payload.update(dict(extra))
    return payload


def _prefix_hazard_event_names(hazard_obj: Any, *, prefix: str) -> None:
    event_count = _hazard_event_count(hazard_obj)
    hazard_obj.event_name = [f"{prefix}_{index}" for index in range(event_count)]


def _concatenate_hazards(hazards: list[Any]) -> Any:
    if not hazards:
        raise ValueError("Cannot concatenate an empty hazard list")

    first = hazards[0]
    try:
        combined = type(first)()
        append_fn = getattr(combined, "append", None)
        if callable(append_fn):
            append_fn(*hazards)
            return combined
    except Exception:
        pass

    concat_fn = getattr(type(first), "concat", None)
    if callable(concat_fn):
        return concat_fn(hazards)
    raise TypeError(f"Hazard class does not expose a supported concatenation API: {type(first).__name__}")


def _bbox_tuple_from_payload(bbox: dict[str, Any]) -> tuple[float, float, float, float]:
    return (
        float(bbox.get("lon_min")),
        float(bbox.get("lat_min")),
        float(bbox.get("lon_max")),
        float(bbox.get("lat_max")),
    )


def _resolve_surge_topography(
    territory_id: str,
    territory_entry: dict[str, Any],
    *,
    settings: Any,
) -> tuple[Path, str]:
    topography = territory_entry.get("topography") if isinstance(territory_entry.get("topography"), dict) else {}
    canonical_path = Path(str(topography.get("canonical_copernicus_path") or ""))
    if territory_id in {"guadeloupe", "martinique"}:
        resolved = resolve_surge_topo_path_for_territory(territory_id, settings=settings)
        if resolved != canonical_path:
            raise ValueError(
                f"{territory_id}: resolve_surge_topo_path_for_territory returned {resolved} instead of registry canonical path {canonical_path}"
            )
        if not resolved.exists():
            raise FileNotFoundError(f"{territory_id}: resolved Copernicus topo path not found: {resolved}")
        return resolved, "config.resolve_surge_topo_path_for_territory"

    if not canonical_path.exists():
        raise FileNotFoundError(f"{territory_id}: registry canonical Copernicus topo path not found: {canonical_path}")
    return canonical_path, "registry.canonical_copernicus_path"


def _catalog_payload(
    basin_code: str,
    provider: str,
    catalog_index: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    entry = catalog_index.get((basin_code, provider))
    if entry is None:
        raise ValueError(f"Missing catalog entry for basin={basin_code} provider={provider}")

    parquet_path = Path(str(entry.get("parquet_path") or ""))
    manifest_path = Path(str(entry.get("manifest_path") or ""))
    manifest = _catalog_manifest_payload(manifest_path)
    row_count = int(manifest.get("row_count") or 0)
    track_count, track_count_corrected = _resolved_catalog_track_count(manifest, parquet_path)
    if row_count <= 0 or track_count <= 0:
        raise ValueError(
            f"Invalid comparison catalog manifest for basin={basin_code} provider={provider}: row_count={row_count}, track_count={track_count}"
        )
    return {
        "provider": provider,
        "provider_label": str(entry.get("provider_label") or provider.upper()),
        "basin_code": basin_code,
        "basin_id": int(entry.get("basin_id") or 0),
        "parquet": _file_details(parquet_path),
        "manifest": _file_details(manifest_path),
        "row_count": row_count,
        "track_count": track_count,
        "track_count_corrected_from_catalog": bool(track_count_corrected),
        "year_min": manifest.get("year_min"),
        "year_max": manifest.get("year_max"),
        "years_covered": int(manifest.get("years_covered") or 0),
        "selected_source_files": int(manifest.get("selected_source_files") or len(manifest.get("source_files") or [])),
    }


def build_hazard_comparison_execution_plan(
    *,
    run_id: str,
    output_root: Path | None = None,
    registry_path: Path | None = None,
    catalogs_path: Path | None = None,
    scenarios_path: Path | None = None,
    territory_ids: tuple[str, ...] | None = None,
    scenario_ids: tuple[str, ...] | None = None,
    check_filesystem: bool = True,
) -> dict[str, Any]:
    registry_validation = validate_hazard_comparison_registry(registry_path, check_filesystem=check_filesystem)
    registry_validation.raise_for_errors()
    scenario_validation = validate_hazard_comparison_scenarios(scenarios_path)
    scenario_validation.raise_for_errors()
    catalog_validation = validate_hazard_comparison_catalogs(catalogs_path, check_filesystem=check_filesystem)
    catalog_validation.raise_for_errors()

    registry = load_hazard_comparison_registry(registry_path)
    scenario_set = load_hazard_comparison_scenarios(scenarios_path)
    catalog_index = _load_catalog_index(catalogs_path)
    settings = load_settings()

    if bool(settings.allow_climada_fallback):
        raise ValueError("Lot 2 contract violation: settings.allow_climada_fallback must remain false")
    if bool(settings.hazard_fallback_to_precomputed):
        raise ValueError("Lot 2 contract violation: settings.hazard_fallback_to_precomputed must remain false")
    if not bool(settings.climada_strict_required_components):
        raise ValueError("Lot 2 contract violation: settings.climada_strict_required_components must remain true")

    selected_territory_ids = _resolve_selected_territory_ids(registry, territory_ids)
    selected_scenario_ids = _resolve_selected_scenario_ids(scenario_set, scenario_ids)
    resolved_output_root = Path(output_root or DEFAULT_HAZARD_COMPARISON_RUNS_ROOT)
    run_dir = resolved_output_root / str(run_id)

    payload: dict[str, Any] = {
        "run_id": str(run_id),
        "created_at": _utc_now(),
        "output_root": str(resolved_output_root),
        "run_dir": str(run_dir),
        "mode": "phase2_preflight",
        "selected_territories": list(selected_territory_ids),
        "selected_scenarios": list(selected_scenario_ids),
        "contracts": {
            "climada_execution_profile": "hazard-comparison",
            "allow_climada_fallback": False,
            "hazard_fallback_to_precomputed": False,
            "climada_strict_required_components": True,
            "storm_convert_10min_to_1min": bool(settings.storm_convert_10min_to_1min),
            "storm_radius_unit_in": str(settings.storm_radius_unit_in),
            "storm_env_pressure_hpa": float(settings.storm_env_pressure_hpa),
            "hazard_rain_model": str(settings.hazard_rain_model),
            "hazard_rain_max_dist_inland_km": float(settings.hazard_rain_max_dist_inland_km),
            "landslide_corr_fact": float(settings.landslide_corr_fact),
            "landslide_n_years": int(settings.landslide_n_years),
            "landslide_dist": str(settings.landslide_dist),
            "return_periods": [int(value) for value in RETURN_PERIODS],
        },
        "inputs": {
            "registry_path": str(registry.path),
            "catalogs_path": str(Path(catalogs_path or DEFAULT_HAZARD_COMPARISON_CATALOGS_PATH)),
            "scenarios_path": str(Path(scenarios_path or DEFAULT_HAZARD_COMPARISON_SCENARIOS_PATH)),
            "registry_validation_warnings": list(registry_validation.warnings),
            "catalog_validation_warnings": list(catalog_validation.warnings),
            "scenario_validation_warnings": list(scenario_validation.warnings),
        },
        "territories": {},
    }

    for territory_id in selected_territory_ids:
        territory_entry = registry.territories[territory_id]
        basin_code = str(territory_entry.get("storm_basin_code") or "").upper()
        bbox = dict(territory_entry.get("comparison_bbox_hint") or {})
        topo_path, topo_resolution = _resolve_surge_topography(territory_id, territory_entry, settings=settings)
        scenario_payloads: dict[str, Any] = {}
        component_count = 0

        for scenario_id in selected_scenario_ids:
            scenario_entry = scenario_set.scenarios[scenario_id]
            provider = str(scenario_entry.get("track_catalog_provider") or "").strip().lower()
            catalog_payload = _catalog_payload(basin_code, provider, catalog_index)
            scenario_dir = run_dir / "territories" / territory_id / "hazards" / scenario_id
            components = scenario_entry.get("components") if isinstance(scenario_entry.get("components"), dict) else {}
            component_payloads: dict[str, Any] = {}

            for component_id in _ALLOWED_COMPONENTS:
                component = components.get(component_id)
                if not isinstance(component, dict):
                    raise ValueError(f"{scenario_id}/{component_id}: missing component payload")

                planned_output_path = scenario_dir / f"{component_id}.h5"
                if component_id == "wind":
                    component_payloads[component_id] = {
                        "status": "ready",
                        "required": True,
                        "source_kind": "track_catalog",
                        "hazard_class": str(component.get("hazard_class") or "TC"),
                        "catalog_parquet_path": catalog_payload["parquet"]["path"],
                        "catalog_track_count": int(catalog_payload["track_count"]),
                        "catalog_years_covered": int(catalog_payload["years_covered"]),
                        "wind_unit_in": str(settings.storm_wind_unit_in),
                        "convert_10min_to_1min": bool(settings.storm_convert_10min_to_1min),
                        "radius_unit_in": str(settings.storm_radius_unit_in),
                        "env_pressure_hpa": float(settings.storm_env_pressure_hpa),
                        "planned_output_path": str(planned_output_path),
                    }
                elif component_id == "rain":
                    component_payloads[component_id] = {
                        "status": "ready",
                        "required": True,
                        "source_kind": "track_catalog",
                        "hazard_class": str(component.get("hazard_class") or "TCRain"),
                        "catalog_parquet_path": catalog_payload["parquet"]["path"],
                        "catalog_track_count": int(catalog_payload["track_count"]),
                        "rain_model": str(settings.hazard_rain_model),
                        "rain_max_dist_inland_km": float(settings.hazard_rain_max_dist_inland_km),
                        "planned_output_path": str(planned_output_path),
                    }
                elif component_id == "surge":
                    component_payloads[component_id] = {
                        "status": "ready",
                        "required": True,
                        "source_kind": "track_catalog_plus_topography",
                        "hazard_class": str(component.get("hazard_class") or "TCSurgeBathtub"),
                        "catalog_parquet_path": catalog_payload["parquet"]["path"],
                        "catalog_track_count": int(catalog_payload["track_count"]),
                        "topography": {
                            **_file_details(topo_path),
                            "resolution_contract": topo_resolution,
                        },
                        "planned_output_path": str(planned_output_path),
                    }
                else:
                    landslide_entry = territory_entry.get("landslide") if isinstance(territory_entry.get("landslide"), dict) else {}
                    raster_fields = [str(value).strip() for value in list(component.get("raster_fields") or [])]
                    input_rasters: list[dict[str, Any]] = []
                    intermediate_paths: dict[str, str] = {}
                    for raster_field in raster_fields:
                        raster_path = Path(str(landslide_entry.get(raster_field) or ""))
                        if check_filesystem and not raster_path.exists():
                            raise FileNotFoundError(
                                f"{territory_id}/{scenario_id}/landslide: raster not found for field {raster_field}: {raster_path}"
                            )
                        input_rasters.append({"field": raster_field, **_file_details(raster_path)})
                        intermediate_paths[raster_field] = str(scenario_dir / f"landslide_{raster_field}.h5")
                    component_payloads[component_id] = {
                        "status": "ready",
                        "required": True,
                        "source_kind": "native_raster_pair",
                        "hazard_class": str(component.get("hazard_class") or "LS"),
                        "combination_mode": str(component.get("combination_mode") or "concatenate_native_hazards"),
                        "input_rasters": input_rasters,
                        "corr_fact": float(settings.landslide_corr_fact),
                        "n_years": int(settings.landslide_n_years),
                        "dist": str(settings.landslide_dist),
                        "planned_intermediate_paths": intermediate_paths,
                        "planned_output_path": str(planned_output_path),
                    }
                component_count += 1

            scenario_payloads[scenario_id] = {
                "status": "ready",
                "label": str(scenario_entry.get("label") or scenario_id),
                "track_catalog_provider": provider,
                "catalog": catalog_payload,
                "components": component_payloads,
            }

        payload["territories"][territory_id] = {
            "label": str(territory_entry.get("label") or territory_id),
            "status": "ready",
            "updated_at": _utc_now(),
            "storm_basin_code": basin_code,
            "comparison_bbox_hint": bbox,
            "surge_grid_deg_override": territory_entry.get("surge_grid_deg_override"),
            "phases": {
                "phase2_preflight": {
                    "status": "complete",
                    "scenario_count": int(len(selected_scenario_ids)),
                    "component_count": int(component_count),
                    "topography_path": str(topo_path),
                    "topography_resolution": topo_resolution,
                    "catalog_providers": [
                        str(scenario_set.scenarios[scenario_id].get("track_catalog_provider"))
                        for scenario_id in selected_scenario_ids
                    ],
                }
            },
            "scenarios": scenario_payloads,
        }

    return payload


def materialize_hazard_comparison_hazards(
    plan_payload: dict[str, Any],
    *,
    dynamic_max_tracks: int | None = None,
    resume_enabled: bool = False,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    runtime = _require_phase3_runtime()
    np = runtime["np"]
    Hazard = runtime["Hazard"]
    TCRain = runtime["TCRain"]
    TCSurgeBathtub = runtime["TCSurgeBathtub"]
    settings = load_settings()

    effective_dynamic_max_tracks = (
        int(dynamic_max_tracks)
        if dynamic_max_tracks is not None
        else int(getattr(settings, "hazard_dynamic_max_tracks", 0) or 0)
    )

    result = copy.deepcopy(plan_payload)
    result["mode"] = "phase3_hazard_generation"
    result["status"] = "running"
    result["updated_at"] = _utc_now()
    contracts = result.setdefault("contracts", {})
    contracts["effective_dynamic_max_tracks"] = int(effective_dynamic_max_tracks)

    try:
        for territory_id, territory_payload in result.get("territories", {}).items():
            territory_payload["status"] = "running"
            territory_payload["updated_at"] = _utc_now()
            bbox = territory_payload.get("comparison_bbox_hint") if isinstance(territory_payload.get("comparison_bbox_hint"), dict) else {}
            grid_step_deg = float(settings.territory_grid_deg)
            surge_grid_override = territory_payload.get("surge_grid_deg_override")
            surge_grid_step_deg = float(
                surge_grid_override
                if surge_grid_override is not None
                else (getattr(settings, "surge_grid_deg", _DEFAULT_SURGE_GRID_DEG) or _DEFAULT_SURGE_GRID_DEG)
            )
            point_records = _build_point_records_from_bbox(bbox, grid_step_deg=grid_step_deg)
            if math.isclose(surge_grid_step_deg, grid_step_deg, rel_tol=0.0, abs_tol=1e-9):
                surge_point_records = point_records
            else:
                surge_point_records = _build_point_records_from_bbox(bbox, grid_step_deg=surge_grid_step_deg)
            point_coords = [(float(item["lat"]), float(item["lon"])) for item in point_records]
            surge_point_coords = [(float(item["lat"]), float(item["lon"])) for item in surge_point_records]
            basin_code = str(territory_payload.get("storm_basin_code") or "").upper()
            basin_coverages = _single_basin_coverage(basin_code)
            territory_phase = territory_payload.setdefault("phases", {}).setdefault("phase3_hazard_build", {})
            territory_phase.update(
                {
                    "status": "running",
                    "started_at": _utc_now(),
                    "grid_step_deg": grid_step_deg,
                    "grid_point_count": int(len(point_records)),
                    "surge_grid_step_deg": surge_grid_step_deg,
                    "surge_grid_point_count": int(len(surge_point_records)),
                    "dynamic_max_tracks": int(effective_dynamic_max_tracks),
                    "scenario_count": int(len(territory_payload.get("scenarios") or {})),
                }
            )
            _emit_progress(
                progress_callback,
                {
                    "event": "territory_started",
                    "phase": "phase3_hazard_build",
                    "territory": territory_id,
                    "grid_point_count": int(len(point_records)),
                    "surge_grid_point_count": int(len(surge_point_records)),
                    "dynamic_max_tracks": int(effective_dynamic_max_tracks),
                },
            )

            scenario_payloads = territory_payload.get("scenarios") if isinstance(territory_payload.get("scenarios"), dict) else {}
            if not scenario_payloads:
                raise ValueError(f"{territory_id}: no scenarios available for lot 3 execution")

            fallback_catalog_payload = next(iter(scenario_payloads.values()))
            storm_catalog_path = Path(
                str(
                    ((scenario_payloads.get("storm") or fallback_catalog_payload).get("catalog") or {}).get("parquet", {}).get("path")
                    or ((scenario_payloads.get("storm") or fallback_catalog_payload).get("catalog") or {}).get("parquet_path")
                    or ""
                )
            )
            storm_cmcc_catalog_path = Path(
                str(
                    ((scenario_payloads.get("storm_cmcc") or fallback_catalog_payload).get("catalog") or {}).get("parquet", {}).get("path")
                    or ((scenario_payloads.get("storm_cmcc") or fallback_catalog_payload).get("catalog") or {}).get("parquet_path")
                    or ""
                )
            )
            if not storm_catalog_path:
                raise ValueError(f"{territory_id}: missing storm parquet catalog path in plan payload")
            if not storm_cmcc_catalog_path:
                raise ValueError(f"{territory_id}: missing storm_cmcc parquet catalog path in plan payload")

            bundle = load_storm_hazards_from_parquet_for_points(
                storm_parquet_path=storm_catalog_path,
                cmcc_parquet_path=storm_cmcc_catalog_path,
                point_coords=point_coords,
                storm_years=1,
                basin_coverages=basin_coverages,
                max_tracks=int(effective_dynamic_max_tracks),
                track_cache_max_entries=0,
                wind_unit_in=str(contracts.get("storm_wind_unit_in") or settings.storm_wind_unit_in),
                convert_10min_to_1min=bool(contracts.get("storm_convert_10min_to_1min")),
                radius_unit_in=str(contracts.get("storm_radius_unit_in") or settings.storm_radius_unit_in),
                env_pressure_hpa=float(contracts.get("storm_env_pressure_hpa") or settings.storm_env_pressure_hpa),
                build_hazards=False,
            )

            for scenario_id, scenario_payload in scenario_payloads.items():
                scenario_payload["status"] = "running"
                scenario_payload["updated_at"] = _utc_now()
                _emit_progress(
                    progress_callback,
                    {
                        "event": "scenario_started",
                        "phase": "phase3_hazard_build",
                        "territory": territory_id,
                        "scenario": scenario_id,
                    },
                )

                try:
                    tracks = resolve_hazard_bundle_tracks(bundle, scenario_id)
                    if tracks is None:
                        raise RuntimeError(f"{territory_id}/{scenario_id}: dynamic tracks could not be resolved")
                    track_count_used = int(len(getattr(tracks, "data", []) or []))
                    catalog_payload = scenario_payload.get("catalog") if isinstance(scenario_payload.get("catalog"), dict) else {}
                    years_covered = int(catalog_payload.get("years_covered") or 0)
                    if years_covered <= 0:
                        raise ValueError(f"{territory_id}/{scenario_id}: catalog years_covered must be > 0")

                    scenario_payload["track_count_used"] = int(track_count_used)
                    scenario_payload["grid_point_count"] = int(len(point_records))
                    scenario_payload["surge_grid_point_count"] = int(len(surge_point_records))
                    scenario_payload["status"] = "building"

                    centroids = _build_centroids_from_points(point_coords)
                    surge_centroids = centroids if surge_point_records is point_records else _build_centroids_from_points(surge_point_coords)
                    components = scenario_payload.get("components") if isinstance(scenario_payload.get("components"), dict) else {}
                    wind_hazard = None

                    for component_id in _ALLOWED_COMPONENTS:
                        component_payload = components.get(component_id)
                        if not isinstance(component_payload, dict):
                            raise ValueError(f"{territory_id}/{scenario_id}: missing component payload for {component_id}")
                        output_path = Path(str(component_payload.get("planned_output_path") or ""))
                        resumed_component = False
                        if resume_enabled:
                            resumed_hazard = None
                            if output_path.exists():
                                try:
                                    resumed_hazard = _load_hazard_from_hdf5(Hazard, output_path)
                                except Exception:
                                    resumed_hazard = None
                            if resumed_hazard is not None:
                                component_payload["status"] = "complete"
                                component_payload["resumed"] = True
                                component_payload["completed_at"] = component_payload.get("completed_at") or _utc_now()
                                component_payload["hazard"] = _hazard_summary(resumed_hazard, output_path=output_path, notes=["resumed=True"])
                                if component_id in {"wind", "rain"}:
                                    component_payload["frequency_normalization_years"] = int(years_covered)
                                    component_payload["track_count_used"] = int(track_count_used)
                                elif component_id == "surge":
                                    component_payload["frequency_normalization_years"] = int(years_covered)
                                if component_id == "wind":
                                    wind_hazard = resumed_hazard
                                _emit_progress(
                                    progress_callback,
                                    {
                                        "event": "component_completed",
                                        "phase": "phase3_hazard_build",
                                        "territory": territory_id,
                                        "scenario": scenario_id,
                                        "component": component_id,
                                        "output_path": str(output_path),
                                        "event_count": int(component_payload.get("hazard", {}).get("event_count") or 0),
                                        "resumed": True,
                                    },
                                )
                                resumed_component = True
                        if not resumed_component:
                            component_payload["status"] = "running"
                            component_payload["started_at"] = _utc_now()
                            _emit_progress(
                                progress_callback,
                                {
                                    "event": "component_started",
                                    "phase": "phase3_hazard_build",
                                    "territory": territory_id,
                                    "scenario": scenario_id,
                                    "component": component_id,
                                    "output_path": str(output_path),
                                },
                            )

                            if component_id == "wind":
                                hazard_obj = _build_hazard_from_tracks(tracks, centroids)
                                hazard_obj = _normalize_frequency_on_copy(hazard_obj, years_covered)
                                _write_hazard_output(hazard_obj, output_path)
                                component_payload.update(
                                    {
                                        "status": "complete",
                                        "completed_at": _utc_now(),
                                        "frequency_normalization_years": int(years_covered),
                                        "track_count_used": int(track_count_used),
                                        "hazard": _hazard_summary(
                                            hazard_obj,
                                            output_path=output_path,
                                            extra={
                                                "track_count_used": int(track_count_used),
                                                "grid_point_count": int(len(point_records)),
                                            },
                                        ),
                                    }
                                )
                                wind_hazard = hazard_obj
                            elif component_id == "rain":
                                hazard_obj = TCRain.from_tracks(
                                    tracks,
                                    centroids=getattr(wind_hazard, "centroids", centroids),
                                    model=str(contracts.get("hazard_rain_model") or settings.hazard_rain_model),
                                    ignore_distance_to_coast=True,
                                    max_dist_inland_km=float(
                                        contracts.get("hazard_rain_max_dist_inland_km") or settings.hazard_rain_max_dist_inland_km
                                    ),
                                )
                                hazard_obj = _normalize_frequency_on_copy(hazard_obj, years_covered)
                                _write_hazard_output(hazard_obj, output_path)
                                component_payload.update(
                                    {
                                        "status": "complete",
                                        "completed_at": _utc_now(),
                                        "frequency_normalization_years": int(years_covered),
                                        "track_count_used": int(track_count_used),
                                        "hazard": _hazard_summary(
                                            hazard_obj,
                                            output_path=output_path,
                                            extra={
                                                "track_count_used": int(track_count_used),
                                                "grid_point_count": int(len(point_records)),
                                            },
                                        ),
                                    }
                                )
                            elif component_id == "surge":
                                topo_payload = component_payload.get("topography") if isinstance(component_payload.get("topography"), dict) else {}
                                topo_path = Path(str(topo_payload.get("path") or ""))
                                surge_wind_hazard = wind_hazard
                                if surge_centroids is not centroids:
                                    surge_wind_hazard = _build_hazard_from_tracks(tracks, surge_centroids)
                                prepared_topo = _prepare_phase3_surge_topography(
                                    topo_path,
                                    point_records=surge_point_records,
                                    hazard_source="dynamic_parquet",
                                )
                                hazard_obj, surge_meta = _build_surge_hazard(
                                    np,
                                    surge_hazard_cls=TCSurgeBathtub,
                                    wind_hazard=surge_wind_hazard,
                                    topo_path=prepared_topo,
                                    hazard_source="dynamic_parquet",
                                )
                                hazard_obj = _normalize_frequency_on_copy(hazard_obj, years_covered)
                                _write_hazard_output(hazard_obj, output_path)
                                component_payload.update(
                                    {
                                        "status": "complete",
                                        "completed_at": _utc_now(),
                                        "frequency_normalization_years": int(years_covered),
                                        "prepared_topography_path": str(prepared_topo),
                                        "surge_meta": dict(surge_meta),
                                        "hazard": _hazard_summary(
                                            hazard_obj,
                                            output_path=output_path,
                                            extra={
                                                "grid_point_count": int(len(surge_point_records)),
                                                "source_wind_grid_point_count": int(len(surge_point_records)),
                                            },
                                            notes=[
                                                f"fraction_mode={surge_meta.get('fraction_mode')}",
                                                f"reason={surge_meta.get('reason')}",
                                            ],
                                        ),
                                    }
                                )
                            else:
                                bbox_tuple = _bbox_tuple_from_payload(bbox)
                                built_inputs: list[dict[str, Any]] = []
                                hazards_to_concat: list[Any] = []
                                intermediate_paths = component_payload.get("planned_intermediate_paths") if isinstance(component_payload.get("planned_intermediate_paths"), dict) else {}
                                input_rasters = component_payload.get("input_rasters") if isinstance(component_payload.get("input_rasters"), list) else []
                                for raster_payload in input_rasters:
                                    if not isinstance(raster_payload, dict):
                                        continue
                                    raster_field = str(raster_payload.get("field") or "")
                                    raster_path = Path(str(raster_payload.get("path") or ""))
                                    intermediate_path = Path(str(intermediate_paths.get(raster_field) or ""))
                                    input_hazard = build_landslide_hazard_from_prob(
                                        bbox=bbox_tuple,
                                        path_sourcefile=raster_path,
                                        corr_fact=float(component_payload.get("corr_fact") or settings.landslide_corr_fact),
                                        n_years=int(component_payload.get("n_years") or settings.landslide_n_years),
                                        dist=str(component_payload.get("dist") or settings.landslide_dist),
                                        target_centroids=getattr(wind_hazard, "centroids", centroids),
                                    )
                                    _prefix_hazard_event_names(input_hazard, prefix=raster_field)
                                    _write_hazard_output(input_hazard, intermediate_path)
                                    built_inputs.append(
                                        {
                                            "field": raster_field,
                                            **_hazard_summary(input_hazard, output_path=intermediate_path),
                                        }
                                    )
                                    hazards_to_concat.append(input_hazard)
                                if len(hazards_to_concat) != 2:
                                    raise ValueError(f"{territory_id}/{scenario_id}/landslide: expected exactly 2 native hazards")
                                hazard_obj = _concatenate_hazards(hazards_to_concat)
                                _write_hazard_output(hazard_obj, output_path)
                                component_payload.update(
                                    {
                                        "status": "complete",
                                        "completed_at": _utc_now(),
                                        "input_hazards": built_inputs,
                                        "hazard": _hazard_summary(
                                            hazard_obj,
                                            output_path=output_path,
                                            extra={"input_hazard_count": int(len(built_inputs))},
                                        ),
                                    }
                                )

                            _emit_progress(
                                progress_callback,
                                {
                                    "event": "component_completed",
                                    "phase": "phase3_hazard_build",
                                    "territory": territory_id,
                                    "scenario": scenario_id,
                                    "component": component_id,
                                    "output_path": str(output_path),
                                    "event_count": int(component_payload.get("hazard", {}).get("event_count") or 0),
                                },
                            )

                    release_hazard_bundle_tracks(bundle, scenario_id)
                    scenario_payload["status"] = "complete"
                    scenario_payload["completed_at"] = _utc_now()
                    _emit_progress(
                        progress_callback,
                        {
                            "event": "scenario_completed",
                            "phase": "phase3_hazard_build",
                            "territory": territory_id,
                            "scenario": scenario_id,
                            "track_count_used": int(track_count_used),
                        },
                    )
                except Exception as exc:
                    scenario_payload["status"] = "failed"
                    scenario_payload["error"] = {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    }
                    territory_payload["status"] = "failed"
                    territory_phase["status"] = "failed"
                    territory_phase["error"] = {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    }
                    result["status"] = "failed"
                    result["updated_at"] = _utc_now()
                    _emit_progress(
                        progress_callback,
                        {
                            "event": "scenario_failed",
                            "phase": "phase3_hazard_build",
                            "territory": territory_id,
                            "scenario": scenario_id,
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                        },
                    )
                    release_hazard_bundle_tracks(bundle, scenario_id)
                    raise HazardComparisonExecutionError(
                        f"{territory_id}/{scenario_id}: {type(exc).__name__}: {exc}",
                        payload=result,
                    ) from exc

            territory_payload["status"] = "complete"
            territory_payload["updated_at"] = _utc_now()
            territory_phase["status"] = "complete"
            territory_phase["completed_at"] = _utc_now()
            _emit_progress(
                progress_callback,
                {
                    "event": "territory_completed",
                    "phase": "phase3_hazard_build",
                    "territory": territory_id,
                    "scenario_count": int(len(scenario_payloads)),
                },
            )

        result["status"] = "complete"
        result["updated_at"] = _utc_now()
        return result
    except HazardComparisonExecutionError:
        raise
    except Exception as exc:
        result["status"] = "failed"
        result["updated_at"] = _utc_now()
        raise HazardComparisonExecutionError(
            f"lot 3 execution failed: {type(exc).__name__}: {exc}",
            payload=result,
        ) from exc


def materialize_hazard_comparison_metrics(
    execution_payload: dict[str, Any],
    *,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    runtime = _require_phase4_runtime()
    np = runtime["np"]
    Hazard = runtime["Hazard"]

    result = copy.deepcopy(execution_payload)
    result["mode"] = "phase4_metric_extraction"
    result["status"] = "running"
    result["updated_at"] = _utc_now()

    run_id = str(result.get("run_id") or "")
    run_dir = Path(
        str(
            result.get("run_dir")
            or (Path(str(result.get("output_root") or DEFAULT_HAZARD_COMPARISON_RUNS_ROOT)) / run_id)
        )
    )
    metrics_output_path = run_dir / "comparison-metrics.json"
    metrics_document: dict[str, Any] = {
        "run_id": run_id,
        "generated_at": _utc_now(),
        "status": "running",
        "pairwise_comparison": "storm_vs_storm_cmcc",
        "component_order": list(_ALLOWED_COMPONENTS),
        "metric_keys": list(_COMPARISON_DELTA_METRIC_KEYS),
        "territories": {},
    }

    try:
        for territory_id, territory_payload in result.get("territories", {}).items():
            territory_payload["status"] = "running"
            territory_payload["updated_at"] = _utc_now()
            territory_phase = territory_payload.setdefault("phases", {}).setdefault("phase4_metric_extraction", {})
            territory_phase.update(
                {
                    "status": "running",
                    "started_at": _utc_now(),
                    "scenario_count": int(len(territory_payload.get("scenarios") or {})),
                }
            )
            _emit_progress(
                progress_callback,
                {
                    "event": "territory_metrics_started",
                    "phase": "phase4_metric_extraction",
                    "territory": territory_id,
                },
            )

            scenario_payloads = territory_payload.get("scenarios") if isinstance(territory_payload.get("scenarios"), dict) else {}
            storm_basin_code = str(territory_payload.get("storm_basin_code") or "").strip().upper()
            geographic_group_id, geographic_group_label = _resolve_phase5_geographic_group(territory_id, storm_basin_code)
            territory_metrics_payload: dict[str, Any] = {
                "label": str(territory_payload.get("label") or territory_id),
                "storm_basin_code": storm_basin_code,
                "geographic_group_id": geographic_group_id,
                "geographic_group_label": geographic_group_label,
                "status": "running",
                "scenarios": {},
            }

            for scenario_id, scenario_payload in scenario_payloads.items():
                scenario_payload["status"] = "running"
                scenario_payload["updated_at"] = _utc_now()
                _emit_progress(
                    progress_callback,
                    {
                        "event": "scenario_metrics_started",
                        "phase": "phase4_metric_extraction",
                        "territory": territory_id,
                        "scenario": scenario_id,
                    },
                )
                components = scenario_payload.get("components") if isinstance(scenario_payload.get("components"), dict) else {}
                component_metrics_payloads: dict[str, Any] = {}

                try:
                    for component_id in _ALLOWED_COMPONENTS:
                        component_payload = components.get(component_id)
                        if not isinstance(component_payload, dict):
                            raise ValueError(f"{territory_id}/{scenario_id}: missing component payload for lot 4: {component_id}")
                        output_path = Path(
                            str(
                                ((component_payload.get("hazard") or {}).get("output") or {}).get("path")
                                or component_payload.get("planned_output_path")
                                or ""
                            )
                        )
                        if not output_path.exists():
                            raise FileNotFoundError(
                                f"{territory_id}/{scenario_id}/{component_id}: hazard output not found for lot 4 metrics: {output_path}"
                            )

                        hazard_obj = _load_hazard_from_hdf5(Hazard, output_path)
                        component_metrics = _summarize_hazard_comparison_metrics(np, hazard_obj, output_path=output_path)
                        component_payload["comparison_metrics"] = component_metrics
                        component_metrics_payloads[component_id] = component_metrics
                        _emit_progress(
                            progress_callback,
                            {
                                "event": "component_metrics_completed",
                                "phase": "phase4_metric_extraction",
                                "territory": territory_id,
                                "scenario": scenario_id,
                                "component": component_id,
                                "output_path": str(output_path),
                                "metric_event_count": int(component_metrics.get("event_count") or 0),
                            },
                        )

                    scenario_payload["comparison_metrics"] = {
                        "status": "complete",
                        "component_order": [component_id for component_id in _ALLOWED_COMPONENTS if component_id in component_metrics_payloads],
                        "components": component_metrics_payloads,
                    }
                    scenario_payload["status"] = "complete"
                    scenario_payload["updated_at"] = _utc_now()
                    territory_metrics_payload["scenarios"][scenario_id] = dict(scenario_payload["comparison_metrics"])
                    _emit_progress(
                        progress_callback,
                        {
                            "event": "scenario_metrics_completed",
                            "phase": "phase4_metric_extraction",
                            "territory": territory_id,
                            "scenario": scenario_id,
                            "component_count": int(len(component_metrics_payloads)),
                        },
                    )
                except Exception as exc:
                    scenario_payload["status"] = "failed"
                    scenario_payload["comparison_metrics"] = {
                        "status": "failed",
                        "error": {
                            "type": type(exc).__name__,
                            "message": str(exc),
                        },
                    }
                    territory_payload["status"] = "failed"
                    territory_phase["status"] = "failed"
                    territory_phase["error"] = {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    }
                    result["status"] = "failed"
                    result["updated_at"] = _utc_now()
                    _emit_progress(
                        progress_callback,
                        {
                            "event": "scenario_metrics_failed",
                            "phase": "phase4_metric_extraction",
                            "territory": territory_id,
                            "scenario": scenario_id,
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                        },
                    )
                    raise HazardComparisonExecutionError(
                        f"{territory_id}/{scenario_id}: {type(exc).__name__}: {exc}",
                        payload=result,
                    ) from exc

            storm_payload = territory_metrics_payload["scenarios"].get("storm") if isinstance(territory_metrics_payload["scenarios"], dict) else None
            cmcc_payload = territory_metrics_payload["scenarios"].get("storm_cmcc") if isinstance(territory_metrics_payload["scenarios"], dict) else None
            if isinstance(storm_payload, dict) and isinstance(cmcc_payload, dict):
                territory_metrics_payload["storm_vs_storm_cmcc"] = {
                    "status": "complete",
                    "components": {
                        component_id: _build_component_metric_comparison(
                            dict((storm_payload.get("components") or {}).get(component_id) or {}),
                            dict((cmcc_payload.get("components") or {}).get(component_id) or {}),
                        )
                        for component_id in _ALLOWED_COMPONENTS
                    },
                }

            territory_metrics_payload["status"] = "complete"
            territory_payload["comparison_metrics"] = territory_metrics_payload
            territory_payload["status"] = "complete"
            territory_payload["updated_at"] = _utc_now()
            territory_phase["status"] = "complete"
            territory_phase["completed_at"] = _utc_now()
            metrics_document["territories"][territory_id] = territory_metrics_payload
            _emit_progress(
                progress_callback,
                {
                    "event": "territory_metrics_completed",
                    "phase": "phase4_metric_extraction",
                    "territory": territory_id,
                    "scenario_count": int(len(scenario_payloads)),
                },
            )

        metrics_document["status"] = "complete"
        metrics_document["generated_at"] = _utc_now()
        _write_json_object(metrics_output_path, metrics_document)

        result["comparison_metrics"] = {
            "status": "complete",
            "path": str(metrics_output_path),
            "generated_at": metrics_document["generated_at"],
            "territory_count": int(len(metrics_document.get("territories") or {})),
            "pairwise_comparison": "storm_vs_storm_cmcc",
        }
        result["status"] = "complete"
        result["updated_at"] = _utc_now()
        return result
    except HazardComparisonExecutionError:
        raise
    except Exception as exc:
        result["status"] = "failed"
        result["updated_at"] = _utc_now()
        raise HazardComparisonExecutionError(
            f"lot 4 metric extraction failed: {type(exc).__name__}: {exc}",
            payload=result,
        ) from exc


def materialize_hazard_comparison_exports(
    execution_payload: dict[str, Any],
    *,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    runtime = _require_phase5_runtime()
    plt = runtime["plt"]

    result = copy.deepcopy(execution_payload)
    result["mode"] = "phase5_export_artifacts"
    result["status"] = "running"
    result["updated_at"] = _utc_now()

    metrics_document, metrics_path = _resolve_phase5_metrics_document(result)
    if str(metrics_document.get("status") or "") != "complete":
        raise ValueError(f"Lot 5 export requires a complete comparison-metrics document, got status={metrics_document.get('status')!r}")

    run_dir = Path(
        str(
            result.get("run_dir")
            or (Path(str(result.get("output_root") or DEFAULT_HAZARD_COMPARISON_RUNS_ROOT)) / str(result.get("run_id") or ""))
        )
    )
    export_root = run_dir / "comparison-exports"
    tables_dir = export_root / "tables"
    charts_dir = export_root / "charts"
    summary_path = export_root / "summary.json"

    try:
        component_rows, comparison_rows, wide_rows = _collect_phase5_export_rows(metrics_document)
        chart_payloads = _build_phase5_chart_payloads(metrics_document)

        tables_dir.mkdir(parents=True, exist_ok=True)
        charts_dir.mkdir(parents=True, exist_ok=True)

        for territory_id, territory_payload in result.get("territories", {}).items():
            if not isinstance(territory_payload, dict):
                continue
            territory_payload["updated_at"] = _utc_now()
            territory_phase = territory_payload.setdefault("phases", {}).setdefault("phase5_export_artifacts", {})
            territory_phase.update({"status": "running", "started_at": _utc_now()})
            _emit_progress(
                progress_callback,
                {
                    "event": "territory_export_started",
                    "phase": "phase5_export_artifacts",
                    "territory": territory_id,
                },
            )

        component_metrics_csv = tables_dir / "component-metrics-long.csv"
        comparison_delta_csv = tables_dir / "storm-vs-storm_cmcc-deltas.csv"
        comparison_wide_csv = tables_dir / "component-comparison-wide.csv"
        _write_csv_rows(component_metrics_csv, component_rows)
        _write_csv_rows(comparison_delta_csv, comparison_rows)
        _write_csv_rows(comparison_wide_csv, wide_rows)
        _emit_progress(
            progress_callback,
            {
                "event": "comparison_tables_completed",
                "phase": "phase5_export_artifacts",
                "component_metrics_csv": str(component_metrics_csv),
                "comparison_delta_csv": str(comparison_delta_csv),
                "row_count_component_metrics": int(len(component_rows)),
                "row_count_comparison_deltas": int(len(comparison_rows)),
            },
        )

        chart_artifacts: list[dict[str, Any]] = []
        for chart_payload in chart_payloads:
            stem = f"{chart_payload['component']}__{chart_payload['metric_key']}"
            payload_path = charts_dir / f"{stem}.json"
            image_path = charts_dir / f"{stem}.png"
            _write_json_object(payload_path, chart_payload)
            _render_phase5_metric_chart(plt, chart_payload, image_path)
            chart_artifacts.append(
                {
                    "component": str(chart_payload.get("component") or ""),
                    "metric_key": str(chart_payload.get("metric_key") or ""),
                    "metric_label": str(
                        chart_payload.get("metric_label")
                        or _metric_label(str(chart_payload.get("metric_key") or ""))
                    ),
                    "scenario_id": str(chart_payload.get("scenario_id") or ""),
                    "payload_path": str(payload_path),
                    "image_path": str(image_path),
                }
            )
            _emit_progress(
                progress_callback,
                {
                    "event": "comparison_chart_completed",
                    "phase": "phase5_export_artifacts",
                    "component": str(chart_payload.get("component") or ""),
                    "metric_key": str(chart_payload.get("metric_key") or ""),
                    "image_path": str(image_path),
                },
            )

        summary_payload = {
            "generated_at": _utc_now(),
            "run_id": str(result.get("run_id") or metrics_document.get("run_id") or ""),
            "comparison_metrics_path": str(metrics_path),
            "table_exports": {
                "component_metrics_csv": str(component_metrics_csv),
                "comparison_delta_csv": str(comparison_delta_csv),
                "comparison_wide_csv": str(comparison_wide_csv),
            },
            "chart_count": int(len(chart_artifacts)),
            "charts": chart_artifacts,
            "component_metric_row_count": int(len(component_rows)),
            "comparison_delta_row_count": int(len(comparison_rows)),
            "territory_count": int(len(metrics_document.get("territories") or {})),
            "plot_metric_keys": list(_PHASE5_PLOT_METRIC_KEYS),
        }
        _write_json_object(summary_path, summary_payload)

        for territory_id, territory_payload in result.get("territories", {}).items():
            if not isinstance(territory_payload, dict):
                continue
            territory_phase = territory_payload.setdefault("phases", {}).setdefault("phase5_export_artifacts", {})
            territory_phase.update({"status": "complete", "completed_at": _utc_now()})
            territory_payload["comparison_exports"] = {
                "status": "complete",
                "included_in_run_level_exports": True,
                "summary_path": str(summary_path),
            }
            territory_payload["updated_at"] = _utc_now()
            _emit_progress(
                progress_callback,
                {
                    "event": "territory_export_completed",
                    "phase": "phase5_export_artifacts",
                    "territory": territory_id,
                },
            )

        result["comparison_exports"] = {
            "status": "complete",
            "summary_path": str(summary_path),
            "table_count": 3,
            "chart_count": int(len(chart_artifacts)),
            "plot_metric_keys": list(_PHASE5_PLOT_METRIC_KEYS),
        }
        result["status"] = "complete"
        result["updated_at"] = _utc_now()
        return result
    except HazardComparisonExecutionError:
        raise
    except Exception as exc:
        result["status"] = "failed"
        result["updated_at"] = _utc_now()
        raise HazardComparisonExecutionError(
            f"lot 5 export failed: {type(exc).__name__}: {exc}",
            payload=result,
        ) from exc


def materialize_hazard_comparison_report(
    execution_payload: dict[str, Any],
    *,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    result = copy.deepcopy(execution_payload)
    result["mode"] = "phase6_html_report"
    result["status"] = "running"
    result["updated_at"] = _utc_now()

    summary_document, summary_path, metrics_document, metrics_path = _resolve_phase6_export_inputs(result)
    report_path = summary_path.parent / "index.html"

    try:
        _render_phase6_report_html(summary_document, summary_path, metrics_document, metrics_path, report_path)
        _emit_progress(
            progress_callback,
            {
                "event": "comparison_report_completed",
                "phase": "phase6_html_report",
                "index_path": str(report_path),
                "chart_count": int(summary_document.get("chart_count") or 0),
            },
        )

        for territory_id, territory_payload in result.get("territories", {}).items():
            if not isinstance(territory_payload, dict):
                continue
            territory_phase = territory_payload.setdefault("phases", {}).setdefault("phase6_html_report", {})
            territory_phase.update({"status": "complete", "completed_at": _utc_now()})
            territory_payload["comparison_report"] = {
                "status": "complete",
                "index_path": str(report_path),
            }
            territory_payload["updated_at"] = _utc_now()

        result["comparison_report"] = {
            "status": "complete",
            "index_path": str(report_path),
            "summary_path": str(summary_path),
        }
        result["status"] = "complete"
        result["updated_at"] = _utc_now()
        return result
    except HazardComparisonExecutionError:
        raise
    except Exception as exc:
        result["status"] = "failed"
        result["updated_at"] = _utc_now()
        raise HazardComparisonExecutionError(
            f"lot 6 report failed: {type(exc).__name__}: {exc}",
            payload=result,
        ) from exc


__all__ = [
    "DEFAULT_HAZARD_COMPARISON_CATALOGS_PATH",
    "DEFAULT_HAZARD_COMPARISON_RUNS_ROOT",
    "DEFAULT_HAZARD_COMPARISON_SCENARIOS_PATH",
    "HazardComparisonCatalogValidation",
    "HazardComparisonExecutionError",
    "HazardComparisonScenarioSet",
    "HazardComparisonScenarioValidation",
    "build_hazard_comparison_execution_plan",
    "load_hazard_comparison_scenarios",
    "materialize_hazard_comparison_hazards",
    "materialize_hazard_comparison_exports",
    "materialize_hazard_comparison_metrics",
    "materialize_hazard_comparison_report",
    "validate_hazard_comparison_catalogs",
    "validate_hazard_comparison_scenarios",
]
