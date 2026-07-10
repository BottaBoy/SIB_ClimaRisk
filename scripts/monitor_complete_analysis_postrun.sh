#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/home/ubuntu/sib-work}"
RUN_ID="${1:-}"
TERRITORY="${2:-guadeloupe}"

if [[ -z "$RUN_ID" ]]; then
  echo "Usage: $0 <run_id> [territory]" >&2
  exit 1
fi

RUN_DIR="$ROOT/outputs/complete-analysis-runs/$RUN_ID"
MANIFEST="$RUN_DIR/manifest.json"
JOURNAL="$RUN_DIR/frontend-supervision.jsonl"
ARCHIVED_DIR="$RUN_DIR/territories/$TERRITORY/web/data"
ARCHIVED_SUMMARY="$ARCHIVED_DIR/${TERRITORY}-scientific-web-summary.json"
ARCHIVED_COMPLETE="$ARCHIVED_DIR/${TERRITORY}-complete-analysis.json"
WEB_SUMMARY="$ROOT/web/data/${TERRITORY}-scientific-web-summary.json"

while true; do
  clear || true
  date '+%Y-%m-%d %H:%M:%S %Z'
  echo "Complete-analysis post-run monitor"
  echo "run_id=$RUN_ID territory=$TERRITORY"
  echo

  echo "-- manifest --"
  if [[ -f "$MANIFEST" ]]; then
    jq '{run_id,status,frontend_artifacts,updated_at,finished_at}' "$MANIFEST"
  else
    echo "missing: $MANIFEST"
  fi
  echo

  echo "-- summary files --"
  for path in "$ARCHIVED_SUMMARY" "$WEB_SUMMARY" "$ARCHIVED_COMPLETE"; do
    if [[ -f "$path" ]]; then
      stat -c '%y %n' "$path"
    else
      echo "missing: $path"
    fi
  done
  echo

  echo "-- scientific payload --"
  if [[ -f "$ARCHIVED_COMPLETE" ]]; then
    jq '{
      scenarios:(.scientific_graph_inputs.scenarios // []),
      social_rp1000:(.scientific_graph_inputs.social_impact_by_scenario.rp1000.storm.total_population_affected_any_network // null),
      network_rp1000_storm:(.scientific_graph_inputs.network_state_service_distribution_by_scenario.rp1000.storm // null),
      availability:(.scientific_graph_inputs.scenario_availability // {})
    }' "$ARCHIVED_COMPLETE"
  else
    echo "complete-analysis missing"
  fi
  echo

  echo "-- frontend journal --"
  if [[ -f "$JOURNAL" ]]; then
    tail -n 20 "$JOURNAL"
  else
    echo "missing: $JOURNAL"
  fi
  echo

  echo "-- active processes --"
  ps -eo pid,ppid,%cpu,%mem,rss,etime,state,cmd | grep -E 'run_complete_analysis.py|rerun_case_studies_light.py|build_.*py|scientific_graph_postprocess.py|generate_run_graphs.py' | grep -v grep || echo 'no matching process'
  sleep 15
done
