#!/usr/bin/env python3
"""
Deploy-only script for SIB web results.

Usage:
    python3 deploy_only.py
    python3 deploy_only.py --vhost sib.shared.elio.dev
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

SCRIPTS_ROOT = Path(__file__).resolve().parent
WEB_DIR = SCRIPTS_ROOT.parent / "web"


def resolve_vhost_destination(vhost: str) -> str:
    normalized = str(vhost or "").strip()
    # nginx serves sib.dev from the shared document root
    if normalized == "sib.dev.elio.bottagisio.com":
        return "/var/www/sib.shared.elio.dev/"
    return f"/var/www/{normalized}/"


def deploy_to_vhost(vhost: str = "sib.shared.elio.dev") -> bool:
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
    
    logger.info(f"Source: {WEB_DIR}")
    logger.info(f"Destination: {dest_dir}")
    
    try:
        start = time.time()
        result = subprocess.run(
            [str(deploy_script), str(WEB_DIR), dest_dir],
            capture_output=True,
            text=True,
            timeout=300,
        )
        elapsed = time.time() - start
        
        if result.returncode != 0:
            logger.error(f"✗ Deployment failed")
            if result.stderr:
                logger.error(f"Error: {result.stderr}")
            return False
        
        logger.info(f"✓ Deployment successful ({elapsed:.1f}s)")
        
        # Show output
        if result.stdout:
            for line in result.stdout.strip().split('\n'):
                if line.strip():
                    logger.info(f"  {line}")
        
        return True
    
    except subprocess.TimeoutExpired:
        logger.error(f"✗ Deployment timed out after 300s")
        return False
    except Exception as e:
        logger.error(f"✗ Deployment error: {e}", exc_info=True)
        return False


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
    
    args = parser.parse_args()
    
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
        if not deploy_to_vhost(vhost):
            all_success = False
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
