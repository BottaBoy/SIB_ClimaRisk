#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

from journal_guamar_run import record_guamar_run


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = REPO_ROOT / "backend" / ".venv" / "bin" / "python"
UTC = timezone.utc
TERRITORY_PAGE_SPACING_M = {
    "guadeloupe": 100.0,
    "martinique": 150.0,
}


def _run(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, env=env)


def _info(message: str) -> None:
    print(f"[INFO] {message}", flush=True)


def _page_spacing_for_territory(territory: str, requested_spacing_m: float | None) -> float:
    if requested_spacing_m is not None:
        return float(requested_spacing_m)
    return float(TERRITORY_PAGE_SPACING_M.get(str(territory).strip().lower(), 100.0))


def _run_with_reuse_fallback(
    cmd: list[str],
    *,
    env: dict[str, str] | None = None,
    reuse_path: Path | None = None,
    label: str,
    allow_reuse_fallback: bool = False,
) -> bool:
    print("+", " ".join(cmd), flush=True)
    try:
        subprocess.run(cmd, check=True, env=env)
        return True
    except subprocess.CalledProcessError as exc:
        if allow_reuse_fallback and reuse_path is not None and reuse_path.exists():
            print(
                f"[{label}] warning: step failed with exit code {exc.returncode}; reusing existing artefact {reuse_path}",
                flush=True,
            )
            return False
        raise


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a lighter, more robust case-study rerun for Guadeloupe/Martinique.")
    parser.add_argument("--territories", nargs="+", choices=["guadeloupe", "martinique"], default=["guadeloupe", "martinique"])
    parser.add_argument("--proxy-spacing-m", type=float, default=800.0)
    parser.add_argument("--proxy-max-points-total", type=int, default=800)
    parser.add_argument("--proxy-max-points-per-feature", type=int, default=8)
    parser.add_argument("--proxy-dynamic-max-tracks", type=int, default=100)
    parser.add_argument(
        "--prefer-complete-analysis-proxy-fallback",
        action="store_true",
        help="Build the case-study proxy directly from complete-analysis component ratios instead of running the lightweight sampled CLIMADA proxy step.",
    )
    parser.add_argument(
        "--prefer-complete-analysis-page-fallback",
        action="store_true",
        help="Build the case-study page-analysis and network-state artefacts directly from complete-analysis asset results instead of running the heavy CLIMADA page-analysis step.",
    )
    parser.add_argument(
        "--page-spacing-m",
        type=float,
        default=None,
        help="Page-analysis spacing in meters. Defaults to 100 for Guadeloupe and 150 for Martinique.",
    )
    parser.add_argument(
        "--page-component-light-spacing-m",
        type=float,
        default=800.0,
        help="Spacing in meters for the lighter component rerun used inside page-analysis rebuilds.",
    )
    parser.add_argument(
        "--page-component-light-max-points-total",
        type=int,
        default=800,
        help="Maximum total sampled points for the lighter component rerun used inside page-analysis rebuilds.",
    )
    parser.add_argument(
        "--page-component-light-max-points-per-feature",
        type=int,
        default=8,
        help="Maximum sampled points per feature for the lighter component rerun used inside page-analysis rebuilds.",
    )
    parser.add_argument(
        "--page-component-light-dynamic-max-tracks",
        type=int,
        default=100,
        help="Maximum dynamic tracks for the lighter component rerun used inside page-analysis rebuilds.",
    )
    parser.add_argument("--map-cell-deg", type=float, default=0.02)
    parser.add_argument("--map-dynamic-max-tracks", type=int, default=300)
    parser.add_argument("--map-surge-native-cell-deg", type=float, default=0.01)
    parser.add_argument(
        "--allow-reuse-fallback",
        action="store_true",
        help="Allow reuse of existing proxy/page artefacts after a failed rebuild step, but still return a non-zero exit code.",
    )
    args = parser.parse_args()

    if not PYTHON.exists():
        raise FileNotFoundError(f"Python backend venv not found: {PYTHON}")

    session_run_id = datetime.now(UTC).strftime("guamar_session_%Y%m%dT%H%M%SZ")
    print(f"[session] run_id={session_run_id}", flush=True)
    reused_steps: list[str] = []

    for territory in args.territories:
        run_id = datetime.now(UTC).strftime(f"{territory}_case_%Y%m%dT%H%M%SZ")
        proxy_json = REPO_ROOT / "web" / "data" / f"{territory}-multi-hazard-proxy.json"
        page_suffix = "page2" if territory == "martinique" else "page1"
        page_json = REPO_ROOT / "web" / "data" / f"{territory}-{page_suffix}-analysis.json"
        page_spacing_m = _page_spacing_for_territory(territory, args.page_spacing_m)
        territory_env = os.environ.copy()
        territory_env.setdefault("SIB_RISK_MULTI_HAZARD_ENABLED", "false")
        territory_env.setdefault("SIB_RISK_CLIMADA_MAX_POINTS_PER_FEATURE", "120")

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
            ,
            env=territory_env,
        )
        proxy_built = _run_with_reuse_fallback(
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
                *( ["--prefer-complete-analysis-fallback"] if args.prefer_complete_analysis_proxy_fallback else [] ),
            ]
            ,
            env=territory_env,
            reuse_path=proxy_json,
            label=f"{territory} proxy",
            allow_reuse_fallback=bool(args.allow_reuse_fallback),
        )
        if not proxy_built:
            reused_steps.append(f"{territory}: proxy")
        _info(f"[{territory}] impacts -> mouvement de terrain (rebuild case-study page analysis)")
        page_built = _run_with_reuse_fallback(
            [
                str(PYTHON),
                str(REPO_ROOT / "scripts" / "build_guadeloupe_page1_data.py"),
                "--territory",
                territory,
                "--spacing-m",
                str(page_spacing_m),
                "--component-light-spacing-m",
                str(args.page_component_light_spacing_m),
                "--component-light-max-points-total",
                str(args.page_component_light_max_points_total),
                "--component-light-max-points-per-feature",
                str(args.page_component_light_max_points_per_feature),
                "--component-light-dynamic-max-tracks",
                str(args.page_component_light_dynamic_max_tracks),
                "--wind-map-json",
                str(REPO_ROOT / "web" / "data" / f"{territory}-wind-maps.json"),
                "--multi-hazard-proxy-json",
                str(proxy_json),
                "--allow-stale-proxy",
                *(["--prefer-complete-analysis-fallback"] if args.prefer_complete_analysis_page_fallback else []),
                "--case-study-run-id",
                run_id,
            ]
            ,
            env=territory_env,
            reuse_path=page_json,
            label=f"{territory} page-analysis",
            allow_reuse_fallback=bool(args.allow_reuse_fallback),
        )
        if not page_built:
            reused_steps.append(f"{territory}: page-analysis")
            print(
                f"[{territory}] journal skipped because page-analysis artefact was reused after fallback",
                flush=True,
            )
            continue

        _assert_case_study_coherence(territory, run_id)
        record_guamar_run(territory, session_run_id=session_run_id)
    if reused_steps:
        print("[summary] one or more case-study frontend steps reused existing artefacts:", flush=True)
        for step in reused_steps:
            print(f"  - {step}", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
