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
    territory_grid_deg: float = 0.2
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
    hazard_dynamic_max_tracks: int = 1200
    hazard_track_cache_max_entries: int = 8
    multi_hazard_enabled: bool = True
    hazard_rain_model: str = "R-CLIPER"
    hazard_rain_max_dist_inland_km: float = 2000.0
    hazard_surge_topo_path: Path = Path(__file__).resolve().parents[2] / "data" / "hazards" / "MNT_ANTS100m_HOMONIM_WGS84_PBMA_ZNEG.asc"
    d2_flood_curve_file: Path = Path(__file__).resolve().parents[2] / "data" / "vulnerability" / "Table_D2_Hazard_Fragility_and_Vulnerability_Curves_V1.1.0.xlsx"
    multi_hazard_rain_base_runoff_coeff: float = 0.25
    wind_asset_type_to_curve_code: dict[str, str] | None = None
    flood_asset_type_to_curve_code: dict[str, str] | None = None
    landslide_precip_current_path: Path = Path("/home/ubuntu/uploads/Landslide/LS_GuaMar_Precipitation_ClimatActuel.tif")
    landslide_precip_ssp585_path: Path = Path("/home/ubuntu/uploads/Landslide/LS_GuaMar_Precipitation_ClimatSSP585.tif")
    landslide_earthquake_path: Path = Path("/home/ubuntu/uploads/Landslide/LS_GuaMar_earthquake_ngi_n1_mosaic_wgs84_opt.tif")
    landslide_corr_fact: float = 500.0
    landslide_n_years: int = 200
    landslide_dist: str = "poisson"
    population_data_dir: Path | None = Path("/home/ubuntu/uploads/Population")
    example_qgis_points_path: Path = Path(__file__).resolve().parents[2] / "data" / "examples" / "QGIS_Points_04_08_25.csv"
    example_qgis_lines_path: Path = Path(__file__).resolve().parents[2] / "data" / "examples" / "QGIS_Lignes_04_08_25.csv"
    example_qgis_polygons_path: Path = Path(__file__).resolve().parents[2] / "data" / "examples" / "QGIS_Polygones_04_08_25.csv"
    impact_engine_mode: str = "climada"
    allow_climada_fallback: bool = False
    climada_metric_crs: str = "EPSG:3857"
    climada_execution_profile: str = "default"
    climada_memory_budget_gb: float = 0.0
    climada_max_points_per_shard: int = 0
    climada_min_points_per_shard: int = 512
    climada_max_shard_retry_depth: int = 4
    climada_strict_required_components: bool = False
    climada_max_points_per_feature: int = 300
    climada_top_events_count: int = 20
    interdependency_state_threshold_s0_to_s1: float = 0.05
    interdependency_state_threshold_s1_to_s2: float = 0.15
    interdependency_state_threshold_s2_to_s3: float = 0.35
    interdependency_health_weight_s1: float = 0.3
    interdependency_health_weight_s2: float = 0.7
    interdependency_health_weight_s3: float = 1.0
    interdependency_dependency_state_threshold_s1: float = 0.75
    interdependency_dependency_state_threshold_s2: float = 0.55
    interdependency_dependency_state_threshold_s3: float = 0.35
    interdependency_uplift_s0: float = 0.0
    interdependency_uplift_s1: float = 0.10
    interdependency_uplift_s2: float = 0.25
    interdependency_uplift_s3: float = 0.45
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
    # Preferred order for dynamic STORM sources:
    # 1) explicit env override
    # 2) local repo default
    # 3) single-file parquet snapshots (legacy but valid)
    # 4) extracted dataset directories (txt/parquet datasets)
    alt_storm_parquet_file = Path("/home/ubuntu/uploads/STORM/storm_ds")
    alt_storm_cmcc_parquet_file = Path("/home/ubuntu/uploads/STORM/storm_ds_CMCC")
    alt_storm_parquet_dir = Path("/home/ubuntu/uploads/STORM/STORM_ds")
    alt_storm_cmcc_parquet_dir = Path("/home/ubuntu/uploads/STORM/STORM_CMCC_ds")
    configured_storm_parquet = Path(env.get("SIB_RISK_STORM_PARQUET_PATH", str(default_storm_parquet)))
    configured_storm_cmcc_parquet = Path(env.get("SIB_RISK_STORM_CMCC_PARQUET_PATH", str(default_storm_cmcc_parquet)))
    storm_parquet_path = _prefer_existing_path(
        configured_storm_parquet,
        default_storm_parquet,
        alt_storm_parquet_file,
        alt_storm_parquet_dir,
    )
    storm_cmcc_parquet_path = _prefer_existing_path(
        configured_storm_cmcc_parquet,
        default_storm_cmcc_parquet,
        alt_storm_cmcc_parquet_file,
        alt_storm_cmcc_parquet_dir,
    )

    default_hazard_topo = Path(__file__).resolve().parents[2] / "data" / "hazards" / "MNT_ANTS100m_HOMONIM_WGS84_PBMA_ZNEG.asc"
    alt_hazard_topo = Path(
        "/home/ubuntu/uploads/DEM_Topo/MNT_FACADE_ANTS_HOMONIM_PBMA/DONNEES/MNT_ANTS100m_HOMONIM_WGS84_PBMA_ZNEG.asc"
    )
    configured_hazard_topo = Path(env.get("SIB_RISK_HAZARD_SURGE_TOPO_PATH", str(default_hazard_topo)))
    hazard_surge_topo_path = _prefer_existing_path(
        configured_hazard_topo,
        default_hazard_topo,
        alt_hazard_topo,
    )

    default_d2_curve = Path(__file__).resolve().parents[2] / "data" / "vulnerability" / "Table_D2_Hazard_Fragility_and_Vulnerability_Curves_V1.1.0.xlsx"
    alt_d2_curve = Path("/home/ubuntu/uploads/Vulnerability/Table_D2_Hazard_Fragility_and_Vulnerability_Curves_V1.1.0.xlsx")
    configured_d2_curve = Path(env.get("SIB_RISK_D2_FLOOD_CURVE_FILE", str(default_d2_curve)))
    d2_flood_curve_file = _prefer_existing_path(
        configured_d2_curve,
        default_d2_curve,
        alt_d2_curve,
    )

    default_landslide_root = Path(__file__).resolve().parents[2] / "data" / "landslide"
    alt_landslide_root = Path("/home/ubuntu/uploads/Landslide")
    configured_landslide_root = Path(env.get("SIB_RISK_LANDSLIDE_ROOT", str(default_landslide_root)))
    landslide_root = _prefer_existing_path(
        configured_landslide_root,
        default_landslide_root,
        alt_landslide_root,
    )
    configured_landslide_precip_current = Path(
        env.get(
            "SIB_RISK_LANDSLIDE_PRECIP_CURRENT_PATH",
            str(landslide_root / "LS_GuaMar_Precipitation_ClimatActuel.tif"),
        )
    )
    configured_landslide_precip_ssp585 = Path(
        env.get(
            "SIB_RISK_LANDSLIDE_PRECIP_SSP585_PATH",
            str(landslide_root / "LS_GuaMar_Precipitation_ClimatSSP585.tif"),
        )
    )
    configured_landslide_earthquake = Path(
        env.get(
            "SIB_RISK_LANDSLIDE_EARTHQUAKE_PATH",
            str(landslide_root / "LS_GuaMar_earthquake_ngi_n1_mosaic_wgs84_opt.tif"),
        )
    )
    landslide_precip_current_path = _prefer_existing_path(
        configured_landslide_precip_current,
        landslide_root / "LS_GuaMar_Precipitation_ClimatActuel.tif",
        alt_landslide_root / "LS_GuaMar_Precipitation_ClimatActuel.tif",
    )
    landslide_precip_ssp585_path = _prefer_existing_path(
        configured_landslide_precip_ssp585,
        landslide_root / "LS_GuaMar_Precipitation_ClimatSSP585.tif",
        alt_landslide_root / "LS_GuaMar_Precipitation_ClimatSSP585.tif",
        alt_landslide_root / "LS_GuaMar_Precipitations_ClimatSSP585.tif",
    )
    landslide_earthquake_path = _prefer_existing_path(
        configured_landslide_earthquake,
        landslide_root / "LS_GuaMar_earthquake_ngi_n1_mosaic_wgs84_opt.tif",
        landslide_root / "LS_GuaMar_Eathquake.tif",
        landslide_root / "LS_GuaMar_Earthquake.tif",
        alt_landslide_root / "LS_GuaMar_earthquake_ngi_n1_mosaic_wgs84_opt.tif",
        alt_landslide_root / "LS_GuaMar_Eathquake.tif",
        alt_landslide_root / "LS_GuaMar_Earthquake.tif",
    )

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
        territory_grid_deg=float(env.get("SIB_RISK_TERRITORY_GRID_DEG", "0.2")),
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
        hazard_dynamic_max_tracks=int(env.get("SIB_RISK_HAZARD_DYNAMIC_MAX_TRACKS", "1200")),
        hazard_track_cache_max_entries=int(env.get("SIB_RISK_TRACK_CACHE_MAX_ENTRIES", "8")),
        multi_hazard_enabled=_env_bool(env, "SIB_RISK_MULTI_HAZARD_ENABLED", True),
        hazard_rain_model=str(env.get("SIB_RISK_HAZARD_RAIN_MODEL", "R-CLIPER")).strip(),
        hazard_rain_max_dist_inland_km=float(env.get("SIB_RISK_HAZARD_RAIN_MAX_DIST_INLAND_KM", "2000.0")),
        hazard_surge_topo_path=hazard_surge_topo_path,
        d2_flood_curve_file=d2_flood_curve_file,
        multi_hazard_rain_base_runoff_coeff=float(env.get("SIB_RISK_MULTI_HAZARD_RAIN_BASE_RUNOFF_COEFF", "0.25")),
        landslide_precip_current_path=landslide_precip_current_path,
        landslide_precip_ssp585_path=landslide_precip_ssp585_path,
        landslide_earthquake_path=landslide_earthquake_path,
        landslide_corr_fact=float(env.get("SIB_RISK_LANDSLIDE_CORR_FACT", "500.0")),
        landslide_n_years=int(env.get("SIB_RISK_LANDSLIDE_N_YEARS", "200")),
        landslide_dist=str(env.get("SIB_RISK_LANDSLIDE_DIST", "poisson")).strip().lower(),
        population_data_dir=Path(env.get("SIB_RISK_POPULATION_DATA_DIR", "/home/ubuntu/uploads/Population")) if env.get("SIB_RISK_POPULATION_DATA_DIR") else None,
        example_qgis_points_path=Path(env.get("SIB_RISK_EXAMPLE_QGIS_POINTS_PATH", str(Path(__file__).resolve().parents[2] / "data" / "examples" / "QGIS_Points_04_08_25.csv"))),
        example_qgis_lines_path=Path(env.get("SIB_RISK_EXAMPLE_QGIS_LINES_PATH", str(Path(__file__).resolve().parents[2] / "data" / "examples" / "QGIS_Lignes_04_08_25.csv"))),
        example_qgis_polygons_path=Path(env.get("SIB_RISK_EXAMPLE_QGIS_POLYGONS_PATH", str(Path(__file__).resolve().parents[2] / "data" / "examples" / "QGIS_Polygones_04_08_25.csv"))),
        impact_engine_mode=str(env.get("SIB_RISK_IMPACT_ENGINE_MODE", "climada")).strip().lower(),
        allow_climada_fallback=_env_bool(env, "SIB_RISK_ALLOW_CLIMADA_FALLBACK", False),
        climada_metric_crs=str(env.get("SIB_RISK_CLIMADA_METRIC_CRS", "EPSG:3857")).strip(),
        climada_execution_profile=str(env.get("SIB_RISK_CLIMADA_EXECUTION_PROFILE", "default")).strip().lower(),
        climada_memory_budget_gb=float(env.get("SIB_RISK_CLIMADA_MEMORY_BUDGET_GB", "0")),
        climada_max_points_per_shard=int(env.get("SIB_RISK_CLIMADA_MAX_POINTS_PER_SHARD", "0")),
        climada_min_points_per_shard=int(env.get("SIB_RISK_CLIMADA_MIN_POINTS_PER_SHARD", "512")),
        climada_max_shard_retry_depth=int(env.get("SIB_RISK_CLIMADA_MAX_SHARD_RETRY_DEPTH", "4")),
        climada_strict_required_components=_env_bool(env, "SIB_RISK_CLIMADA_STRICT_REQUIRED_COMPONENTS", False),
        climada_max_points_per_feature=int(env.get("SIB_RISK_CLIMADA_MAX_POINTS_PER_FEATURE", "300")),
        climada_top_events_count=int(env.get("SIB_RISK_CLIMADA_TOP_EVENTS_COUNT", "20")),
        interdependency_state_threshold_s0_to_s1=float(env.get("SIB_RISK_INTERDEPENDENCY_STATE_THRESHOLD_S0_TO_S1", "0.05")),
        interdependency_state_threshold_s1_to_s2=float(env.get("SIB_RISK_INTERDEPENDENCY_STATE_THRESHOLD_S1_TO_S2", "0.15")),
        interdependency_state_threshold_s2_to_s3=float(env.get("SIB_RISK_INTERDEPENDENCY_STATE_THRESHOLD_S2_TO_S3", "0.35")),
        interdependency_health_weight_s1=float(env.get("SIB_RISK_INTERDEPENDENCY_HEALTH_WEIGHT_S1", "0.3")),
        interdependency_health_weight_s2=float(env.get("SIB_RISK_INTERDEPENDENCY_HEALTH_WEIGHT_S2", "0.7")),
        interdependency_health_weight_s3=float(env.get("SIB_RISK_INTERDEPENDENCY_HEALTH_WEIGHT_S3", "1.0")),
        interdependency_dependency_state_threshold_s1=float(env.get("SIB_RISK_INTERDEPENDENCY_DEPENDENCY_STATE_THRESHOLD_S1", "0.75")),
        interdependency_dependency_state_threshold_s2=float(env.get("SIB_RISK_INTERDEPENDENCY_DEPENDENCY_STATE_THRESHOLD_S2", "0.55")),
        interdependency_dependency_state_threshold_s3=float(env.get("SIB_RISK_INTERDEPENDENCY_DEPENDENCY_STATE_THRESHOLD_S3", "0.35")),
        interdependency_uplift_s0=float(env.get("SIB_RISK_INTERDEPENDENCY_UPLIFT_S0", "0.0")),
        interdependency_uplift_s1=float(env.get("SIB_RISK_INTERDEPENDENCY_UPLIFT_S1", "0.10")),
        interdependency_uplift_s2=float(env.get("SIB_RISK_INTERDEPENDENCY_UPLIFT_S2", "0.25")),
        interdependency_uplift_s3=float(env.get("SIB_RISK_INTERDEPENDENCY_UPLIFT_S3", "0.45")),
        cors_allowed_origins=_env_csv(
            env,
            "SIB_RISK_CORS_ALLOWED_ORIGINS",
            (
                "https://app.sib.elio.dev",
                "https://sib.dev.elio.bottagisio.com",
            ),
        ),
    )
