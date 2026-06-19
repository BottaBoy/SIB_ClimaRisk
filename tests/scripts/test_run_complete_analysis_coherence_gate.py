from __future__ import annotations

from pathlib import Path
import json
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from scripts import run_complete_analysis_coherence_gate


def test_compute_gate_verdict_is_blocked_when_required_step_fails() -> None:
    steps = [
        run_complete_analysis_coherence_gate.StepResult(
            name="targeted_pytests",
            required=True,
            status="passed",
            returncode=0,
            elapsed_seconds=1.0,
            command=["python", "-m", "pytest"],
            log_path=None,
            details={},
        ),
        run_complete_analysis_coherence_gate.StepResult(
            name="complete_analysis_smoke",
            required=True,
            status="failed",
            returncode=1,
            elapsed_seconds=2.0,
            command=["python", "scripts/run_complete_analysis.py"],
            log_path=None,
            details={},
        ),
    ]

    assert run_complete_analysis_coherence_gate._compute_gate_verdict(steps) == "blocked"


def test_compute_gate_verdict_is_safe_when_required_steps_pass() -> None:
    steps = [
        run_complete_analysis_coherence_gate.StepResult(
            name="targeted_pytests",
            required=True,
            status="passed",
            returncode=0,
            elapsed_seconds=1.0,
            command=["python", "-m", "pytest"],
            log_path=None,
            details={},
        ),
        run_complete_analysis_coherence_gate.StepResult(
            name="frontend_audit",
            required=False,
            status="skipped",
            returncode=None,
            elapsed_seconds=0.0,
            command=None,
            log_path=None,
            details={"reason": "not requested"},
        ),
    ]

    assert run_complete_analysis_coherence_gate._compute_gate_verdict(steps) == "safe to rerun"


def test_resolve_new_run_id_prefers_new_directory(tmp_path: Path) -> None:
    before = {"20260615_191554"}
    (tmp_path / "20260615_191554").mkdir()
    (tmp_path / "20260616_080000").mkdir()

    resolved = run_complete_analysis_coherence_gate._resolve_new_run_id(tmp_path, before=before)

    assert resolved == "20260616_080000"


def test_resolve_new_run_id_falls_back_to_latest_manifest(tmp_path: Path) -> None:
    latest_manifest = tmp_path / "latest-manifest.json"
    latest_manifest.write_text(
        json.dumps({"run_id": "20260616_090000"}),
        encoding="utf-8",
    )

    resolved = run_complete_analysis_coherence_gate._resolve_new_run_id(
        tmp_path,
        before=set(),
        latest_manifest_path=latest_manifest,
    )

    assert resolved == "20260616_090000"
