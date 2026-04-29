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


def resolve_run_id(raw_value: str) -> str:
    value = str(raw_value or "").strip()
    if not value:
        raise ValueError("run_id must not be empty")
    if value.lower() != "latest":
        return value
    latest_manifest = RUN_OUTPUTS_DIR / "latest-manifest.json"
    if not latest_manifest.exists():
        raise FileNotFoundError(f"Latest run manifest not found: {latest_manifest}")
    payload = json.loads(latest_manifest.read_text(encoding="utf-8"))
    run_id = str((payload or {}).get("run_id") or "").strip()
    if not run_id:
        raise ValueError(f"Latest run manifest does not contain a run_id: {latest_manifest}")
    return run_id


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
    return "page2" if normalized == "martinique" else "page1"


def territory_complete_analysis_relative_path(territory: str) -> str:
    normalized = str(territory or "").strip().lower()
    return f"data/{normalized}-complete-analysis.json"


def territory_frontend_rebuild_relative_paths(territory: str) -> tuple[str, ...]:
    normalized = str(territory or "").strip().lower()
    return (
        f"data/{normalized}-wind-maps.json",
        f"data/{normalized}-multi-hazard-proxy.json",
        f"data/{normalized}-{case_study_page_suffix(normalized)}-analysis.json",
        f"data/{normalized}-network-states.geojson",
    )


def territory_optional_snapshot_relative_paths(territory: str) -> tuple[str, ...]:
    normalized = str(territory or "").strip().lower()
    return (
        f"data/{normalized}-landslide-maps.json",
    )


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
        "frontend_timestamps": {},
        "publication_trace": {},
    }

    case_study_run_ids: dict[str, str] = {}
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
        if path.suffix.lower() == ".json":
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
                validation["publication_trace"][relative_path] = publication_trace

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


def snapshot_run_web_artifacts(
    run_id: str,
    territories: list[str] | tuple[str, ...] | None = None,
    *,
    source_web_dir: Path = WEB_DIR,
) -> tuple[str, dict[str, dict[str, str]], dict[str, dict[str, Any]]]:
    resolved_run_id = resolve_run_id(run_id)
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
    write_run_manifest(resolved_run_id, manifest)
    return resolved_run_id, archived_by_territory, validation_by_territory


def collect_archived_run_files(
    run_id: str,
    territories: list[str] | tuple[str, ...] | None = None,
) -> tuple[str, dict[str, dict[str, str]]]:
    resolved_run_id = resolve_run_id(run_id)
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
    resolved_run_id, restored = collect_archived_run_files(run_id, territories)

    temp_dir = tempfile.TemporaryDirectory(prefix=f"sib-deploy-{resolved_run_id}-")
    stage_root = Path(temp_dir.name) / "web"
    shutil.copytree(base_web_dir, stage_root)

    for territory_files in restored.values():
        for relative_path, archived_path in territory_files.items():
            destination_path = stage_root / relative_path
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(archived_path), destination_path)

    return temp_dir, stage_root, resolved_run_id, restored