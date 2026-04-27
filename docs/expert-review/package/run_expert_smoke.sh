#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
BACKEND_ROOT="${REPO_ROOT}/backend"

MODE="minimal"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE="${2:-}"
      shift 2
      ;;
    -h|--help)
      cat <<USAGE
Usage: run_expert_smoke.sh --mode minimal|full

Modes:
  minimal  Validate inputs and run backend sample only.
  full     minimal + non-deployment complete-analysis run (GUA+MQ).

Optional environment variables:
  EXPERT_PYTHON_BIN                 Python executable to use.
  EXPERT_SMOKE_DYNAMIC_MAX_TRACKS   Tracks for full mode (default: 120).
  EXPERT_SMOKE_MEMORY_BUDGET_GB     Memory budget for full mode (default: 2.0).
USAGE
      exit 0
      ;;
    *)
      echo "[smoke] Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ "$MODE" != "minimal" && "$MODE" != "full" ]]; then
  echo "[smoke] Invalid mode: $MODE (expected minimal|full)" >&2
  exit 2
fi

if [[ -f "${SCRIPT_DIR}/expert-env-template.sh" ]]; then
  # shellcheck source=/dev/null
  source "${SCRIPT_DIR}/expert-env-template.sh"
fi

PYTHON_BIN="${EXPERT_PYTHON_BIN:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "${BACKEND_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${BACKEND_ROOT}/.venv/bin/python"
  else
    PYTHON_BIN="$(command -v python3)"
  fi
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[smoke] Python executable not found or not executable: $PYTHON_BIN" >&2
  exit 1
fi

echo "[smoke] mode=$MODE"
echo "[smoke] repo_root=$REPO_ROOT"
echo "[smoke] python=$PYTHON_BIN"

"$PYTHON_BIN" "${SCRIPT_DIR}/check_expert_inputs.py" --mode "$MODE"

mkdir -p "${REPO_ROOT}/outputs/expert-smoke"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKOFFICE_OUT="${REPO_ROOT}/outputs/expert-smoke/backoffice-sample-${TS}.json"

echo "[smoke] running backend sample"
(
  cd "$BACKEND_ROOT"
  "$PYTHON_BIN" scripts/run_backoffice_sample.py \
    --file scripts/samples/backoffice_sample_assets.csv \
    --output "$BACKOFFICE_OUT"
)

echo "[smoke] validating backend sample output"
"$PYTHON_BIN" - <<PY
import json
from pathlib import Path
p = Path(${BACKOFFICE_OUT@Q})
if not p.exists():
    raise SystemExit(f"Missing sample output: {p}")
payload = json.loads(p.read_text(encoding="utf-8"))
meta = payload.get("meta") or {}
engine = str(meta.get("engine") or "")
hazards = list(meta.get("hazards") or [])
components = list(meta.get("hazard_components") or [])
if not engine:
    raise SystemExit("Sample output has empty meta.engine")
if not hazards:
    raise SystemExit("Sample output has empty meta.hazards")
print(f"[smoke] sample engine={engine}")
print(f"[smoke] sample hazards={hazards}")
print(f"[smoke] sample components={components}")
PY

if [[ "$MODE" == "full" ]]; then
  DYNAMIC_MAX_TRACKS="${EXPERT_SMOKE_DYNAMIC_MAX_TRACKS:-120}"
  MEMORY_BUDGET_GB="${EXPERT_SMOKE_MEMORY_BUDGET_GB:-2.0}"

  echo "[smoke] running complete-analysis (non-deploy) territories=both"
  (
    cd "$REPO_ROOT"
    "$PYTHON_BIN" scripts/run_complete_analysis.py \
      --territories both \
      --no-deploy \
      --dynamic-max-tracks "$DYNAMIC_MAX_TRACKS" \
      --memory-budget-gb "$MEMORY_BUDGET_GB"
  )

  echo "[smoke] validating complete-analysis artifacts"
  "$PYTHON_BIN" - <<PY
from pathlib import Path
repo = Path(${REPO_ROOT@Q})
required = [
    repo / "web" / "data" / "guadeloupe-complete-analysis.json",
    repo / "web" / "data" / "martinique-complete-analysis.json",
    repo / "outputs" / "complete-analysis-runs" / "latest-manifest.json",
]
missing = [str(p) for p in required if not p.exists()]
if missing:
    raise SystemExit("Missing full-mode artifacts:\n" + "\n".join(missing))
print("[smoke] full-mode artifacts present")
PY
fi

echo "[smoke] success"
echo "[smoke] sample_output=$BACKOFFICE_OUT"
