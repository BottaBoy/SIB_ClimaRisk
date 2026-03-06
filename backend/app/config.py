from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


def _env_bool(env: dict[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_csv(env: dict[str, str], key: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = env.get(key)
    if raw is None:
        return default
    values = tuple(item.strip() for item in str(raw).split(",") if item.strip())
    return values or default


def _prefer_existing_path(*candidates: Path) -> Path:
    for candidate in candidates:
        try:
            if candidate.exists():
                return candidate
        except Exception:
            continue
    return candidates[0]


@dataclass(frozen=True)
class Settings:
    app_name: str = "SIB Cyclone Risk API"
    api_prefix: str = "/api/v1"
    job_root: Path = Path("/tmp/sib-risk-jobs")
    job_ttl_hours: int = 24
    max_runs_kept: int = 10
    max_upload_mb: int = 50
    worker_concurrency: int = 1
    demo_result_path: Path = Path(__file__).resolve().parents[2] / "web" / "data" / "guadeloupe-complete-analysis.json"
    storm_years: int = 10000
    default_sampling_spacing_m: float = 100.0
    data_root: Path = Path(__file__).resolve().parents[2] / "data"
    hazard_storm_path: Path = Path(__file__).resolve().parents[2] / "data" / "hazards" / "tc_hazard_guadeloupe.h5"
    hazard_storm_cmcc_path: Path = Path(__file__).resolve().parents[2] / "data" / "hazards" / "tc_hazard_guadeloupe_CMCC.h5"
    storm_parquet_path: Path = Path(__file__).resolve().parents[2] / "data" / "hazards" / "storm_ds"
    storm_cmcc_parquet_path: Path = Path(__file__).resolve().parents[2] / "data" / "hazards" / "storm_ds_CMCC"
    hazard_prefer_dynamic_from_parquet: bool = True
    hazard_fallback_to_precomputed: bool = True
    storm_wind_unit_in: str = "m/s"
    storm_radius_unit_in: str = "km"
    storm_env_pressure_hpa: float = 1010.0
    example_qgis_points_path: Path = Path(__file__).resolve().parents[2] / "data" / "examples" / "QGIS_Points_04_08_25.csv"
    example_qgis_lines_path: Path = Path(__file__).resolve().parents[2] / "data" / "examples" / "QGIS_Lignes_04_08_25.csv"
    example_qgis_polygons_path: Path = Path(__file__).resolve().parents[2] / "data" / "examples" / "QGIS_Polygones_04_08_25.csv"
    impact_engine_mode: str = "climada"
    allow_climada_fallback: bool = False
    climada_metric_crs: str = "EPSG:3857"
    climada_max_points_per_feature: int = 300
    climada_top_events_count: int = 20
    cors_allowed_origins: tuple[str, ...] = (
        "https://app.sib.elio.dev",
        "https://sib.dev.elio.bottagisio.com",
    )


def load_settings() -> Settings:
    env = os.environ

    job_root = Path(env.get("SIB_RISK_JOB_ROOT", "/tmp/sib-risk-jobs"))
    demo_result_path = Path(
        env.get(
            "SIB_RISK_DEMO_RESULT_PATH",
            str(Path(__file__).resolve().parents[2] / "web" / "data" / "guadeloupe-complete-analysis.json"),
        )
    )

    default_storm_parquet = Path(__file__).resolve().parents[2] / "data" / "hazards" / "storm_ds"
    default_storm_cmcc_parquet = Path(__file__).resolve().parents[2] / "data" / "hazards" / "storm_ds_CMCC"
    alt_storm_parquet = Path("/home/ubuntu/uploads/STORM/storm_ds")
    alt_storm_cmcc_parquet = Path("/home/ubuntu/uploads/STORM/storm_ds_CMCC")
    configured_storm_parquet = Path(env.get("SIB_RISK_STORM_PARQUET_PATH", str(default_storm_parquet)))
    configured_storm_cmcc_parquet = Path(env.get("SIB_RISK_STORM_CMCC_PARQUET_PATH", str(default_storm_cmcc_parquet)))
    storm_parquet_path = _prefer_existing_path(configured_storm_parquet, default_storm_parquet, alt_storm_parquet)
    storm_cmcc_parquet_path = _prefer_existing_path(configured_storm_cmcc_parquet, default_storm_cmcc_parquet, alt_storm_cmcc_parquet)

    return Settings(
        app_name=env.get("SIB_RISK_APP_NAME", "SIB Cyclone Risk API"),
        api_prefix=env.get("SIB_RISK_API_PREFIX", "/api/v1"),
        job_root=job_root,
        job_ttl_hours=int(env.get("SIB_RISK_JOB_TTL_HOURS", "24")),
        max_runs_kept=max(1, int(env.get("SIB_RISK_MAX_RUNS_KEPT", "10"))),
        max_upload_mb=int(env.get("SIB_RISK_MAX_UPLOAD_MB", "50")),
        worker_concurrency=int(env.get("SIB_RISK_WORKER_CONCURRENCY", "1")),
        demo_result_path=demo_result_path,
        storm_years=int(env.get("SIB_RISK_STORM_YEARS", "10000")),
        default_sampling_spacing_m=float(env.get("SIB_RISK_DEFAULT_SAMPLING_SPACING_M", "100")),
        data_root=Path(env.get("SIB_RISK_DATA_ROOT", str(Path(__file__).resolve().parents[2] / "data"))),
        hazard_storm_path=Path(env.get("SIB_RISK_HAZARD_STORM_PATH", str(Path(__file__).resolve().parents[2] / "data" / "hazards" / "tc_hazard_guadeloupe.h5"))),
        hazard_storm_cmcc_path=Path(env.get("SIB_RISK_HAZARD_STORM_CMCC_PATH", str(Path(__file__).resolve().parents[2] / "data" / "hazards" / "tc_hazard_guadeloupe_CMCC.h5"))),
        storm_parquet_path=storm_parquet_path,
        storm_cmcc_parquet_path=storm_cmcc_parquet_path,
        hazard_prefer_dynamic_from_parquet=_env_bool(env, "SIB_RISK_HAZARD_PREFER_DYNAMIC_FROM_PARQUET", True),
        hazard_fallback_to_precomputed=_env_bool(env, "SIB_RISK_HAZARD_FALLBACK_TO_PRECOMPUTED", True),
        storm_wind_unit_in=str(env.get("SIB_RISK_STORM_WIND_UNIT_IN", "m/s")).strip(),
        storm_radius_unit_in=str(env.get("SIB_RISK_STORM_RADIUS_UNIT_IN", "km")).strip(),
        storm_env_pressure_hpa=float(env.get("SIB_RISK_STORM_ENV_PRESSURE_HPA", "1010.0")),
        example_qgis_points_path=Path(env.get("SIB_RISK_EXAMPLE_QGIS_POINTS_PATH", str(Path(__file__).resolve().parents[2] / "data" / "examples" / "QGIS_Points_04_08_25.csv"))),
        example_qgis_lines_path=Path(env.get("SIB_RISK_EXAMPLE_QGIS_LINES_PATH", str(Path(__file__).resolve().parents[2] / "data" / "examples" / "QGIS_Lignes_04_08_25.csv"))),
        example_qgis_polygons_path=Path(env.get("SIB_RISK_EXAMPLE_QGIS_POLYGONS_PATH", str(Path(__file__).resolve().parents[2] / "data" / "examples" / "QGIS_Polygones_04_08_25.csv"))),
        impact_engine_mode=str(env.get("SIB_RISK_IMPACT_ENGINE_MODE", "climada")).strip().lower(),
        allow_climada_fallback=_env_bool(env, "SIB_RISK_ALLOW_CLIMADA_FALLBACK", False),
        climada_metric_crs=str(env.get("SIB_RISK_CLIMADA_METRIC_CRS", "EPSG:3857")).strip(),
        climada_max_points_per_feature=int(env.get("SIB_RISK_CLIMADA_MAX_POINTS_PER_FEATURE", "300")),
        climada_top_events_count=int(env.get("SIB_RISK_CLIMADA_TOP_EVENTS_COUNT", "20")),
        cors_allowed_origins=_env_csv(
            env,
            "SIB_RISK_CORS_ALLOWED_ORIGINS",
            (
                "https://app.sib.elio.dev",
                "https://sib.dev.elio.bottagisio.com",
            ),
        ),
    )
