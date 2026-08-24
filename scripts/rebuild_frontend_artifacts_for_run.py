#!/usr/bin/env python3
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Iterator

from case_study_sources import parse_territory

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from frontend_supervision import (  # noqa: E402
    ENV_FRONTEND_SUPERVISION_JOURNAL,
    ENV_FRONTEND_SUPERVISION_RUN_ID,
    frontend_supervision_journal_path,
)
from rebuild_frontend_artifacts_from_local_run import (  # noqa: E402
    _extract_requested_dynamic_max_tracks,
    build_rerun_command,
)
from run_web_artifacts import (  # noqa: E402
    RUN_OUTPUTS_DIR,
    resolve_run_id,
    snapshot_run_web_artifacts,
)


LATEST_SUCCESS_ALIASES = frozenset({"latest-success", "latest_success", "latest-successful"})
WEB_DATA_DIR = REPO_ROOT / "web" / "data"


def _load_json_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object at {path}")
    return payload


def resolve_selected_run_id(raw_value: str) -> str:
    value = str(raw_value or "").strip()
    if not value:
        raise ValueError("run_id must not be empty")
    normalized = value.lower()
    if normalized in LATEST_SUCCESS_ALIASES:
        for manifest_path in sorted(RUN_OUTPUTS_DIR.glob("20*/manifest.json"), reverse=True):
            payload = _load_json_payload(manifest_path)
            if str(payload.get("status") or "").strip().lower() == "success":
                return str(payload.get("run_id") or manifest_path.parent.name)
        raise FileNotFoundError("No successful complete-analysis run found")
    return resolve_run_id(value)


def _resolve_run_manifest(resolved_run_id: str) -> dict[str, Any]:
    manifest_path = RUN_OUTPUTS_DIR / resolved_run_id / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Run manifest not found: {manifest_path}")
    return _load_json_payload(manifest_path)


def _resolve_available_territories(manifest: dict[str, Any]) -> list[str]:
    territories = manifest.get("territories") if isinstance(manifest.get("territories"), dict) else {}
    out: list[str] = []
    for territory, payload in territories.items():
        if not isinstance(payload, dict):
            continue
        if str(payload.get("status") or "").strip().lower() != "complete":
            continue
        out.append(str(territory))
    if not out:
        raise RuntimeError("Selected run does not expose any completed territory suitable for frontend rebuild")
    return sorted(out)


def _resolve_selected_territories(manifest: dict[str, Any], requested: list[str] | None) -> list[str]:
    available = _resolve_available_territories(manifest)
    if not requested:
        return available
    normalized_requested = [str(item or "").strip().lower() for item in requested]
    missing = [territory for territory in normalized_requested if territory not in available]
    if missing:
        raise RuntimeError(
            f"Selected run does not expose the requested completed territories: {', '.join(missing)}"
        )
    return normalized_requested


def territory_archived_complete_analysis_path(manifest: dict[str, Any], territory: str) -> Path:
    territories = manifest.get("territories") if isinstance(manifest.get("territories"), dict) else {}
    territory_payload = territories.get(str(territory)) if isinstance(territories, dict) else None
    if not isinstance(territory_payload, dict):
        raise RuntimeError(f"Missing territory payload for {territory}")
    phases = territory_payload.get("phases") if isinstance(territory_payload.get("phases"), dict) else {}
    export_phase = phases.get("export") if isinstance(phases, dict) else {}
    candidates = [
        territory_payload.get("archived_complete_analysis_path"),
        export_phase.get("archived_output_file") if isinstance(export_phase, dict) else None,
        RUN_OUTPUTS_DIR / str(manifest.get("run_id") or "") / "territories" / str(territory) / "web" / "data" / f"{territory}-complete-analysis.json",
    ]
    for raw_path in candidates:
        candidate = Path(str(raw_path or ""))
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"[{territory}] archived complete-analysis payload not found for run {manifest.get('run_id')}")


@contextmanager
def staged_archived_complete_analysis_payloads(
    manifest: dict[str, Any],
    territories: list[str] | tuple[str, ...],
) -> Iterator[dict[str, str]]:
    staged_targets: dict[str, str] = {}
    backups: list[tuple[Path, Path | None]] = []
    with tempfile.TemporaryDirectory(prefix="rebuild-frontend-archived-complete-") as tmp_dir:
        backup_root = Path(tmp_dir)
        for territory in territories:
            source_path = territory_archived_complete_analysis_path(manifest, territory)
            target_path = WEB_DATA_DIR / f"{territory}-complete-analysis.json"
            backup_path: Path | None = None
            if target_path.exists():
                backup_path = backup_root / f"{territory}-complete-analysis.json"
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target_path, backup_path)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)
            staged_targets[str(territory)] = str(target_path)
            backups.append((target_path, backup_path))
        try:
            yield staged_targets
        finally:
            for target_path, backup_path in backups:
                if backup_path is not None and backup_path.exists():
                    shutil.copy2(backup_path, target_path)
                elif target_path.exists():
                    target_path.unlink()


def resolve_run_requested_dynamic_max_tracks(
    manifest: dict[str, Any],
    territories: list[str] | tuple[str, ...],
) -> tuple[int, dict[str, int]]:
    resolved_by_territory: dict[str, int] = {}
    for territory in territories:
        complete_analysis_path = territory_archived_complete_analysis_path(manifest, territory)
        payload = _load_json_payload(complete_analysis_path)
        requested_tracks = _extract_requested_dynamic_max_tracks(payload)
        if requested_tracks is None:
            raise RuntimeError(
                f"[{territory}] could not resolve requested dynamic max tracks from archived payload {complete_analysis_path}"
            )
        resolved_by_territory[str(territory)] = int(requested_tracks)

    distinct_values = sorted(set(resolved_by_territory.values()))
    if len(distinct_values) != 1:
        details = ", ".join(
            f"{territory}={resolved_by_territory[territory]}"
            for territory in sorted(resolved_by_territory.keys())
        )
        raise RuntimeError(
            "Selected territories do not share the same requested dynamic max tracks in archived payloads: "
            + details
        )
    return distinct_values[0], resolved_by_territory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild frontend artifacts from the archived complete-analysis payloads of a selected run, "
            "then snapshot the rebuilt web outputs back into that run archive."
        )
    )
    parser.add_argument("--run-id", required=True, help="Run ID exact, or selector: latest, latest-success.")
    parser.add_argument("--territories", nargs="+", default=None)
    parser.add_argument("--proxy-max-points-total", type=int, default=600)
    parser.add_argument("--proxy-max-points-per-feature", type=int, default=6)
    parser.add_argument("--proxy-dynamic-max-tracks", type=int, default=100)
    parser.add_argument("--map-dynamic-max-tracks", type=int, default=300)
    parser.add_argument(
        "--page-component-light-dynamic-max-tracks",
        type=int,
        default=None,
        help="Optional override. Defaults to the shared requested dynamic track cap resolved from the archived run payloads.",
    )
    args = parser.parse_args(argv)
    try:
        if args.territories is not None:
            args.territories = [parse_territory(value) for value in args.territories]
    except ValueError as exc:
        parser.error(str(exc))

    resolved_run_id = resolve_selected_run_id(args.run_id)
    manifest = _resolve_run_manifest(resolved_run_id)
    territories = _resolve_selected_territories(manifest, args.territories)

    dynamic_max_tracks = args.page_component_light_dynamic_max_tracks
    resolved_by_territory: dict[str, int] = {}
    if dynamic_max_tracks is None:
        dynamic_max_tracks, resolved_by_territory = resolve_run_requested_dynamic_max_tracks(manifest, territories)
    else:
        dynamic_max_tracks = int(dynamic_max_tracks)

    rerun_args = argparse.Namespace(
        territories=territories,
        proxy_max_points_total=int(args.proxy_max_points_total),
        proxy_max_points_per_feature=int(args.proxy_max_points_per_feature),
        proxy_dynamic_max_tracks=int(args.proxy_dynamic_max_tracks),
        map_dynamic_max_tracks=int(args.map_dynamic_max_tracks),
    )
    command = build_rerun_command(rerun_args, dynamic_max_tracks=int(dynamic_max_tracks))

    env = os.environ.copy()
    env["SIB_RISK_HAZARD_DYNAMIC_MAX_TRACKS"] = str(int(dynamic_max_tracks))
    env[ENV_FRONTEND_SUPERVISION_RUN_ID] = resolved_run_id
    env[ENV_FRONTEND_SUPERVISION_JOURNAL] = str(
        frontend_supervision_journal_path(RUN_OUTPUTS_DIR / resolved_run_id)
    )

    print(f"[info] resolved run_id={resolved_run_id}")
    print(f"[info] rebuilding territories={','.join(territories)}")
    if resolved_by_territory:
        details = ", ".join(
            f"{territory}={resolved_by_territory[territory]}"
            for territory in sorted(resolved_by_territory.keys())
        )
        print(f"[info] resolved requested dynamic max tracks from archived run payloads: {details}")
    print(f"[info] exporting SIB_RISK_HAZARD_DYNAMIC_MAX_TRACKS={int(dynamic_max_tracks)}")
    with staged_archived_complete_analysis_payloads(manifest, territories) as staged_payloads:
        if staged_payloads:
            details = ", ".join(
                f"{territory}={path}"
                for territory, path in sorted(staged_payloads.items())
            )
            print(f"[info] staged archived complete-analysis payloads into web/data: {details}")
        print("+", " ".join(command), flush=True)
        subprocess.run(command, check=True, env=env)
        snapshot_run_web_artifacts(resolved_run_id, territories)
    print(f"[ok] archived rebuilt frontend artefacts into run {resolved_run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
