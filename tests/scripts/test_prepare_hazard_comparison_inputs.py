from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import tarfile

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from scripts import prepare_hazard_comparison_inputs


def test_load_catalog_targets_exposes_expected_basin_provider_matrix() -> None:
    targets = prepare_hazard_comparison_inputs.load_catalog_targets()

    assert sorted(targets.keys()) == [
        ("NA", "storm"),
        ("NA", "storm_cmcc"),
        ("SI", "storm"),
        ("SI", "storm_cmcc"),
        ("SP", "storm"),
        ("SP", "storm_cmcc"),
    ]
    assert targets[("SP", "storm")].basin_id == 4
    assert str(targets[("NA", "storm_cmcc")].parquet_path).endswith("/catalogs/na/storm_cmcc_tracks.parquet")


def test_extract_canonical_topography_writes_single_raster_member(tmp_path: Path) -> None:
    archive_path = tmp_path / "Demo_rasters_COP30.tar.gz"
    canonical_path = tmp_path / "Demo_COP30.tif"
    raster_bytes = b"demo-raster-bytes"

    with tarfile.open(archive_path, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="output_hh.tif")
        info.size = len(raster_bytes)
        tar.addfile(info, io.BytesIO(raster_bytes))

    result = prepare_hazard_comparison_inputs.extract_canonical_topography(archive_path, canonical_path)

    assert result["status"] == "extracted"
    assert canonical_path.read_bytes() == raster_bytes


def test_build_comparison_catalog_normalizes_unique_track_ids_and_years(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "STORM_DATA_IBTRACS_NA_1000_YEARS_0.txt").write_text(
        "0,6,10,0,1,15.0,-61.0,990,20,40,2,0,100\n"
        "0,6,10,1,1,15.1,-61.1,989,22,41,2,0,90\n",
        encoding="utf-8",
    )
    (raw_dir / "STORM_DATA_IBTRACS_NA_1000_YEARS_1.txt").write_text(
        "1,7,10,0,1,16.0,-60.0,988,25,42,3,1,80\n"
        "1,7,10,1,1,16.1,-60.1,987,26,43,3,1,70\n",
        encoding="utf-8",
    )

    target = prepare_hazard_comparison_inputs.ComparisonCatalogTarget(
        basin_code="NA",
        basin_id=1,
        provider="storm",
        provider_label="STORM",
        parquet_path=tmp_path / "catalogs" / "na" / "storm_tracks.parquet",
        manifest_path=tmp_path / "catalogs" / "na" / "storm_tracks.manifest.json",
        wind_unit_in="m/s",
        radius_unit_in="km",
        timestep_hours=3,
    )

    summary = prepare_hazard_comparison_inputs.build_comparison_catalog(
        target=target,
        raw_dir=raw_dir,
        raw_pattern="STORM_DATA_IBTRACS_NA_1000_YEARS_*.txt",
    )

    df = pd.read_parquet(target.parquet_path)
    manifest = json.loads(target.manifest_path.read_text(encoding="utf-8"))

    assert summary["row_count"] == 4
    assert summary["track_count"] == 2
    assert sorted(df["track_id"].unique().tolist()) == ["storm:NA:0:10", "storm:NA:1001:10"]
    assert sorted(df["Year"].unique().tolist()) == [0, 1001]
    assert sorted(df["dataset_id"].unique().tolist()) == [0, 1]
    assert sorted(df["source_tc_number"].unique().tolist()) == [10]
    assert manifest["row_count"] == 4
    assert manifest["track_count"] == 2
    assert manifest["track_identity_version"] == 2
    assert [item["dataset_id"] for item in manifest["source_files"]] == [0, 1]