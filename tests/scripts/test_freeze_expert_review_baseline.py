from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import scripts.freeze_expert_review_baseline as freeze_baseline


def test_build_reference_snapshot_pins_latest_manifest_to_requested_run(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    run_id = "20260427_113740"
    run_dir = repo_root / "outputs" / "complete-analysis-runs" / run_id
    run_dir.mkdir(parents=True)
    latest_manifest_path = repo_root / "outputs" / "complete-analysis-runs" / "latest-manifest.json"
    latest_manifest_path.parent.mkdir(parents=True, exist_ok=True)

    pinned_manifest = {"run_id": run_id, "status": "success"}
    mutable_latest_manifest = {"run_id": "20260428_124950", "status": "running"}
    (run_dir / "manifest.json").write_text(json.dumps(pinned_manifest), encoding="utf-8")
    latest_manifest_path.write_text(json.dumps(mutable_latest_manifest), encoding="utf-8")

    docs_dir = repo_root / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "Journalisation_Run_CompleteAnalysis.md").write_text("# journal\n", encoding="utf-8")
    (docs_dir / "Journalisation_Run_CompleteAnalysis.jsonl").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(freeze_baseline, "REPO_ROOT", repo_root)
    monkeypatch.setattr(freeze_baseline, "DOCS_DIR", docs_dir)
    monkeypatch.setattr(freeze_baseline, "RUN_JOURNAL_MD", docs_dir / "Journalisation_Run_CompleteAnalysis.md")
    monkeypatch.setattr(freeze_baseline, "RUN_JOURNAL_JSONL", docs_dir / "Journalisation_Run_CompleteAnalysis.jsonl")
    monkeypatch.setattr(freeze_baseline, "resolve_run_id", lambda value: run_id)
    monkeypatch.setattr(freeze_baseline, "load_run_manifest", lambda value: {"territories": {}})

    output_dir = repo_root / "docs" / "expert-review" / "reference-run" / run_id
    freeze_baseline.build_reference_snapshot(run_id, output_dir)

    frozen_manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    frozen_latest_manifest = json.loads((output_dir / "latest-manifest.json").read_text(encoding="utf-8"))

    assert frozen_manifest == pinned_manifest
    assert frozen_latest_manifest == pinned_manifest