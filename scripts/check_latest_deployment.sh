#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="/home/ubuntu/sib-work"
NGINX_SITE="/etc/nginx/sites-enabled/sib.dev.elio.bottagisio.com"

LOCAL_FILES=(
  "web/data/guadeloupe-complete-analysis.json"
  "web/data/martinique-complete-analysis.json"
  "web/data/guadeloupe-page1-analysis.json"
  "web/data/martinique-page2-analysis.json"
  "web/data/guadeloupe-water-infra.geojson"
  "web/data/martinique-water-infra.geojson"
  "web/data/guadeloupe-network-states.geojson"
  "web/data/martinique-network-states.geojson"
)

DEPLOYED_FILES=(
  "/var/www/sib.shared.elio.dev/data/guadeloupe-complete-analysis.json"
  "/var/www/sib.shared.elio.dev/data/martinique-complete-analysis.json"
  "/var/www/sib.shared.elio.dev/data/guadeloupe-page1-analysis.json"
  "/var/www/sib.shared.elio.dev/data/martinique-page2-analysis.json"
  "/var/www/sib.shared.elio.dev/data/guadeloupe-water-infra.geojson"
  "/var/www/sib.shared.elio.dev/data/martinique-water-infra.geojson"
  "/var/www/sib.shared.elio.dev/data/guadeloupe-network-states.geojson"
  "/var/www/sib.shared.elio.dev/data/martinique-network-states.geojson"
)

print_file_summary() {
  local file_path="$1"
  if [[ ! -f "$file_path" ]]; then
    printf 'MISSING %s\n' "$file_path"
    return
  fi
  stat -c '%y %n' "$file_path"
  grep -m1 -E '"generated_at"|"updated_at"' "$file_path" || true
}

printf '=== NGINX LIVE ROOT ===\n'
grep -n -E 'server_name|root ' "$NGINX_SITE" | cat

printf '\n=== LOCAL SOURCE ===\n'
cd "$REPO_ROOT"
for file_path in "${LOCAL_FILES[@]}"; do
  print_file_summary "$file_path"
done

printf '\n=== DEPLOYED LIVE ROOT ===\n'
for file_path in "${DEPLOYED_FILES[@]}"; do
  print_file_summary "$file_path"
done