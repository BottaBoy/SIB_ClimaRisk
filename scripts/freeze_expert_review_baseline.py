#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"

import sys

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.risk_engine.expert_review_baseline import (  # noqa: E402
    build_artifact_record,
    build_regression_rows,
    load_json_file,
    sha256_file,
)
from run_web_artifacts import load_run_manifest, resolve_run_id  # noqa: E402


DOCS_DIR = REPO_ROOT / "docs"
EXPERT_REVIEW_DIR = DOCS_DIR / "expert-review"
REFERENCE_RUN_DIR = EXPERT_REVIEW_DIR / "reference-run"
RUN_JOURNAL_MD = DOCS_DIR / "Journalisation_Run_CompleteAnalysis.md"
RUN_JOURNAL_JSONL = DOCS_DIR / "Journalisation_Run_CompleteAnalysis.jsonl"
COPIED_FILES = ("manifest.json", "latest-manifest.json", "Journalisation_Run_CompleteAnalysis.md", "Journalisation_Run_CompleteAnalysis.jsonl")


def _territory_page_filename(territory: str) -> str:
    return f"{territory}-page2-analysis.json" if territory == "martinique" else f"{territory}-page1-analysis.json"


def _copy_if_exists(source: Path, destination: Path) -> bool:
    if not source.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return True


def _relative_repo_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_run_scoped_jsonl(source: Path, destination: Path, run_id: str) -> bool:
    if not source.exists():
        return False
    matched_lines: list[str] = []
    with source.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if payload.get("run_id") == run_id:
                matched_lines.append(stripped)
    if not matched_lines:
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(matched_lines) + "\n", encoding="utf-8")
    return True


def _write_run_scoped_markdown(source: Path, destination: Path, run_id: str) -> bool:
    if not source.exists():
        return False
    lines = source.read_text(encoding="utf-8").splitlines()
    section_starts = [index for index, line in enumerate(lines) if line.startswith("## Run ")]
    selected_section: list[str] | None = None
    for position, start_index in enumerate(section_starts):
        end_index = section_starts[position + 1] if position + 1 < len(section_starts) else len(lines)
        section_lines = lines[start_index:end_index]
        if any(f"`{run_id}`" in line for line in section_lines):
            selected_section = section_lines
            break
    if not selected_section:
        return False
    rendered = [
        "# Journalisation Runs Complete Analysis",
        "",
        f"Extrait filtre pour le run `{run_id}`.",
        "",
        *selected_section,
        "",
    ]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(rendered), encoding="utf-8")
    return True


def _render_markdown_table(rows: list[dict[str, Any]]) -> str:
    headers = [
        "Territory",
        "Hazard",
        "EAI EUR",
        "PML50 EUR",
        "PML100 EUR",
        "Percentile 99 EUR",
        "Wind",
        "Rain",
        "Surge",
        "Landslide",
        "Default Value Count",
        "Scientific Fallback",
        "Publication Fallback",
    ]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        def _fmt(value: Any) -> str:
            if value is None:
                return "n/a"
            if isinstance(value, bool):
                return "yes" if value else "no"
            if isinstance(value, (int, float)):
                return f"{value:.6g}"
            return str(value)

        lines.append(
            "| "
            + " | ".join(
                [
                    _fmt(row.get("territory")),
                    _fmt(row.get("hazard")),
                    _fmt(row.get("eai_eur")),
                    _fmt(row.get("pml_50_eur")),
                    _fmt(row.get("pml_100_eur")),
                    _fmt(row.get("percentile_99_loss_eur", row.get("max_event_loss_eur"))),
                    _fmt(row.get("component_share_wind")),
                    _fmt(row.get("component_share_rain")),
                    _fmt(row.get("component_share_surge")),
                    _fmt(row.get("component_share_landslide")),
                    _fmt(row.get("default_valuation_asset_count")),
                    _fmt(row.get("scientific_fallback_present")),
                    _fmt(row.get("publication_fallback_present")),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def build_reference_snapshot(run_id: str, output_dir: Path) -> dict[str, Any]:
    resolved_run_id = resolve_run_id(run_id)
    manifest = load_run_manifest(resolved_run_id)
    output_dir.mkdir(parents=True, exist_ok=True)

    copied_files: dict[str, str] = {}
    source_manifest = REPO_ROOT / "outputs" / "complete-analysis-runs" / resolved_run_id / "manifest.json"
    copy_pairs = [
        (source_manifest, output_dir / "manifest.json"),
        (source_manifest, output_dir / "latest-manifest.json"),
    ]
    for source, destination in copy_pairs:
        if _copy_if_exists(source, destination):
            copied_files[destination.name] = str(destination)
    if _write_run_scoped_markdown(RUN_JOURNAL_MD, output_dir / RUN_JOURNAL_MD.name, resolved_run_id):
        copied_files[RUN_JOURNAL_MD.name] = str(output_dir / RUN_JOURNAL_MD.name)
    if _write_run_scoped_jsonl(RUN_JOURNAL_JSONL, output_dir / RUN_JOURNAL_JSONL.name, resolved_run_id):
        copied_files[RUN_JOURNAL_JSONL.name] = str(output_dir / RUN_JOURNAL_JSONL.name)

    artifact_index: dict[str, Any] = {
        "run_id": resolved_run_id,
        "snapshot_dir": str(output_dir),
        "copied_files": [
            build_artifact_record(output_dir / name, label=name, required=name in COPIED_FILES)
            for name in COPIED_FILES
        ],
        "territories": {},
        "notes": [
            "Run-scoped web artefacts remain archived under outputs/complete-analysis-runs/<run_id>/territories/<territory>/web/.",
            "CSV exports are not archived by the current complete-analysis run workflow; this baseline records that gap explicitly.",
            "Journalisation_Run_CompleteAnalysis.* files are filtered extracts for the selected run_id, generated from the global run journal.",
        ],
    }

    regression_rows: list[dict[str, Any]] = []
    manifest_territories = manifest.get("territories") if isinstance(manifest.get("territories"), dict) else {}

    for territory in sorted(str(key) for key in manifest_territories.keys()):
        territory_entry = manifest_territories[territory]
        territory_dir = REPO_ROOT / "outputs" / "complete-analysis-runs" / resolved_run_id / "territories" / territory / "web" / "data"
        complete_path = territory_dir / f"{territory}-complete-analysis.json"
        proxy_path = territory_dir / f"{territory}-multi-hazard-proxy.json"
        page_path = territory_dir / _territory_page_filename(territory)
        wind_path = territory_dir / f"{territory}-wind-maps.json"
        network_path = territory_dir / f"{territory}-network-states.geojson"
        landslide_path = territory_dir / f"{territory}-landslide-maps.json"

        complete_payload = load_json_file(complete_path)
        proxy_payload = load_json_file(proxy_path) if proxy_path.exists() else None
        page_payload = load_json_file(page_path) if page_path.exists() else None
        regression_rows.extend(
            build_regression_rows(
                territory=territory,
                manifest_entry=territory_entry,
                complete_payload=complete_payload,
                proxy_payload=proxy_payload,
                page_payload=page_payload,
            )
        )

        artifact_index["territories"][territory] = {
            "archived_complete_analysis": build_artifact_record(complete_path, label="complete-analysis"),
            "archived_web_artifacts": [
                build_artifact_record(wind_path, label="wind-maps"),
                build_artifact_record(proxy_path, label="multi-hazard-proxy"),
                build_artifact_record(page_path, label="page-analysis"),
                build_artifact_record(network_path, label="network-states"),
                build_artifact_record(landslide_path, label="landslide-maps", required=False),
            ],
            "csv_exports": [],
        }

    _write_json(output_dir / "artifact-index.json", artifact_index)
    _write_json(output_dir / "regression-matrix.json", regression_rows)
    (output_dir / "regression-matrix.md").write_text(_render_markdown_table(regression_rows), encoding="utf-8")

    readme_lines = [
        "# Frozen Reference Run (Expert Review Baseline)",
        "",
        f"Run ID: **{resolved_run_id}**",
        "",
        "This folder freezes the baseline bookkeeping for Lot A without duplicating the large archived web payloads.",
        "",
        "Included files:",
    ]
    for copied_name in sorted(copied_files.keys()):
        readme_lines.append(f"- `{copied_name}`")
    readme_lines.extend(
        [
            "- `artifact-index.json` (archived artefact locations + SHA256 + size)",
            "- `regression-matrix.json` (machine-readable baseline matrix)",
            "- `regression-matrix.md` (compact reviewer-facing matrix)",
            "",
            "Archived run payloads tracked by checksum remain in:",
            f"- `{_relative_repo_path(REPO_ROOT / 'outputs' / 'complete-analysis-runs' / resolved_run_id)}`",
            "",
            "Quick check:",
            "```bash",
            f"cd {output_dir}",
            "cat regression-matrix.md",
            "```",
        ]
    )
    (output_dir / "README.md").write_text("\n".join(readme_lines) + "\n", encoding="utf-8")

    sha_lines = []
    for name in sorted(["README.md", "artifact-index.json", "regression-matrix.json", "regression-matrix.md", *copied_files.keys()]):
        path = output_dir / name
        if path.exists():
            sha_lines.append(f"{sha256_file(path)}  {name}")
    (output_dir / "SHA256SUMS").write_text("\n".join(sha_lines) + "\n", encoding="utf-8")

    return {
        "run_id": resolved_run_id,
        "output_dir": str(output_dir),
        "regression_rows": len(regression_rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Freeze an expert-review baseline for a complete-analysis run.")
    parser.add_argument("--run-id", default="latest", help="Run ID or 'latest'.")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Optional override for the snapshot directory. Defaults to docs/expert-review/reference-run/<run_id>.",
    )
    args = parser.parse_args()

    resolved_run_id = resolve_run_id(args.run_id)
    output_dir = Path(args.output_dir) if args.output_dir else REFERENCE_RUN_DIR / resolved_run_id
    summary = build_reference_snapshot(resolved_run_id, output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())