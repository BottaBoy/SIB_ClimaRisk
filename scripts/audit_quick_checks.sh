#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
RUFF_BIN="${RUFF_BIN:-}" 

if [[ -z "$RUFF_BIN" ]]; then
  if command -v ruff >/dev/null 2>&1; then
    RUFF_BIN="$(command -v ruff)"
  elif [[ -x "/tmp/sib-audit-venv/bin/ruff" ]]; then
    RUFF_BIN="/tmp/sib-audit-venv/bin/ruff"
  else
    "$PYTHON_BIN" -m venv /tmp/sib-audit-venv
    /tmp/sib-audit-venv/bin/pip install -q ruff
    RUFF_BIN="/tmp/sib-audit-venv/bin/ruff"
  fi
fi

echo "[audit] python=$($PYTHON_BIN --version 2>&1)"
echo "[audit] ruff=$($RUFF_BIN --version 2>&1)"

echo "[audit] compileall scripts"
"$PYTHON_BIN" -m compileall -q scripts backend/app backend/scripts

echo "[audit] ruff check"
"$RUFF_BIN" check scripts backend/app backend/scripts

echo "[audit] smoke --help scripts/*.py"
"$PYTHON_BIN" - <<'PY'
import glob
import subprocess
import sys

bad = []
for path in sorted(glob.glob("scripts/*.py")):
    proc = subprocess.run([sys.executable, path, "--help"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if proc.returncode != 0:
        bad.append((path, proc.returncode))
if bad:
    for item, code in bad:
        print(f"[audit] FAIL --help: {item} rc={code}")
    raise SystemExit(1)
print("[audit] script --help smoke: OK")
PY

echo "[audit] quick checks completed"
