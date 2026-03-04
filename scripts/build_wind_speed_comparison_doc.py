#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
import re
import sys
from typing import Any

import numpy as np
import pandas as pd
from climada.hazard import Hazard


UTC = timezone.utc

COLUMNS = [
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

USECOLS = ["Year", "Basin ID", "Latitude", "Longitude", "Maximum wind speed", "TC number"]

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
from app.config import load_settings  # noqa: E402


@dataclass(frozen=True)
class RegionSpec:
    key: str
    label: str
    lat_min: float | None = None
    lat_max: float | None = None
    lon_min: float | None = None
    lon_max: float | None = None


def _parse_block(path: Path) -> int:
    m = re.search(r"_1000_YEARS_(\d+)", path.name)
    if not m:
        return 0
    return int(m.group(1))


def _normalize_wind_unit(raw: str) -> str:
    unit = str(raw or "m/s").strip().lower()
    aliases = {
        "m/s": "m/s",
        "ms": "m/s",
        "mps": "m/s",
        "meter_per_second": "m/s",
        "meters_per_second": "m/s",
        "knot": "kn",
        "knots": "kn",
        "kt": "kn",
        "kts": "kn",
        "kn": "kn",
        "km/h": "km/h",
        "kmh": "km/h",
        "kph": "km/h",
    }
    if unit not in aliases:
        raise ValueError(f"Unsupported wind unit '{raw}'. Supported: m/s, kn, km/h")
    return aliases[unit]


def _wind_to_mps(series: pd.Series, unit_in: str) -> pd.Series:
    unit = _normalize_wind_unit(unit_in)
    wind = pd.to_numeric(series, errors="coerce").astype(float)
    if unit == "m/s":
        return wind
    if unit == "kn":
        return wind * 0.514444
    return wind / 3.6  # km/h -> m/s


def _iter_files(root: Path, pattern: str) -> list[Path]:
    files = sorted(root.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No files matching {pattern} under {root}")
    return files


def _compute_stats(
    files: list[Path],
    *,
    basin_id: int,
    wind_unit_in: str,
    region: RegionSpec,
) -> dict[str, Any]:
    year_max: dict[int, float] = {}
    track_max: dict[tuple[int, int], float] = {}

    for txt in files:
        block = _parse_block(txt)
        for chunk in pd.read_csv(
            txt,
            names=COLUMNS,
            sep=",",
            usecols=USECOLS,
            chunksize=250_000,
            low_memory=False,
        ):
            chunk = chunk.rename(
                columns={
                    "Year": "year",
                    "Basin ID": "basin_id",
                    "Latitude": "lat",
                    "Longitude": "lon",
                    "Maximum wind speed": "wind_max",
                    "TC number": "tc_number",
                }
            )
            chunk["year"] = pd.to_numeric(chunk["year"], errors="coerce")
            chunk["basin_id"] = pd.to_numeric(chunk["basin_id"], errors="coerce")
            chunk["lat"] = pd.to_numeric(chunk["lat"], errors="coerce")
            chunk["lon"] = pd.to_numeric(chunk["lon"], errors="coerce")
            chunk["lon"] = chunk["lon"].astype(float)
            chunk.loc[chunk["lon"] > 180.0, "lon"] = chunk.loc[chunk["lon"] > 180.0, "lon"] - 360.0
            chunk["wind_max"] = _wind_to_mps(chunk["wind_max"], wind_unit_in)
            chunk["tc_number"] = pd.to_numeric(chunk["tc_number"], errors="coerce")

            chunk = chunk[
                (chunk["basin_id"] == float(basin_id))
                & np.isfinite(chunk["year"])
                & np.isfinite(chunk["wind_max"])
                & np.isfinite(chunk["tc_number"])
            ]
            if chunk.empty:
                continue

            if region.lat_min is not None:
                chunk = chunk[
                    (chunk["lat"] >= float(region.lat_min))
                    & (chunk["lat"] <= float(region.lat_max))
                    & (chunk["lon"] >= float(region.lon_min))
                    & (chunk["lon"] <= float(region.lon_max))
                ]
            if chunk.empty:
                continue

            chunk["year_global"] = chunk["year"].astype(int) + (1000 * int(block))

            g_year = chunk.groupby("year_global", as_index=False)["wind_max"].max()
            for row in g_year.itertuples(index=False):
                key = int(row.year_global)
                val = float(row.wind_max)
                prev = year_max.get(key)
                if prev is None or val > prev:
                    year_max[key] = val

            g_track = chunk.groupby(["year_global", "tc_number"], as_index=False)["wind_max"].max()
            for row in g_track.itertuples(index=False):
                key = (int(row.year_global), int(row.tc_number))
                val = float(row.wind_max)
                prev = track_max.get(key)
                if prev is None or val > prev:
                    track_max[key] = val

    year_vals = np.array(list(year_max.values()), dtype=float)
    track_vals = np.array(list(track_max.values()), dtype=float)

    return {
        "years": int(year_vals.size),
        "tracks": int(track_vals.size),
        "year_max_mean_mps": float(year_vals.mean()) if year_vals.size else 0.0,
        "track_max_mean_mps": float(track_vals.mean()) if track_vals.size else 0.0,
        "year_max_p95_mps": float(np.percentile(year_vals, 95)) if year_vals.size else 0.0,
        "track_max_p95_mps": float(np.percentile(track_vals, 95)) if track_vals.size else 0.0,
        "year_max_max_mps": float(year_vals.max()) if year_vals.size else 0.0,
        "track_max_max_mps": float(track_vals.max()) if track_vals.size else 0.0,
    }


def _infer_hazard_grid(hazard_path: Path) -> dict[str, Any]:
    hz = Hazard.from_hdf5(str(hazard_path))
    lat = np.unique(np.round(np.asarray(hz.centroids.lat, dtype=float), 8))
    lon = np.unique(np.round(np.asarray(hz.centroids.lon, dtype=float), 8))
    dlat = np.diff(np.sort(lat))
    dlon = np.diff(np.sort(lon))
    dlat = dlat[dlat > 1e-9]
    dlon = dlon[dlon > 1e-9]
    return {
        "centroids": int(hz.centroids.size),
        "step_lat_deg_median": float(np.median(dlat)) if dlat.size else None,
        "step_lon_deg_median": float(np.median(dlon)) if dlon.size else None,
        "lat_min": float(lat.min()) if lat.size else None,
        "lat_max": float(lat.max()) if lat.size else None,
        "lon_min": float(lon.min()) if lon.size else None,
        "lon_max": float(lon.max()) if lon.size else None,
    }


def _fmt(v: float, nd: int = 2) -> str:
    return f"{v:,.{nd}f}".replace(",", " ").replace(".", ",")


def _table_region(storm: dict[str, Any], cmcc: dict[str, Any]) -> str:
    def row(label: str, key: str, nd: int = 2) -> str:
        s = float(storm.get(key, 0.0))
        c = float(cmcc.get(key, 0.0))
        d = c - s
        return f"| {label} | {_fmt(s, nd)} | {_fmt(c, nd)} | {_fmt(d, nd)} |"

    lines = [
        "| Indicateur | STORM | STORM_CMCC | Delta (CMCC-STORM) |",
        "|---|---:|---:|---:|",
        row("Nombre d annees actives (>=1 passage dans la zone)", "years", 0),
        row("Nombre de cyclones/evenements (max par track)", "tracks", 0),
        row("Moyenne des vitesses max annuelles (m/s)", "year_max_mean_mps", 2),
        row("Moyenne des vitesses max par cyclone/evenement (m/s)", "track_max_mean_mps", 2),
        row("P95 des vitesses max annuelles (m/s)", "year_max_p95_mps", 2),
        row("P95 des vitesses max par cyclone/evenement (m/s)", "track_max_p95_mps", 2),
        row("Max des vitesses max annuelles (m/s)", "year_max_max_mps", 2),
        row("Max des vitesses max par cyclone/evenement (m/s)", "track_max_max_mps", 2),
    ]
    return "\n".join(lines)


def _safe_num(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _table_impact_summary(impact: dict[str, Any]) -> str:
    summary = impact.get("summary_metrics", {})
    storm = summary.get("storm", {})
    cmcc = summary.get("storm_cmcc", {})
    lines = [
        "| Indicateur impact | STORM | STORM_CMCC | Delta (CMCC-STORM) |",
        "|---|---:|---:|---:|",
    ]
    rows = [
        ("EAI total (€)", "eai_total_eur"),
        ("Perte evenement max (€)", "event_max_total_loss_eur"),
        ("HS direct S3 annuel (%)", "direct_hs_pct_annual"),
        ("HS indirect S3 annuel (%)", "indirect_hs_pct_annual"),
        ("HS direct S3 evt max (%)", "direct_hs_pct_event_max"),
        ("HS indirect S3 evt max (%)", "indirect_hs_pct_event_max"),
    ]
    for label, key in rows:
        s = _safe_num(storm.get(key, 0.0))
        c = _safe_num(cmcc.get(key, 0.0))
        lines.append(f"| {label} | {_fmt(s, 2)} | {_fmt(c, 2)} | {_fmt(c - s, 2)} |")
    return "\n".join(lines)


def _table_impact_by_network(impact: dict[str, Any]) -> str:
    rows = impact.get("state_damage_table", [])
    lines = [
        "| Reseau | STORM EAI (€) | STORM evt max (€) | STORM_CMCC EAI (€) | STORM_CMCC evt max (€) |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        label = str(row.get("class_label") or row.get("class_key") or "Reseau")
        storm = row.get("storm", {})
        cmcc = row.get("storm_cmcc", {})
        lines.append(
            "| "
            f"{label} | "
            f"{_fmt(_safe_num(storm.get('eai_eur', 0.0)), 2)} | "
            f"{_fmt(_safe_num(storm.get('event_max_loss_eur', 0.0)), 2)} | "
            f"{_fmt(_safe_num(cmcc.get('eai_eur', 0.0)), 2)} | "
            f"{_fmt(_safe_num(cmcc.get('event_max_loss_eur', 0.0)), 2)} |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build markdown note comparing STORM and STORM_CMCC wind-speed maxima.")
    parser.add_argument("--storm-dir", default="/home/ubuntu/uploads/STORM/STORM_ds")
    parser.add_argument("--cmcc-dir", default="/home/ubuntu/uploads/STORM/STORM_CMCC_ds")
    parser.add_argument("--storm-pattern", default="STORM_DATA_IBTRACS_NA_1000_YEARS_*.txt")
    parser.add_argument("--cmcc-pattern", default="STORM_DATA_CMCC-CM2-VHR4_NA_1000_YEARS_*_IBTRACSDELTA.txt")
    parser.add_argument("--wind-unit-in", default="m/s")
    parser.add_argument("--basin-id", type=int, default=1)
    parser.add_argument("--wind-map-json", default=str(REPO_ROOT / "web" / "data" / "guadeloupe-wind-maps.json"))
    parser.add_argument(
        "--page1-analysis-json",
        default=str(REPO_ROOT / "web" / "data" / "guadeloupe-page1-analysis.json"),
    )
    parser.add_argument("--out-md", default=str(REPO_ROOT / "docs" / "diagnostic-vents-et-mailles.md"))
    args = parser.parse_args()

    storm_files = _iter_files(Path(args.storm_dir), args.storm_pattern)
    cmcc_files = _iter_files(Path(args.cmcc_dir), args.cmcc_pattern)

    regions = [
        RegionSpec(key="na", label="Bassin NA complet"),
        RegionSpec(
            key="guadeloupe",
            label="Zone Guadeloupe",
            lat_min=15.5,
            lat_max=16.95625,
            lon_min=-62.48125,
            lon_max=-60.66875,
        ),
        RegionSpec(
            key="martinique",
            label="Zone Martinique",
            lat_min=14.3,
            lat_max=15.1,
            lon_min=-61.4,
            lon_max=-60.7,
        ),
    ]

    stats: dict[str, dict[str, dict[str, Any]]] = {}
    for region in regions:
        stats[region.key] = {
            "storm": _compute_stats(
                storm_files,
                basin_id=int(args.basin_id),
                wind_unit_in=args.wind_unit_in,
                region=region,
            ),
            "cmcc": _compute_stats(
                cmcc_files,
                basin_id=int(args.basin_id),
                wind_unit_in=args.wind_unit_in,
                region=region,
            ),
        }

    settings = load_settings()
    hazard_grid = _infer_hazard_grid(settings.hazard_storm_path)
    wind_map_meta = json.loads(Path(args.wind_map_json).read_text(encoding="utf-8")).get("meta", {})
    page1_payload = json.loads(Path(args.page1_analysis_json).read_text(encoding="utf-8"))
    impact_payload = page1_payload.get("impact", {})

    lines: list[str] = []
    lines.append("# Diagnostic vents et mailles (auto-genere)")
    lines.append("")
    lines.append(f"- Genere le: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("- Unite vent normalisee: m/s")
    lines.append(
        "- Regeneration: `python scripts/build_wind_speed_comparison_doc.py` "
        "(met a jour automatiquement tableaux et mailles)."
    )
    lines.append("")

    for region in regions:
        lines.append(f"## Comparaison vitesses max - {region.label}")
        if region.lat_min is not None:
            lines.append(
                f"- BBox: lat [{region.lat_min}, {region.lat_max}] ; lon [{region.lon_min}, {region.lon_max}]"
            )
            lines.append("- Note: le nombre d annees correspond aux annees actives avec au moins un passage dans la zone.")
        lines.append("")
        lines.append(_table_region(stats[region.key]["storm"], stats[region.key]["cmcc"]))
    lines.append("")

    lines.append("## Impacts (resume auto)")
    lines.append("")
    lines.append(_table_impact_summary(impact_payload))
    lines.append("")
    lines.append(_table_impact_by_network(impact_payload))
    lines.append("")

    lines.append("## Mailles utilisees")
    lines.append("")
    lines.append("| Couche | Valeur |")
    lines.append("|---|---|")
    lines.append(
        "| Maille hazard (impact CLIMADA) | "
        f"{_fmt(float(hazard_grid['step_lat_deg_median'] or 0.0), 3)} deg (lat) x "
        f"{_fmt(float(hazard_grid['step_lon_deg_median'] or 0.0), 3)} deg (lon), "
        f"{hazard_grid['centroids']} centroids |"
    )
    lines.append(
        "| BBox hazard (impact CLIMADA) | "
        f"lat [{_fmt(float(hazard_grid['lat_min'] or 0.0), 3)}, {_fmt(float(hazard_grid['lat_max'] or 0.0), 3)}], "
        f"lon [{_fmt(float(hazard_grid['lon_min'] or 0.0), 3)}, {_fmt(float(hazard_grid['lon_max'] or 0.0), 3)}] |"
    )
    lines.append(
        "| Maille carte vents moyenne (web) | "
        f"{_fmt(float(wind_map_meta.get('grid_cell_deg', 0.0)), 3)} deg |"
    )
    lines.append(
        "| Maille points d exposition (sampling) | "
        f"{_fmt(float(settings.default_sampling_spacing_m), 0)} m (pas nominal), "
        f"max {int(settings.climada_max_points_per_feature)} points/feature |"
    )
    lines.append("")

    out_path = Path(args.out_md)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
