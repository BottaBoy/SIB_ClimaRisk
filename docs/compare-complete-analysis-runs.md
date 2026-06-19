# Comparer Deux Runs Complete-Analysis

Ce guide decrit l'usage du script CLI ponctuel de comparaison des runs complete-analysis.

## Objectif

Comparer deux runs archives sur les axes suivants:

- impacts monetaires
- impacts en pourcentage
- impacts population
- etat des reseaux (agregats + detail S0/S1/S2/S3)

Le script est strict: il echoue explicitement si un run est invalide, non `success`, non 1500 tracks, ou si des artefacts/champs requis sont absents.

## Script

- Script: `scripts/compare_complete_analysis_runs.py`

## Commande

```bash
cd /home/ubuntu/sib-work
/home/ubuntu/.venv_openpyxl/bin/python scripts/compare_complete_analysis_runs.py \
  --run-a 20260511_141135 \
  --run-b 20260527_160919 \
  --territories guadeloupe martinique
```

## Sorties

Par defaut, les sorties sont ecrites sous:

- `outputs/run-comparisons/<run_a>_vs_<run_b>/run-comparison.md`
- `outputs/run-comparisons/<run_a>_vs_<run_b>/run-comparison-summary.csv`
- `outputs/run-comparisons/<run_a>_vs_<run_b>/run-comparison-network-states.csv`

Le rapport Markdown utilise la convention:

- `delta = run_B - run_A`

## Parametres

- `--run-a`: run de reference (baseline)
- `--run-b`: run compare
- `--territories`: `guadeloupe`, `martinique` (par defaut les deux)
- `--output-dir`: repertoire parent de sortie (optionnel)

## Notes

- Le script cible les runs complete-analysis 1500 tracks.
- Les comparaisons reseau S0/S1/S2/S3 proviennent des `state_damage_tables` des payloads page-analysis.
- Les metriques population proviennent de `portfolio_results.social_impact_worst_case_summary` (ou alias legacy `social_impact_summary`).
