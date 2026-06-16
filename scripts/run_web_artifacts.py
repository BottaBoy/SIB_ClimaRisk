from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_OUTPUTS_DIR = REPO_ROOT / "outputs" / "complete-analysis-runs"
WEB_DIR = REPO_ROOT / "web"
UTC = timezone.utc
MAX_COMPLETE_ANALYSIS_TIMESTAMP_SKEW_SECONDS = 900
MIN_PUBLICATION_DYNAMIC_MAX_TRACKS = 1500
LATEST_PUBLISHED_RUN_ALIASES = frozenset({"latest-published", "latest_published", "published"})
FORBIDDEN_PUBLICATION_SOURCE_MODES = {
    "complete_analysis_component_ratios",
    "complete_analysis_asset_fallback",
}
PUBLIC_COMPLETE_ANALYSIS_FIELD_MAP = {
    "annual": "eai_eur",
    "rp50": "pml_50_eur",
    "rp100": "pml_100_eur",
    "event_max": "percentile_99_loss_eur",
}
PAGE_ANALYSIS_SUMMARY_FIELD_MAP = {
    "annual": "eai_total_eur",
    "rp50": "rp50_total_loss_eur",
    "rp100": "rp100_total_loss_eur",
    "event_max": "p99_total_loss_eur",
}
PROXY_BREAKDOWN_SHARE_SCENARIOS = ("annual", "rp50", "rp100")
PUBLIC_LOSS_ALIGNMENT_ABS_TOLERANCE_EUR = 0.5
PUBLIC_LOSS_ALIGNMENT_REL_TOLERANCE = 1e-8
REQUIRED_NETWORK_STATES_METADATA = {
    "state_geometry_mode": "hydraulic_zoning_v2",
    "water_state_geometry_mode": "hydraulic_zoning_v2",
    "water_service_unit": "zone_component_key",
    "electric_state_geometry_mode": "fixed_grid_0p1deg",
    "schema_version": "aggregated_service_state_v1",
    "aggregation_method": "aggregated_service_state",
    "electric_state_unit": "fixed_grid_0p1deg",
    "water_state_unit": "zone_component_key",
    "geometry_semantics": "native_service_geometry",
    "methodology_breaks_comparability": True,
}


def _coerce_int(raw_value: object, *, default: int = 0) -> int:
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return int(default)


def _coerce_float(raw_value: object, *, default: float = 0.0) -> float:
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return float(default)


def publication_policy_for_requested_tracks(raw_value: object) -> dict[str, Any]:
    requested_dynamic_max_tracks = _coerce_int(raw_value)
    minimum_dynamic_max_tracks = int(MIN_PUBLICATION_DYNAMIC_MAX_TRACKS)
    eligible = requested_dynamic_max_tracks >= minimum_dynamic_max_tracks
    reason = None
    if not eligible:
        reason = (
            f"requested_dynamic_max_tracks={requested_dynamic_max_tracks} is below "
            f"the publication-safe minimum {minimum_dynamic_max_tracks}"
        )
    return {
        "eligible": bool(eligible),
        "requested_dynamic_max_tracks": requested_dynamic_max_tracks,
        "min_dynamic_max_tracks": minimum_dynamic_max_tracks,
        "reason": reason,
    }


def publication_policy_for_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    parameters = manifest.get("parameters") if isinstance(manifest.get("parameters"), dict) else {}
    requested_dynamic_max_tracks = parameters.get("requested_dynamic_max_tracks")
    if requested_dynamic_max_tracks is None:
        requested_dynamic_max_tracks = parameters.get("dynamic_max_tracks")
    return publication_policy_for_requested_tracks(requested_dynamic_max_tracks)


def ensure_run_publication_eligible(run_id: str, manifest: dict[str, Any]) -> dict[str, Any]:
    policy = publication_policy_for_manifest(manifest)
    if bool(policy.get("eligible")):
        return policy
    raise RuntimeError(f"Run {run_id} is not publication-eligible: {policy.get('reason')}")


def _normalize_requested_territories(
    territories: list[str] | tuple[str, ...] | None,
) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in territories or ():
        value = str(item or "").strip().lower()
        if not value or value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    return normalized


def _manifest_has_archived_frontend_artifacts(
    manifest: dict[str, Any],
    territories: list[str] | tuple[str, ...] | None = None,
) -> bool:
    frontend_artifacts = manifest.get("frontend_artifacts") if isinstance(manifest.get("frontend_artifacts"), dict) else {}
    if str(frontend_artifacts.get("status") or "").strip().lower() != "complete":
        return False

    archived_files_by_territory = (
        frontend_artifacts.get("archived_files_by_territory")
        if isinstance(frontend_artifacts.get("archived_files_by_territory"), dict)
        else {}
    )
    if not archived_files_by_territory:
        return False

    manifest_territories = manifest.get("territories") if isinstance(manifest.get("territories"), dict) else {}
    requested_territories = _normalize_requested_territories(territories)
    if not requested_territories:
        requested_territories = _normalize_requested_territories(list(archived_files_by_territory.keys()))
    if not requested_territories:
        return False

    for territory in requested_territories:
        entry = manifest_territories.get(territory) if isinstance(manifest_territories, dict) else None
        archived_files = archived_files_by_territory.get(territory) if isinstance(archived_files_by_territory, dict) else None
        if not isinstance(entry, dict) or str(entry.get("status") or "").strip().lower() != "complete":
            return False
        if not isinstance(archived_files, dict) or not archived_files:
            return False
    return True


def resolve_latest_published_run_id(
    territories: list[str] | tuple[str, ...] | None = None,
) -> str:
    requested_territories = _normalize_requested_territories(territories)
    for manifest_path in sorted(RUN_OUTPUTS_DIR.glob("20*/manifest.json"), key=lambda path: path.parent.name, reverse=True):
        payload = _load_json_payload(manifest_path)
        if not isinstance(payload, dict):
            continue
        run_id = str(payload.get("run_id") or manifest_path.parent.name).strip()
        if not run_id:
            continue
        if not bool(publication_policy_for_manifest(payload).get("eligible")):
            continue
        if not _manifest_has_archived_frontend_artifacts(payload, requested_territories):
            continue
        return run_id

    requested_scope = ", ".join(requested_territories) if requested_territories else "the requested scope"
    raise FileNotFoundError(f"No publication-ready archived run found for {requested_scope}")


def resolve_run_id(raw_value: str) -> str:
    value = str(raw_value or "").strip()
    if not value:
        raise ValueError("run_id must not be empty")
    normalized = value.lower()
    if normalized in LATEST_PUBLISHED_RUN_ALIASES:
        return resolve_latest_published_run_id()
    if normalized != "latest":
        return value
    latest_manifest = RUN_OUTPUTS_DIR / "latest-manifest.json"
    if not latest_manifest.exists():
        raise FileNotFoundError(f"Latest run manifest not found: {latest_manifest}")
    payload = json.loads(latest_manifest.read_text(encoding="utf-8"))
    run_id = str((payload or {}).get("run_id") or "").strip()
    if not run_id:
        raise ValueError(f"Latest run manifest does not contain a run_id: {latest_manifest}")
    return run_id


def resolve_publication_run_id(
    raw_value: str | None,
    territories: list[str] | tuple[str, ...] | None = None,
) -> str:
    value = str(raw_value or "").strip()
    if not value or value.lower() in LATEST_PUBLISHED_RUN_ALIASES:
        return resolve_latest_published_run_id(territories)
    return resolve_run_id(value)


def run_manifest_path(run_id: str) -> Path:
    return RUN_OUTPUTS_DIR / resolve_run_id(run_id) / "manifest.json"


def load_run_manifest(run_id: str) -> dict[str, Any]:
    manifest_path = run_manifest_path(run_id)
    if not manifest_path.exists():
        raise FileNotFoundError(f"Run manifest not found: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid run manifest payload: {manifest_path}")
    return payload


def write_run_manifest(run_id: str, payload: dict[str, Any]) -> None:
    resolved_run_id = resolve_run_id(run_id)
    manifest_path = run_manifest_path(resolved_run_id)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    manifest_path.write_text(text, encoding="utf-8")

    latest_manifest = RUN_OUTPUTS_DIR / "latest-manifest.json"
    if latest_manifest.exists():
        try:
            latest_payload = json.loads(latest_manifest.read_text(encoding="utf-8"))
        except Exception:
            latest_payload = None
        if isinstance(latest_payload, dict) and str(latest_payload.get("run_id") or "") == resolved_run_id:
            latest_manifest.write_text(text, encoding="utf-8")


def case_study_page_suffix(territory: str) -> str:
    normalized = str(territory or "").strip().lower()
    if normalized == "martinique":
        return "page2"
    if normalized == "saint-barthelemy":
        return "page7"
    return "page1"


def territory_complete_analysis_relative_path(territory: str) -> str:
    normalized = str(territory or "").strip().lower()
    return f"data/{normalized}-complete-analysis.json"


def territory_scientific_web_summary_relative_path(territory: str) -> str:
    normalized = str(territory or "").strip().lower()
    return f"data/{normalized}-scientific-web-summary.json"


def territory_frontend_rebuild_relative_paths(territory: str) -> tuple[str, ...]:
    normalized = str(territory or "").strip().lower()
    return (
        territory_scientific_web_summary_relative_path(normalized),
        f"data/{normalized}-wind-maps.json",
        f"data/{normalized}-landslide-maps.json",
        f"data/{normalized}-multi-hazard-proxy.json",
        f"data/{normalized}-{case_study_page_suffix(normalized)}-analysis.json",
        f"data/{normalized}-water-infra.geojson",
        f"data/{normalized}-network-states.geojson",
    )


def territory_optional_snapshot_relative_paths(territory: str) -> tuple[str, ...]:
    return ()


def territory_run_generated_relative_paths(territory: str) -> tuple[str, ...]:
    return (
        territory_complete_analysis_relative_path(territory),
        *territory_frontend_rebuild_relative_paths(territory),
        *territory_optional_snapshot_relative_paths(territory),
    )


def archived_territory_web_dir(run_id: str, territory: str) -> Path:
    resolved_run_id = resolve_run_id(run_id)
    normalized = str(territory or "").strip().lower()
    return RUN_OUTPUTS_DIR / resolved_run_id / "territories" / normalized / "web"


def normalized_territories_for_run(
    manifest: dict[str, Any],
    territories: list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    if territories is None:
        manifest_territories = manifest.get("territories") if isinstance(manifest.get("territories"), dict) else {}
        territories = sorted(str(key) for key in manifest_territories.keys())
    normalized: list[str] = []
    seen: set[str] = set()
    for item in territories:
        value = str(item).strip().lower()
        if not value or value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    if not normalized:
        raise ValueError("No territories available for this run operation")
    return normalized


def copy_territory_web_relative_paths(
    run_id: str,
    territory: str,
    relative_paths: list[str] | tuple[str, ...],
    *,
    source_web_dir: Path = WEB_DIR,
    min_mtime_epoch: float | None = None,
) -> tuple[dict[str, str], list[str], list[str]]:
    resolved_run_id = resolve_run_id(run_id)
    normalized = str(territory or "").strip().lower()
    archive_root = archived_territory_web_dir(resolved_run_id, normalized)
    copied: dict[str, str] = {}
    missing: list[str] = []
    stale: list[str] = []
    for relative_path in relative_paths:
        source_path = source_web_dir / relative_path
        if not source_path.exists():
            missing.append(relative_path)
            continue
        if min_mtime_epoch is not None and source_path.stat().st_mtime < float(min_mtime_epoch):
            stale.append(relative_path)
        destination_path = archive_root / relative_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)
        copied[relative_path] = str(destination_path)
    return copied, missing, stale


def _load_json_payload(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _parse_iso_datetime(raw_value: object) -> datetime | None:
    value = str(raw_value or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _payload_timestamp(payload: dict[str, Any] | None) -> datetime | None:
    if not isinstance(payload, dict):
        return None
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    for container in (meta, payload):
        for key in ("generated_at", "updated_at"):
            timestamp = _parse_iso_datetime(container.get(key))
            if timestamp is not None:
                return timestamp
    return None


def _payload_case_study_run_id(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    return str(meta.get("case_study_run_id") or "").strip()


def _payload_publication_trace(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    trace = meta.get("publication_trace") if isinstance(meta.get("publication_trace"), dict) else None
    modeling = meta.get("modeling") if isinstance(meta.get("modeling"), dict) else {}
    if trace is None and not modeling:
        return None
    source = trace if isinstance(trace, dict) else {}
    return {
        "artifact_kind": str(source.get("artifact_kind") or "") or None,
        "source_mode": str(source.get("source_mode") or modeling.get("source") or "") or None,
        "fallback_active": bool(source.get("fallback_active") if trace is not None else modeling.get("fallback")),
        "fallback_reason": str(source.get("fallback_reason") or "") or None,
        "complete_analysis_run_id": str(source.get("complete_analysis_run_id") or "") or None,
        "complete_analysis_generated_at": str(source.get("complete_analysis_generated_at") or "") or None,
        "wind_map_run_id": str(source.get("wind_map_run_id") or source.get("hazard_map_run_id") or "") or None,
        "wind_map_generated_at": str(source.get("wind_map_generated_at") or source.get("hazard_map_generated_at") or "") or None,
        "multi_hazard_proxy_run_id": str(source.get("multi_hazard_proxy_run_id") or "") or None,
        "multi_hazard_proxy_fallback_active": bool(source.get("multi_hazard_proxy_fallback_active")),
        "multi_hazard_proxy_source_mode": str(source.get("multi_hazard_proxy_source_mode") or "") or None,
        "multi_hazard_proxy_fallback_reason": str(source.get("multi_hazard_proxy_fallback_reason") or "") or None,
    }


def _extract_complete_analysis_public_loss_targets(
    payload: dict[str, Any] | None,
    hazard_key: str,
) -> dict[str, float]:
    portfolio = payload.get("portfolio_results") if isinstance(payload, dict) else None
    hazard_payload = portfolio.get(hazard_key) if isinstance(portfolio, dict) else None
    if not isinstance(hazard_payload, dict):
        return {}

    targets: dict[str, float] = {}
    for scenario, field in PUBLIC_COMPLETE_ANALYSIS_FIELD_MAP.items():
        value = _coerce_float(hazard_payload.get(field), default=0.0)
        if value > 0.0:
            targets[scenario] = value
    return targets


def _extract_page_analysis_public_loss_totals(
    payload: dict[str, Any] | None,
    hazard_key: str,
) -> dict[str, float]:
    impact = payload.get("impact") if isinstance(payload, dict) else None
    summary_metrics = impact.get("summary_metrics") if isinstance(impact, dict) else None
    hazard_payload = summary_metrics.get(hazard_key) if isinstance(summary_metrics, dict) else None
    if not isinstance(hazard_payload, dict):
        return {}

    totals: dict[str, float] = {}
    for scenario, field in PAGE_ANALYSIS_SUMMARY_FIELD_MAP.items():
        value = _coerce_float(hazard_payload.get(field), default=0.0)
        if value > 0.0:
            totals[scenario] = value
    return totals


def _public_loss_alignment_tolerance(expected_total: float) -> float:
    return max(
        float(PUBLIC_LOSS_ALIGNMENT_ABS_TOLERANCE_EUR),
        abs(float(expected_total)) * float(PUBLIC_LOSS_ALIGNMENT_REL_TOLERANCE),
    )


def _validate_page_analysis_public_loss_alignment(
    *,
    run_id: str,
    territory: str,
    complete_payload: dict[str, Any] | None,
    page_payload: dict[str, Any] | None,
) -> dict[str, dict[str, dict[str, float]]]:
    if not isinstance(page_payload, dict):
        raise RuntimeError(f"{territory} page-analysis payload is missing or invalid for run {run_id}")

    alignment: dict[str, dict[str, dict[str, float]]] = {}
    for hazard_key in ("storm", "storm_cmcc"):
        expected_totals = _extract_complete_analysis_public_loss_targets(complete_payload, hazard_key)
        if not expected_totals:
            continue

        observed_totals = _extract_page_analysis_public_loss_totals(page_payload, hazard_key)
        if not observed_totals:
            raise RuntimeError(
                f"{territory} page-analysis is missing impact.summary_metrics.{hazard_key} for run {run_id}"
            )

        hazard_alignment: dict[str, dict[str, float]] = {}
        for scenario, expected_total in expected_totals.items():
            if scenario not in observed_totals:
                raise RuntimeError(
                    f"{territory} page-analysis is missing public total {hazard_key}.{scenario} for run {run_id}"
                )
            observed_total = float(observed_totals[scenario])
            abs_diff = abs(observed_total - float(expected_total))
            tolerance = _public_loss_alignment_tolerance(expected_total)
            if abs_diff > tolerance:
                raise RuntimeError(
                    f"{territory} page-analysis public loss totals mismatch complete-analysis for {hazard_key}.{scenario}: "
                    f"observed={observed_total:.6f} expected={float(expected_total):.6f} diff={abs_diff:.6f} tol={tolerance:.6f}"
                )
            hazard_alignment[scenario] = {
                "expected_eur": float(expected_total),
                "observed_eur": observed_total,
                "abs_diff_eur": abs_diff,
            }
        alignment[hazard_key] = hazard_alignment
    return alignment


def _normalized_float_mapping(raw_value: object) -> dict[str, float]:
    if not isinstance(raw_value, dict):
        return {}
    normalized: dict[str, float] = {}
    for key, value in raw_value.items():
        name = str(key or "").strip()
        if not name:
            continue
        normalized[name] = _coerce_float(value, default=0.0)
    return normalized


def _float_mappings_equal(
    left: dict[str, float],
    right: dict[str, float],
    *,
    tolerance: float = 1e-12,
) -> bool:
    if not left or not right:
        return False
    keys = sorted(set(left.keys()) | set(right.keys()))
    return all(abs(float(left.get(key, 0.0)) - float(right.get(key, 0.0))) <= tolerance for key in keys)


def _float_mappings_differ(
    left: dict[str, float],
    right: dict[str, float],
    *,
    tolerance: float = 1e-6,
) -> bool:
    keys = sorted(set(left.keys()) | set(right.keys()))
    return any(abs(float(left.get(key, 0.0)) - float(right.get(key, 0.0))) > tolerance for key in keys)


def _validate_proxy_breakdown_share_variation(
    *,
    run_id: str,
    territory: str,
    proxy_payload: dict[str, Any] | None,
) -> dict[str, dict[str, dict[str, bool]]]:
    hazards = proxy_payload.get("hazards") if isinstance(proxy_payload, dict) else None
    if not isinstance(hazards, dict):
        raise RuntimeError(f"{territory} multi-hazard proxy is missing hazards payload for run {run_id}")

    validation: dict[str, dict[str, dict[str, bool]]] = {}
    scenario_pairs = (("annual", "rp50"), ("annual", "rp100"), ("rp50", "rp100"))
    for hazard_key in ("storm", "storm_cmcc"):
        hazard_payload = hazards.get(hazard_key)
        scenarios = hazard_payload.get("scenarios") if isinstance(hazard_payload, dict) else None
        if not isinstance(scenarios, dict):
            raise RuntimeError(
                f"{territory} multi-hazard proxy is missing hazards.{hazard_key}.scenarios for run {run_id}"
            )

        hazard_checks: dict[str, dict[str, bool]] = {}
        for left_scenario, right_scenario in scenario_pairs:
            left_payload = scenarios.get(left_scenario) if isinstance(scenarios.get(left_scenario), dict) else None
            right_payload = scenarios.get(right_scenario) if isinstance(scenarios.get(right_scenario), dict) else None
            if left_payload is None or right_payload is None:
                raise RuntimeError(
                    f"{territory} multi-hazard proxy is missing {hazard_key} scenario pair {left_scenario}/{right_scenario} for run {run_id}"
                )

            left_ratios = _normalized_float_mapping(left_payload.get("component_ratios"))
            right_ratios = _normalized_float_mapping(right_payload.get("component_ratios"))
            left_shares = _normalized_float_mapping(left_payload.get("breakdown_shares"))
            right_shares = _normalized_float_mapping(right_payload.get("breakdown_shares"))

            ratios_differ = _float_mappings_differ(left_ratios, right_ratios)
            shares_equal = _float_mappings_equal(left_shares, right_shares)
            if ratios_differ and shares_equal:
                raise RuntimeError(
                    f"{territory} multi-hazard proxy has frozen breakdown_shares for {hazard_key} between "
                    f"{left_scenario} and {right_scenario} despite differing component ratios"
                )
            hazard_checks[f"{left_scenario}_vs_{right_scenario}"] = {
                "component_ratios_differ": bool(ratios_differ),
                "breakdown_shares_equal": bool(shares_equal),
            }
        validation[hazard_key] = hazard_checks
    return validation


def _requires_publication_trace(relative_path: str) -> bool:
    path = str(relative_path or "").strip().lower()
    return path.endswith("-multi-hazard-proxy.json") or path.endswith("-analysis.json")


def _path_timestamp(path: Path) -> datetime | None:
    if not path.exists():
        return None
    payload = _load_json_payload(path)
    timestamp = _payload_timestamp(payload)
    if timestamp is not None:
        return timestamp
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)


def _validate_geojson_feature_collection(relative_path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RuntimeError(f"{relative_path} is not valid JSON")
    if str(payload.get("type") or "") != "FeatureCollection":
        raise RuntimeError(f"{relative_path} is not a GeoJSON FeatureCollection")
    features = payload.get("features")
    if not isinstance(features, list):
        raise RuntimeError(f"{relative_path} is missing a GeoJSON features array")
    return payload


def _validate_complete_analysis_network_methodology(
    relative_path: str,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RuntimeError(f"{relative_path} is not valid JSON")
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else None
    if meta is None:
        raise RuntimeError(f"{relative_path} is missing meta")
    methodology = (
        meta.get("network_state_methodology")
        if isinstance(meta.get("network_state_methodology"), dict)
        else None
    )
    if methodology is None:
        raise RuntimeError(f"{relative_path} is missing meta.network_state_methodology")
    comparability_break = meta.get("network_state_methodology_breaks_comparability")
    if comparability_break is not True:
        raise RuntimeError(
            f"{relative_path} has invalid meta.network_state_methodology_breaks_comparability: expected true, got {comparability_break!r}"
        )
    contract = (
        meta.get("network_state_payload_contract")
        if isinstance(meta.get("network_state_payload_contract"), dict)
        else None
    )
    if contract is None:
        raise RuntimeError(f"{relative_path} is missing meta.network_state_payload_contract")
    observed = {
        "schema_version": methodology.get("schema_version"),
        "aggregation_method": methodology.get("aggregation_method"),
        "electric_state_unit": methodology.get("electric_state_unit"),
        "water_state_unit": methodology.get("water_state_unit"),
        "native_service_states_key": contract.get("native_service_states_key"),
        "population_projected_service_states_key": contract.get("population_projected_service_states_key"),
    }
    expected = {
        "schema_version": "aggregated_service_state_v1",
        "aggregation_method": "aggregated_service_state",
        "electric_state_unit": "fixed_grid_0p1deg",
        "water_state_unit": "zone_component_key",
        "native_service_states_key": "native_service_states",
        "population_projected_service_states_key": "population_projected_service_states",
    }
    for key, expected_value in expected.items():
        if observed.get(key) != expected_value:
            raise RuntimeError(
                f"{relative_path} has invalid {key}: expected {expected_value}, got {observed.get(key)}"
            )
    return observed


def _validate_network_states_geojson(relative_path: str, payload: dict[str, Any] | None) -> dict[str, str | None]:
    geojson = _validate_geojson_feature_collection(relative_path, payload)
    metadata = geojson.get("metadata") if isinstance(geojson.get("metadata"), dict) else None
    if metadata is None:
        raise RuntimeError(f"{relative_path} is missing hydraulic network-state metadata")

    observed: dict[str, Any] = {}
    for key, expected_value in REQUIRED_NETWORK_STATES_METADATA.items():
        raw_value = metadata.get(key)
        if isinstance(expected_value, bool):
            value = bool(raw_value)
        else:
            value = str(raw_value or "").strip() or None
        observed[key] = value
        if value != expected_value:
            raise RuntimeError(
                f"{relative_path} has invalid metadata.{key}: expected {expected_value}, got {value}"
            )
    return observed


def _manifest_complete_analysis_timestamp(manifest: dict[str, Any], territory: str) -> datetime | None:
    territories = manifest.get("territories") if isinstance(manifest.get("territories"), dict) else {}
    entry = territories.get(str(territory)) if isinstance(territories, dict) else None
    if not isinstance(entry, dict):
        return None
    phases = entry.get("phases") if isinstance(entry.get("phases"), dict) else {}
    export_phase = phases.get("export") if isinstance(phases, dict) else {}
    impacts_phase = phases.get("impacts") if isinstance(phases, dict) else {}
    for candidate in (
        export_phase.get("updated_at") if isinstance(export_phase, dict) else None,
        impacts_phase.get("updated_at") if isinstance(impacts_phase, dict) else None,
        entry.get("updated_at"),
    ):
        parsed = _parse_iso_datetime(candidate)
        if parsed is not None:
            return parsed
    return None


def _validate_scientific_web_summary_alignment(
    *,
    run_id: str,
    territory: str,
    complete_payload: dict[str, Any],
    summary_payload: dict[str, Any],
) -> dict[str, Any]:
    meta = summary_payload.get("meta") if isinstance(summary_payload.get("meta"), dict) else {}
    if not bool(meta.get("scientific_source")):
        raise RuntimeError(f"{territory} scientific web summary must declare meta.scientific_source=true")
    if str(meta.get("schema_version") or "").strip() != "scientific_web_summary_v1":
        raise RuntimeError(
            f"{territory} scientific web summary has invalid meta.schema_version={meta.get('schema_version')}"
        )
    summary_run_id = str(meta.get("run_id") or "").strip()
    if summary_run_id and summary_run_id != run_id:
        raise RuntimeError(
            f"{territory} scientific web summary references run_id={summary_run_id}, expected {run_id}"
        )
    if str(meta.get("territory") or "").strip().lower() != str(territory).strip().lower():
        raise RuntimeError(
            f"{territory} scientific web summary has invalid meta.territory={meta.get('territory')}"
        )

    portfolio = complete_payload.get("portfolio_results") if isinstance(complete_payload.get("portfolio_results"), dict) else {}
    published = summary_payload.get("portfolio_summary") if isinstance(summary_payload.get("portfolio_summary"), dict) else {}
    alignment: dict[str, Any] = {"hazards": {}}
    field_map = {
        "annual_eur": "eai_eur",
        "rp50_eur": "pml_50_eur",
        "rp100_eur": "pml_100_eur",
        "p99_eur": "percentile_99_loss_eur",
    }
    for hazard_key in ("storm", "storm_cmcc"):
        source_row = portfolio.get(hazard_key) if isinstance(portfolio.get(hazard_key), dict) else {}
        published_row = published.get(hazard_key) if isinstance(published.get(hazard_key), dict) else {}
        checks: dict[str, Any] = {}
        for public_key, source_key in field_map.items():
            expected = _coerce_float(source_row.get(source_key))
            observed = _coerce_float(published_row.get(public_key))
            if abs(observed - expected) > PUBLIC_LOSS_ALIGNMENT_ABS_TOLERANCE_EUR:
                raise RuntimeError(
                    f"{territory} scientific summary mismatch for {hazard_key}.{public_key}: "
                    f"expected {expected}, observed {observed}"
                )
            checks[public_key] = observed
        alignment["hazards"][hazard_key] = checks
    return alignment


def validate_territory_web_snapshot(
    run_id: str,
    territory: str,
    *,
    source_web_dir: Path = WEB_DIR,
    max_complete_analysis_timestamp_skew_seconds: int = MAX_COMPLETE_ANALYSIS_TIMESTAMP_SKEW_SECONDS,
) -> dict[str, Any]:
    resolved_run_id = resolve_run_id(run_id)
    normalized_territory = str(territory or "").strip().lower()
    manifest = load_run_manifest(resolved_run_id)

    manifest_territories = manifest.get("territories") if isinstance(manifest.get("territories"), dict) else {}
    entry = manifest_territories.get(normalized_territory) if isinstance(manifest_territories, dict) else None
    if not isinstance(entry, dict):
        raise ValueError(f"Run {resolved_run_id} does not contain territory {normalized_territory}")
    if str(entry.get("status") or "") != "complete":
        raise RuntimeError(f"Run {resolved_run_id} territory {normalized_territory} is not complete")

    complete_rel = territory_complete_analysis_relative_path(normalized_territory)
    required_frontend = territory_frontend_rebuild_relative_paths(normalized_territory)
    required_paths = (complete_rel, *required_frontend)

    missing = [relative_path for relative_path in required_paths if not (source_web_dir / relative_path).exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing required web artefacts for {normalized_territory}: {', '.join(missing)}"
        )

    complete_path = source_web_dir / complete_rel
    complete_payload = _load_json_payload(complete_path)
    complete_timestamp = _path_timestamp(complete_path)
    if complete_timestamp is None:
        raise RuntimeError(f"Unable to determine timestamp for {complete_path}")

    manifest_complete_timestamp = _manifest_complete_analysis_timestamp(manifest, normalized_territory)
    if manifest_complete_timestamp is not None:
        skew_seconds = abs((complete_timestamp - manifest_complete_timestamp).total_seconds())
        if skew_seconds > float(max_complete_analysis_timestamp_skew_seconds):
            raise RuntimeError(
                f"{complete_rel} does not match run {resolved_run_id}: "
                f"file timestamp {complete_timestamp.isoformat()} differs from manifest timestamp "
                f"{manifest_complete_timestamp.isoformat()} by {int(skew_seconds)}s"
            )

    validation: dict[str, Any] = {
        "run_id": resolved_run_id,
        "territory": normalized_territory,
        "complete_analysis_updated_at": complete_timestamp.isoformat(),
        "manifest_complete_updated_at": manifest_complete_timestamp.isoformat() if manifest_complete_timestamp else None,
        "case_study_run_id": None,
        "complete_analysis_contract": _validate_complete_analysis_network_methodology(
            complete_rel,
            complete_payload,
        ),
        "frontend_timestamps": {},
        "publication_trace": {},
        "public_loss_alignment": {},
        "scientific_web_summary_alignment": {},
        "proxy_breakdown_share_validation": {},
        "geojson_contract": {},
    }

    case_study_run_ids: dict[str, str] = {}
    proxy_payload: dict[str, Any] | None = None
    page_payload: dict[str, Any] | None = None
    scientific_summary_payload: dict[str, Any] | None = None
    for relative_path in required_frontend:
        path = source_web_dir / relative_path
        payload = _load_json_payload(path)
        timestamp = _path_timestamp(path)
        if timestamp is None:
            raise RuntimeError(f"Unable to determine timestamp for {path}")
        validation["frontend_timestamps"][relative_path] = timestamp.isoformat()
        if timestamp < complete_timestamp:
            raise RuntimeError(
                f"{relative_path} is older than {complete_rel}: "
                f"{timestamp.isoformat()} < {complete_timestamp.isoformat()}"
            )
        if path.suffix.lower() == ".geojson":
            geojson_payload = _validate_geojson_feature_collection(relative_path, payload)
            if relative_path.endswith("network-states.geojson"):
                validation["geojson_contract"][relative_path] = _validate_network_states_geojson(
                    relative_path,
                    geojson_payload,
                )
            else:
                validation["geojson_contract"][relative_path] = {
                    "type": str(geojson_payload.get("type") or ""),
                    "feature_count": len(geojson_payload.get("features") or []),
                }
            continue
        if path.suffix.lower() == ".json":
            if relative_path.endswith("-scientific-web-summary.json"):
                scientific_summary_payload = payload
                continue
            case_study_run_id = _payload_case_study_run_id(payload)
            if relative_path.endswith("network-states.geojson"):
                continue
            if not case_study_run_id:
                raise RuntimeError(f"{relative_path} is missing meta.case_study_run_id")
            case_study_run_ids[relative_path] = case_study_run_id
            publication_trace = _payload_publication_trace(payload)
            if _requires_publication_trace(relative_path) and publication_trace is None:
                raise RuntimeError(f"{relative_path} is missing meta.publication_trace")
            if publication_trace is not None:
                if bool(publication_trace.get("fallback_active")):
                    raise RuntimeError(
                        f"{relative_path} declares fallback_active=true; fallback publication is forbidden"
                    )
                if bool(publication_trace.get("multi_hazard_proxy_fallback_active")):
                    raise RuntimeError(
                        f"{relative_path} declares an upstream proxy fallback; fallback publication is forbidden"
                    )
                source_mode = str(publication_trace.get("source_mode") or "").strip()
                if source_mode in FORBIDDEN_PUBLICATION_SOURCE_MODES:
                    raise RuntimeError(
                        f"{relative_path} uses forbidden publication source mode {source_mode}"
                    )
                upstream_proxy_source_mode = str(
                    publication_trace.get("multi_hazard_proxy_source_mode") or ""
                ).strip()
                if upstream_proxy_source_mode in FORBIDDEN_PUBLICATION_SOURCE_MODES:
                    raise RuntimeError(
                        f"{relative_path} references forbidden upstream proxy source mode {upstream_proxy_source_mode}"
                    )
                referenced_complete_run_id = str(publication_trace.get("complete_analysis_run_id") or "").strip()
                if referenced_complete_run_id and referenced_complete_run_id != resolved_run_id:
                    raise RuntimeError(
                        f"{relative_path} references complete-analysis run {referenced_complete_run_id}, expected {resolved_run_id}"
                    )
                validation["publication_trace"][relative_path] = publication_trace

            if relative_path.endswith("-multi-hazard-proxy.json"):
                proxy_payload = payload
            elif relative_path.endswith("-analysis.json"):
                page_payload = payload

    distinct_case_study_run_ids = sorted({value for value in case_study_run_ids.values() if value})
    if len(distinct_case_study_run_ids) != 1:
        raise RuntimeError(
            f"Incoherent case-study artefacts for {normalized_territory}: {case_study_run_ids}"
        )

    validation["case_study_run_id"] = distinct_case_study_run_ids[0]
    proxy_key = next(
        (path for path in validation["publication_trace"].keys() if str(path).endswith("-multi-hazard-proxy.json")),
        None,
    )
    page_key = next(
        (path for path in validation["publication_trace"].keys() if str(path).endswith("-analysis.json")),
        None,
    )
    if proxy_key and page_key:
        proxy_trace = validation["publication_trace"].get(proxy_key) or {}
        page_trace = validation["publication_trace"].get(page_key) or {}
        if bool(proxy_trace.get("fallback_active")) != bool(page_trace.get("multi_hazard_proxy_fallback_active")):
            raise RuntimeError(
                f"Incoherent publication trace for {normalized_territory}: proxy fallback state does not match page-analysis upstream proxy state"
            )
        proxy_source_mode = str(proxy_trace.get("source_mode") or "")
        page_proxy_source_mode = str(page_trace.get("multi_hazard_proxy_source_mode") or "")
        if proxy_source_mode and page_proxy_source_mode and proxy_source_mode != page_proxy_source_mode:
            raise RuntimeError(
                f"Incoherent publication trace for {normalized_territory}: proxy source mode {proxy_source_mode} != page-analysis upstream proxy source mode {page_proxy_source_mode}"
            )
    if proxy_payload is not None:
        validation["proxy_breakdown_share_validation"] = _validate_proxy_breakdown_share_variation(
            run_id=resolved_run_id,
            territory=normalized_territory,
            proxy_payload=proxy_payload,
        )
    if page_payload is not None:
        validation["public_loss_alignment"] = _validate_page_analysis_public_loss_alignment(
            run_id=resolved_run_id,
            territory=normalized_territory,
            complete_payload=complete_payload,
            page_payload=page_payload,
        )
    if scientific_summary_payload is not None:
        validation["scientific_web_summary_alignment"] = _validate_scientific_web_summary_alignment(
            run_id=resolved_run_id,
            territory=normalized_territory,
            complete_payload=complete_payload,
            summary_payload=scientific_summary_payload,
        )
    validation["publication_fallback_present"] = any(
        bool(trace.get("fallback_active")) or bool(trace.get("multi_hazard_proxy_fallback_active"))
        for trace in validation["publication_trace"].values()
        if isinstance(trace, dict)
    )
    optional_paths: dict[str, str | None] = {}
    for relative_path in territory_optional_snapshot_relative_paths(normalized_territory):
        optional_path = source_web_dir / relative_path
        optional_paths[relative_path] = str(optional_path) if optional_path.exists() else None
    validation["optional_paths"] = optional_paths
    if isinstance(complete_payload, dict):
        validation["complete_analysis_payload_updated_at"] = str(complete_payload.get("updated_at") or "") or None
    return validation


def _repair_manifest_status_after_frontend_snapshot(manifest: dict[str, Any], archived_at: str) -> None:
    territories_payload = manifest.get("territories") if isinstance(manifest.get("territories"), dict) else {}
    complete_territories = [
        territory
        for territory, entry in territories_payload.items()
        if isinstance(entry, dict) and str(entry.get("status") or "").strip().lower() == "complete"
    ]
    manifest["updated_at"] = archived_at
    manifest["territories_completed"] = len(complete_territories)

    frontend_artifacts = manifest.get("frontend_artifacts") if isinstance(manifest.get("frontend_artifacts"), dict) else {}
    frontend_complete = str(frontend_artifacts.get("status") or "").strip().lower() == "complete"
    if not territories_payload or len(complete_territories) != len(territories_payload) or not frontend_complete:
        return

    manifest["status"] = "success"
    manifest["current_phase"] = None
    manifest["finished_at"] = str(manifest.get("finished_at") or archived_at)
    manifest["reconciled_at"] = archived_at
    manifest["frontend_artifacts_success"] = True
    manifest.pop("reconcile_reason", None)
    manifest.pop("partial_reason", None)


def snapshot_run_web_artifacts(
    run_id: str,
    territories: list[str] | tuple[str, ...] | None = None,
    *,
    source_web_dir: Path = WEB_DIR,
) -> tuple[str, dict[str, dict[str, str]], dict[str, dict[str, Any]]]:
    resolved_run_id = resolve_publication_run_id(run_id, territories)
    manifest = load_run_manifest(resolved_run_id)
    normalized_territories = normalized_territories_for_run(manifest, territories)

    archived_by_territory: dict[str, dict[str, str]] = {}
    validation_by_territory: dict[str, dict[str, Any]] = {}
    archived_complete_paths: dict[str, str] = {}

    for territory in normalized_territories:
        validation_by_territory[territory] = validate_territory_web_snapshot(
            resolved_run_id,
            territory,
            source_web_dir=source_web_dir,
        )
        complete_archived, missing_complete, _ = copy_territory_web_relative_paths(
            resolved_run_id,
            territory,
            (territory_complete_analysis_relative_path(territory),),
            source_web_dir=source_web_dir,
        )
        required_archived, missing_required, _ = copy_territory_web_relative_paths(
            resolved_run_id,
            territory,
            territory_frontend_rebuild_relative_paths(territory),
            source_web_dir=source_web_dir,
        )
        optional_archived, _, _ = copy_territory_web_relative_paths(
            resolved_run_id,
            territory,
            territory_optional_snapshot_relative_paths(territory),
            source_web_dir=source_web_dir,
        )
        missing = [*missing_complete, *missing_required]
        if missing:
            raise FileNotFoundError(
                f"Unable to snapshot run {resolved_run_id} for {territory}: missing {', '.join(missing)}"
            )
        complete_relative_path = territory_complete_analysis_relative_path(territory)
        archived_complete_paths[territory] = complete_archived[complete_relative_path]
        archived_by_territory[territory] = {
            **required_archived,
            **optional_archived,
        }

    archived_at = datetime.now(UTC).isoformat()
    territories_payload = manifest.get("territories") if isinstance(manifest.get("territories"), dict) else {}
    for territory in normalized_territories:
        entry = territories_payload.get(territory) if isinstance(territories_payload, dict) else None
        if not isinstance(entry, dict):
            continue
        entry["archived_complete_analysis_path"] = archived_complete_paths[territory]
        entry["archived_frontend_artifacts"] = archived_by_territory[territory]
        entry["archived_frontend_validation"] = validation_by_territory[territory]
        entry["updated_at"] = archived_at

    frontend_artifacts = manifest.get("frontend_artifacts") if isinstance(manifest.get("frontend_artifacts"), dict) else {}
    existing_territories = frontend_artifacts.get("territories") if isinstance(frontend_artifacts.get("territories"), list) else []
    existing_archived_files = frontend_artifacts.get("archived_files_by_territory") if isinstance(frontend_artifacts.get("archived_files_by_territory"), dict) else {}
    merged_territories = sorted({str(item) for item in [*existing_territories, *normalized_territories] if str(item).strip()})
    merged_archived_files = dict(existing_archived_files)
    merged_archived_files.update(archived_by_territory)
    frontend_artifacts.update(
        {
            "status": "complete",
            "territories": merged_territories,
            "archived_files_by_territory": merged_archived_files,
            "archived_at": archived_at,
        }
    )
    manifest["frontend_artifacts"] = frontend_artifacts
    manifest["frontend_artifacts_success"] = True
    _repair_manifest_status_after_frontend_snapshot(manifest, archived_at)
    write_run_manifest(resolved_run_id, manifest)
    return resolved_run_id, archived_by_territory, validation_by_territory


def collect_archived_run_files(
    run_id: str,
    territories: list[str] | tuple[str, ...] | None = None,
) -> tuple[str, dict[str, dict[str, str]]]:
    resolved_run_id = resolve_publication_run_id(run_id, territories)
    manifest = load_run_manifest(resolved_run_id)
    normalized_territories = normalized_territories_for_run(manifest, territories)

    archived_files_by_territory: dict[str, dict[str, str]] = {}
    for territory in normalized_territories:
        archive_root = archived_territory_web_dir(resolved_run_id, territory)
        territory_archived: dict[str, str] = {}
        missing_required: list[str] = []

        complete_relative_path = territory_complete_analysis_relative_path(territory)
        complete_archived_path = archive_root / complete_relative_path
        if not complete_archived_path.exists():
            missing_required.append(complete_relative_path)
        else:
            territory_archived[complete_relative_path] = str(complete_archived_path)

        for relative_path in territory_frontend_rebuild_relative_paths(territory):
            archived_path = archive_root / relative_path
            if not archived_path.exists():
                missing_required.append(relative_path)
                continue
            territory_archived[relative_path] = str(archived_path)

        for relative_path in territory_optional_snapshot_relative_paths(territory):
            archived_path = archive_root / relative_path
            if archived_path.exists():
                territory_archived[relative_path] = str(archived_path)

        if missing_required:
            raise FileNotFoundError(
                f"Run {resolved_run_id} is missing archived web artefacts for {territory}: {', '.join(missing_required)}"
            )
        archived_files_by_territory[territory] = territory_archived
    return resolved_run_id, archived_files_by_territory


def build_staging_web_dir_from_run(
    run_id: str,
    territories: list[str] | tuple[str, ...] | None = None,
    *,
    base_web_dir: Path = WEB_DIR,
):
    resolved_run_id = resolve_publication_run_id(run_id, territories)
    manifest = load_run_manifest(resolved_run_id)
    ensure_run_publication_eligible(resolved_run_id, manifest)
    resolved_run_id, restored = collect_archived_run_files(resolved_run_id, territories)

    temp_dir = tempfile.TemporaryDirectory(prefix=f"sib-deploy-{resolved_run_id}-")
    stage_root = Path(temp_dir.name) / "web"
    shutil.copytree(base_web_dir, stage_root)

    for territory_files in restored.values():
        for relative_path, archived_path in territory_files.items():
            destination_path = stage_root / relative_path
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(archived_path), destination_path)

    for territory in restored.keys():
        validate_territory_web_snapshot(
            resolved_run_id,
            territory,
            source_web_dir=stage_root,
        )

    return temp_dir, stage_root, resolved_run_id, restored
