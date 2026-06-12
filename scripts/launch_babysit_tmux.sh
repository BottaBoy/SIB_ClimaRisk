#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  launch_babysit_tmux.sh --kind {complete|hazard-comparison} --run-id RUN_ID

Options:
  --poll-seconds SECONDS
  --stale-after-minutes MINUTES
  --silent-hang-after-minutes MINUTES
  --restart-delay-seconds SECONDS
EOF
}

kind=""
run_id=""
poll_seconds="60"
stale_after_minutes="20"
silent_hang_after_minutes="30"
restart_delay_seconds="30"

while (($#)); do
  case "$1" in
    --kind)
      kind="${2:-}"
      shift 2
      ;;
    --run-id)
      run_id="${2:-}"
      shift 2
      ;;
    --poll-seconds)
      poll_seconds="${2:-}"
      shift 2
      ;;
    --stale-after-minutes)
      stale_after_minutes="${2:-}"
      shift 2
      ;;
    --silent-hang-after-minutes)
      silent_hang_after_minutes="${2:-}"
      shift 2
      ;;
    --restart-delay-seconds)
      restart_delay_seconds="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$kind" || -z "$run_id" ]]; then
  usage >&2
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="$repo_root/backend/.venv/bin/python"

case "$kind" in
  complete)
    babysit_script="$repo_root/scripts/babysit_complete_analysis_run.py"
    session_prefix="babysit"
    log_file="$repo_root/logs/babysit_complete_analysis_${run_id}.log"
    ;;
  hazard-comparison)
    babysit_script="$repo_root/scripts/babysit_hazard_comparison_run.py"
    session_prefix="babysit-hazard-comparison"
    log_file="$repo_root/logs/babysit_hazard_comparison_${run_id}.log"
    ;;
  *)
    echo "Unsupported kind: $kind" >&2
    usage >&2
    exit 2
    ;;
esac

session="${session_prefix}-${run_id}"
mkdir -p "$(dirname "$log_file")"

ts() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

log_line() {
  printf '[%s] %s\n' "$(ts)" "$*" | tee -a "$log_file"
}

log_line "Preparing tmux session $session for kind=$kind run_id=$run_id"

runner_script="$(mktemp "$repo_root/logs/.${session}.XXXXXX.sh")"
cat >"$runner_script" <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd "$repo_root"
"$python_bin" "$babysit_script" \
  --run-id "$run_id" \
  --poll-seconds "$poll_seconds" \
  --stale-after-minutes "$stale_after_minutes" \
  --silent-hang-after-minutes "$silent_hang_after_minutes" \
  --restart-delay-seconds "$restart_delay_seconds" 2>&1 | tee -a "$log_file"
EOF
chmod 700 "$runner_script"
trap 'rm -f "$runner_script"' EXIT

if tmux has-session -t "$session" 2>/dev/null; then
  log_line "Reusing tmux session $session"
else
  log_line "Starting tmux session $session"
  tmux new-session -d -s "$session" -- "$runner_script"
  log_line "Started tmux session $session"
fi

log_line "Attaching to tmux session $session"
exec env TERM=xterm-256color tmux attach -t "$session"
