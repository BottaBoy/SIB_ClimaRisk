# Frozen Reference Run (Expert Review Baseline)

Run ID: **20260427_113740**

This folder freezes the baseline bookkeeping for Lot A without duplicating the large archived web payloads.

Included files:
- `Journalisation_Run_CompleteAnalysis.jsonl`
- `Journalisation_Run_CompleteAnalysis.md`
- `latest-manifest.json`
- `manifest.json`
- `artifact-index.json` (archived artefact locations + SHA256 + size)
- `regression-matrix.json` (machine-readable baseline matrix)
- `regression-matrix.md` (compact reviewer-facing matrix)

Archived run payloads tracked by checksum remain in:
- `outputs/complete-analysis-runs/20260427_113740`

Quick check:
```bash
cd /home/ubuntu/sib-work/docs/expert-review/reference-run/20260427_113740
cat regression-matrix.md
```
