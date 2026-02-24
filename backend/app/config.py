from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class Settings:
    app_name: str = "SIB Cyclone Risk API"
    api_prefix: str = "/api/v1"
    job_root: Path = Path("/tmp/sib-risk-jobs")
    job_ttl_hours: int = 24
    max_upload_mb: int = 50
    worker_concurrency: int = 1
    demo_result_path: Path = Path(__file__).resolve().parents[2] / "web" / "data" / "sib-thesis-demo.json"
    storm_years: int = 2000
    default_sampling_spacing_m: float = 100.0
    data_root: Path = Path(__file__).resolve().parents[2] / "data"
    hazard_storm_path: Path = Path(__file__).resolve().parents[2] / "data" / "hazards" / "tc_hazard_guadeloupe.h5"
    hazard_storm_cmcc_path: Path = Path(__file__).resolve().parents[2] / "data" / "hazards" / "tc_hazard_guadeloupe_CMCC.h5"
    storm_parquet_path: Path = Path(__file__).resolve().parents[2] / "data" / "hazards" / "storm_ds"
    storm_cmcc_parquet_path: Path = Path(__file__).resolve().parents[2] / "data" / "hazards" / "storm_ds_CMCC"
    example_qgis_points_path: Path = Path(__file__).resolve().parents[2] / "data" / "examples" / "QGIS_Points_04_08_25.csv"
    example_qgis_lines_path: Path = Path(__file__).resolve().parents[2] / "data" / "examples" / "QGIS_Lignes_04_08_25.csv"
    example_qgis_polygons_path: Path = Path(__file__).resolve().parents[2] / "data" / "examples" / "QGIS_Polygones_04_08_25.csv"


def load_settings() -> Settings:
    env = os.environ

    job_root = Path(env.get("SIB_RISK_JOB_ROOT", "/tmp/sib-risk-jobs"))
    demo_result_path = Path(
        env.get(
            "SIB_RISK_DEMO_RESULT_PATH",
            str(Path(__file__).resolve().parents[2] / "web" / "data" / "sib-thesis-demo.json"),
        )
    )

    return Settings(
        app_name=env.get("SIB_RISK_APP_NAME", "SIB Cyclone Risk API"),
        api_prefix=env.get("SIB_RISK_API_PREFIX", "/api/v1"),
        job_root=job_root,
        job_ttl_hours=int(env.get("SIB_RISK_JOB_TTL_HOURS", "24")),
        max_upload_mb=int(env.get("SIB_RISK_MAX_UPLOAD_MB", "50")),
        worker_concurrency=int(env.get("SIB_RISK_WORKER_CONCURRENCY", "1")),
        demo_result_path=demo_result_path,
        storm_years=int(env.get("SIB_RISK_STORM_YEARS", "2000")),
        default_sampling_spacing_m=float(env.get("SIB_RISK_DEFAULT_SAMPLING_SPACING_M", "100")),
        data_root=Path(env.get("SIB_RISK_DATA_ROOT", str(Path(__file__).resolve().parents[2] / "data"))),
        hazard_storm_path=Path(env.get("SIB_RISK_HAZARD_STORM_PATH", str(Path(__file__).resolve().parents[2] / "data" / "hazards" / "tc_hazard_guadeloupe.h5"))),
        hazard_storm_cmcc_path=Path(env.get("SIB_RISK_HAZARD_STORM_CMCC_PATH", str(Path(__file__).resolve().parents[2] / "data" / "hazards" / "tc_hazard_guadeloupe_CMCC.h5"))),
        storm_parquet_path=Path(env.get("SIB_RISK_STORM_PARQUET_PATH", str(Path(__file__).resolve().parents[2] / "data" / "hazards" / "storm_ds"))),
        storm_cmcc_parquet_path=Path(env.get("SIB_RISK_STORM_CMCC_PARQUET_PATH", str(Path(__file__).resolve().parents[2] / "data" / "hazards" / "storm_ds_CMCC"))),
        example_qgis_points_path=Path(env.get("SIB_RISK_EXAMPLE_QGIS_POINTS_PATH", str(Path(__file__).resolve().parents[2] / "data" / "examples" / "QGIS_Points_04_08_25.csv"))),
        example_qgis_lines_path=Path(env.get("SIB_RISK_EXAMPLE_QGIS_LINES_PATH", str(Path(__file__).resolve().parents[2] / "data" / "examples" / "QGIS_Lignes_04_08_25.csv"))),
        example_qgis_polygons_path=Path(env.get("SIB_RISK_EXAMPLE_QGIS_POLYGONS_PATH", str(Path(__file__).resolve().parents[2] / "data" / "examples" / "QGIS_Polygones_04_08_25.csv"))),
    )
