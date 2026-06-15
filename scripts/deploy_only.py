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
import logging
import subprocess
import sys
import time
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
DEPLOY_VERIFY_RELATIVE_PATHS = (
    "index.html",
    "assets/app.js",
    "data/guadeloupe-complete-analysis.json",
    "data/martinique-complete-analysis.json",
    "data/guadeloupe-wind-maps.json",
    "data/martinique-wind-maps.json",
    "data/guadeloupe-landslide-maps.json",
    "data/martinique-landslide-maps.json",
    "data/guadeloupe-multi-hazard-proxy.json",
    "data/martinique-multi-hazard-proxy.json",
    "data/guadeloupe-page1-analysis.json",
    "data/martinique-page2-analysis.json",
    "data/guadeloupe-water-infra.geojson",
    "data/martinique-water-infra.geojson",
    "data/guadeloupe-network-states.geojson",
    "data/martinique-network-states.geojson",
)


def resolve_vhost_destination(vhost: str) -> str:
    normalized = str(vhost or "").strip()
    # nginx serves sib.dev from the shared document root
    if normalized == "sib.dev.elio.bottagisio.com":
        return "/var/www/sib.shared.elio.dev/"
    return f"/var/www/{normalized}/"


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
        choices=["sib.shared.elio.dev", "sib.dev.elio.bottagisio.com", "both"],
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
    
    args = parser.parse_args()
    try:
        if args.territories is not None:
            args.territories = [parse_territory(value) for value in args.territories]
    except ValueError as exc:
        parser.error(str(exc))
    
    # Determine vhosts
    vhosts = []
    if args.vhost == "both":
        vhosts = ["sib.shared.elio.dev", "sib.dev.elio.bottagisio.com"]
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
            else:
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
