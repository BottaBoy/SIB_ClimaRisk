from __future__ import annotations

from pathlib import Path
from typing import Any
import hashlib
import json


COMPONENT_KEYS: tuple[str, ...] = ("wind", "rain", "surge", "landslide")


def load_json_file(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def infer_default_valuation_asset_count(payload: dict[str, Any]) -> int | None:
    asset_results = payload.get("asset_results")
    if not isinstance(asset_results, list) or not asset_results:
        return 0

    count = 0
    found_explicit_flag = False
    for row in asset_results:
        if not isinstance(row, dict):
            continue
        for key in ("uses_default_value", "value_was_default", "default_value_used"):
            if key in row:
                found_explicit_flag = True
                if bool(row.get(key)):
                    count += 1
                break

    if found_explicit_flag:
        return count
    return None


def default_valuation_count_source(payload: dict[str, Any]) -> str:
    count = infer_default_valuation_asset_count(payload)
    return "explicit_payload_flag" if count is not None else "not_exposed_in_current_payload"


def scientific_fallback_present(manifest_entry: dict[str, Any]) -> bool:
    phases = manifest_entry.get("phases") if isinstance(manifest_entry, dict) else {}
    impacts = phases.get("impacts") if isinstance(phases, dict) else {}
    modeling = impacts.get("modeling") if isinstance(impacts, dict) else {}
    if not isinstance(modeling, dict):
        return False

    impact_engine_mode = str(modeling.get("impact_engine_mode") or "").strip().lower()
    if impact_engine_mode and impact_engine_mode != "climada":
        return True

    component_status = modeling.get("multi_hazard_component_status_by_hazard")
    if not isinstance(component_status, dict):
        return False

    degraded_states = {"fallback", "degraded", "partial", "error", "failed"}
    for statuses_by_component in component_status.values():
        if not isinstance(statuses_by_component, dict):
            continue
        for status in statuses_by_component.values():
            state = str(status or "").strip().lower()
            if state in degraded_states:
                return True
    return False


def publication_fallback_present(*payloads: dict[str, Any] | None) -> bool:
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        modeling = meta.get("modeling") if isinstance(meta.get("modeling"), dict) else {}
        if bool(modeling.get("fallback")):
            return True
    return False


def _component_share_map(proxy_payload: dict[str, Any], hazard_key: str) -> dict[str, float | None]:
    hazards = proxy_payload.get("hazards") if isinstance(proxy_payload, dict) else {}
    hazard_payload = hazards.get(hazard_key) if isinstance(hazards, dict) else {}
    scenarios = hazard_payload.get("scenarios") if isinstance(hazard_payload, dict) else {}
    annual = scenarios.get("annual") if isinstance(scenarios, dict) else {}
    ratios = annual.get("component_ratios") if isinstance(annual, dict) else {}

    result: dict[str, float | None] = {}
    for component in COMPONENT_KEYS:
        raw_value = ratios.get(component) if isinstance(ratios, dict) else None
        result[component] = float(raw_value) if raw_value is not None else None
    return result


def build_regression_rows(
    *,
    territory: str,
    manifest_entry: dict[str, Any],
    complete_payload: dict[str, Any],
    proxy_payload: dict[str, Any] | None = None,
    page_payload: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    portfolio_results = complete_payload.get("portfolio_results")
    if not isinstance(portfolio_results, dict):
        return []

    default_count = infer_default_valuation_asset_count(complete_payload)
    default_count_source = default_valuation_count_source(complete_payload)
    publication_fallback = publication_fallback_present(proxy_payload, page_payload)
    scientific_fallback = scientific_fallback_present(manifest_entry)

    rows: list[dict[str, Any]] = []
    for hazard_key, metrics in portfolio_results.items():
        if not isinstance(metrics, dict):
            continue
        if str(hazard_key) not in {"storm", "storm_cmcc"}:
            continue
        if not any(key in metrics for key in ("eai_eur", "pml_50_eur", "pml_100_eur", "percentile_99_loss_eur", "max_event_loss_eur")):
            continue
        row = {
            "territory": str(territory),
            "hazard": str(hazard_key),
            "eai_eur": metrics.get("eai_eur"),
            "pml_50_eur": metrics.get("pml_50_eur"),
            "pml_100_eur": metrics.get("pml_100_eur"),
            "max_event_loss_eur": metrics.get("max_event_loss_eur", metrics.get("percentile_99_loss_eur")),
            "percentile_99_loss_eur": metrics.get("percentile_99_loss_eur", metrics.get("max_event_loss_eur")),
            "default_valuation_asset_count": default_count,
            "default_valuation_count_source": default_count_source,
            "scientific_fallback_present": scientific_fallback,
            "publication_fallback_present": publication_fallback,
            "page_analysis_fallback": publication_fallback_present(page_payload),
            "proxy_fallback": publication_fallback_present(proxy_payload),
        }
        component_shares = _component_share_map(proxy_payload or {}, str(hazard_key))
        for component, share in component_shares.items():
            row[f"component_share_{component}"] = share
        rows.append(row)

    rows.sort(key=lambda item: str(item.get("hazard") or ""))
    return rows


def build_artifact_record(path: Path, *, label: str, required: bool = True) -> dict[str, Any]:
    exists = path.exists()
    return {
        "label": label,
        "path": str(path),
        "required": bool(required),
        "exists": exists,
        "size_bytes": int(path.stat().st_size) if exists else None,
        "sha256": sha256_file(path) if exists else None,
    }