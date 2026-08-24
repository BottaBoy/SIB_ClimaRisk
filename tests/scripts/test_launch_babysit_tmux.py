from __future__ import annotations

from pathlib import Path
import subprocess
import os


REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = REPO_ROOT / "scripts" / "launch_babysit_tmux.sh"


def _write_fake_tmux(bin_dir: Path) -> Path:
    tmux = bin_dir / "tmux"
    tmux.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
log_file="${TMUX_LOG_FILE:?}"
printf '%s\n' "tmux $*" >> "$log_file"
case "${1:-}" in
  has-session)
    exit "${TMUX_HAS_SESSION_EXIT:-1}"
    ;;
  new-session)
    dump_file="${TMUX_DUMP_FILE:-}"
    if [[ -n "$dump_file" ]]; then
      last_arg="${@: -1}"
      cp "$last_arg" "$dump_file"
    fi
    exit 0
    ;;
  attach)
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
""",
        encoding="utf-8",
    )
    tmux.chmod(0o755)
    return tmux


def test_launch_babysit_tmux_starts_and_attaches_for_sensitivity(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_tmux(fake_bin)
    log_file = tmp_path / "tmux.log"
    runner_dump = tmp_path / "runner.sh"

    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        "TMUX_LOG_FILE": str(log_file),
        "TMUX_DUMP_FILE": str(runner_dump),
        "TMUX_HAS_SESSION_EXIT": "1",
    }

    result = subprocess.run(
        [
            "bash",
            str(LAUNCHER),
            "--kind",
            "sensitivity",
            "--run-id",
            "sensitivity_20260609_140911",
        ],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    log_output = log_file.read_text(encoding="utf-8")
    runner_output = runner_dump.read_text(encoding="utf-8")

    assert "tmux new-session" in log_output
    assert "tmux attach" in log_output
    assert "babysit_sensitivity_analysis_run.py" in runner_output
    assert "Preparing tmux session babysit-sensitivity-sensitivity_20260609_140911" in result.stdout
    assert "Attaching to tmux session babysit-sensitivity-sensitivity_20260609_140911" in result.stdout


def test_launch_babysit_tmux_reuses_existing_session(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_tmux(fake_bin)
    log_file = tmp_path / "tmux.log"

    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        "TMUX_LOG_FILE": str(log_file),
        "TMUX_HAS_SESSION_EXIT": "0",
    }

    result = subprocess.run(
        [
            "bash",
            str(LAUNCHER),
            "--kind",
            "sensitivity",
            "--run-id",
            "sensitivity_20260609_140911",
        ],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    log_output = log_file.read_text(encoding="utf-8")

    assert "tmux new-session" not in log_output
    assert "tmux attach" in log_output
    assert "Reusing tmux session babysit-sensitivity-sensitivity_20260609_140911" in result.stdout
