from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from scripts import resume_hazard_comparison_safe as safe  # noqa: E402


def test_main_uses_resume_launcher_and_writes_pidfile(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "sib-work"
    run_outputs = repo_root / "outputs" / "hazard-comparison-runs"
    log_root = repo_root / "logs"
    run_id = "20260611_075636"
    manifest_path = run_outputs / run_id / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "status": "failed",
                "parameters": {"dynamic_max_tracks": 1200},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(safe, "REPO_ROOT", repo_root)
    monkeypatch.setattr(safe, "RUN_OUTPUTS_DIR", run_outputs)
    monkeypatch.setattr(safe, "LOGS_DIR", log_root)

    monkeypatch.setattr(safe.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout="", returncode=0))

    recorded: dict[str, object] = {}

    class _FakeProc:
        pid = 98765

    def _fake_popen(cmd, cwd=None, stdout=None, stderr=None, start_new_session=None, env=None):
        recorded["cmd"] = cmd
        recorded["cwd"] = cwd
        recorded["env"] = env
        return _FakeProc()

    monkeypatch.setattr(safe.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(sys, "argv", ["resume_hazard_comparison_safe.py", "--run-id", run_id])

    exit_code = safe.main()

    assert exit_code == 0
    assert recorded["cmd"][1].endswith("run_hazard_comparative_analysis.py")
    assert "--resume-run-id" in recorded["cmd"]
    assert recorded["cwd"] == str(repo_root)
    assert recorded["env"]["PYTHONUNBUFFERED"] == "1"
    assert (run_outputs / run_id / "resume.pid").read_text(encoding="utf-8").strip() == "98765"
