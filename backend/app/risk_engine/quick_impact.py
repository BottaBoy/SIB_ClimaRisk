from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from html import escape
from io import StringIO
from pathlib import Path
from typing import Any
import csv
import json
import math

from ..config import Settings
from ..job_store import JobStore
from .errors import InputValidationError
from .exposure_ingest import ingest_drawn_geojson, ingest_uploaded_exposure
from .hazard_loader import list_default_basin_coverages
from .types import NormalizedExposure, NormalizedFeature

try:
    from shapely.geometry import Point, shape as shapely_shape  # type: ignore
except Exception:  # pragma: no cover
    Point = None
    shapely_shape = None


UTC = timezone.utc
QUICK_ENGINE = "precomputed_user_impact_v1"
REFERENCE_ENGINE = "climada_with_interdependency_v1"
HAZARDS = ("storm", "storm_cmcc")
SCENARIOS = ("rp10", "rp50", "rp100", "rp1000")
COMPONENTS = ("wind", "rain", "surge", "landslide")
STATE_KEYS = ("S0", "S1", "S2", "S3")
BASIN_ZONE_KEYS = {"basin-na": "NA", "basin-si": "SI"}
BASIN_ZONE_ALIASES = {
    "na": "basin-na",
    "north_atlantic": "basin-na",
    "nord_atlantique": "basin-na",
    "bassin_na": "basin-na",
    "basin_na": "basin-na",
    "basin-na": "basin-na",
    "si": "basin-si",
    "south_indian": "basin-si",
    "sud_indien": "basin-si",
    "bassin_si": "basin-si",
    "basin_si": "basin-si",
    "basin-si": "basin-si",
}
BASIN_LABELS = {
    "NA": "Bassin Nord Atlantique",
    "SI": "Bassin Sud Indien",
}
STATE_THRESHOLDS = (
    ("S3", 0.35),
    ("S2", 0.15),
    ("S1", 0.05),
)
ASSET_CLASS_ALIASES = {
    "habitation": "habitation",
    "eau_aep": "eau_aep",
    "eau_aep_cana": "eau_aep",
    "eau_aep_ouvrage_trait": "eau_aep",
    "eau_aep_ouvrage_stpmp": "eau_aep",
    "eau_aep_ouvrage_cap": "eau_aep",
    "eau_aep_ouvrage_cuv": "eau_aep",
    "eau_aep_ouvrage_ouveb": "eau_aep",
    "eau_aep_ouvrage_na": "eau_aep",
    "eau_eu": "eau_eu",
    "eau_eu_cana": "eau_eu",
    "eau_eu_pr": "eau_eu",
    "eau_eu_step": "eau_eu",
    "elec_bt_aerien": "elec_bt_aerien",
    "elec_bt_souterrain": "elec_bt_souterrain",
    "elec_hta_aerien": "elec_hta_aerien",
    "elec_hta_souterrain": "elec_hta_souterrain",
}


def _num(value: Any) -> float:
    try:
        out = float(value or 0.0)
    except Exception:
        return 0.0
    return out if math.isfinite(out) else 0.0


def _round(value: Any, digits: int = 2) -> float:
    return round(_num(value), digits)


def _unique_strings(values: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _normalize_token(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def _normalize_zone(value: Any, aliases: dict[str, str]) -> str:
    raw = str(value or "auto").strip().lower().replace(" ", "_")
    normalized = raw.replace("_", "-")
    return aliases.get(raw, BASIN_ZONE_ALIASES.get(raw, normalized))


def _normalize_asset_type(value: Any) -> str:
    raw = _normalize_token(value)
    aliases = {
        "eau_aep": "eau_aep_cana",
        "eau_eu": "eau_eu_cana",
        "aep_ouvrage_trait": "eau_aep_ouvrage_trait",
        "aep_ouvrage_stpmp": "eau_aep_ouvrage_stpmp",
        "aep_ouvrage_cap": "eau_aep_ouvrage_cap",
        "aep_ouvrage_cuv": "eau_aep_ouvrage_cuv",
        "aep_ouvrage_ouveb": "eau_aep_ouvrage_ouveb",
        "aep_ouvrage_autres": "eau_aep_ouvrage_na",
    }
    return aliases.get(raw, raw or "habitation")


def _asset_class(asset_type: str) -> str:
    return ASSET_CLASS_ALIASES.get(_normalize_asset_type(asset_type), "habitation")


def _service_group(asset_class: str) -> str:
    if asset_class.startswith("elec_"):
        return "elec"
    if asset_class == "eau_aep":
        return "eau_aep"
    if asset_class == "eau_eu":
        return "eau_eu"
    return "habitation"


def _state_from_ratio(loss_ratio: float) -> str:
    for state, threshold in STATE_THRESHOLDS:
        if loss_ratio >= threshold:
            return state
    return "S0"


def _feature_asset_type(feature: NormalizedFeature) -> str:
    props = feature.properties or {}
    return _normalize_asset_type(props.get("asset_type") or feature.exposure_category or "habitation")


def _feature_population(feature: NormalizedFeature) -> float:
    props = feature.properties or {}
    for key in ("population", "population_count", "population_exposed", "habitants"):
        value = props.get(key)
        if value not in (None, ""):
            return max(0.0, _num(value))
    return 0.0


@lru_cache(maxsize=4)
def _load_surfaces_cached(path: str, mtime_ns: int) -> dict[str, Any]:
    del mtime_ns
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != "user_impact_surfaces_v1":
        raise InputValidationError("Invalid user impact surfaces artifact")
    return payload


def load_user_impact_surfaces(path: Path) -> dict[str, Any]:
    surface_path = Path(path)
    if not surface_path.exists():
        raise InputValidationError(f"User impact surfaces artifact not found: {surface_path}")
    return _load_surfaces_cached(str(surface_path), surface_path.stat().st_mtime_ns)


def list_quick_zones(settings: Settings) -> list[dict[str, Any]]:
    payload = load_user_impact_surfaces(settings.user_impact_surfaces_path)
    zones: list[dict[str, Any]] = []
    for key, territory in sorted((payload.get("territories") or {}).items()):
        zones.append(
            {
                "key": key,
                "label": territory.get("label") or key,
                "basin": territory.get("basin") or "",
                "mode": territory.get("mode") or "unknown",
                "bbox": territory.get("bbox"),
                "limits": territory.get("limits") or [],
            }
        )
    for coverage in list_default_basin_coverages():
        code = str(coverage.get("code") or "").upper()
        zone_key = f"basin-{code.lower()}"
        if zone_key not in BASIN_ZONE_KEYS:
            continue
        zones.append(
            {
                "key": zone_key,
                "label": f"{BASIN_LABELS.get(code, code)} - screening bassin",
                "basin": code,
                "mode": f"{code.lower()}_basin_screening_generic",
                "bbox": {
                    "lon_min": coverage.get("lon_min"),
                    "lat_min": coverage.get("lat_min"),
                    "lon_max": coverage.get("lon_max"),
                    "lat_max": coverage.get("lat_max"),
                },
                "limits": [
                    "Screening rapide de bassin hors zones insulaires calibrees.",
                    "Les facteurs sont generalises depuis les surfaces disponibles; la chaine CLIMADA complete reste la reference scientifique.",
                    "Les etats reseau et indicateurs sociaux spatialises peuvent etre indisponibles hors zones calibrees.",
                ],
            }
        )
    return zones


def _load_exposure(job_id: str, params: dict[str, Any], store: JobStore) -> NormalizedExposure:
    input_mode = str(params.get("input_mode") or "").strip()
    if input_mode == "drawn_geojson":
        drawn_geojson = params.get("drawn_geojson")
        if not drawn_geojson:
            raise InputValidationError("drawn_geojson is required")
        return ingest_drawn_geojson(
            str(drawn_geojson),
            default_value_eur=0.0,
            default_exposure_category=str(params.get("default_exposure_category") or "habitation"),
        )
    if input_mode == "file":
        upload_name = str(params.get("upload_saved_name") or "").strip()
        if not upload_name:
            raise InputValidationError("uploaded exposure file is missing")
        return ingest_uploaded_exposure(
            store.upload_path(job_id, upload_name),
            value_field=params.get("value_field") or "value_eur",
            id_field=params.get("id_field") or "asset_id",
            asset_type_field=params.get("asset_type_field") or "asset_type",
            exposure_category_field=params.get("exposure_category_field") or "exposure_category",
            default_exposure_category=str(params.get("default_exposure_category") or "habitation"),
            crs=params.get("crs"),
        )
    raise InputValidationError("input_mode must be file or drawn_geojson")


def _bbox_contains(bbox: dict[str, Any] | None, lon: float, lat: float) -> bool:
    if not bbox:
        return False
    return (
        _num(bbox.get("lon_min")) <= lon <= _num(bbox.get("lon_max"))
        and _num(bbox.get("lat_min")) <= lat <= _num(bbox.get("lat_max"))
    )


def _basin_coverage_bbox(code: str) -> dict[str, float] | None:
    wanted = str(code or "").upper()
    for coverage in list_default_basin_coverages():
        if str(coverage.get("code") or "").upper() != wanted:
            continue
        return {
            "lon_min": _num(coverage.get("lon_min")),
            "lat_min": _num(coverage.get("lat_min")),
            "lon_max": _num(coverage.get("lon_max")),
            "lat_max": _num(coverage.get("lat_max")),
        }
    return None


def _basin_for_point(lon: float, lat: float) -> str | None:
    for coverage in list_default_basin_coverages():
        code = str(coverage.get("code") or "").upper()
        bbox = {
            "lon_min": coverage.get("lon_min"),
            "lat_min": coverage.get("lat_min"),
            "lon_max": coverage.get("lon_max"),
            "lat_max": coverage.get("lat_max"),
        }
        if code in {"NA", "SI"} and _bbox_contains(bbox, lon, lat):
            return code
    return None


def _average_tree(values: list[Any]) -> Any:
    numeric_values = [
        float(value)
        for value in values
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    ]
    if numeric_values:
        return sum(numeric_values) / len(numeric_values)
    dict_values = [value for value in values if isinstance(value, dict)]
    if dict_values:
        keys = sorted({key for value in dict_values for key in value.keys()})
        return {
            key: _average_tree([value[key] for value in dict_values if key in value])
            for key in keys
        }
    list_values = [value for value in values if isinstance(value, list)]
    if list_values:
        seen: list[Any] = []
        for value in list_values:
            for item in value:
                if item not in seen:
                    seen.append(item)
        return seen
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _territories_for_basin(payload: dict[str, Any], basin_code: str) -> list[tuple[str, dict[str, Any]]]:
    territories = payload.get("territories") if isinstance(payload.get("territories"), dict) else {}
    wanted = str(basin_code or "").upper()
    return [
        (key, territory)
        for key, territory in territories.items()
        if isinstance(territory, dict) and str(territory.get("basin") or "").upper() == wanted
    ]


def _basin_screening_territory(payload: dict[str, Any], basin_code: str) -> dict[str, Any]:
    code = str(basin_code or "").upper()
    sources = _territories_for_basin(payload, code)
    if not sources:
        raise InputValidationError(f"No quick-impact screening profile is available for basin {code}")
    source_keys = [key for key, _territory in sources]
    source_territories = [territory for _key, territory in sources]
    bbox = _basin_coverage_bbox(code)
    return {
        "label": f"{BASIN_LABELS.get(code, code)} - screening bassin",
        "basin": code,
        "mode": f"{code.lower()}_basin_screening_generic",
        "bbox": bbox,
        "calibration": {
            "source_artifacts": [
                territory.get("calibration", {}).get("source_artifact")
                for territory in source_territories
                if isinstance(territory.get("calibration"), dict)
                and territory.get("calibration", {}).get("source_artifact")
            ],
            "source_territories": source_keys,
            "reference_engine": payload.get("reference_engine") or REFERENCE_ENGINE,
            "screening_basis": "mean_of_available_quick_impact_surfaces_in_basin",
        },
        "annual": _average_tree([
            territory.get("annual") for territory in source_territories if isinstance(territory.get("annual"), dict)
        ]),
        "scenarios": _average_tree([
            territory.get("scenarios") for territory in source_territories if isinstance(territory.get("scenarios"), dict)
        ]),
        "portfolio_reference": _average_tree([
            territory.get("portfolio_reference")
            for territory in source_territories
            if isinstance(territory.get("portfolio_reference"), dict)
        ]),
        "limits": [
            f"Screening rapide generique pour le bassin {code}, utilisable hors zones insulaires calibrees.",
            "Les facteurs sont moyennes depuis les surfaces rapides disponibles du meme bassin; ils ne representent pas une calibration locale.",
            "Les etats reseau et indicateurs sociaux spatialises sont indisponibles hors zones calibrees, sauf champs fournis par l'utilisateur.",
            "La chaine CLIMADA complete reste la reference scientifique pour toute decision finale.",
        ],
    }


def _get_assignment_territory(payload: dict[str, Any], zone_key: str) -> dict[str, Any]:
    territories = payload.get("territories") if isinstance(payload.get("territories"), dict) else {}
    territory = territories.get(zone_key)
    if isinstance(territory, dict):
        return territory
    basin_code = BASIN_ZONE_KEYS.get(zone_key)
    if basin_code:
        return _basin_screening_territory(payload, basin_code)
    raise InputValidationError(f"Unsupported quick impact zone: {zone_key}")


def _validate_base_exposure(exposure: NormalizedExposure, *, max_features: int) -> None:
    if not exposure.features:
        raise InputValidationError("Exposure contains no feature")
    if len(exposure.features) > max_features:
        raise InputValidationError(f"Quick mode accepts at most {max_features} features")
    invalid_values = [feature.feature_id for feature in exposure.features if feature.value_eur <= 0.0]
    missing_geometry = [
        feature.feature_id
        for feature in exposure.features
        if feature.lon is None or feature.lat is None
    ]
    if invalid_values:
        preview = ", ".join(invalid_values[:10])
        raise InputValidationError(f"Quick mode requires positive value_eur for every feature: {preview}")
    if missing_geometry:
        preview = ", ".join(missing_geometry[:10])
        raise InputValidationError(f"Quick mode requires WGS84 geometry centroids for every feature: {preview}")


def _resolve_zone(
    exposure: NormalizedExposure,
    payload: dict[str, Any],
    requested_zone: str,
) -> str:
    aliases = payload.get("territory_aliases") if isinstance(payload.get("territory_aliases"), dict) else {}
    zone = _normalize_zone(requested_zone, aliases)
    territories = payload.get("territories") if isinstance(payload.get("territories"), dict) else {}
    if zone != "auto":
        if zone not in territories:
            raise InputValidationError(f"Unsupported quick impact zone: {requested_zone}")
        return zone

    candidates: list[str] = []
    for key, territory in territories.items():
        bbox = territory.get("bbox") if isinstance(territory, dict) else None
        if all(
            feature.lon is not None
            and feature.lat is not None
            and _bbox_contains(bbox, float(feature.lon), float(feature.lat))
            for feature in exposure.features
        ):
            candidates.append(key)
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise InputValidationError(
            "No supported quick-impact zone contains all exposure centroids. Select Guadeloupe, Martinique, Saint-Barthelemy, La Reunion or Mayotte."
        )
    raise InputValidationError(
        "Several quick-impact zones match the exposure. Select one zone explicitly."
    )


def _validate_exposure(exposure: NormalizedExposure, *, zone_key: str, territory: dict[str, Any], max_features: int) -> None:
    if not exposure.features:
        raise InputValidationError("Exposure contains no feature")
    if len(exposure.features) > max_features:
        raise InputValidationError(f"Quick mode accepts at most {max_features} features")
    bbox = territory.get("bbox") if isinstance(territory.get("bbox"), dict) else None
    if not bbox:
        raise InputValidationError(f"Quick mode zone has no bounding box: {zone_key}")
    outside: list[str] = []
    invalid_values: list[str] = []
    missing_geometry: list[str] = []
    for feature in exposure.features:
        if feature.value_eur <= 0.0:
            invalid_values.append(feature.feature_id)
        if feature.lon is None or feature.lat is None:
            missing_geometry.append(feature.feature_id)
            continue
        if not _bbox_contains(bbox, float(feature.lon), float(feature.lat)):
            outside.append(feature.feature_id)
    if invalid_values:
        preview = ", ".join(invalid_values[:10])
        raise InputValidationError(f"Quick mode requires positive value_eur for every feature: {preview}")
    if missing_geometry:
        preview = ", ".join(missing_geometry[:10])
        raise InputValidationError(f"Quick mode requires WGS84 geometry centroids for every feature: {preview}")
    if outside:
        preview = ", ".join(outside[:10])
        raise InputValidationError(f"Feature(s) outside selected quick-impact zone {zone_key}: {preview}")


def _auto_zone_for_feature(feature: NormalizedFeature, payload: dict[str, Any]) -> str | None:
    if feature.lon is None or feature.lat is None:
        return None
    lon = float(feature.lon)
    lat = float(feature.lat)
    territories = payload.get("territories") if isinstance(payload.get("territories"), dict) else {}
    for key, territory in territories.items():
        if not isinstance(territory, dict):
            continue
        bbox = territory.get("bbox") if isinstance(territory.get("bbox"), dict) else None
        if _bbox_contains(bbox, lon, lat):
            return key
    basin = _basin_for_point(lon, lat)
    return f"basin-{basin.lower()}" if basin else None


def _assign_feature_zones(
    exposure: NormalizedExposure,
    payload: dict[str, Any],
    requested_zone: str,
    *,
    max_features: int,
) -> tuple[list[dict[str, Any]], str]:
    _validate_base_exposure(exposure, max_features=max_features)
    aliases = payload.get("territory_aliases") if isinstance(payload.get("territory_aliases"), dict) else {}
    zone = _normalize_zone(requested_zone, aliases)
    territories = payload.get("territories") if isinstance(payload.get("territories"), dict) else {}
    assignments: list[dict[str, Any]] = []
    outside: list[str] = []

    if zone == "auto":
        for feature in exposure.features:
            zone_key = _auto_zone_for_feature(feature, payload)
            if not zone_key:
                outside.append(feature.feature_id)
                continue
            territory = _get_assignment_territory(payload, zone_key)
            assignments.append(
                {
                    "feature_id": feature.feature_id,
                    "zone_key": zone_key,
                    "territory": territory,
                    "label": territory.get("label") or zone_key,
                    "mode": territory.get("mode") or "unknown",
                    "basin": territory.get("basin") or "",
                    "assignment_source": "territory_bbox" if zone_key in territories else "basin_bbox",
                }
            )
        if outside:
            preview = ", ".join(outside[:10])
            raise InputValidationError(f"Feature(s) outside supported cyclone basins NA/SI: {preview}")
        return assignments, zone

    if zone in territories:
        territory = _get_assignment_territory(payload, zone)
        bbox = territory.get("bbox") if isinstance(territory.get("bbox"), dict) else None
        if not bbox:
            raise InputValidationError(f"Quick mode zone has no bounding box: {zone}")
        for feature in exposure.features:
            if not _bbox_contains(bbox, float(feature.lon), float(feature.lat)):
                outside.append(feature.feature_id)
                continue
            assignments.append(
                {
                    "feature_id": feature.feature_id,
                    "zone_key": zone,
                    "territory": territory,
                    "label": territory.get("label") or zone,
                    "mode": territory.get("mode") or "unknown",
                    "basin": territory.get("basin") or "",
                    "assignment_source": "selected_territory_bbox",
                }
            )
        if outside:
            preview = ", ".join(outside[:10])
            raise InputValidationError(f"Feature(s) outside selected quick-impact zone {zone}: {preview}")
        return assignments, zone

    basin_code = BASIN_ZONE_KEYS.get(zone)
    if basin_code:
        territory = _get_assignment_territory(payload, zone)
        for feature in exposure.features:
            feature_basin = _basin_for_point(float(feature.lon), float(feature.lat))
            if feature_basin != basin_code:
                outside.append(feature.feature_id)
                continue
            assignments.append(
                {
                    "feature_id": feature.feature_id,
                    "zone_key": zone,
                    "territory": territory,
                    "label": territory.get("label") or zone,
                    "mode": territory.get("mode") or "unknown",
                    "basin": basin_code,
                    "assignment_source": "selected_basin_bbox",
                }
            )
        if outside:
            preview = ", ".join(outside[:10])
            raise InputValidationError(f"Feature(s) outside selected quick-impact basin {basin_code}: {preview}")
        return assignments, zone

    raise InputValidationError(f"Unsupported quick impact zone: {requested_zone}")


def _assignment_counts(assignments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for assignment in assignments:
        key = str(assignment.get("zone_key") or "unknown")
        record = grouped.setdefault(
            key,
            {
                "zone": key,
                "label": assignment.get("label") or key,
                "mode": assignment.get("mode") or "unknown",
                "basin": assignment.get("basin") or "",
                "assignment_source": assignment.get("assignment_source") or "",
                "asset_count": 0,
            },
        )
        record["asset_count"] += 1
    return sorted(grouped.values(), key=lambda item: str(item.get("zone") or ""))


def _quick_zone_meta(assignments: list[dict[str, Any]]) -> tuple[str, str, str]:
    counts = _assignment_counts(assignments)
    if len(counts) == 1:
        item = counts[0]
        return str(item.get("zone") or ""), str(item.get("label") or item.get("zone") or ""), str(item.get("mode") or "unknown")
    labels = ", ".join(str(item.get("label") or item.get("zone") or "") for item in counts[:4])
    if len(counts) > 4:
        labels = f"{labels}, ..."
    return "mixed", f"Portefeuille multi-zones ({labels})", "mixed"


def _territory_results_by_assignment(assignments: list[dict[str, Any]], asset_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for assignment, row in zip(assignments, asset_results):
        zone_key = str(assignment.get("zone_key") or "unknown")
        record = grouped.setdefault(
            zone_key,
            {
                "territory": assignment.get("territory") or {},
                "rows": [],
            },
        )
        record["rows"].append(row)
    out: list[dict[str, Any]] = []
    for zone_key, record in sorted(grouped.items()):
        out.extend(_territory_results(zone_key, record["territory"], _sum_assets(record["rows"])))
    return out


def _annual_factor(territory: dict[str, Any], asset_type: str) -> dict[str, Any]:
    annual = territory.get("annual") if isinstance(territory.get("annual"), dict) else {}
    by_asset = annual.get("by_asset_type") if isinstance(annual.get("by_asset_type"), dict) else {}
    if asset_type in by_asset:
        return by_asset[asset_type]
    by_class = annual.get("by_class") if isinstance(annual.get("by_class"), dict) else {}
    asset_class = _asset_class(asset_type)
    if asset_class in by_class:
        return by_class[asset_class]
    return annual.get("default") if isinstance(annual.get("default"), dict) else {}


def _scenario_factor(territory: dict[str, Any], asset_type: str, hazard: str, scenario: str) -> dict[str, Any]:
    scenario_payload = territory.get("scenarios") if isinstance(territory.get("scenarios"), dict) else {}
    by_class = scenario_payload.get("by_class") if isinstance(scenario_payload.get("by_class"), dict) else {}
    asset_class = _asset_class(asset_type)
    source = by_class.get(asset_class)
    if not source:
        source = scenario_payload.get("default")
    if not isinstance(source, dict):
        return {}
    return source.get(hazard, {}).get(scenario, {}) if isinstance(source.get(hazard), dict) else {}


@lru_cache(maxsize=8)
def _load_network_state_index(path: str, mtime_ns: int) -> list[dict[str, Any]]:
    del mtime_ns
    if shapely_shape is None:
        return []
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    features = payload.get("features") if isinstance(payload, dict) else []
    indexed: list[dict[str, Any]] = []
    for feature in features or []:
        if not isinstance(feature, dict):
            continue
        geom = feature.get("geometry")
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        if not isinstance(geom, dict):
            continue
        try:
            shape = shapely_shape(geom)
        except Exception:
            continue
        indexed.append({"shape": shape, "properties": props})
    return indexed


def _network_state_artifact_path(settings: Settings, territory: dict[str, Any]) -> Path | None:
    rel = territory.get("calibration", {}).get("network_states_artifact") if isinstance(territory.get("calibration"), dict) else None
    if not rel:
        return None
    repo_root = Path(settings.user_impact_surfaces_path).resolve().parents[2]
    path = repo_root / str(rel)
    return path if path.exists() else None


def _sample_network_state(
    settings: Settings,
    territory: dict[str, Any],
    feature: NormalizedFeature,
    asset_type: str,
    hazard: str,
    scenario: str,
) -> tuple[str | None, str | None, str]:
    if Point is None:
        return None, None, "unavailable"
    path = _network_state_artifact_path(settings, territory)
    if path is None or feature.lon is None or feature.lat is None:
        return None, None, "unavailable"
    try:
        index = _load_network_state_index(str(path), path.stat().st_mtime_ns)
    except Exception:
        return None, None, "unavailable"
    point = Point(float(feature.lon), float(feature.lat))
    asset_class = _asset_class(asset_type)
    preferred_layers: tuple[str, ...]
    if asset_class.startswith("elec_"):
        preferred_layers = ("elec_grid_0p1deg",)
    elif asset_class == "eau_aep":
        preferred_layers = ("eau_aep", "eau_aep_ouvrages")
    elif asset_class == "eau_eu":
        preferred_layers = ("eau_eu", "eau_eu_pr", "eau_eu_step")
    else:
        preferred_layers = ("elec_grid_0p1deg", "eau_aep", "eau_eu")

    scenario_key = f"state_{scenario}_{hazard}"
    cause_key = f"cause_{scenario}_{hazard}"
    for layer_key in preferred_layers:
        for item in index:
            props = item["properties"]
            if str(props.get("layer_key") or "") != layer_key:
                continue
            try:
                if item["shape"].covers(point):
                    state = str(props.get(scenario_key) or "").upper()
                    cause = str(props.get(cause_key) or "none")
                    if state in STATE_KEYS:
                        return state, cause, "network_states_geojson"
            except Exception:
                continue
    return None, None, "unavailable"


def _component_amounts(value_eur: float, factor: dict[str, Any]) -> dict[str, float]:
    components = factor.get("component_ratios") if isinstance(factor.get("component_ratios"), dict) else {}
    return {component: _round(value_eur * _num(components.get(component)), 2) for component in COMPONENTS}


def _build_asset_result(
    settings: Settings,
    territory: dict[str, Any],
    feature: NormalizedFeature,
) -> dict[str, Any]:
    value = float(feature.value_eur)
    asset_type = _feature_asset_type(feature)
    asset_class = _asset_class(asset_type)
    annual = _annual_factor(territory, asset_type)
    hazard_factors = annual.get("hazards") if isinstance(annual.get("hazards"), dict) else {}
    result: dict[str, Any] = {
        "asset_id": feature.feature_id,
        "asset_label": feature.label,
        "geometry_type": feature.geometry_type,
        "asset_type": asset_type,
        "exposure_category": feature.exposure_category,
        "asset_class": asset_class,
        "service_group": _service_group(asset_class),
        "exposure_eur": _round(value, 2),
        "population_count": _round(_feature_population(feature), 0),
        "quick_factor_source": "asset_type" if asset_type in (territory.get("annual", {}).get("by_asset_type") or {}) else "class_or_default",
    }
    for hazard in HAZARDS:
        factor = hazard_factors.get(hazard) if isinstance(hazard_factors.get(hazard), dict) else {}
        direct = value * _num(factor.get("eai_direct_ratio"))
        indirect = value * _num(factor.get("eai_indirect_ratio"))
        total = value * (_num(factor.get("eai_total_ratio")) or _num(factor.get("eai_direct_ratio")) + _num(factor.get("eai_indirect_ratio")))
        suffix = "storm" if hazard == "storm" else "cmcc"
        result[f"eai_{suffix}_direct_eur"] = _round(direct, 2)
        result[f"eai_{suffix}_indirect_eur"] = _round(indirect, 2)
        result[f"eai_{suffix}_eur"] = _round(total, 2)
        result[f"risk_index_{suffix}"] = _round((total / value) if value > 0 else 0.0, 6)
        result.setdefault("annual_components_eur", {})[hazard] = {
            component: _round(total * _num((territory.get("portfolio_reference", {}).get(hazard, {}).get("components_direct_eai_eur") or {}).get(component)) / max(_num(territory.get("portfolio_reference", {}).get(hazard, {}).get("eai_eur")), 1.0), 2)
            for component in COMPONENTS
        }
        for scenario in SCENARIOS:
            scenario_factor = _scenario_factor(territory, asset_type, hazard, scenario)
            damage = value * _num(scenario_factor.get("damage_ratio"))
            direct_damage = value * _num(scenario_factor.get("direct_ratio"))
            indirect_damage = value * _num(scenario_factor.get("indirect_ratio"))
            sampled_state, cause, source = _sample_network_state(settings, territory, feature, asset_type, hazard, scenario)
            loss_state = _state_from_ratio(damage / value if value > 0 else 0.0)
            state = sampled_state or loss_state
            result.setdefault("scenario_losses_eur", {}).setdefault(hazard, {})[scenario] = _round(damage, 2)
            result.setdefault("scenario_direct_losses_eur", {}).setdefault(hazard, {})[scenario] = _round(direct_damage, 2)
            result.setdefault("scenario_indirect_losses_eur", {}).setdefault(hazard, {})[scenario] = _round(indirect_damage, 2)
            result.setdefault("scenario_components_eur", {}).setdefault(hazard, {})[scenario] = _component_amounts(value, scenario_factor)
            result[f"pml_{scenario}_{hazard}_eur"] = _round(damage, 2)
            result[f"service_state_{scenario}_{hazard}"] = state
            result[f"service_state_source_{scenario}_{hazard}"] = source if sampled_state else "damage_threshold"
            result[f"outage_cause_{scenario}_{hazard}"] = cause or ("direct_damage" if state != "S0" else "none")
    return result


def _empty_hazard_portfolio() -> dict[str, float]:
    return {
        "eai_eur": 0.0,
        "aai_agg_eur": 0.0,
        "eai_direct_eur": 0.0,
        "eai_indirect_eur": 0.0,
        "pml_10_eur": 0.0,
        "pml_50_eur": 0.0,
        "pml_100_eur": 0.0,
        "pml_1000_eur": 0.0,
        "percentile_99_loss_eur": 0.0,
    }


def _sum_assets(asset_results: list[dict[str, Any]]) -> dict[str, Any]:
    portfolio: dict[str, Any] = {hazard: _empty_hazard_portfolio() for hazard in HAZARDS}
    for hazard in HAZARDS:
        suffix = "storm" if hazard == "storm" else "cmcc"
        component_totals = {component: 0.0 for component in COMPONENTS}
        for row in asset_results:
            portfolio[hazard]["eai_direct_eur"] += _num(row.get(f"eai_{suffix}_direct_eur"))
            portfolio[hazard]["eai_indirect_eur"] += _num(row.get(f"eai_{suffix}_indirect_eur"))
            portfolio[hazard]["eai_eur"] += _num(row.get(f"eai_{suffix}_eur"))
            for scenario, rp in (("rp10", "10"), ("rp50", "50"), ("rp100", "100"), ("rp1000", "1000")):
                portfolio[hazard][f"pml_{rp}_eur"] += _num(row.get("scenario_losses_eur", {}).get(hazard, {}).get(scenario))
            for component, amount in (row.get("annual_components_eur", {}).get(hazard) or {}).items():
                component_totals[component] += _num(amount)
        portfolio[hazard]["aai_agg_eur"] = portfolio[hazard]["eai_eur"]
        portfolio[hazard]["percentile_99_loss_eur"] = portfolio[hazard]["pml_100_eur"]
        portfolio[hazard]["components_direct_eai_eur"] = {key: _round(value, 2) for key, value in component_totals.items()}
        portfolio[hazard]["components_direct_eai_eur"]["combined_capped"] = _round(portfolio[hazard]["eai_eur"], 2)
        for key, value in list(portfolio[hazard].items()):
            if isinstance(value, (int, float)):
                portfolio[hazard][key] = _round(value, 2)
    storm = portfolio["storm"]
    cmcc = portfolio["storm_cmcc"]
    portfolio["delta"] = {
        "eai_eur": _round(cmcc["eai_eur"] - storm["eai_eur"], 2),
        "pml_50_eur": _round(cmcc["pml_50_eur"] - storm["pml_50_eur"], 2),
        "pml_100_eur": _round(cmcc["pml_100_eur"] - storm["pml_100_eur"], 2),
        "pml_1000_eur": _round(cmcc["pml_1000_eur"] - storm["pml_1000_eur"], 2),
    }
    return portfolio


def _state_distribution(asset_results: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for scenario in SCENARIOS:
        out[scenario] = {}
        for hazard in HAZARDS:
            out[scenario][hazard] = {
                "eau_aep": {state: 0 for state in STATE_KEYS},
                "eau_eu": {state: 0 for state in STATE_KEYS},
                "elec": {state: 0 for state in STATE_KEYS},
                "habitation": {state: 0 for state in STATE_KEYS},
            }
            for row in asset_results:
                group = row.get("service_group") or "habitation"
                state = str(row.get(f"service_state_{scenario}_{hazard}") or "S0").upper()
                if state not in STATE_KEYS:
                    state = "S0"
                if group not in out[scenario][hazard]:
                    group = "habitation"
                out[scenario][hazard][group][state] += 1
            for group, values in out[scenario][hazard].items():
                values["total_units"] = sum(values[state] for state in STATE_KEYS)
    return out


def _build_pml_network_inputs(asset_results: list[dict[str, Any]], portfolio: dict[str, Any]) -> dict[str, Any]:
    rows_by_scenario: dict[str, list[dict[str, Any]]] = {}
    for scenario in SCENARIOS:
        class_rows: dict[str, dict[str, Any]] = {}
        for row in asset_results:
            class_key = row.get("asset_class") or "habitation"
            record = class_rows.setdefault(
                class_key,
                {
                    "class_key": class_key,
                    "class_label": class_key.replace("_", " ").title(),
                    "storm": _empty_pml_class_row(),
                    "storm_cmcc": _empty_pml_class_row(),
                },
            )
            exposure = _num(row.get("exposure_eur"))
            for hazard in HAZARDS:
                state = str(row.get(f"service_state_{scenario}_{hazard}") or "S0").upper()
                if state not in STATE_KEYS:
                    state = "S0"
                damage = _num(row.get("scenario_losses_eur", {}).get(hazard, {}).get(scenario))
                direct = _num(row.get("scenario_direct_losses_eur", {}).get(hazard, {}).get(scenario))
                indirect = _num(row.get("scenario_indirect_losses_eur", {}).get(hazard, {}).get(scenario))
                haz = record[hazard]
                haz["exposure_eur"] += exposure
                haz["damage_eur"] += damage
                haz["direct_damage_eur"] += direct
                haz["indirect_damage_eur"] += indirect
                haz["total_damage_eur"] += damage
                haz["state_counts"][state] += 1
                for component, amount in (row.get("scenario_components_eur", {}).get(hazard, {}).get(scenario) or {}).items():
                    haz["damage_components_eur"][component] += _num(amount)
        rows: list[dict[str, Any]] = []
        for record in class_rows.values():
            for hazard in HAZARDS:
                haz = record[hazard]
                total_units = sum(haz["state_counts"].values()) or 1
                haz["state_pct"] = {state: round(haz["state_counts"][state] / total_units * 100.0, 3) for state in STATE_KEYS}
                haz.pop("state_counts", None)
                for key in ("exposure_eur", "damage_eur", "direct_damage_eur", "indirect_damage_eur", "total_damage_eur"):
                    haz[key] = _round(haz[key], 2)
                haz["dysfunction_eur"] = 0.0
                haz["blocking_ouvrage_eur"] = _round(haz["indirect_damage_eur"], 2)
                haz["damage_components_eur"] = {
                    component: _round(haz["damage_components_eur"].get(component), 2)
                    for component in COMPONENTS
                }
            rows.append(record)
        rows_by_scenario[scenario] = sorted(rows, key=lambda item: item["class_key"])

    return {
        "schema_version": "user_quick_pml_network_graph_inputs_v1",
        "source_of_truth": QUICK_ENGINE,
        "method": "precomputed_user_impact_surface_screening",
        "approximation": True,
        "event_selection_basis": "complete_analysis_calibrated_ratios",
        "scenarios": list(SCENARIOS),
        "return_period_by_scenario": {"rp10": 10, "rp50": 50, "rp100": 100, "rp1000": 1000},
        "hazards": list(HAZARDS),
        "target_totals_by_hazard": {
            "storm": {
                "rp10": portfolio["storm"]["pml_10_eur"],
                "rp50": portfolio["storm"]["pml_50_eur"],
                "rp100": portfolio["storm"]["pml_100_eur"],
                "rp1000": portfolio["storm"]["pml_1000_eur"],
            },
            "storm_cmcc": {
                "rp10": portfolio["storm_cmcc"]["pml_10_eur"],
                "rp50": portfolio["storm_cmcc"]["pml_50_eur"],
                "rp100": portfolio["storm_cmcc"]["pml_100_eur"],
                "rp1000": portfolio["storm_cmcc"]["pml_1000_eur"],
            },
        },
        "state_damage_tables": rows_by_scenario,
        "network_state_service_distribution_by_scenario": _state_distribution(asset_results),
        "scenario_availability": {
            scenario: {hazard: True for hazard in HAZARDS}
            for scenario in SCENARIOS
        },
        "inputs": {
            "asset_count": len(asset_results),
            "engine": QUICK_ENGINE,
        },
    }


def _empty_pml_class_row() -> dict[str, Any]:
    return {
        "state_pct": {state: 0.0 for state in STATE_KEYS},
        "state_counts": {state: 0 for state in STATE_KEYS},
        "exposure_eur": 0.0,
        "damage_eur": 0.0,
        "direct_damage_eur": 0.0,
        "dysfunction_eur": 0.0,
        "blocking_ouvrage_eur": 0.0,
        "indirect_damage_eur": 0.0,
        "total_damage_eur": 0.0,
        "damage_components_eur": {component: 0.0 for component in COMPONENTS},
    }


def _exposure_summary(exposure: NormalizedExposure, asset_results: list[dict[str, Any]]) -> dict[str, Any]:
    geometry_counts: dict[str, int] = defaultdict(int)
    category_counts: dict[str, int] = defaultdict(int)
    asset_type_counts: dict[str, int] = defaultdict(int)
    quick_zone_counts: dict[str, int] = defaultdict(int)
    basin_counts: dict[str, int] = defaultdict(int)
    for feature, row in zip(exposure.features, asset_results):
        geometry_counts[feature.geometry_type] += 1
        category_counts[feature.exposure_category] += 1
        asset_type_counts[row.get("asset_type") or "habitation"] += 1
        quick_zone_counts[row.get("quick_zone") or "unknown"] += 1
        basin_counts[row.get("quick_basin") or "unknown"] += 1
    return {
        "asset_count_original": len(exposure.features),
        "asset_count_points": len(exposure.features),
        "total_exposure_eur": _round(exposure.total_exposure_eur, 2),
        "source_name": exposure.source_name,
        "source_format": exposure.source_format,
        "input_mode": exposure.input_mode,
        "geometry_type_counts": dict(sorted(geometry_counts.items())),
        "exposure_category_counts": dict(sorted(category_counts.items())),
        "asset_type_counts": dict(sorted(asset_type_counts.items())),
        "quick_zone_counts": dict(sorted(quick_zone_counts.items())),
        "quick_basin_counts": dict(sorted(basin_counts.items())),
        "metric_crs": "EPSG:4326",
        "default_value_asset_count": sum(1 for feature in exposure.features if (feature.properties or {}).get("uses_default_value")),
        "explicit_value_asset_count": sum(1 for feature in exposure.features if not (feature.properties or {}).get("uses_default_value")),
    }


def _territory_results(zone_key: str, territory: dict[str, Any], portfolio: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for hazard in HAZARDS:
        rows.append(
            {
                "territory": zone_key,
                "territory_label": territory.get("label") or zone_key,
                "hazard": hazard,
                "eai_eur": portfolio[hazard]["eai_eur"],
                "eai_direct_eur": portfolio[hazard]["eai_direct_eur"],
                "eai_indirect_eur": portfolio[hazard]["eai_indirect_eur"],
                "pml_50_eur": portfolio[hazard]["pml_50_eur"],
                "pml_100_eur": portfolio[hazard]["pml_100_eur"],
                "pml_1000_eur": portfolio[hazard]["pml_1000_eur"],
            }
        )
    return rows


def _input_features_geojson(exposure: NormalizedExposure, asset_results: list[dict[str, Any]]) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    for feature, result in zip(exposure.features, asset_results):
        geom = feature.geometry_geojson
        if not isinstance(geom, dict) and feature.lon is not None and feature.lat is not None:
            geom = {"type": "Point", "coordinates": [feature.lon, feature.lat]}
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "asset_id": feature.feature_id,
                    "label": feature.label,
                    "value_eur": _round(feature.value_eur, 2),
                    "asset_type": result.get("asset_type"),
                    "exposure_category": feature.exposure_category,
                    "quick_zone": result.get("quick_zone"),
                    "quick_zone_label": result.get("quick_zone_label"),
                    "quick_zone_mode": result.get("quick_zone_mode"),
                    "quick_basin": result.get("quick_basin"),
                    "eai_storm_eur": result.get("eai_storm_eur"),
                    "eai_cmcc_eur": result.get("eai_cmcc_eur"),
                    "pml_rp100_storm_eur": result.get("pml_rp100_storm_eur"),
                    "pml_rp1000_storm_cmcc_eur": result.get("pml_rp1000_storm_cmcc_eur"),
                },
                "geometry": geom,
            }
        )
    return {"type": "FeatureCollection", "features": features}


def _save_artifacts(job_id: str, store: JobStore, result: dict[str, Any], geojson: dict[str, Any]) -> dict[str, Any]:
    csv_content = _asset_csv(result.get("asset_results") or [])
    report_html = _report_html(result)
    summary_json = json.dumps(
        {
            "meta": result.get("meta"),
            "exposure_summary": result.get("exposure_summary"),
            "portfolio_results": result.get("portfolio_results"),
            "pml_network_graph_inputs": result.get("pml_network_graph_inputs"),
            "notes": result.get("notes"),
        },
        ensure_ascii=False,
        indent=2,
    )
    artifacts = [
        ("user-quick-results.csv", csv_content.encode("utf-8")),
        ("user-quick-results.geojson", json.dumps(geojson, ensure_ascii=False, indent=2).encode("utf-8")),
        ("user-quick-summary.json", summary_json.encode("utf-8")),
        ("user-quick-report.html", report_html.encode("utf-8")),
    ]
    downloads = []
    for name, content in artifacts:
        path = store.save_artifact_bytes(job_id, name, content)
        downloads.append({"name": path.name, "url": f"/api/v1/runs/{job_id}/artifacts/{path.name}"})
    return {
        "downloads": downloads,
        "csv": "user-quick-results.csv",
        "geojson": "user-quick-results.geojson",
        "summary_json": "user-quick-summary.json",
        "report_html": "user-quick-report.html",
    }


def _asset_csv(asset_results: list[dict[str, Any]]) -> str:
    fields = [
        "asset_id",
        "asset_label",
        "geometry_type",
        "asset_type",
        "exposure_category",
        "quick_zone",
        "quick_zone_label",
        "quick_zone_mode",
        "quick_basin",
        "exposure_eur",
        "eai_storm_eur",
        "eai_cmcc_eur",
        "pml_rp50_storm_eur",
        "pml_rp100_storm_eur",
        "pml_rp1000_storm_eur",
        "pml_rp50_storm_cmcc_eur",
        "pml_rp100_storm_cmcc_eur",
        "pml_rp1000_storm_cmcc_eur",
    ]
    out = StringIO()
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    for row in asset_results:
        writer.writerow({field: row.get(field, "") for field in fields})
    return out.getvalue()


def _report_html(result: dict[str, Any]) -> str:
    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
    summary = result.get("exposure_summary") if isinstance(result.get("exposure_summary"), dict) else {}
    portfolio = result.get("portfolio_results") if isinstance(result.get("portfolio_results"), dict) else {}
    notes = result.get("notes") if isinstance(result.get("notes"), list) else []
    rows = []
    for hazard in HAZARDS:
        haz = portfolio.get(hazard) if isinstance(portfolio.get(hazard), dict) else {}
        rows.append(
            "<tr>"
            f"<td>{escape(hazard.upper())}</td>"
            f"<td>{_round(haz.get('eai_eur')):,.0f}</td>"
            f"<td>{_round(haz.get('pml_50_eur')):,.0f}</td>"
            f"<td>{_round(haz.get('pml_100_eur')):,.0f}</td>"
            f"<td>{_round(haz.get('pml_1000_eur')):,.0f}</td>"
            "</tr>"
        )
    notes_html = "".join(f"<li>{escape(str(note))}</li>" for note in notes)
    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <title>Rapport SIB - donnees utilisateurs</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 32px; color: #17202a; }}
    h1, h2 {{ color: #003b5c; }}
    table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
    th, td {{ border: 1px solid #d6dde5; padding: 8px; text-align: left; }}
    th {{ background: #eef5f8; }}
    .muted {{ color: #5d6d7e; }}
  </style>
</head>
<body>
  <h1>Rapport SIB - donnees utilisateurs</h1>
  <p class="muted">Run {escape(str(meta.get("job_id") or ""))} genere le {escape(str(meta.get("updated_at") or ""))}.</p>
  <h2>Perimetre</h2>
  <p>Zone: {escape(str(meta.get("quick_zone_label") or meta.get("quick_zone") or ""))}. Exposition totale: {_round(summary.get("total_exposure_eur")):,.0f} EUR. Actifs: {int(_num(summary.get("asset_count_original")))}.</p>
  <h2>Resultats portefeuille</h2>
  <table>
    <thead><tr><th>Alea</th><th>EAI EUR</th><th>RP50 EUR</th><th>RP100 EUR</th><th>RP1000 EUR</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  <h2>Methodologie</h2>
  <p>Mode rapide: {escape(str(meta.get("engine") or QUICK_ENGINE))}. Reference: {escape(str(meta.get("reference_engine") or REFERENCE_ENGINE))}. Les resultats sont un screening base sur impacts pre-calcules calibres.</p>
  <ul>{notes_html}</ul>
</body>
</html>
"""


def run_quick_pipeline(job_id: str, params: dict[str, Any], settings: Settings, store: JobStore) -> dict[str, Any]:
    surfaces = load_user_impact_surfaces(settings.user_impact_surfaces_path)
    exposure = _load_exposure(job_id, params, store)
    assignments, requested_zone = _assign_feature_zones(
        exposure,
        surfaces,
        str(params.get("target_zone") or "auto"),
        max_features=max(1, int(settings.quick_max_features)),
    )
    asset_results: list[dict[str, Any]] = []
    for feature, assignment in zip(exposure.features, assignments):
        territory = assignment["territory"]
        row = _build_asset_result(settings, territory, feature)
        row["quick_zone"] = assignment.get("zone_key")
        row["quick_zone_label"] = assignment.get("label")
        row["quick_zone_mode"] = assignment.get("mode")
        row["quick_basin"] = assignment.get("basin")
        row["quick_assignment_source"] = assignment.get("assignment_source")
        asset_results.append(row)
    portfolio = _sum_assets(asset_results)
    pml_inputs = _build_pml_network_inputs(asset_results, portfolio)
    geojson = _input_features_geojson(exposure, asset_results)
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    assignment_summary = _assignment_counts(assignments)
    zone_key, zone_label, zone_mode = _quick_zone_meta(assignments)
    assigned_territories = [
        assignment.get("territory")
        for assignment in assignments
        if isinstance(assignment.get("territory"), dict)
    ]
    limitations = _unique_strings(
        list(surfaces.get("limits") or [])
        + [
            limit
            for territory in assigned_territories
            for limit in list(territory.get("limits") or [])
        ]
        + [
            "Le Quick Run peut couvrir plusieurs zones et bassins; les actifs hors iles calibrees utilisent un screening generique de bassin."
            if len(assignment_summary) > 1 or any(str(item.get("zone") or "").startswith("basin-") for item in assignment_summary)
            else ""
        ]
        + list(exposure.warnings or [])
    )
    has_population = any(_feature_population(feature) > 0.0 for feature in exposure.features)
    social_basis = "user_population_count" if has_population else "unavailable_no_user_population"
    portfolio["network_states_projected"] = pml_inputs["network_state_service_distribution_by_scenario"].get("rp100", {})
    portfolio["network_states_native"] = portfolio["network_states_projected"]
    portfolio["network_states_projected_coverage"] = {
        "basis": "user_asset_centroids",
        "coverage_rate": 1.0,
        "limitations": limitations,
    }
    portfolio["social_impact_summary"] = {
        "basis": social_basis,
        "available": has_population,
        "message": (
            "Population utilisateur exploitee depuis les champs population_count/population/habitants."
            if has_population
            else "Indicateurs sociaux non chiffres: ajoutez population_count dans le fichier pour produire une synthese sociale utilisateur."
        ),
    }
    result: dict[str, Any] = {
        "meta": {
            "title": "SIB User Exposure Quick Impact",
            "run_label": params.get("run_label"),
            "source": "user_quick_impact",
            "job_id": job_id,
            "dataset_mode": "drawn" if exposure.input_mode == "drawn_geojson" else "uploaded",
            "updated_at": now,
            "unit_currency": "EUR",
            "currency_display_unit": "MEUR",
            "sampling_spacing_m": None,
            "impact_function": "precomputed_complete_analysis_ratios",
            "hazards": ["STORM", "STORM_CMCC"],
            "hazard_components": list(COMPONENTS),
            "engine": QUICK_ENGINE,
            "reference_engine": surfaces.get("reference_engine") or REFERENCE_ENGINE,
            "approximation": True,
            "quick_zone": zone_key,
            "quick_zone_label": zone_label,
            "quick_zone_mode": zone_mode,
            "target_zone_requested": requested_zone,
            "quick_zone_assignments": assignment_summary,
            "quick_basin_codes": sorted(
                {
                    str(assignment.get("basin") or "")
                    for assignment in assignments
                    if str(assignment.get("basin") or "")
                }
            ),
            "quick_surface_schema_version": surfaces.get("schema_version"),
            "quick_surface_generated_at": surfaces.get("generated_at"),
            "calibration": {
                "assignment_basis": "feature_centroid_to_territory_or_basin",
                "territories": [
                    {
                        "zone": item.get("zone"),
                        "label": item.get("label"),
                        "mode": item.get("mode"),
                        "basin": item.get("basin"),
                        "asset_count": item.get("asset_count"),
                    }
                    for item in assignment_summary
                ],
            },
            "limitations": limitations,
            "retention_ttl_hours": settings.job_ttl_hours,
        },
        "exposure_summary": _exposure_summary(exposure, asset_results),
        "valuation_audit": {
            "mode": "user_declared_values",
            "default_value_asset_count": sum(1 for feature in exposure.features if (feature.properties or {}).get("uses_default_value")),
            "notes": [
                "Le mode rapide refuse les valeurs nulles ou negatives.",
                "Les valeurs dessinees doivent etre visibles et envoyees dans value_eur.",
            ],
        },
        "territory_results": _territory_results_by_assignment(assignments, asset_results),
        "asset_results": asset_results,
        "portfolio_results": portfolio,
        "matching_qa": {
            "status": "quick_screening",
            "point_count": len(exposure.features),
            "assignment_method": "feature_centroid_to_territory_or_basin",
            "zone": zone_key,
            "target_zone_requested": requested_zone,
            "zone_assignments": assignment_summary,
        },
        "graphs": {
            "user_quick": {
                "portfolio": {
                    hazard: {
                        "annual": portfolio[hazard]["eai_eur"],
                        "rp50": portfolio[hazard]["pml_50_eur"],
                        "rp100": portfolio[hazard]["pml_100_eur"],
                        "rp1000": portfolio[hazard]["pml_1000_eur"],
                    }
                    for hazard in HAZARDS
                }
            }
        },
        "notes": limitations,
        "input_features_geojson": geojson,
        "pml_network_graph_inputs": pml_inputs,
        "scientific_graph_inputs": {
            "source_of_truth": QUICK_ENGINE,
            "approximation": True,
            "reference_engine": surfaces.get("reference_engine") or REFERENCE_ENGINE,
            "scenarios": list(SCENARIOS),
        },
    }
    # PDF/XLSX and their visual pack are generated by the API output stage so
    # the public result exposes one canonical report and one raw-data export.
    result["artifacts"] = {"downloads": [], "visuals": [], "plots_png": []}
    return result
