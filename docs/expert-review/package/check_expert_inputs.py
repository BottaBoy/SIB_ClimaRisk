#!/usr/bin/env python3
"""Preflight checks for expert-review data and script prerequisites."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
from typing import Iterable


@dataclass(frozen=True)
class CheckItem:
    name: str
    path: Path
    expected: str  # file, dir, file_or_dir
    required: bool
    reason: str


def _human_size(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(max(0, num_bytes))
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            return f"{size:.1f}{unit}"
        size /= 1024.0
    return f"{num_bytes}B"


def _path_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return int(path.stat().st_size)
        except OSError:
            return 0
    total = 0
    try:
        for child in path.rglob("*"):
            if child.is_file():
                try:
                    total += int(child.stat().st_size)
                except OSError:
                    continue
    except OSError:
        return 0
    return total


def _is_non_empty_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    try:
        next(path.iterdir())
        return True
    except StopIteration:
        return False
    except OSError:
        return False


def _check_path(item: CheckItem) -> tuple[bool, str]:
    p = item.path
    if not p.exists():
        return False, "missing"

    if item.expected == "file":
        if not p.is_file():
            return False, "exists but not a file"
    elif item.expected == "dir":
        if not p.is_dir():
            return False, "exists but not a directory"
        if not _is_non_empty_dir(p):
            return False, "directory is empty"
    elif item.expected == "file_or_dir":
        if p.is_dir() and not _is_non_empty_dir(p):
            return False, "directory is empty"
    else:
        return False, f"invalid expected type: {item.expected}"

    size = _human_size(_path_size(p))
    return True, f"ok ({size})"


def _build_checks(repo_root: Path, uploads_root: Path) -> tuple[list[CheckItem], list[CheckItem]]:
    env = os.environ

    required = [
        CheckItem(
            "STORM dynamic dataset",
            Path(env.get("SIB_RISK_STORM_PARQUET_PATH", str(uploads_root / "STORM" / "storm_ds"))),
            "file_or_dir",
            True,
            "Default dynamic STORM source used by hazard loader",
        ),
        CheckItem(
            "STORM_CMCC dynamic dataset",
            Path(env.get("SIB_RISK_STORM_CMCC_PARQUET_PATH", str(uploads_root / "STORM" / "storm_ds_CMCC"))),
            "file_or_dir",
            True,
            "Default dynamic STORM_CMCC source",
        ),
        CheckItem(
            "Surge DEM (Antilles)",
            Path(
                env.get(
                    "SIB_RISK_HAZARD_SURGE_TOPO_PATH",
                    str(
                        uploads_root
                        / "DEM_Topo"
                        / "MNT_FACADE_ANTS_HOMONIM_PBMA"
                        / "DONNEES"
                        / "MNT_ANTS100m_HOMONIM_WGS84_PBMA_ZNEG.asc"
                    ),
                )
            ),
            "file",
            True,
            "Required by surge component",
        ),
        CheckItem(
            "D2 vulnerability workbook",
            Path(
                env.get(
                    "SIB_RISK_D2_FLOOD_CURVE_FILE",
                    str(uploads_root / "Vulnerability" / "Table_D2_Hazard_Fragility_and_Vulnerability_Curves_V1.1.0.xlsx"),
                )
            ),
            "file",
            True,
            "Required for rain/surge vulnerability mapping",
        ),
        CheckItem(
            "Infra Elec Guadeloupe",
            Path(env.get("SIB_EXPERT_INFRA_ELEC_GUA_DIR", str(uploads_root / "Infra_Elec_Guadeloupe"))),
            "dir",
            True,
            "Electricity exposures for Guadeloupe complete run",
        ),
        CheckItem(
            "Infra Elec Martinique",
            Path(env.get("SIB_EXPERT_INFRA_ELEC_MTQ_DIR", str(uploads_root / "Infra_Elec_Martinique"))),
            "dir",
            True,
            "Electricity exposures for Martinique complete run",
        ),
        CheckItem(
            "Infra Eau Guadeloupe",
            Path(env.get("SIB_EXPERT_INFRA_EAU_GUA_DIR", str(uploads_root / "Infra_Eau_Guadeloupe"))),
            "dir",
            True,
            "Water exposures for Guadeloupe complete run",
        ),
        CheckItem(
            "Infra Eau Martinique",
            Path(env.get("SIB_EXPERT_INFRA_EAU_MTQ_DIR", str(uploads_root / "Infra_Eau_Martinique"))),
            "dir",
            True,
            "Water exposures for Martinique complete run",
        ),
    ]

    optional = [
        CheckItem(
            "Fallback hazard GUA STORM",
            Path(env.get("SIB_RISK_HAZARD_STORM_PATH", str(repo_root / "data" / "hazards" / "tc_hazard_guadeloupe.h5"))),
            "file",
            False,
            "Fallback path if dynamic hazard loading is unavailable",
        ),
        CheckItem(
            "Fallback hazard GUA STORM_CMCC",
            Path(
                env.get(
                    "SIB_RISK_HAZARD_STORM_CMCC_PATH",
                    str(repo_root / "data" / "hazards" / "tc_hazard_guadeloupe_CMCC.h5"),
                )
            ),
            "file",
            False,
            "Fallback path if dynamic hazard loading is unavailable",
        ),
        CheckItem(
            "Fallback hazard MTQ STORM",
            repo_root / "data" / "hazards" / "tc_hazard_martinique.h5",
            "file",
            False,
            "Recommended to validate Martinique fallback reproducibility",
        ),
        CheckItem(
            "Fallback hazard MTQ STORM_CMCC",
            repo_root / "data" / "hazards" / "tc_hazard_martinique_CMCC.h5",
            "file",
            False,
            "Recommended to validate Martinique fallback reproducibility",
        ),
        CheckItem(
            "Population raster GLP",
            Path(env.get("SIB_RISK_POPULATION_DATA_DIR", str(uploads_root / "Population"))) / "glp_pop_2020_CN_100m_R2025A_v1.tif",
            "file",
            False,
            "Enables social impact metrics in Guadeloupe cells",
        ),
        CheckItem(
            "Population raster MTQ",
            Path(env.get("SIB_RISK_POPULATION_DATA_DIR", str(uploads_root / "Population"))) / "mtq_pop_2020_CN_100m_R2025A_v1.tif",
            "file",
            False,
            "Enables social impact metrics in Martinique cells",
        ),
        CheckItem(
            "Landslide raster current climate",
            Path(env.get("SIB_RISK_LANDSLIDE_ROOT", str(uploads_root / "Landslide"))) / "LS_GuaMar_Precipitation_ClimatActuel.tif",
            "file",
            False,
            "Supports landslide/rainfall scenario checks",
        ),
        CheckItem(
            "Landslide raster SSP585",
            Path(env.get("SIB_RISK_LANDSLIDE_ROOT", str(uploads_root / "Landslide"))) / "LS_GuaMar_Precipitation_ClimatSSP585.tif",
            "file",
            False,
            "Supports landslide climate scenario checks",
        ),
        CheckItem(
            "Landslide raster earthquake",
            Path(env.get("SIB_RISK_LANDSLIDE_ROOT", str(uploads_root / "Landslide"))) / "LS_GuaMar_Eathquake.tif",
            "file",
            False,
            "Supports landslide earthquake scenario checks",
        ),
        CheckItem(
            "Admin mask geojson",
            Path(
                env.get(
                    "SIB_EXPERT_ADMIN_MASK_PATH",
                    str(uploads_root / "DEM_Topo" / "Limites Pays" / "geoBoundariesCGAZ_ADM0.geojson"),
                )
            ),
            "file",
            False,
            "Recommended for boundary/mask reproducibility",
        ),
    ]

    return required, optional


def _print_results(title: str, items: Iterable[CheckItem], required_failures: list[str], optional_missing: list[str]) -> None:
    print(f"\n[{title}]")
    for item in items:
        ok, detail = _check_path(item)
        status = "OK" if ok else ("FAIL" if item.required else "WARN")
        print(f"- {status:4} {item.name}: {item.path} ({detail})")
        if not ok and item.required:
            required_failures.append(item.name)
        elif not ok and not item.required:
            optional_missing.append(item.name)


def _settings_probe(repo_root: Path) -> tuple[bool, str]:
    cmd = [
        sys.executable,
        "-c",
        (
            "import json,sys;"
            f"sys.path.insert(0,{json.dumps(str(repo_root / 'backend'))});"
            "from app.config import load_settings;"
            "s=load_settings();"
            "print(json.dumps({"
            "'storm_parquet_path': str(s.storm_parquet_path),"
            "'storm_cmcc_parquet_path': str(s.storm_cmcc_parquet_path),"
            "'hazard_surge_topo_path': str(s.hazard_surge_topo_path),"
            "'d2_flood_curve_file': str(s.d2_flood_curve_file)"
            "}))"
        ),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except Exception as exc:
        return False, f"settings probe failed to run: {exc}"

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        return False, f"settings probe returned {proc.returncode}: {stderr}"

    try:
        payload = json.loads(proc.stdout.strip() or "{}")
    except json.JSONDecodeError:
        return False, "settings probe output is not valid JSON"

    missing = []
    for key, raw_path in payload.items():
        p = Path(str(raw_path))
        if not p.exists():
            missing.append(f"{key} -> {p}")

    if missing:
        return False, "settings resolve to missing paths: " + "; ".join(missing)
    return True, "settings paths resolve to existing files"


def main() -> int:
    parser = argparse.ArgumentParser(description="Check required data/scripts for expert reruns")
    parser.add_argument("--mode", choices=["minimal", "full"], default="minimal")
    parser.add_argument(
        "--uploads-root",
        default=None,
        help="Override uploads root (default: $SIB_EXPERT_UPLOADS_ROOT or <repo>/../uploads)",
    )
    args = parser.parse_args()

    script_path = Path(__file__).resolve()
    repo_root = script_path.parents[3]
    uploads_root = Path(
        args.uploads_root
        or os.environ.get("SIB_EXPERT_UPLOADS_ROOT")
        or (repo_root / ".." / "uploads")
    ).resolve()

    print(f"[info] mode={args.mode}")
    print(f"[info] repo_root={repo_root}")
    print(f"[info] uploads_root={uploads_root}")

    required, optional = _build_checks(repo_root=repo_root, uploads_root=uploads_root)

    required_failures: list[str] = []
    optional_missing: list[str] = []

    _print_results("required", required, required_failures, optional_missing)
    _print_results("optional_recommended", optional, required_failures, optional_missing)

    if args.mode == "full":
        script_checks = [
            CheckItem(
                "Backend sample script",
                repo_root / "backend" / "scripts" / "run_backoffice_sample.py",
                "file",
                True,
                "Required for smoke run",
            ),
            CheckItem(
                "Complete analysis runner",
                repo_root / "scripts" / "run_complete_analysis.py",
                "file",
                True,
                "Required for full non-deploy rerun",
            ),
            CheckItem(
                "Expert smoke runner",
                repo_root / "docs" / "expert-review" / "package" / "run_expert_smoke.sh",
                "file",
                True,
                "Package integrity",
            ),
        ]
        _print_results("full_mode_scripts", script_checks, required_failures, optional_missing)

        ok, detail = _settings_probe(repo_root)
        tag = "OK" if ok else "WARN"
        print(f"\n[settings_probe] {tag}: {detail}")

    if required_failures:
        print("\n[result] FAIL")
        print("[result] missing required items: " + ", ".join(sorted(set(required_failures))))
        if optional_missing:
            print("[result] optional missing: " + ", ".join(sorted(set(optional_missing))))
        return 1

    print("\n[result] PASS")
    if optional_missing:
        print("[result] optional missing (non-blocking): " + ", ".join(sorted(set(optional_missing))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
