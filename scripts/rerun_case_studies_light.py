#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = REPO_ROOT / "backend" / ".venv" / "bin" / "python"
UTC = timezone.utc


def _run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def _read_meta(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    meta = payload.get("meta") if isinstance(payload, dict) else None
    return meta if isinstance(meta, dict) else {}


def _assert_case_study_coherence(territory: str, run_id: str) -> None:
    wind_map_path = REPO_ROOT / "web" / "data" / f"{territory}-wind-maps.json"
    proxy_path = REPO_ROOT / "web" / "data" / f"{territory}-multi-hazard-proxy.json"
    page_suffix = "page2" if territory == "martinique" else "page1"
    page_path = REPO_ROOT / "web" / "data" / f"{territory}-{page_suffix}-analysis.json"

    wind_meta = _read_meta(wind_map_path)
    proxy_meta = _read_meta(proxy_path)
    page_meta = _read_meta(page_path)

    observed = {
        "wind-maps": str(wind_meta.get("case_study_run_id") or ""),
        "multi-hazard-proxy": str(proxy_meta.get("case_study_run_id") or ""),
        "page-analysis": str(page_meta.get("case_study_run_id") or ""),
    }
    mismatches = [name for name, value in observed.items() if value != run_id]
    if mismatches:
        raise RuntimeError(
            f"[{territory}] incoherent case-study artefacts: expected run_id={run_id}, "
            f"got {observed}"
        )

    print(
        f"[{territory}] coherence OK run_id={run_id} "
        f"(wind={wind_meta.get('generated_at')}, proxy={proxy_meta.get('generated_at')}, page={page_meta.get('generated_at')})",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a lighter, more robust case-study rerun for Guadeloupe/Martinique.")
    parser.add_argument("--territories", nargs="+", choices=["guadeloupe", "martinique"], default=["guadeloupe", "martinique"])
    parser.add_argument("--proxy-spacing-m", type=float, default=800.0)
    parser.add_argument("--proxy-max-points-total", type=int, default=800)
    parser.add_argument("--proxy-max-points-per-feature", type=int, default=8)
    parser.add_argument("--proxy-dynamic-max-tracks", type=int, default=100)
    parser.add_argument("--page-spacing-m", type=float, default=100.0)
    parser.add_argument("--map-cell-deg", type=float, default=0.02)
    parser.add_argument("--map-dynamic-max-tracks", type=int, default=300)
    parser.add_argument("--map-surge-native-cell-deg", type=float, default=0.01)
    args = parser.parse_args()

    if not PYTHON.exists():
        raise FileNotFoundError(f"Python backend venv not found: {PYTHON}")

    for territory in args.territories:
        run_id = datetime.now(UTC).strftime(f"{territory}_case_%Y%m%dT%H%M%SZ")
        proxy_json = REPO_ROOT / "web" / "data" / f"{territory}-multi-hazard-proxy.json"

        _run(
            [
                str(PYTHON),
                str(REPO_ROOT / "scripts" / "build_guadeloupe_wind_maps.py"),
                "--territory",
                territory,
                "--cell-deg",
                str(args.map_cell_deg),
                "--dynamic-max-tracks",
                str(args.map_dynamic_max_tracks),
                "--surge-native-cell-deg",
                str(args.map_surge_native_cell_deg),
                "--case-study-run-id",
                run_id,
            ]
        )
        _run(
            [
                str(PYTHON),
                str(REPO_ROOT / "scripts" / "build_case_study_multi_hazard_proxy.py"),
                "--territory",
                territory,
                "--spacing-m",
                str(args.proxy_spacing_m),
                "--max-points-total",
                str(args.proxy_max_points_total),
                "--max-points-per-feature",
                str(args.proxy_max_points_per_feature),
                "--dynamic-max-tracks",
                str(args.proxy_dynamic_max_tracks),
                "--hazard-map-json",
                str(REPO_ROOT / "web" / "data" / f"{territory}-wind-maps.json"),
                "--out-json",
                str(proxy_json),
                "--case-study-run-id",
                run_id,
            ]
        )
        _run(
            [
                str(PYTHON),
                str(REPO_ROOT / "scripts" / "build_guadeloupe_page1_data.py"),
                "--territory",
                territory,
                "--spacing-m",
                str(args.page_spacing_m),
                "--wind-map-json",
                str(REPO_ROOT / "web" / "data" / f"{territory}-wind-maps.json"),
                "--multi-hazard-proxy-json",
                str(proxy_json),
                "--case-study-run-id",
                run_id,
            ]
        )
        _assert_case_study_coherence(territory, run_id)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
