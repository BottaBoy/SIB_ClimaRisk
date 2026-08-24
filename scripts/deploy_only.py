#!/usr/bin/env python3
"""
Deploy-only script for SIB web results.

Usage:
    python3 deploy_only.py
    python3 deploy_only.py --vhost sib.shared.elio.dev
    python3 deploy_only.py --run-id latest-published --vhost sib.dev.elio.bottagisio.com
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import subprocess
import sys
import time
import tempfile
from pathlib import Path

from case_study_sources import parse_territory
from run_web_artifacts import (
    build_staging_web_dir_from_run,
    load_run_manifest,
    normalized_territories_for_run,
    resolve_publication_run_id,
    validate_territory_web_snapshot,
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

SCRIPTS_ROOT = Path(__file__).resolve().parent
WEB_DIR = SCRIPTS_ROOT.parent / "web"
WEB_DATA_GLOBAL_FILES = {
    "vulnerability-curves-landslide.json",
    "vulnerability-curves-rain.json",
    "vulnerability-curves-surge.json",
    "vulnerability-curves-wind.json",
}
DEPLOY_VERIFY_RELATIVE_PATHS = (
    "index.html",
    "assets/app.js",
    "data/vulnerability-curves-wind.json",
    "data/vulnerability-curves-rain.json",
    "data/vulnerability-curves-surge.json",
    "data/vulnerability-curves-landslide.json",
    "data/guadeloupe-complete-analysis.json",
    "data/martinique-complete-analysis.json",
    "data/saint-barthelemy-complete-analysis.json",
    "data/guadeloupe-scientific-web-summary.json",
    "data/martinique-scientific-web-summary.json",
    "data/saint-barthelemy-scientific-web-summary.json",
    "data/guadeloupe-wind-maps.json",
    "data/martinique-wind-maps.json",
    "data/saint-barthelemy-wind-maps.json",
    "data/guadeloupe-landslide-maps.json",
    "data/martinique-landslide-maps.json",
    "data/saint-barthelemy-landslide-maps.json",
    "data/guadeloupe-multi-hazard-proxy.json",
    "data/martinique-multi-hazard-proxy.json",
    "data/saint-barthelemy-multi-hazard-proxy.json",
    "data/guadeloupe-page1-analysis.json",
    "data/martinique-page2-analysis.json",
    "data/saint-barthelemy-page7-analysis.json",
    "data/guadeloupe-water-infra.geojson",
    "data/martinique-water-infra.geojson",
    "data/saint-barthelemy-water-infra.geojson",
    "data/guadeloupe-network-states.geojson",
    "data/martinique-network-states.geojson",
    "data/saint-barthelemy-network-states.geojson",
    "data/sib-work-methodology.html",
    "assets/methodology/sib-work-summary.png",
    "assets/methodology/methode-sib-work-image-1.png",
    "assets/methodology/methode-sib-work-image-2.png",
    "assets/methodology/methode-sib-work-image-3.png",
)


def resolve_vhost_destination(vhost: str) -> str:
    normalized = str(vhost or "").strip()
    # nginx serves sib.dev from the shared document root
    if normalized == "sib.dev.elio.bottagisio.com":
        return "/var/www/sib.shared.elio.dev/"
    if normalized == "visu.sib.dev.elio.bottagisio.com":
        return "/var/www/visu.sib.dev.elio.bottagisio.com/"
    return f"/var/www/{normalized}/"


def _load_json_object(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return payload


def _infer_graph_pack_territory(graph_pack_dir: Path) -> str:
    archive_dir = graph_pack_dir / "scientific_archive"
    candidates = sorted(archive_dir.glob("*-complete-analysis.json"))
    if len(candidates) != 1:
        raise RuntimeError(
            f"Unable to infer graph-pack territory from {archive_dir}: found {len(candidates)} complete-analysis payloads"
        )
    return candidates[0].name.removesuffix("-complete-analysis.json")


def _parse_graph_pack_spec(raw_spec: str) -> tuple[str | None, Path]:
    raw = str(raw_spec or "").strip()
    if not raw:
        raise ValueError("graph-pack spec must not be empty")
    if "=" in raw:
        territory, path = raw.split("=", 1)
        return parse_territory(territory), Path(path).expanduser().resolve()
    return None, Path(raw).expanduser().resolve()


def _replace_public_legacy_labels(value):
    if isinstance(value, str):
        cleaned = re.sub(r",\s*p99\s+[-+0-9.,\s]+€", "", value, flags=re.IGNORECASE)
        cleaned = cleaned.replace("Public annual/RP50/RP100/P99", "Public RP10/RP50/RP100/RP1000")
        return (
            cleaned
            .replace("P99", "RP1000")
            .replace("p99", "RP1000")
            .replace("percentile 99", "temps de retour 1000 ans")
            .replace("Percentile 99", "Temps de retour 1000 ans")
            .replace("Evenement le plus fort", "Maximum catalogue")
            .replace("Événement le plus fort", "Maximum catalogue")
        )
    if isinstance(value, list):
        return [_replace_public_legacy_labels(item) for item in value]
    if isinstance(value, dict):
        return {key: _replace_public_legacy_labels(item) for key, item in value.items()}
    return value


def sanitize_public_web_data_file(path: Path) -> None:
    if "-page" not in path.name or not path.name.endswith("-analysis.json"):
        return
    try:
        payload = _load_json_object(path)
    except Exception:
        return
    sanitized = _replace_public_legacy_labels(payload)
    path.write_text(json.dumps(sanitized, ensure_ascii=False, indent=2), encoding="utf-8")


def should_copy_web_data_file(territory: str, source_file: Path) -> bool:
    name = source_file.name
    return name.startswith(f"{territory}-") or name in WEB_DATA_GLOBAL_FILES


def copy_external_graph_pack_web_data(source_root: Path, graph_pack_dir: Path, territory: str) -> list[str]:
    web_data_dir = graph_pack_dir / "web_data"
    if not web_data_dir.is_dir():
        return []
    copied: list[str] = []
    target_dir = source_root / "data"
    target_dir.mkdir(parents=True, exist_ok=True)
    for source_file in sorted(web_data_dir.iterdir()):
        if not source_file.is_file() or not should_copy_web_data_file(territory, source_file):
            continue
        target_file = target_dir / source_file.name
        shutil.copy2(source_file, target_file)
        sanitize_public_web_data_file(target_file)
        copied.append(str(target_file.relative_to(source_root)))
    return copied


def apply_external_graph_pack(source_root: Path, raw_spec: str) -> tuple[str, list[str]]:
    requested_territory, graph_pack_dir = _parse_graph_pack_spec(raw_spec)
    if not graph_pack_dir.is_dir():
        raise FileNotFoundError(f"Graph pack directory not found: {graph_pack_dir}")
    territory = requested_territory or _infer_graph_pack_territory(graph_pack_dir)
    archive_dir = graph_pack_dir / "scientific_archive"
    copied: list[str] = []
    copied.extend(copy_external_graph_pack_web_data(source_root, graph_pack_dir, territory))

    archive_sources = {
        f"data/{territory}-complete-analysis.json": archive_dir / f"{territory}-complete-analysis.json",
        f"data/{territory}-scientific-web-summary.json": archive_dir / f"{territory}-scientific-web-summary.json",
    }
    archive_available = all(source_path.is_file() for source_path in archive_sources.values())
    if archive_available:
        for relative_path, source_path in archive_sources.items():
            target_path = source_root / relative_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)
            copied.append(relative_path)
        complete_payload = _load_json_object(archive_sources[f"data/{territory}-complete-analysis.json"])
        scientific_archive_label = str(archive_dir)
        source_mode = "scientific_archive"
    elif requested_territory:
        complete_path = source_root / "data" / f"{territory}-complete-analysis.json"
        summary_path = source_root / "data" / f"{territory}-scientific-web-summary.json"
        if not complete_path.is_file() or not summary_path.is_file():
            raise FileNotFoundError(
                f"[{territory}] graph-only pack requires existing staging JSON files: {complete_path}, {summary_path}"
            )
        complete_payload = _load_json_object(complete_path)
        scientific_archive_label = None
        source_mode = "graphs_only_existing_web_data"
    else:
        raise FileNotFoundError(
            f"[{territory}] required graph-pack scientific_archive missing. "
            "Use TERRITORY=PATH for a graphs-only pack with existing web/data JSON files."
        )

    graph_inputs = complete_payload.get("scientific_graph_inputs") if isinstance(complete_payload.get("scientific_graph_inputs"), dict) else {}
    expected_scenarios = ["rp10", "rp50", "rp100", "rp1000"]
    if graph_inputs.get("scenarios") != expected_scenarios:
        raise RuntimeError(f"[{territory}] graph pack scientific scenarios must equal {expected_scenarios}")
    forbidden = {"annual", "p99", "event_max"}
    observed_forbidden = sorted(
        forbidden.intersection((graph_inputs.get("state_damage_tables") or {}).keys())
        | forbidden.intersection((graph_inputs.get("damage_breakdown_by_scenario") or {}).keys())
    )
    if observed_forbidden:
        raise RuntimeError(f"[{territory}] graph pack contains forbidden public scenarios: {', '.join(observed_forbidden)}")

    graph_asset_root = source_root / "graphs" / territory / graph_pack_dir.name
    for name in ("charts", "maps", "Population", "png", "tables", "Damages_Zones"):
        source_dir = graph_pack_dir / name
        if not source_dir.is_dir():
            continue
        target_dir = graph_asset_root / name
        shutil.copytree(source_dir, target_dir, dirs_exist_ok=True)
        copied.append(str(target_dir.relative_to(source_root)))
    for name in ("index.html", "graphs-manifest.json"):
        source_file = graph_pack_dir / name
        if source_file.is_file():
            target_file = graph_asset_root / name
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target_file)
            copied.append(str(target_file.relative_to(source_root)))

    source_manifest = {
        "territory": territory,
        "graph_pack_dir": str(graph_pack_dir),
        "run_id": graph_pack_dir.name,
        "source_mode": source_mode,
        "scientific_archive": scientific_archive_label,
        "published_graph_assets": str(graph_asset_root.relative_to(source_root)),
        "copied": copied,
    }
    manifest_path = source_root / "data" / f"{territory}-graph-pack-source.json"
    manifest_path.write_text(json.dumps(source_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    copied.append(str(manifest_path.relative_to(source_root)))
    return territory, copied


def verify_deployed_web_root(destination: str, *, source_root: Path = WEB_DIR) -> tuple[bool, list[str]]:
    destination_root = Path(str(destination).rstrip("/"))
    issues: list[str] = []
    for relative_path in DEPLOY_VERIFY_RELATIVE_PATHS:
        source_path = source_root / relative_path
        if not source_path.exists():
            continue
        deployed_path = destination_root / relative_path
        if not deployed_path.exists():
            issues.append(f"missing {deployed_path}")
            continue
        source_stat = source_path.stat()
        deployed_stat = deployed_path.stat()
        if source_stat.st_size != deployed_stat.st_size or source_stat.st_mtime_ns != deployed_stat.st_mtime_ns:
            issues.append(f"out-of-sync {relative_path}")
    return not issues, issues


def deploy_to_vhost(
    vhost: str = "sib.shared.elio.dev",
    *,
    source_root: Path = WEB_DIR,
    source_label: str | None = None,
) -> bool:
    """Deploy to specified vhost."""
    logger.info("=" * 60)
    logger.info(f"SIB Web Deployment")
    logger.info(f"Target: {vhost}")
    logger.info("=" * 60)
    
    deploy_script = SCRIPTS_ROOT / "deploy_shared_web.sh"
    if not deploy_script.exists():
        logger.error(f"Deploy script not found: {deploy_script}")
        return False

    dest_dir = resolve_vhost_destination(vhost)

    logger.info(f"Source: {source_label or source_root}")
    logger.info(f"Destination: {dest_dir}")

    try:
        start = time.time()
        result = subprocess.run(
            [str(deploy_script), str(source_root), dest_dir],
            capture_output=True,
            text=True,
            timeout=300,
        )
        elapsed = time.time() - start

        if result.returncode != 0:
            logger.error("✗ Deployment failed")
            if result.stderr:
                logger.error(f"Error: {result.stderr}")
            return False

        logger.info(f"✓ Deployment successful ({elapsed:.1f}s)")
        verified, issues = verify_deployed_web_root(dest_dir, source_root=source_root)
        if not verified:
            for issue in issues:
                logger.error(f"✗ Deployment verification failed: {issue}")
            return False
        logger.info(f"✓ Verified deployment in {dest_dir}")

        if result.stdout:
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    logger.info(f"  {line}")

        return True

    except subprocess.TimeoutExpired:
        logger.error("✗ Deployment timed out after 300s")
        return False
    except Exception as e:
        logger.error(f"✗ Deployment error: {e}", exc_info=True)
        return False


def validate_source_web_root_for_deploy(
    *,
    source_root: Path,
    run_id: str | None = None,
    territories: list[str] | None = None,
) -> tuple[str, list[str]]:
    resolved_run_id = resolve_publication_run_id(run_id or "latest-published", territories)
    manifest = load_run_manifest(resolved_run_id)
    normalized_territories = normalized_territories_for_run(manifest, territories)
    for territory in normalized_territories:
        validate_territory_web_snapshot(
            resolved_run_id,
            territory,
            source_web_dir=source_root,
        )
    return resolved_run_id, normalized_territories


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Deploy SIB web results to vhost(s)"
    )
    parser.add_argument(
        "--vhost",
        default="sib.shared.elio.dev",
        choices=[
            "sib.shared.elio.dev",
            "sib.dev.elio.bottagisio.com",
            "visu.sib.dev.elio.bottagisio.com",
            "both",
            "all",
        ],
        help="Target vhost (default: sib.shared.elio.dev)"
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help=(
            "Optional run_id from outputs/complete-analysis-runs to stage archived data files before deploy "
            "(or use 'latest' for the newest complete-analysis run, or 'latest-published' for the newest archived publication-safe run)."
        ),
    )
    parser.add_argument(
        "--territories",
        nargs="+",
        default=None,
        help="Optional territory subset to restore from an archived run before deploy (default: all archived territories in the run).",
    )
    parser.add_argument(
        "--graph-pack",
        action="append",
        default=[],
        metavar="[TERRITORY=]PATH",
        help=(
            "Optional external Graphs run directory to overlay into the deployment source. "
            "Use e.g. guadeloupe=/home/ubuntu/uploads/from_popa/20260711_071243."
        ),
    )
    
    args = parser.parse_args()
    try:
        if args.territories is not None:
            args.territories = [parse_territory(value) for value in args.territories]
    except ValueError as exc:
        parser.error(str(exc))
    
    # Determine vhosts
    vhosts = []
    if args.vhost == "both":
        vhosts = ["sib.dev.elio.bottagisio.com", "visu.sib.dev.elio.bottagisio.com"]
    elif args.vhost == "all":
        vhosts = ["sib.shared.elio.dev", "sib.dev.elio.bottagisio.com", "visu.sib.dev.elio.bottagisio.com"]
    else:
        vhosts = [args.vhost]

    seen_destinations = set()
    deduped_vhosts = []
    for vhost in vhosts:
        destination = resolve_vhost_destination(vhost)
        if destination in seen_destinations:
            logger.info(f"Skipping duplicate target {vhost} -> {destination}")
            continue
        seen_destinations.add(destination)
        deduped_vhosts.append(vhost)
    vhosts = deduped_vhosts
    
    # Deploy to each vhost
    all_success = True
    for vhost in vhosts:
        staging_handle = None
        try:
            source_root = WEB_DIR
            source_label = str(WEB_DIR)
            if args.run_id:
                staging_handle, source_root, resolved_run_id, restored = build_staging_web_dir_from_run(
                    args.run_id,
                    args.territories,
                    base_web_dir=WEB_DIR,
                )
                source_label = f"{source_root} (repo web baseline + archived run {resolved_run_id})"
                logger.info(f"Using archived run {resolved_run_id} as deployment source for {vhost}")
                for territory, files in restored.items():
                    logger.info(f"  restored {territory}: {len(files)} archived files")
            if args.graph_pack:
                if staging_handle is None:
                    staging_handle = tempfile.TemporaryDirectory(prefix="sib-deploy-local-web-")
                    source_root = Path(staging_handle.name) / "web"
                    shutil.copytree(WEB_DIR, source_root)
                    source_label = f"{source_root} (repo web baseline + external graph pack)"
                for graph_pack_spec in args.graph_pack:
                    territory, copied = apply_external_graph_pack(source_root, graph_pack_spec)
                    logger.info(
                        f"Applied external graph pack for {territory}: {graph_pack_spec} ({len(copied)} copied paths)"
                    )
            elif not args.run_id:
                validated_run_id, validated_territories = validate_source_web_root_for_deploy(
                    source_root=source_root,
                    territories=args.territories,
                )
                logger.info(
                    f"Validated local web artefacts against latest published run {validated_run_id} "
                    f"for territories: {', '.join(validated_territories)}"
                )

            if not deploy_to_vhost(vhost, source_root=source_root, source_label=source_label):
                all_success = False
        except Exception as exc:
            logger.error(f"✗ Deployment preparation failed for {vhost}: {exc}")
            if args.run_id:
                logger.error(
                    "Run deploy expects archived artefacts. For a legacy run, create them first with snapshot_run_web_artifacts.py."
                )
            all_success = False
        finally:
            if staging_handle is not None:
                staging_handle.cleanup()
        if len(vhosts) > 1:
            logger.info("")  # Blank line between vhosts
    
    logger.info("=" * 60)
    if all_success:
        logger.info("✓ All deployments completed successfully")
        return 0
    else:
        logger.error("✗ One or more deployments failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
