#!/usr/bin/env bash
set -euo pipefail

# Portable environment template for external expert reruns.
# Usage:
#   source docs/expert-review/package/expert-env-template.sh
# Optional override before sourcing:
#   export EXPERT_UPLOADS_ROOT=/path/to/uploads

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
BACKEND_ROOT="${REPO_ROOT}/backend"

# Expected data root for transferred datasets.
UPLOADS_ROOT="${EXPERT_UPLOADS_ROOT:-${REPO_ROOT}/../uploads}"

export SIB_EXPERT_REPO_ROOT="${REPO_ROOT}"
export SIB_EXPERT_BACKEND_ROOT="${BACKEND_ROOT}"
export SIB_EXPERT_UPLOADS_ROOT="${UPLOADS_ROOT}"

# Core hazard and vulnerability data.
export SIB_RISK_STORM_PARQUET_PATH="${SIB_RISK_STORM_PARQUET_PATH:-${UPLOADS_ROOT}/STORM/storm_ds}"
export SIB_RISK_STORM_CMCC_PARQUET_PATH="${SIB_RISK_STORM_CMCC_PARQUET_PATH:-${UPLOADS_ROOT}/STORM/storm_ds_CMCC}"
export SIB_RISK_HAZARD_SURGE_TOPO_PATH="${SIB_RISK_HAZARD_SURGE_TOPO_PATH:-${UPLOADS_ROOT}/DEM_Topo/MNT_FACADE_ANTS_HOMONIM_PBMA/DONNEES/MNT_ANTS100m_HOMONIM_WGS84_PBMA_ZNEG.asc}"
export SIB_RISK_D2_FLOOD_CURVE_FILE="${SIB_RISK_D2_FLOOD_CURVE_FILE:-${UPLOADS_ROOT}/Vulnerability/Table_D2_Hazard_Fragility_and_Vulnerability_Curves_V1.1.0.xlsx}"

# Optional fallback hazards (recommended).
export SIB_RISK_HAZARD_STORM_PATH="${SIB_RISK_HAZARD_STORM_PATH:-${REPO_ROOT}/data/hazards/tc_hazard_guadeloupe.h5}"
export SIB_RISK_HAZARD_STORM_CMCC_PATH="${SIB_RISK_HAZARD_STORM_CMCC_PATH:-${REPO_ROOT}/data/hazards/tc_hazard_guadeloupe_CMCC.h5}"

# Optional social and landslide paths.
export SIB_RISK_POPULATION_DATA_DIR="${SIB_RISK_POPULATION_DATA_DIR:-${UPLOADS_ROOT}/Population}"
export SIB_RISK_LANDSLIDE_ROOT="${SIB_RISK_LANDSLIDE_ROOT:-${UPLOADS_ROOT}/Landslide}"

# Runtime defaults for expert reproducibility.
export SIB_RISK_IMPACT_ENGINE_MODE="${SIB_RISK_IMPACT_ENGINE_MODE:-climada}"
export SIB_RISK_ALLOW_CLIMADA_FALLBACK="${SIB_RISK_ALLOW_CLIMADA_FALLBACK:-true}"
export SIB_RISK_HAZARD_PREFER_DYNAMIC_FROM_PARQUET="${SIB_RISK_HAZARD_PREFER_DYNAMIC_FROM_PARQUET:-true}"
export SIB_RISK_HAZARD_FALLBACK_TO_PRECOMPUTED="${SIB_RISK_HAZARD_FALLBACK_TO_PRECOMPUTED:-true}"

# Keep job outputs local to repository by default.
export SIB_RISK_JOB_ROOT="${SIB_RISK_JOB_ROOT:-${REPO_ROOT}/outputs/expert-jobs}"

cat <<MSG
[expert-env] REPO_ROOT=${REPO_ROOT}
[expert-env] UPLOADS_ROOT=${UPLOADS_ROOT}
[expert-env] STORM=${SIB_RISK_STORM_PARQUET_PATH}
[expert-env] STORM_CMCC=${SIB_RISK_STORM_CMCC_PARQUET_PATH}
[expert-env] SURGE_TOPO=${SIB_RISK_HAZARD_SURGE_TOPO_PATH}
[expert-env] D2_CURVES=${SIB_RISK_D2_FLOOD_CURVE_FILE}
MSG
