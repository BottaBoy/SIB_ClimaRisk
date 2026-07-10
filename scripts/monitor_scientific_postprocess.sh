#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-/home/ubuntu/sib-work}"
RUN_ID="${2:-20260701_071828}"
TERR="${3:-guadeloupe}"

LOG="$ROOT/outputs/complete-analysis-runs/$RUN_ID/regeneration-logs/postprocess_latest.log"
CA_JSON="$ROOT/outputs/complete-analysis-runs/$RUN_ID/territories/$TERR/web/data/${TERR}-complete-analysis.json"
SUMMARY_JSON="$ROOT/outputs/complete-analysis-runs/$RUN_ID/territories/$TERR/web/data/${TERR}-scientific-web-summary.json"
GRAPH_DIR="$ROOT/outputs/Graphs/$RUN_ID"

while true; do
  printf '\033[2J\033[H'
  date '+%Y-%m-%d %H:%M:%S %Z'
  echo "Scientific post-process monitor"
  echo "run_id=$RUN_ID territory=$TERR"
  echo

  echo "-- tmux --"
  tmux ls 2>/dev/null | grep 'regen_' || echo 'no regen tmux session'
  echo

  echo "-- processes --"
  ps -eo pid,ppid,%cpu,%mem,rss,etime,state,cmd \
    | grep -E 'scientific_graph_postprocess.py|generate_run_graphs.py|worker-component-totals' \
    | grep -v grep || echo 'no matching process'
  echo

  echo "-- progress --"
  if [[ -f "$LOG" ]]; then
    grep -E 'Scientific rebuild start|Resolved scenario event indices|Starting hazard|Worker start|Worker class start|Worker class done|Worker done|Scientific rebuild finished' "$LOG" | tail -n 12 || true
    echo
    echo "centroid_distance_warnings=$(grep -c 'Distance to closest centroid' "$LOG" || true)"
    echo "no_exposure_warnings=$(grep -c 'No exposures with value >0 in the vicinity of the hazard' "$LOG" || true)"
    echo
    echo "log_tail:"
    tail -n 20 "$LOG"
  else
    echo "log missing: $LOG"
  fi
  echo

  echo "-- scientific payload --"
  if [[ -f "$CA_JSON" ]]; then
    jq '{
      scenarios:(.scientific_graph_inputs.scenarios // []),
      rows_rp10:(.scientific_graph_inputs.state_damage_tables.rp10|length),
      rows_rp50:(.scientific_graph_inputs.state_damage_tables.rp50|length),
      rows_rp100:(.scientific_graph_inputs.state_damage_tables.rp100|length),
      rows_rp1000:(.scientific_graph_inputs.state_damage_tables.rp1000|length),
      storm_rp10:(.scientific_graph_inputs.damage_breakdown_by_scenario.rp10.storm|length),
      storm_rp50:(.scientific_graph_inputs.damage_breakdown_by_scenario.rp50.storm|length),
      storm_rp100:(.scientific_graph_inputs.damage_breakdown_by_scenario.rp100.storm|length),
      storm_rp1000:(.scientific_graph_inputs.damage_breakdown_by_scenario.rp1000.storm|length),
      notes:(.notes // [])[-2:]
    }' "$CA_JSON"
  else
    echo "complete-analysis missing: $CA_JSON"
  fi
  echo

  echo "-- summary payload --"
  if [[ -f "$SUMMARY_JSON" ]]; then
    stat -c '%y %n' "$SUMMARY_JSON"
  else
    echo "summary missing: $SUMMARY_JSON"
  fi
  echo

  echo "-- graphs --"
  if [[ -d "$GRAPH_DIR" ]]; then
    graph_count=$(find "$GRAPH_DIR" -type f | wc -l)
    echo "graph_count=$graph_count"
    find "$GRAPH_DIR" -type f -printf '%TY-%Tm-%Td %TH:%TM:%TS %p\n' | sort | tail -n 8
  else
    echo "graph dir missing: $GRAPH_DIR"
  fi

  sleep 15
done
