#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import re
from pathlib import Path
import shutil
import sys
import tarfile
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.risk_engine.hazard_comparison_registry import (  # noqa: E402
    DEFAULT_HAZARD_COMPARISON_REGISTRY_PATH,
    load_hazard_comparison_registry,
    validate_hazard_comparison_registry,
)

UTC = timezone.utc
DEFAULT_HAZARD_COMPARISON_CATALOGS_PATH = REPO_ROOT / "config" / "hazard-comparison" / "catalogs.json"

BASIN_ID_BY_CODE: dict[str, int] = {
    "NA": 1,
    "SI": 3,
    "SP": 4,
}
PROVIDER_KEYS = ("storm", "storm_cmcc")
RAW_COLUMNS = [
    "Year",
    "Month",
    "TC number",
    "Time step",
    "Basin ID",
    "Latitude",
    "Longitude",
    "Minimum pressure",
    "Maximum wind speed",
    "Radius to maximum winds",
    "Category",
    "Landfall",
    "Distance to land",
]
OUTPUT_COLUMNS = [
    "Year",
    "Month",
    "Basin ID",
    "time_step",
    "track_id",
    "lat",
    "lon",
    "p_c",
    "wind_max",
    "rmax",
    "Category",
    "Landfall",
    "distance_to_land_km",
    "dataset_id",
    "source_year_in_block",
    "source_tc_number",
]
_BLOCK_INDEX_RE = re.compile(r"_1000_YEARS_(\d+)")


@dataclass(frozen=True)
class ComparisonCatalogTarget:
    basin_code: str
    basin_id: int
    provider: str
    provider_label: str
    parquet_path: Path
    manifest_path: Path
    wind_unit_in: str
    radius_unit_in: str
    timestep_hours: int


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_catalog_runtime_deps() -> tuple[Any, Any, Any]:
    missing: list[str] = []
    try:
        import numpy as np  # type: ignore
    except Exception:
        np = None  # type: ignore[assignment]
        missing.append("numpy")
    try:
        import pandas as pd  # type: ignore
    except Exception:
        pd = None  # type: ignore[assignment]
        missing.append("pandas")
    try:
        import pyarrow as pa  # type: ignore
        import pyarrow.parquet as pq  # type: ignore
    except Exception:
        pa = None  # type: ignore[assignment]
        pq = None  # type: ignore[assignment]
        missing.append("pyarrow")
    if missing:
        raise RuntimeError(
            "Missing dependencies for prepare_hazard_comparison_inputs.py: "
            + ", ".join(sorted(set(missing)))
            + ". Install backend requirements and retry."
        )
    return np, pd, (pa, pq)


def _parse_block_index(path: Path) -> int:
    match = _BLOCK_INDEX_RE.search(path.name)
    if not match:
        raise ValueError(f"Could not parse block index from file name: {path.name}")
    return int(match.group(1))


def load_catalog_targets(path: Path | None = None) -> dict[tuple[str, str], ComparisonCatalogTarget]:
    resolved = Path(path or DEFAULT_HAZARD_COMPARISON_CATALOGS_PATH)
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Hazard comparison catalogs config must be a JSON object: {resolved}")

    catalogs = payload.get("catalogs")
    if not isinstance(catalogs, dict):
        raise ValueError(f"Missing catalogs map in {resolved}")

    targets: dict[tuple[str, str], ComparisonCatalogTarget] = {}
    errors: list[str] = []
    for basin_code, basin_id in BASIN_ID_BY_CODE.items():
        basin_entry = catalogs.get(basin_code)
        if not isinstance(basin_entry, dict):
            errors.append(f"Missing basin catalog entry for {basin_code}")
            continue
        for provider in PROVIDER_KEYS:
            entry = basin_entry.get(provider)
            if not isinstance(entry, dict):
                errors.append(f"Missing provider catalog entry for {basin_code}/{provider}")
                continue
            actual_basin_id = int(entry.get("basin_id"))
            if actual_basin_id != basin_id:
                errors.append(
                    f"Unexpected basin_id for {basin_code}/{provider}: expected {basin_id}, got {actual_basin_id}"
                )
                continue
            parquet_path = Path(str(entry.get("parquet_path") or ""))
            manifest_path = Path(str(entry.get("manifest_path") or ""))
            if not parquet_path:
                errors.append(f"Missing parquet_path for {basin_code}/{provider}")
                continue
            if not manifest_path:
                errors.append(f"Missing manifest_path for {basin_code}/{provider}")
                continue
            targets[(basin_code, provider)] = ComparisonCatalogTarget(
                basin_code=basin_code,
                basin_id=actual_basin_id,
                provider=provider,
                provider_label=str(entry.get("provider_label") or provider.upper()),
                parquet_path=parquet_path,
                manifest_path=manifest_path,
                wind_unit_in=str(entry.get("wind_unit_in") or "m/s"),
                radius_unit_in=str(entry.get("radius_unit_in") or "km"),
                timestep_hours=int(entry.get("timestep_hours") or 3),
            )
    if errors:
        raise ValueError("Invalid hazard comparison catalogs config:\n- " + "\n- ".join(errors))
    return targets


def _catalog_summary_default_path(catalogs_path: Path) -> Path:
    payload = json.loads(Path(catalogs_path).read_text(encoding="utf-8"))
    meta = payload.get("meta") if isinstance(payload, dict) else {}
    output_root = Path(str((meta or {}).get("output_root") or (REPO_ROOT / "outputs" / "hazard-comparison-inputs")))
    return output_root / "preparation-summary.json"


def _source_specs_from_registry(registry_path: Path | None = None) -> dict[tuple[str, str], tuple[Path, str]]:
    registry = load_hazard_comparison_registry(registry_path)
    shared = registry.shared_sources
    raw_catalogs = shared.get("raw_track_catalogs") if isinstance(shared.get("raw_track_catalogs"), dict) else {}
    patterns_by_basin = raw_catalogs.get("patterns_by_basin") if isinstance(raw_catalogs.get("patterns_by_basin"), dict) else {}

    storm_dir = Path(str(raw_catalogs.get("storm_dir") or ""))
    storm_cmcc_dir = Path(str(raw_catalogs.get("storm_cmcc_dir") or ""))
    specs: dict[tuple[str, str], tuple[Path, str]] = {}
    for basin_code in BASIN_ID_BY_CODE:
        basin_patterns = patterns_by_basin.get(basin_code)
        if not isinstance(basin_patterns, dict):
            raise ValueError(f"Missing raw track patterns for basin {basin_code}")
        specs[(basin_code, "storm")] = (storm_dir, str(basin_patterns.get("storm") or "").strip())
        specs[(basin_code, "storm_cmcc")] = (storm_cmcc_dir, str(basin_patterns.get("storm_cmcc") or "").strip())
    return specs


def _single_raster_member(archive_path: Path) -> tarfile.TarInfo:
    with tarfile.open(archive_path, mode="r:gz") as tar:
        raster_members = [
            member
            for member in tar.getmembers()
            if member.isfile() and member.name.lower().endswith((".tif", ".tiff"))
        ]
    if len(raster_members) != 1:
        raise ValueError(
            f"Expected exactly one raster member in {archive_path}, found {len(raster_members)}"
        )
    return raster_members[0]


def extract_canonical_topography(
    archive_path: Path,
    canonical_path: Path,
    *,
    dry_run: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    if not archive_path.exists():
        raise FileNotFoundError(f"Missing Copernicus archive: {archive_path}")

    member = _single_raster_member(archive_path)
    if canonical_path.exists() and not overwrite:
        return {
            "status": "already_present",
            "archive_path": str(archive_path),
            "canonical_path": str(canonical_path),
            "archive_member": member.name,
            "size_bytes": int(canonical_path.stat().st_size),
        }
    if dry_run:
        return {
            "status": "would_extract",
            "archive_path": str(archive_path),
            "canonical_path": str(canonical_path),
            "archive_member": member.name,
        }

    tmp_path = canonical_path.with_suffix(canonical_path.suffix + ".tmp")
    canonical_path.parent.mkdir(parents=True, exist_ok=True)
    if tmp_path.exists():
        tmp_path.unlink()

    with tarfile.open(archive_path, mode="r:gz") as tar:
        extracted = tar.extractfile(member)
        if extracted is None:
            raise ValueError(f"Could not extract raster member {member.name} from {archive_path}")
        with extracted, tmp_path.open("wb") as tmp_fp:
            shutil.copyfileobj(extracted, tmp_fp, length=8 * 1024 * 1024)

    tmp_path.replace(canonical_path)
    return {
        "status": "extracted",
        "archive_path": str(archive_path),
        "canonical_path": str(canonical_path),
        "archive_member": member.name,
        "size_bytes": int(canonical_path.stat().st_size),
    }


def prepare_comparison_topography(
    *,
    registry_path: Path | None = None,
    territory_ids: set[str] | None = None,
    dry_run: bool = False,
    overwrite: bool = False,
) -> list[dict[str, Any]]:
    registry = load_hazard_comparison_registry(registry_path)
    selected_ids = territory_ids or set(registry.included_ids)
    results: list[dict[str, Any]] = []

    for territory_id in registry.included_ids:
        if territory_id not in selected_ids:
            continue
        entry = registry.territories[territory_id]
        topography = entry.get("topography") if isinstance(entry.get("topography"), dict) else None
        if not isinstance(topography, dict):
            raise ValueError(f"Missing topography section for territory {territory_id}")

        canonical_path = Path(str(topography.get("canonical_copernicus_path") or ""))
        archive_path = Path(str(topography.get("copernicus_archive_path") or ""))
        if not canonical_path:
            raise ValueError(f"Missing canonical_copernicus_path for territory {territory_id}")
        if not archive_path:
            raise ValueError(f"Missing copernicus_archive_path for territory {territory_id}")

        if canonical_path.exists() and not overwrite:
            results.append(
                {
                    "territory_id": territory_id,
                    "label": str(entry.get("label") or territory_id),
                    "status": "already_ready",
                    "archive_path": str(archive_path),
                    "canonical_path": str(canonical_path),
                    "size_bytes": int(canonical_path.stat().st_size),
                }
            )
            continue

        extraction = extract_canonical_topography(
            archive_path,
            canonical_path,
            dry_run=dry_run,
            overwrite=overwrite,
        )
        extraction.update(
            {
                "territory_id": territory_id,
                "label": str(entry.get("label") or territory_id),
            }
        )
        results.append(extraction)
    return results


def _catalog_schema(pa: Any) -> Any:
    return pa.schema(
        [
            pa.field("Year", pa.int32()),
            pa.field("Month", pa.int16()),
            pa.field("Basin ID", pa.int16()),
            pa.field("time_step", pa.int32()),
            pa.field("track_id", pa.string()),
            pa.field("lat", pa.float64()),
            pa.field("lon", pa.float64()),
            pa.field("p_c", pa.float64()),
            pa.field("wind_max", pa.float64()),
            pa.field("rmax", pa.float64()),
            pa.field("Category", pa.int16()),
            pa.field("Landfall", pa.int16()),
            pa.field("distance_to_land_km", pa.float64()),
            pa.field("dataset_id", pa.int32()),
            pa.field("source_year_in_block", pa.int32()),
            pa.field("source_tc_number", pa.int32()),
        ]
    )


def _normalize_track_chunk(chunk: Any, *, basin_id: int, dataset_id: int, provider: str, basin_code: str, np: Any, pd: Any) -> Any:
    chunk = chunk.rename(
        columns={
            "Time step": "time_step",
            "Latitude": "lat",
            "Longitude": "lon",
            "Minimum pressure": "p_c",
            "Maximum wind speed": "wind_max",
            "Radius to maximum winds": "rmax",
            "Distance to land": "distance_to_land_km",
            "TC number": "source_tc_number",
        }
    )

    numeric_cols = [
        "Year",
        "Month",
        "source_tc_number",
        "time_step",
        "Basin ID",
        "lat",
        "lon",
        "p_c",
        "wind_max",
        "rmax",
        "Category",
        "Landfall",
        "distance_to_land_km",
    ]
    for column_name in numeric_cols:
        chunk[column_name] = pd.to_numeric(chunk[column_name], errors="coerce")

    required_cols = ["Year", "source_tc_number", "time_step", "Basin ID", "lat", "lon", "p_c", "wind_max", "rmax"]
    chunk = chunk.dropna(subset=required_cols)
    chunk = chunk[chunk["Basin ID"].astype(int) == int(basin_id)].copy()
    if chunk.empty:
        return chunk

    source_year = chunk["Year"].astype(int)
    source_track = chunk["source_tc_number"].astype(int)
    chunk["source_year_in_block"] = source_year
    chunk["Year"] = source_year + (1000 * int(dataset_id))
    chunk["Month"] = chunk["Month"].fillna(0).astype(int)
    chunk["time_step"] = chunk["time_step"].astype(int)
    chunk["Basin ID"] = chunk["Basin ID"].astype(int)
    chunk["lat"] = chunk["lat"].astype(float)
    chunk["lon"] = chunk["lon"].astype(float)
    chunk["p_c"] = chunk["p_c"].astype(float)
    chunk["wind_max"] = chunk["wind_max"].astype(float)
    chunk["rmax"] = chunk["rmax"].astype(float)
    chunk["Category"] = chunk["Category"].fillna(0).astype(int)
    chunk["Landfall"] = chunk["Landfall"].fillna(0).astype(int)
    chunk["distance_to_land_km"] = chunk["distance_to_land_km"].astype(float)
    chunk["dataset_id"] = int(dataset_id)
    chunk["source_tc_number"] = source_track
    chunk["track_id"] = [
        f"{provider}:{basin_code}:{int(year_value)}:{int(track_value)}"
        for year_value, track_value in zip(chunk["Year"].astype(int).tolist(), source_track.tolist())
    ]

    chunk = chunk[OUTPUT_COLUMNS].copy()
    if not np.isfinite(chunk[["lat", "lon", "p_c", "wind_max", "rmax", "distance_to_land_km"]].to_numpy()).all():
        raise ValueError(
            f"Non-finite numeric values remain after normalization for {provider}/{basin_code}/dataset {dataset_id}"
        )
    return chunk


def build_comparison_catalog(
    *,
    target: ComparisonCatalogTarget,
    raw_dir: Path,
    raw_pattern: str,
    dry_run: bool = False,
    overwrite: bool = False,
    max_source_files: int = 0,
) -> dict[str, Any]:
    if not raw_dir.exists():
        raise FileNotFoundError(f"Missing raw track directory for {target.provider}/{target.basin_code}: {raw_dir}")
    files = sorted(raw_dir.glob(raw_pattern))
    if not files:
        raise FileNotFoundError(
            f"No raw track files found for {target.provider}/{target.basin_code}: dir={raw_dir} pattern={raw_pattern}"
        )
    if max_source_files > 0:
        files = files[: int(max_source_files)]

    source_file_rows: list[dict[str, Any]] = []
    summary = {
        "status": "dry_run" if dry_run else "built",
        "basin_code": target.basin_code,
        "basin_id": int(target.basin_id),
        "provider": target.provider,
        "provider_label": target.provider_label,
        "parquet_path": str(target.parquet_path),
        "manifest_path": str(target.manifest_path),
        "source_dir": str(raw_dir),
        "source_pattern": raw_pattern,
        "selected_source_files": len(files),
        "selected_dataset_ids": [int(_parse_block_index(path)) for path in files],
        "wind_unit_in": target.wind_unit_in,
        "radius_unit_in": target.radius_unit_in,
        "timestep_hours": int(target.timestep_hours),
    }
    if dry_run:
        summary["source_files"] = [str(path) for path in files]
        return summary

    np, pd, arrow_mods = _require_catalog_runtime_deps()
    pa, pq = arrow_mods
    schema = _catalog_schema(pa)

    if target.parquet_path.exists() and not overwrite:
        raise FileExistsError(
            f"Catalog output already exists for {target.provider}/{target.basin_code}: {target.parquet_path}. Use --overwrite to rebuild."
        )
    if target.manifest_path.exists() and not overwrite:
        raise FileExistsError(
            f"Catalog manifest already exists for {target.provider}/{target.basin_code}: {target.manifest_path}. Use --overwrite to rebuild."
        )

    target.parquet_path.parent.mkdir(parents=True, exist_ok=True)
    target.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_parquet_path = target.parquet_path.with_suffix(target.parquet_path.suffix + ".tmp")
    if tmp_parquet_path.exists():
        tmp_parquet_path.unlink()

    writer = pq.ParquetWriter(tmp_parquet_path, schema=schema, compression="zstd")
    total_rows = 0
    track_ids: set[str] = set()
    year_min: int | None = None
    year_max: int | None = None
    build_started_at = _utc_now()

    try:
        for raw_path in files:
            dataset_id = _parse_block_index(raw_path)
            rows_for_file = 0
            tracks_for_file: set[str] = set()

            for chunk in pd.read_csv(
                raw_path,
                names=RAW_COLUMNS,
                sep=",",
                skipinitialspace=True,
                chunksize=250_000,
                low_memory=False,
            ):
                normalized = _normalize_track_chunk(
                    chunk,
                    basin_id=target.basin_id,
                    dataset_id=dataset_id,
                    provider=target.provider,
                    basin_code=target.basin_code,
                    np=np,
                    pd=pd,
                )
                if normalized.empty:
                    continue
                table = pa.Table.from_pandas(normalized, schema=schema, preserve_index=False, safe=False)
                writer.write_table(table)

                rows_for_file += int(len(normalized))
                total_rows += int(len(normalized))
                chunk_track_ids = set(str(value) for value in normalized["track_id"].dropna().unique().tolist())
                tracks_for_file.update(chunk_track_ids)
                track_ids.update(chunk_track_ids)
                chunk_year_min = int(normalized["Year"].min())
                chunk_year_max = int(normalized["Year"].max())
                year_min = chunk_year_min if year_min is None else min(year_min, chunk_year_min)
                year_max = chunk_year_max if year_max is None else max(year_max, chunk_year_max)

            source_file_rows.append(
                {
                    "dataset_id": int(dataset_id),
                    "source_path": str(raw_path),
                    "size_bytes": int(raw_path.stat().st_size),
                    "row_count": int(rows_for_file),
                    "track_count": int(len(tracks_for_file)),
                }
            )

        if total_rows <= 0:
            raise ValueError(
                f"No rows were written for {target.provider}/{target.basin_code}; check the source pattern or basin mapping."
            )
    except Exception:
        writer.close()
        if tmp_parquet_path.exists():
            tmp_parquet_path.unlink()
        raise
    else:
        writer.close()
        tmp_parquet_path.replace(target.parquet_path)

    manifest = {
        "generated_at": _utc_now(),
        "build_started_at": build_started_at,
        "column_contract_version": 2,
        "track_identity_version": 2,
        "track_identity_description": "track_id is year-aware and unique per synthetic cyclone instance",
        "basin_code": target.basin_code,
        "basin_id": int(target.basin_id),
        "provider": target.provider,
        "provider_label": target.provider_label,
        "parquet_path": str(target.parquet_path),
        "row_count": int(total_rows),
        "track_count": int(len(track_ids)),
        "year_min": int(year_min) if year_min is not None else None,
        "year_max": int(year_max) if year_max is not None else None,
        "years_covered": (int(year_max) - int(year_min) + 1) if year_min is not None and year_max is not None else 0,
        "wind_unit_in": target.wind_unit_in,
        "radius_unit_in": target.radius_unit_in,
        "timestep_hours": int(target.timestep_hours),
        "raw_source_dir": str(raw_dir),
        "raw_source_pattern": raw_pattern,
        "source_files": source_file_rows,
        "columns": list(OUTPUT_COLUMNS),
    }
    target.manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    summary.update(
        {
            "row_count": int(total_rows),
            "track_count": int(len(track_ids)),
            "year_min": manifest["year_min"],
            "year_max": manifest["year_max"],
            "years_covered": manifest["years_covered"],
            "source_files": source_file_rows,
        }
    )
    return summary


def prepare_hazard_comparison_inputs(
    *,
    registry_path: Path | None = None,
    catalogs_path: Path | None = None,
    territories: set[str] | None = None,
    basins: set[str] | None = None,
    providers: set[str] | None = None,
    dry_run: bool = False,
    overwrite: bool = False,
    skip_topography: bool = False,
    skip_catalogs: bool = False,
    max_source_files: int = 0,
    summary_path: Path | None = None,
) -> dict[str, Any]:
    validation = validate_hazard_comparison_registry(registry_path, check_filesystem=True)
    validation.raise_for_errors()

    targets = load_catalog_targets(catalogs_path)
    source_specs = _source_specs_from_registry(registry_path)
    selected_basins = set(basins or BASIN_ID_BY_CODE.keys())
    selected_providers = set(providers or PROVIDER_KEYS)

    summary = {
        "generated_at": _utc_now(),
        "registry_path": str(Path(registry_path or DEFAULT_HAZARD_COMPARISON_REGISTRY_PATH)),
        "catalogs_path": str(Path(catalogs_path or DEFAULT_HAZARD_COMPARISON_CATALOGS_PATH)),
        "dry_run": bool(dry_run),
        "overwrite": bool(overwrite),
        "max_source_files": int(max_source_files),
        "topography": [],
        "catalogs": [],
    }

    if not skip_topography:
        summary["topography"] = prepare_comparison_topography(
            registry_path=registry_path,
            territory_ids=territories,
            dry_run=dry_run,
            overwrite=overwrite,
        )

    if not skip_catalogs:
        for basin_code in sorted(selected_basins):
            if basin_code not in BASIN_ID_BY_CODE:
                raise ValueError(f"Unsupported basin selection: {basin_code}")
            for provider in PROVIDER_KEYS:
                if provider not in selected_providers:
                    continue
                target = targets[(basin_code, provider)]
                raw_dir, raw_pattern = source_specs[(basin_code, provider)]
                summary["catalogs"].append(
                    build_comparison_catalog(
                        target=target,
                        raw_dir=raw_dir,
                        raw_pattern=raw_pattern,
                        dry_run=dry_run,
                        overwrite=overwrite,
                        max_source_files=max_source_files,
                    )
                )

    output_summary_path = Path(summary_path or _catalog_summary_default_path(Path(catalogs_path or DEFAULT_HAZARD_COMPARISON_CATALOGS_PATH)))
    if not dry_run:
        output_summary_path.parent.mkdir(parents=True, exist_ok=True)
        output_summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        summary["summary_path"] = str(output_summary_path)
    else:
        summary["summary_path"] = str(output_summary_path)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare immutable inputs for the hazard-only comparison chain (Copernicus extraction + dedicated STORM parquet catalogs)."
    )
    parser.add_argument(
        "--registry-path",
        default=str(DEFAULT_HAZARD_COMPARISON_REGISTRY_PATH),
        help="Territory registry JSON path.",
    )
    parser.add_argument(
        "--catalogs-path",
        default=str(DEFAULT_HAZARD_COMPARISON_CATALOGS_PATH),
        help="Comparison catalogs JSON path.",
    )
    parser.add_argument(
        "--territories",
        nargs="*",
        default=None,
        help="Optional subset of territory ids for the topography extraction step.",
    )
    parser.add_argument(
        "--basins",
        nargs="*",
        default=None,
        help="Optional subset of basin codes to build (NA, SI, SP).",
    )
    parser.add_argument(
        "--providers",
        nargs="*",
        default=None,
        help="Optional subset of providers to build (storm, storm_cmcc).",
    )
    parser.add_argument("--skip-topography", action="store_true", help="Skip Copernicus extraction.")
    parser.add_argument("--skip-catalogs", action="store_true", help="Skip STORM parquet catalog generation.")
    parser.add_argument("--dry-run", action="store_true", help="Audit inputs without writing outputs.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing extracted rasters and parquet catalogs.")
    parser.add_argument(
        "--max-source-files",
        type=int,
        default=0,
        help="Optional cap on the number of raw txt files selected per catalog (0 means all).",
    )
    parser.add_argument(
        "--summary-path",
        default=None,
        help="Optional explicit summary JSON output path.",
    )
    args = parser.parse_args()

    summary = prepare_hazard_comparison_inputs(
        registry_path=Path(args.registry_path),
        catalogs_path=Path(args.catalogs_path),
        territories={str(value) for value in args.territories} if args.territories else None,
        basins={str(value).upper() for value in args.basins} if args.basins else None,
        providers={str(value).lower() for value in args.providers} if args.providers else None,
        dry_run=bool(args.dry_run),
        overwrite=bool(args.overwrite),
        skip_topography=bool(args.skip_topography),
        skip_catalogs=bool(args.skip_catalogs),
        max_source_files=int(args.max_source_files),
        summary_path=Path(args.summary_path) if args.summary_path else None,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()