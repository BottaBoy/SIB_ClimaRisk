# Expert Data Manifest (GUA+MQ)

Last updated: **2026-04-29**

This manifest defines the minimum data transfer package for an autonomous expert rerun on Guadeloupe + Martinique.

## 1) Required Data (Blocking)

| Path | Approx size (reference env) | Why required |
|---|---:|---|
| `/home/ubuntu/uploads/STORM/storm_ds` | 58 MB | Dynamic STORM present-climate track dataset used by default hazard path. |
| `/home/ubuntu/uploads/STORM/storm_ds_CMCC` | 71 MB | Dynamic STORM_CMCC dataset for climate-change scenario comparison. |
| `/home/ubuntu/uploads/DEM_Topo/Topo/Guadeloupe.tif` | ~37 MB | Current Guadeloupe DEM/topography used by the live surge component path. |
| `/home/ubuntu/uploads/DEM_Topo/Topo/Martinique.tif` | ~21 MB | Current Martinique DEM/topography used by the live surge component path. |
| `/home/ubuntu/uploads/Vulnerability/Table_D2_Hazard_Fragility_and_Vulnerability_Curves_V1.1.0.xlsx` | 1.6 MB | Vulnerability curves for rain/surge mapping and landslide proxy payload. |
| `/home/ubuntu/uploads/Infra_Elec_Guadeloupe/` | 53 MB | Guadeloupe electricity exposure sources. |
| `/home/ubuntu/uploads/Infra_Elec_Martinique/` | 41 MB | Martinique electricity exposure sources. |
| `/home/ubuntu/uploads/Infra_Eau_Guadeloupe/` | 20 MB | Guadeloupe water exposure sources. |
| `/home/ubuntu/uploads/Infra_Eau_Martinique/` | 296 MB | Martinique water exposure sources. |

## 2) Optional - Historical Audit or Extended Reproducibility

| Path | Approx size (reference env) | Value for expert review |
|---|---:|---|
| `/home/ubuntu/sib-work/data/hazards/tc_hazard_guadeloupe.h5` | 424 MB | Historical audit only. Current production compute rejects scientific fallback to precomputed hazards. |
| `/home/ubuntu/sib-work/data/hazards/tc_hazard_guadeloupe_CMCC.h5` | 458 MB | Historical audit only. Current production compute rejects scientific fallback to precomputed hazards. |
| `/home/ubuntu/sib-work/data/hazards/tc_hazard_martinique.h5` | 105 MB | Historical audit only. Current production compute rejects scientific fallback to precomputed hazards. |
| `/home/ubuntu/sib-work/data/hazards/tc_hazard_martinique_CMCC.h5` | 113 MB | Historical audit only. Current production compute rejects scientific fallback to precomputed hazards. |
| `/home/ubuntu/uploads/Population/glp_pop_2020_CN_100m_R2025A_v1.tif` | <1 MB | Enables social metrics for Guadeloupe. |
| `/home/ubuntu/uploads/Population/mtq_pop_2020_CN_100m_R2025A_v1.tif` | <1 MB | Enables social metrics for Martinique. |
| `/home/ubuntu/uploads/Landslide/LS_GuaMar_Precipitation_ClimatActuel.tif` | ~9 MB | Landslide/rainfall scenario support for extended analysis. |
| `/home/ubuntu/uploads/Landslide/LS_GuaMar_Precipitation_ClimatSSP585.tif` | ~9 MB | Landslide climate scenario support. |
| `/home/ubuntu/uploads/Landslide/LS_GuaMar_Eathquake.tif` | ~9 MB | Landslide earthquake scenario support. |
| `/home/ubuntu/uploads/DEM_Topo/Limites Pays/geoBoundariesCGAZ_ADM0.geojson` | 383 MB | Admin mask/boundary support for mapping and external reproducibility checks. |

## 3) Quick Validation Commands
From repository root:

```bash
./docs/expert-review/package/check_expert_inputs.py --mode minimal
./docs/expert-review/package/check_expert_inputs.py --mode full
```

Manual spot check (example):

```bash
du -sh \
  /home/ubuntu/uploads/STORM/storm_ds \
  /home/ubuntu/uploads/STORM/storm_ds_CMCC \
  /home/ubuntu/uploads/Infra_Elec_Guadeloupe \
  /home/ubuntu/uploads/Infra_Elec_Martinique \
  /home/ubuntu/uploads/Infra_Eau_Guadeloupe \
  /home/ubuntu/uploads/Infra_Eau_Martinique
```

## 4) Transfer Policy for Current Expert Review
Selected scope and sharing policy:
- scope: **GUA + MQ complete rerun**,
- policy: **full infrastructure data sharing**.

Reference evidence policy:
- frozen comparison baseline: `20260427_113740`
- targeted post-integration validation evidence: `20260429_075050` (optional, Guadeloupe only)

This means all required directories above should be transferred as-is to preserve geometry and attribute fidelity.

Important:
- the documents in `docs/expert-review/` describe the package, but they do not replace the required runtime data
- if any required input changed since the previous transfer, that updated input must be sent again even if the docs themselves did not change
- this currently applies to the surge DEM inputs under `/home/ubuntu/uploads/DEM_Topo/Topo/`

## 5) Practical Packaging Notes
- Preserve relative filenames and directory names exactly.
- Preserve symlinks if you transfer the historical HDF5 files from repository paths.
- After extraction on expert machine, set environment variables via `docs/expert-review/package/expert-env-template.sh`.
- Run `check_expert_inputs.py` before any heavy run.
- For the full reviewer handoff checklist, use `docs/expert-review/expert-return-package-2026-04-29.md`.
