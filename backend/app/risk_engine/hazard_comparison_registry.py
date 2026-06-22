from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_HAZARD_COMPARISON_REGISTRY_PATH = REPO_ROOT / "config" / "hazard-comparison" / "territories.json"
_ALLOWED_BASIN_CODES = {"NA", "SI", "SP"}
_ALLOWED_TOPO_STATUS = {"ready", "pending_extract"}


@dataclass(frozen=True)
class HazardComparisonRegistry:
    path: Path
    payload: dict[str, Any]

    @property
    def meta(self) -> dict[str, Any]:
        return dict(self.payload.get("meta") or {})

    @property
    def shared_sources(self) -> dict[str, Any]:
        return dict(self.payload.get("shared_sources") or {})

    @property
    def territories(self) -> dict[str, dict[str, Any]]:
        raw = self.payload.get("territories") or {}
        return {
            str(key): dict(value)
            for key, value in raw.items()
            if isinstance(value, dict)
        }

    def _flagged_ids(self, *, included: bool) -> tuple[str, ...]:
        return tuple(
            territory_id
            for territory_id, entry in self.territories.items()
            if bool(entry.get("include_in_comparison")) is included
        )

    def _ordered_meta_ids(self, meta_key: str, *, included: bool) -> tuple[str, ...]:
        flagged_ids = self._flagged_ids(included=included)
        declared = self.meta.get(meta_key)
        if not isinstance(declared, list):
            return flagged_ids

        ordered: list[str] = []
        for value in declared:
            territory_id = str(value).strip()
            if territory_id in flagged_ids and territory_id not in ordered:
                ordered.append(territory_id)
        for territory_id in flagged_ids:
            if territory_id not in ordered:
                ordered.append(territory_id)
        return tuple(ordered)

    @property
    def included_ids(self) -> tuple[str, ...]:
        return self._ordered_meta_ids("included_territories", included=True)

    @property
    def excluded_ids(self) -> tuple[str, ...]:
        return self._ordered_meta_ids("excluded_territories", included=False)


@dataclass(frozen=True)
class HazardComparisonRegistryValidation:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    included_ids: tuple[str, ...]
    excluded_ids: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    def raise_for_errors(self) -> None:
        if self.errors:
            raise ValueError("Invalid hazard comparison registry:\n- " + "\n- ".join(self.errors))


def load_hazard_comparison_registry(path: Path | None = None) -> HazardComparisonRegistry:
    resolved = Path(path or DEFAULT_HAZARD_COMPARISON_REGISTRY_PATH)
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Hazard comparison registry must be a JSON object: {resolved}")
    return HazardComparisonRegistry(path=resolved, payload=payload)


def validate_hazard_comparison_registry(
    path: Path | None = None,
    *,
    check_filesystem: bool = True,
) -> HazardComparisonRegistryValidation:
    registry = load_hazard_comparison_registry(path)
    errors: list[str] = []
    warnings: list[str] = []

    meta = registry.meta
    territories = registry.territories
    shared = registry.shared_sources

    if not territories:
        errors.append("territories map is empty")

    declared_included = tuple(str(value) for value in meta.get("included_territories") or [])
    declared_excluded = tuple(str(value) for value in meta.get("excluded_territories") or [])

    flag_included_ids = registry._flagged_ids(included=True)
    flag_excluded_ids = registry._flagged_ids(included=False)
    included_ids = registry.included_ids
    excluded_ids = registry.excluded_ids

    if set(declared_included) != set(flag_included_ids):
        errors.append(
            "meta.included_territories does not match territory flags: "
            f"declared={declared_included} actual={flag_included_ids}"
        )
    if set(declared_excluded) != set(flag_excluded_ids):
        errors.append(
            "meta.excluded_territories does not match territory flags: "
            f"declared={declared_excluded} actual={flag_excluded_ids}"
        )
    if set(included_ids) & set(excluded_ids):
        errors.append("a territory cannot be both included and excluded")

    copernicus_dir = Path(str(shared.get("copernicus_topography_dir") or ""))
    admin_boundaries_path = Path(str(shared.get("admin_boundaries_adm0_path") or ""))
    raw_catalogs = shared.get("raw_track_catalogs") if isinstance(shared.get("raw_track_catalogs"), dict) else {}

    if check_filesystem and not admin_boundaries_path.exists():
        errors.append(f"shared admin boundary path not found: {admin_boundaries_path}")
    if check_filesystem and not copernicus_dir.exists():
        errors.append(f"shared Copernicus topography dir not found: {copernicus_dir}")

    patterns_by_basin = raw_catalogs.get("patterns_by_basin") if isinstance(raw_catalogs.get("patterns_by_basin"), dict) else {}
    for basin_code in sorted(_ALLOWED_BASIN_CODES):
        basin_patterns = patterns_by_basin.get(basin_code)
        if not isinstance(basin_patterns, dict):
            errors.append(f"missing raw track patterns for basin {basin_code}")
            continue
        for provider_key in ("storm", "storm_cmcc"):
            pattern = str(basin_patterns.get(provider_key) or "").strip()
            if not pattern:
                errors.append(f"missing {provider_key} raw pattern for basin {basin_code}")

    seen_aliases: dict[str, str] = {}
    for territory_id, entry in territories.items():
        label = str(entry.get("label") or "").strip()
        if not label:
            errors.append(f"{territory_id}: missing label")
        aliases = entry.get("aliases")
        if not isinstance(aliases, list) or not aliases:
            errors.append(f"{territory_id}: aliases must be a non-empty list")
            aliases = []
        for alias in aliases:
            alias_key = str(alias).strip().lower()
            if not alias_key:
                errors.append(f"{territory_id}: contains an empty alias")
                continue
            previous = seen_aliases.get(alias_key)
            if previous is not None and previous != territory_id:
                errors.append(f"alias '{alias_key}' is duplicated by {previous} and {territory_id}")
            else:
                seen_aliases[alias_key] = territory_id

        if not bool(entry.get("include_in_comparison")):
            reason = str(entry.get("exclusion_reason") or "").strip()
            if not reason:
                errors.append(f"{territory_id}: excluded territories must declare exclusion_reason")
            continue

        basin_code = str(entry.get("storm_basin_code") or "").strip().upper()
        if basin_code not in _ALLOWED_BASIN_CODES:
            errors.append(f"{territory_id}: unsupported storm_basin_code '{basin_code}'")

        bbox = entry.get("comparison_bbox_hint")
        _validate_bbox(errors, territory_id, bbox)

        admin_mask = entry.get("admin_mask")
        if not isinstance(admin_mask, dict):
            errors.append(f"{territory_id}: admin_mask must be an object")
        else:
            adm0_path = Path(str(admin_mask.get("adm0_path") or ""))
            if check_filesystem and not adm0_path.exists():
                errors.append(f"{territory_id}: admin mask path not found: {adm0_path}")

        topography = entry.get("topography")
        if not isinstance(topography, dict):
            errors.append(f"{territory_id}: topography must be an object")
        else:
            canonical_topo_path = Path(str(topography.get("canonical_copernicus_path") or ""))
            archive_path = Path(str(topography.get("copernicus_archive_path") or ""))
            topo_status = str(topography.get("lot0_status") or "").strip().lower()
            exists_now = bool(topography.get("exists_now"))
            if topo_status not in _ALLOWED_TOPO_STATUS:
                errors.append(f"{territory_id}: invalid topography lot0_status '{topo_status}'")
            if copernicus_dir and canonical_topo_path.parent != copernicus_dir:
                errors.append(
                    f"{territory_id}: canonical Copernicus path must live under {copernicus_dir}: {canonical_topo_path}"
                )
            if check_filesystem:
                if topo_status == "ready":
                    if not canonical_topo_path.exists():
                        errors.append(f"{territory_id}: topography marked ready but file is missing: {canonical_topo_path}")
                    if not exists_now:
                        errors.append(f"{territory_id}: topography marked ready but exists_now=false")
                elif topo_status == "pending_extract":
                    if not archive_path.exists():
                        errors.append(f"{territory_id}: topography archive missing: {archive_path}")
                    if canonical_topo_path.exists() and not exists_now:
                        warnings.append(
                            f"{territory_id}: canonical topography already exists on disk while exists_now=false"
                        )

        landslide = entry.get("landslide")
        if not isinstance(landslide, dict):
            errors.append(f"{territory_id}: landslide must be an object")
        else:
            for field_name in ("earthquake_path", "precip_current_path", "precip_ssp585_path"):
                candidate = Path(str(landslide.get(field_name) or ""))
                if check_filesystem and not candidate.exists():
                    errors.append(f"{territory_id}: landslide path not found for {field_name}: {candidate}")

        population = entry.get("population")
        if not isinstance(population, dict):
            errors.append(f"{territory_id}: population must be an object")
        else:
            if bool(population.get("required_for_hazard_only")):
                errors.append(f"{territory_id}: population must stay optional for hazard-only lot 0")
            population_path = Path(str(population.get("path") or ""))
            if check_filesystem and not population_path.exists():
                errors.append(f"{territory_id}: population path not found: {population_path}")

    return HazardComparisonRegistryValidation(
        errors=tuple(errors),
        warnings=tuple(warnings),
        included_ids=included_ids,
        excluded_ids=excluded_ids,
    )


def _validate_bbox(errors: list[str], territory_id: str, bbox: Any) -> None:
    if not isinstance(bbox, dict):
        errors.append(f"{territory_id}: comparison_bbox_hint must be an object")
        return

    try:
        lon_min = float(bbox.get("lon_min"))
        lat_min = float(bbox.get("lat_min"))
        lon_max = float(bbox.get("lon_max"))
        lat_max = float(bbox.get("lat_max"))
    except Exception:
        errors.append(f"{territory_id}: comparison_bbox_hint contains non-numeric values")
        return

    values = (lon_min, lat_min, lon_max, lat_max)
    if not all(math.isfinite(value) for value in values):
        errors.append(f"{territory_id}: comparison_bbox_hint contains non-finite values")
        return
    if lon_min >= lon_max or lat_min >= lat_max:
        errors.append(f"{territory_id}: comparison_bbox_hint must have min < max")


__all__ = [
    "DEFAULT_HAZARD_COMPARISON_REGISTRY_PATH",
    "HazardComparisonRegistry",
    "HazardComparisonRegistryValidation",
    "load_hazard_comparison_registry",
    "validate_hazard_comparison_registry",
]
