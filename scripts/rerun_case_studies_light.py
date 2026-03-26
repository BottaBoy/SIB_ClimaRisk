#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = REPO_ROOT / "backend" / ".venv" / "bin" / "python"


def _run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


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
                "--multi-hazard-proxy-json",
                str(proxy_json),
            ]
        )


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
