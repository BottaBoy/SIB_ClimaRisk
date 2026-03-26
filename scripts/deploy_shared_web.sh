#!/usr/bin/env bash
set -euo pipefail

SRC_DIR="${1:-/home/ubuntu/sib-work/web/}"
DEST_DIR="${2:-/var/www/sib.shared.elio.dev/}"

sudo mkdir -p "${DEST_DIR}"
sudo rsync -av --delete "${SRC_DIR}" "${DEST_DIR}"
sudo find "${DEST_DIR}" -type d -exec chmod 755 {} +
sudo find "${DEST_DIR}" -type f -exec chmod 644 {} +

echo "Deployment completed: ${SRC_DIR} -> ${DEST_DIR}"
