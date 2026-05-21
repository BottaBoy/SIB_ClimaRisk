#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from frontend_supervision import (
    frontend_supervision_journal_from_env,
    frontend_supervision_run_id_from_env,
    write_frontend_supervision_event,
)
from journal_guamar_run import record_guamar_run


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.config import load_settings, resolve_surge_topo_path_for_territory

PYTHON = REPO_ROOT / "backend" / ".venv" / "bin" / "python"
UTC = timezone.utc
TERRITORY_PAGE_SPACING_M = {
    "guadeloupe": 100.0,
    "martinique": 150.0,
}


def _normalized_subprocess_returncode(returncode: int) -> int:
    code = int(returncode)
    if code >= 0:
        return code
    return 128 + abs(code)


def _run(
    cmd: list[str],
    *,
    env: dict[str, str] | None = None,
    journal_path: Path | None = None,
    territory: str | None = None,
    step: str | None = None,
) -> None:
    step_name = str(step or (Path(cmd[1]).stem if len(cmd) > 1 else "subprocess"))
    write_frontend_supervision_event(
        journal_path,
        actor="child",
        event="step_started",
        territory=territory,
        step=step_name,
        command=" ".join(str(part) for part in cmd),
    )
    print("+", " ".join(cmd), flush=True)
    try:
        subprocess.run(cmd, check=True, env=env)
    except subprocess.CalledProcessError as exc:
        write_frontend_supervision_event(
            journal_path,
            actor="child",
            event="step_failed",
            territory=territory,
            step=step_name,
            returncode_raw=int(exc.returncode),
            returncode_normalized=_normalized_subprocess_returncode(int(exc.returncode)),
        )
        raise
    write_frontend_supervision_event(
        journal_path,
        actor="child",
        event="step_completed",
        territory=territory,
        step=step_name,
        returncode_raw=0,
        returncode_normalized=0,
    )


def _info(message: str) -> None:
    print(f"[INFO] {message}", flush=True)


def _normalize_called_process_exit_code(exc: subprocess.CalledProcessError) -> int:
    raw_code = int(exc.returncode)
    code = _normalized_subprocess_returncode(raw_code)
    if raw_code >= 0:
        return raw_code
    signal_number = abs(raw_code)
    cmd = exc.cmd if isinstance(exc.cmd, (list, tuple)) else [str(exc.cmd)]
    print(
        f"[fatal] child process terminated by signal {signal_number}: {' '.join(str(part) for part in cmd)}",
        file=sys.stderr,
        flush=True,
    )
    return code


def _python_supports_gdal_array(python_path: Path) -> bool:
    if not python_path.exists():
        return False
    try:
        result = subprocess.run(
            [
                str(python_path),
                "-c",
                "from osgeo import gdal, gdal_array; print(gdal.VersionInfo())",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except Exception:
        return False
    return result.returncode == 0


def _resolve_landslide_python() -> Path:
    candidates: list[Path] = [PYTHON, Path(sys.executable), Path("/usr/bin/python3")]
    discovered_python3 = shutil.which("python3")
    if discovered_python3:
        candidates.append(Path(discovered_python3))

    seen: set[str] = set()
    for candidate in candidates:
        candidate_key = str(candidate)
        if candidate_key in seen:
            continue
        seen.add(candidate_key)
        if _python_supports_gdal_array(candidate):
            return candidate

    raise RuntimeError(
        "No Python interpreter with working osgeo.gdal/gdal_array bindings is available for landslide rebuilds"
    )


def _page_spacing_for_territory(territory: str, requested_spacing_m: float | None) -> float:
    if requested_spacing_m is not None:
        return float(requested_spacing_m)
    return float(TERRITORY_PAGE_SPACING_M.get(str(territory).strip().lower(), 100.0))


def _assert_supported_page_component_light_config(
    *,
    territory: str,
    page_spacing_m: float,
    component_light_spacing_m: float,
    component_light_max_points_total: int,
    component_light_max_points_per_feature: int,
    component_light_dynamic_max_tracks: int,
    settings: object,
    env: dict[str, str] | None = None,
) -> None:
    runtime_env = os.environ if env is None else env
    unsupported: list[str] = []
    if float(component_light_spacing_m) != float(page_spacing_m):
        unsupported.append(
            f"spacing_m={component_light_spacing_m} differs from page spacing {page_spacing_m}"
        )

    if int(component_light_max_points_total) > 0:
        unsupported.append(
            "max_points_total is unsupported because page-analysis must preserve complete per-feature state coverage"
        )

    configured_max_points_per_feature = int(
        runtime_env.get(
            "SIB_RISK_CLIMADA_MAX_POINTS_PER_FEATURE",
            getattr(settings, "climada_max_points_per_feature"),
        )
    )
    if int(component_light_max_points_per_feature) != configured_max_points_per_feature:
        unsupported.append(
            f"max_points_per_feature={component_light_max_points_per_feature} differs from configured {configured_max_points_per_feature}"
        )

    configured_dynamic_max_tracks = int(
        runtime_env.get(
            "SIB_RISK_HAZARD_DYNAMIC_MAX_TRACKS",
            getattr(settings, "hazard_dynamic_max_tracks"),
        )
    )
    if int(component_light_dynamic_max_tracks) != configured_dynamic_max_tracks:
        unsupported.append(
            f"dynamic_max_tracks={component_light_dynamic_max_tracks} differs from configured {configured_dynamic_max_tracks}"
        )

    if not unsupported:
        return

    details = "; ".join(unsupported)
    raise RuntimeError(
        f"[{territory}] unsupported page component-light configuration: {details}. "
        "Explicit failure enforced because no fallback or partial-coverage page-analysis mode is allowed."
    )


def _case_study_output_paths(territory: str) -> tuple[Path, Path, Path, Path, Path]:
    page_suffix = "page2" if territory == "martinique" else "page1"
    data_root = REPO_ROOT / "web" / "data"
    return (
        data_root / f"{territory}-wind-maps.json",
        data_root / f"{territory}-landslide-maps.json",
        data_root / f"{territory}-multi-hazard-proxy.json",
        data_root / f"{territory}-{page_suffix}-analysis.json",
        data_root / f"{territory}-network-states.geojson",
    )


def _purge_case_study_outputs(territory: str) -> None:
    removed: list[str] = []
    for path in _case_study_output_paths(territory):
        if not path.exists():
            continue
        path.unlink()
        removed.append(path.name)
    if removed:
        _info(f"[{territory}] removed stale artefacts before rebuild: {', '.join(removed)}")


def _build_territory_env(territory: str, *, base_settings: object) -> dict[str, str]:
    territory_env = os.environ.copy()
    territory_env.setdefault("SIB_RISK_CLIMADA_MAX_POINTS_PER_FEATURE", "120")
    territory_env["SIB_RISK_HAZARD_SURGE_TOPO_PATH"] = str(
        resolve_surge_topo_path_for_territory(
            territory,
            settings=base_settings,
            env=territory_env,
        )
    )
    return territory_env


def _resolve_page_component_light_config(
    *,
    page_spacing_m: float,
    component_light_spacing_m: float | None,
    component_light_max_points_total: int | None,
    component_light_max_points_per_feature: int | None,
    component_light_dynamic_max_tracks: int | None,
    settings: object,
    env: dict[str, str],
) -> dict[str, int | float]:
    configured_max_points_per_feature = int(
        env.get(
            "SIB_RISK_CLIMADA_MAX_POINTS_PER_FEATURE",
            getattr(settings, "climada_max_points_per_feature"),
        )
    )
    configured_dynamic_max_tracks = int(
        env.get(
            "SIB_RISK_HAZARD_DYNAMIC_MAX_TRACKS",
            getattr(settings, "hazard_dynamic_max_tracks"),
        )
    )
    return {
        "spacing_m": float(page_spacing_m if component_light_spacing_m is None else component_light_spacing_m),
        "max_points_total": int(0 if component_light_max_points_total is None else component_light_max_points_total),
        "max_points_per_feature": int(
            configured_max_points_per_feature
            if component_light_max_points_per_feature is None
            else component_light_max_points_per_feature
        ),
        "dynamic_max_tracks": int(
            configured_dynamic_max_tracks
            if component_light_dynamic_max_tracks is None
            else component_light_dynamic_max_tracks
        ),
    }


def _read_meta(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    meta = payload.get("meta") if isinstance(payload, dict) else None
    return meta if isinstance(meta, dict) else {}


def _assert_case_study_coherence(territory: str, run_id: str) -> None:
    wind_map_path = REPO_ROOT / "web" / "data" / f"{territory}-wind-maps.json"
    landslide_path = REPO_ROOT / "web" / "data" / f"{territory}-landslide-maps.json"
    proxy_path = REPO_ROOT / "web" / "data" / f"{territory}-multi-hazard-proxy.json"
    page_suffix = "page2" if territory == "martinique" else "page1"
    page_path = REPO_ROOT / "web" / "data" / f"{territory}-{page_suffix}-analysis.json"

    wind_meta = _read_meta(wind_map_path)
    landslide_meta = _read_meta(landslide_path)
    proxy_meta = _read_meta(proxy_path)
    page_meta = _read_meta(page_path)

    observed = {
        "wind-maps": str(wind_meta.get("case_study_run_id") or ""),
        "landslide-maps": str(landslide_meta.get("case_study_run_id") or ""),
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
        f"(wind={wind_meta.get('generated_at')}, landslide={landslide_meta.get('generated_at')}, proxy={proxy_meta.get('generated_at')}, page={page_meta.get('generated_at')})",
        flush=True,
    )


def main(*, journal_path: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a lighter, more robust case-study rerun for Guadeloupe/Martinique.")
    parser.add_argument("--territories", nargs="+", choices=["guadeloupe", "martinique"], default=["guadeloupe", "martinique"])
    parser.add_argument("--proxy-spacing-m", type=float, default=800.0)
    parser.add_argument("--proxy-max-points-total", type=int, default=800)
    parser.add_argument("--proxy-max-points-per-feature", type=int, default=8)
    parser.add_argument("--proxy-dynamic-max-tracks", type=int, default=100)
    parser.add_argument(
        "--page-spacing-m",
        type=float,
        default=None,
        help="Page-analysis spacing in meters. Defaults to 100 for Guadeloupe and 150 for Martinique.",
    )
    parser.add_argument(
        "--page-component-light-spacing-m",
        type=float,
        default=None,
        help="Spacing in meters for the lighter component rerun used inside page-analysis rebuilds.",
    )
    parser.add_argument(
        "--page-component-light-max-points-total",
        type=int,
        default=None,
        help="Maximum total sampled points for the lighter component rerun used inside page-analysis rebuilds.",
    )
    parser.add_argument(
        "--page-component-light-max-points-per-feature",
        type=int,
        default=None,
        help="Maximum sampled points per feature for the lighter component rerun used inside page-analysis rebuilds.",
    )
    parser.add_argument(
        "--page-component-light-dynamic-max-tracks",
        type=int,
        default=None,
        help="Maximum dynamic tracks for the lighter component rerun used inside page-analysis rebuilds.",
    )
    parser.add_argument("--map-cell-deg", type=float, default=0.02)
    parser.add_argument("--map-dynamic-max-tracks", type=int, default=300)
    parser.add_argument("--map-surge-native-cell-deg", type=float, default=0.01)
    args = parser.parse_args()

    if not PYTHON.exists():
        raise FileNotFoundError(f"Python backend venv not found: {PYTHON}")

    landslide_python = _resolve_landslide_python()
    if landslide_python != PYTHON:
        _info(
            f"Using GDAL-capable interpreter {landslide_python} for landslide maps "
            f"because {PYTHON} lacks working GDAL bindings"
        )

    base_settings = load_settings()
    session_run_id = datetime.now(UTC).strftime("guamar_session_%Y%m%dT%H%M%SZ")
    print(f"[session] run_id={session_run_id}", flush=True)
    write_frontend_supervision_event(
        journal_path,
        actor="child",
        event="child_started",
        pid=os.getpid(),
        session_run_id=session_run_id,
        complete_analysis_run_id=frontend_supervision_run_id_from_env(),
        territories=list(args.territories),
    )

    for territory in args.territories:
        run_id = datetime.now(UTC).strftime(f"{territory}_case_%Y%m%dT%H%M%SZ")
        proxy_json = REPO_ROOT / "web" / "data" / f"{territory}-multi-hazard-proxy.json"
        page_suffix = "page2" if territory == "martinique" else "page1"
        page_json = REPO_ROOT / "web" / "data" / f"{territory}-{page_suffix}-analysis.json"
        page_spacing_m = _page_spacing_for_territory(territory, args.page_spacing_m)
        territory_env = _build_territory_env(territory, base_settings=base_settings)
        component_light_config = _resolve_page_component_light_config(
            page_spacing_m=page_spacing_m,
            component_light_spacing_m=args.page_component_light_spacing_m,
            component_light_max_points_total=args.page_component_light_max_points_total,
            component_light_max_points_per_feature=args.page_component_light_max_points_per_feature,
            component_light_dynamic_max_tracks=args.page_component_light_dynamic_max_tracks,
            settings=base_settings,
            env=territory_env,
        )
        _assert_supported_page_component_light_config(
            territory=territory,
            page_spacing_m=page_spacing_m,
            component_light_spacing_m=float(component_light_config["spacing_m"]),
            component_light_max_points_total=int(component_light_config["max_points_total"]),
            component_light_max_points_per_feature=int(component_light_config["max_points_per_feature"]),
            component_light_dynamic_max_tracks=int(component_light_config["dynamic_max_tracks"]),
            settings=base_settings,
            env=territory_env,
        )
        write_frontend_supervision_event(
            journal_path,
            actor="child",
            event="territory_started",
            territory=territory,
            case_study_run_id=run_id,
            proxy_json=str(proxy_json),
            page_json=str(page_json),
        )
        _purge_case_study_outputs(territory)

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
            journal_path=journal_path,
            territory=territory,
            step="build_wind_maps",
        )
        _run(
            [
                str(landslide_python),
                str(REPO_ROOT / "scripts" / "build_case_study_landslide_maps.py"),
                "--territories",
                territory,
                "--web-data-dir",
                str(REPO_ROOT / "web" / "data"),
            ],
            env=territory_env,
            journal_path=journal_path,
            territory=territory,
            step="build_landslide_maps",
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
            ,
            env=territory_env,
            journal_path=journal_path,
            territory=territory,
            step="build_multi_hazard_proxy",
        )
        _info(f"[{territory}] impacts -> mouvement de terrain (rebuild case-study page analysis)")
        _run(
            [
                str(PYTHON),
                str(REPO_ROOT / "scripts" / "build_guadeloupe_page1_data.py"),
                "--territory",
                territory,
                "--spacing-m",
                str(page_spacing_m),
                "--component-light-spacing-m",
                str(component_light_config["spacing_m"]),
                "--component-light-max-points-total",
                str(component_light_config["max_points_total"]),
                "--component-light-max-points-per-feature",
                str(component_light_config["max_points_per_feature"]),
                "--component-light-dynamic-max-tracks",
                str(component_light_config["dynamic_max_tracks"]),
                "--wind-map-json",
                str(REPO_ROOT / "web" / "data" / f"{territory}-wind-maps.json"),
                "--multi-hazard-proxy-json",
                str(proxy_json),
                "--case-study-run-id",
                run_id,
            ]
            ,
            env=territory_env,
            journal_path=journal_path,
            territory=territory,
            step="build_page_analysis",
        )

        write_frontend_supervision_event(
            journal_path,
            actor="child",
            event="coherence_check_started",
            territory=territory,
            case_study_run_id=run_id,
        )
        _assert_case_study_coherence(territory, run_id)
        write_frontend_supervision_event(
            journal_path,
            actor="child",
            event="coherence_check_completed",
            territory=territory,
            case_study_run_id=run_id,
        )
        record_guamar_run(territory, session_run_id=session_run_id)
        write_frontend_supervision_event(
            journal_path,
            actor="child",
            event="territory_completed",
            territory=territory,
            case_study_run_id=run_id,
        )
    write_frontend_supervision_event(
        journal_path,
        actor="child",
        event="child_completed",
        pid=os.getpid(),
        session_run_id=session_run_id,
        complete_analysis_run_id=frontend_supervision_run_id_from_env(),
        territories=list(args.territories),
    )
    return 0


if __name__ == "__main__":
    journal_path = frontend_supervision_journal_from_env()
    try:
        sys.exit(main(journal_path=journal_path))
    except subprocess.CalledProcessError as exc:
        normalized_code = _normalize_called_process_exit_code(exc)
        write_frontend_supervision_event(
            journal_path,
            actor="child",
            event="child_failed",
            reason="called_process_error",
            returncode_raw=int(exc.returncode),
            returncode_normalized=int(normalized_code),
        )
        sys.exit(normalized_code)
    except Exception as exc:
        write_frontend_supervision_event(
            journal_path,
            actor="child",
            event="child_failed",
            reason="unhandled_exception",
            error=str(exc),
        )
        raise
