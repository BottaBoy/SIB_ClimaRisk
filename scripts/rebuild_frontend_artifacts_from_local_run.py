#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from case_study_sources import parse_territory

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DATA_DIR = REPO_ROOT / "web" / "data"


def _load_json_payload(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object at {path}")
    return payload


def _extract_requested_dynamic_max_tracks(payload: object) -> int | None:
    if isinstance(payload, dict):
        for key in ("hazard_dynamic_max_tracks_requested", "requested_dynamic_max_tracks"):
            raw_value = payload.get(key)
            if raw_value is None or isinstance(raw_value, bool):
                continue
            try:
                value = int(raw_value)
            except (TypeError, ValueError):
                continue
            if value > 0:
                return value
        for value in payload.values():
            resolved = _extract_requested_dynamic_max_tracks(value)
            if resolved is not None:
                return resolved
        return None

    if isinstance(payload, list):
        for item in payload:
            resolved = _extract_requested_dynamic_max_tracks(item)
            if resolved is not None:
                return resolved
    return None


def territory_complete_analysis_path(territory: str, *, data_root: Path | None = None) -> Path:
    normalized = str(territory or "").strip().lower()
    if not normalized:
        raise ValueError("territory must not be empty")
    resolved_data_root = WEB_DATA_DIR if data_root is None else Path(data_root)
    return resolved_data_root / f"{normalized}-complete-analysis.json"


def resolve_local_requested_dynamic_max_tracks(
    territories: list[str] | tuple[str, ...],
    *,
    data_root: Path | None = None,
) -> tuple[int, dict[str, int]]:
    if not territories:
        raise ValueError("At least one territory is required")

    resolved_data_root = WEB_DATA_DIR if data_root is None else Path(data_root)
    resolved_by_territory: dict[str, int] = {}
    for territory in territories:
        normalized = str(territory or "").strip().lower()
        if not normalized:
            raise ValueError("territory must not be empty")
        complete_analysis_path = territory_complete_analysis_path(normalized, data_root=resolved_data_root)
        if not complete_analysis_path.exists():
            raise FileNotFoundError(
                f"[{normalized}] complete-analysis payload not found: {complete_analysis_path}"
            )
        payload = _load_json_payload(complete_analysis_path)
        requested_tracks = _extract_requested_dynamic_max_tracks(payload)
        if requested_tracks is None:
            raise RuntimeError(
                f"[{normalized}] could not resolve requested dynamic max tracks from {complete_analysis_path}"
            )
        resolved_by_territory[normalized] = int(requested_tracks)

    distinct_values = sorted(set(resolved_by_territory.values()))
    if len(distinct_values) != 1:
        details = ", ".join(
            f"{territory}={resolved_by_territory[territory]}"
            for territory in sorted(resolved_by_territory.keys())
        )
        raise RuntimeError(
            "Selected territories do not share the same requested dynamic max tracks: "
            + details
        )
    return distinct_values[0], resolved_by_territory


def build_rerun_command(args: argparse.Namespace, *, dynamic_max_tracks: int) -> list[str]:
    return [
        sys.executable,
        str(REPO_ROOT / "scripts" / "rerun_case_studies_light.py"),
        "--territories",
        *[str(territory).strip().lower() for territory in args.territories],
        "--proxy-max-points-total",
        str(args.proxy_max_points_total),
        "--proxy-max-points-per-feature",
        str(args.proxy_max_points_per_feature),
        "--proxy-dynamic-max-tracks",
        str(args.proxy_dynamic_max_tracks),
        "--map-dynamic-max-tracks",
        str(args.map_dynamic_max_tracks),
        "--page-component-light-dynamic-max-tracks",
        str(int(dynamic_max_tracks)),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild frontend artifacts using the requested dynamic track cap declared by the local "
            "complete-analysis payloads."
        )
    )
    parser.add_argument("--territories", nargs="+", required=True)
    parser.add_argument("--proxy-max-points-total", type=int, default=600)
    parser.add_argument("--proxy-max-points-per-feature", type=int, default=6)
    parser.add_argument("--proxy-dynamic-max-tracks", type=int, default=100)
    parser.add_argument("--map-dynamic-max-tracks", type=int, default=300)
    parser.add_argument(
        "--page-component-light-dynamic-max-tracks",
        type=int,
        default=None,
        help="Optional override. Defaults to the shared requested dynamic track cap resolved from local complete-analysis payloads.",
    )
    args = parser.parse_args(argv)
    try:
        args.territories = [parse_territory(value) for value in args.territories]
    except ValueError as exc:
        parser.error(str(exc))

    dynamic_max_tracks = args.page_component_light_dynamic_max_tracks
    resolved_by_territory: dict[str, int] = {}
    if dynamic_max_tracks is None:
        dynamic_max_tracks, resolved_by_territory = resolve_local_requested_dynamic_max_tracks(args.territories)
    else:
        dynamic_max_tracks = int(dynamic_max_tracks)

    env = os.environ.copy()
    env["SIB_RISK_HAZARD_DYNAMIC_MAX_TRACKS"] = str(int(dynamic_max_tracks))
    command = build_rerun_command(args, dynamic_max_tracks=int(dynamic_max_tracks))

    if resolved_by_territory:
        details = ", ".join(
            f"{territory}={resolved_by_territory[territory]}"
            for territory in sorted(resolved_by_territory.keys())
        )
        print(f"[info] resolved requested dynamic max tracks from local complete-analysis payloads: {details}")
    print(f"[info] exporting SIB_RISK_HAZARD_DYNAMIC_MAX_TRACKS={int(dynamic_max_tracks)}")
    print("+", " ".join(command), flush=True)
    subprocess.run(command, check=True, env=env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
