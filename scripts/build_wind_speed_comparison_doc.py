#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any

try:
    import numpy as np
except Exception:  # pragma: no cover - optional at import time for CLI --help
    np = None  # type: ignore[assignment]

try:
    import pandas as pd
except Exception:  # pragma: no cover - optional at import time for CLI --help
    pd = None  # type: ignore[assignment]

from case_study_sources import CASE_STUDY_BBOX


UTC = timezone.utc
KMH_PER_MPS = 3.6
REPO_ROOT = Path(__file__).resolve().parents[1]
ELECTRIC_DEPENDENCY_GRID_DEG = 0.1
SMALL_SAMPLE_GRID_STEP_DEG = 0.01

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


@dataclass(frozen=True)
class RegionSpec:
    key: str
    label: str
    lat_min: float | None = None
    lat_max: float | None = None
    lon_min: float | None = None
    lon_max: float | None = None


@dataclass(frozen=True)
class BasinSpec:
    key: str
    label: str
    basin_id: int
    storm_pattern: str
    cmcc_pattern: str


def _require_runtime_deps() -> None:
    missing: list[str] = []
    if np is None:
        missing.append("numpy")
    if pd is None:
        missing.append("pandas")
    if missing:
        raise RuntimeError(
            "Missing dependencies for build_wind_speed_comparison_doc.py: "
            + ", ".join(sorted(set(missing)))
            + ". Install script requirements and retry."
        )


def _parse_block(path: Path) -> int:
    match = re.search(r"_1000_YEARS_(\d+)", path.name)
    if not match:
        return 0
    return int(match.group(1))


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
    return wind / 3.6


def _iter_files(root: Path, pattern: str) -> list[Path]:
    files = sorted(root.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No files matching {pattern} under {root}")
    return files


def _finalize_stats(
    *,
    year_max: dict[int, float],
    track_max: dict[tuple[int, int], float],
) -> dict[str, Any]:
    year_vals = np.array(list(year_max.values()), dtype=float)
    track_vals = np.array(list(track_max.values()), dtype=float)
    year_q_rp100 = float(np.quantile(year_vals, 0.99)) if year_vals.size else 0.0
    year_q_rp1000 = float(np.quantile(year_vals, 0.999)) if year_vals.size else 0.0
    track_q_rp100 = float(np.quantile(track_vals, 0.99)) if track_vals.size else 0.0
    track_q_rp1000 = float(np.quantile(track_vals, 0.999)) if track_vals.size else 0.0
    return {
        "years": int(year_vals.size),
        "tracks": int(track_vals.size),
        "year_max_mean_mps": float(year_vals.mean()) if year_vals.size else 0.0,
        "track_max_mean_mps": float(track_vals.mean()) if track_vals.size else 0.0,
        "year_max_rp100_mps": year_q_rp100,
        "track_max_rp100_mps": track_q_rp100,
        "year_max_rp1000_mps": year_q_rp1000,
        "track_max_rp1000_mps": track_q_rp1000,
        "year_max_max_mps": float(year_vals.max()) if year_vals.size else 0.0,
        "track_max_max_mps": float(track_vals.max()) if track_vals.size else 0.0,
    }


def _compute_stats_by_region(
    files: list[Path],
    *,
    basin_id: int,
    wind_unit_in: str,
    regions: list[RegionSpec],
) -> dict[str, dict[str, Any]]:
    region_year_max: dict[str, dict[int, float]] = {region.key: {} for region in regions}
    region_track_max: dict[str, dict[tuple[int, int], float]] = {region.key: {} for region in regions}

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

            chunk["year_global"] = chunk["year"].astype(int) + (1000 * int(block))

            for region in regions:
                region_chunk = chunk
                if region.lat_min is not None:
                    region_chunk = chunk[
                        (chunk["lat"] >= float(region.lat_min))
                        & (chunk["lat"] <= float(region.lat_max))
                        & (chunk["lon"] >= float(region.lon_min))
                        & (chunk["lon"] <= float(region.lon_max))
                    ]
                if region_chunk.empty:
                    continue

                g_year = region_chunk.groupby("year_global", as_index=False)["wind_max"].max()
                year_max = region_year_max[region.key]
                for row in g_year.itertuples(index=False):
                    key = int(row.year_global)
                    val = float(row.wind_max)
                    prev = year_max.get(key)
                    if prev is None or val > prev:
                        year_max[key] = val

                g_track = region_chunk.groupby(["year_global", "tc_number"], as_index=False)["wind_max"].max()
                track_max = region_track_max[region.key]
                for row in g_track.itertuples(index=False):
                    key = (int(row.year_global), int(row.tc_number))
                    val = float(row.wind_max)
                    prev = track_max.get(key)
                    if prev is None or val > prev:
                        track_max[key] = val

    return {
        region.key: _finalize_stats(
            year_max=region_year_max[region.key],
            track_max=region_track_max[region.key],
        )
        for region in regions
    }


def _fmt(v: float, nd: int = 2) -> str:
    return f"{v:,.{nd}f}".replace(",", " ").replace(".", ",")


def _mps_to_kmh(value: float) -> float:
    return float(value) * KMH_PER_MPS


def _table_region(storm: dict[str, Any], cmcc: dict[str, Any]) -> str:
    def row(label: str, key: str, nd: int = 2, *, wind_metric: bool = False) -> str:
        s = float(storm.get(key, 0.0))
        c = float(cmcc.get(key, 0.0))
        if wind_metric:
            s = _mps_to_kmh(s)
            c = _mps_to_kmh(c)
        d = c - s
        return f"| {label} | {_fmt(s, nd)} | {_fmt(c, nd)} | {_fmt(d, nd)} |"

    lines = [
        "| Indicateur | STORM | STORM_CMCC | Delta (CMCC-STORM) |",
        "|---|---:|---:|---:|",
        row("Nombre d annees actives (>=1 passage dans la zone)", "years", 0),
        row("Nombre de cyclones/evenements (max par track)", "tracks", 0),
        row("Moyenne des vitesses max annuelles (km/h)", "year_max_mean_mps", 2, wind_metric=True),
        row("Moyenne des vitesses max par cyclone/evenement (km/h)", "track_max_mean_mps", 2, wind_metric=True),
        row("Vitesse max annuelle - temps de retour 100 ans (km/h)", "year_max_rp100_mps", 2, wind_metric=True),
        row("Vitesse max par cyclone/evenement - temps de retour 100 ans (km/h)", "track_max_rp100_mps", 2, wind_metric=True),
        row("Vitesse max annuelle - temps de retour 1000 ans (km/h)", "year_max_rp1000_mps", 2, wind_metric=True),
        row("Vitesse max par cyclone/evenement - temps de retour 1000 ans (km/h)", "track_max_rp1000_mps", 2, wind_metric=True),
        row("Max des vitesses max annuelles (km/h)", "year_max_max_mps", 2, wind_metric=True),
        row("Max des vitesses max par cyclone/evenement (km/h)", "track_max_max_mps", 2, wind_metric=True),
    ]
    return "\n".join(lines)


def _default_storm_txt_dir() -> Path:
    env_value = str(os.environ.get("SIB_RISK_STORM_TXT_DIR", "")).strip()
    candidates = []
    if env_value:
        candidates.append(Path(env_value))
    candidates.extend(
        [
            REPO_ROOT / "data" / "hazards" / "STORM_ds",
            Path("/home/ubuntu/uploads/STORM/STORM_ds"),
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]


def _default_cmcc_txt_dir() -> Path:
    env_value = str(os.environ.get("SIB_RISK_STORM_CMCC_TXT_DIR", "")).strip()
    candidates = []
    if env_value:
        candidates.append(Path(env_value))
    candidates.extend(
        [
            REPO_ROOT / "data" / "hazards" / "STORM_CMCC_ds",
            Path("/home/ubuntu/uploads/STORM/STORM_CMCC_ds"),
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build markdown note comparing STORM and STORM_CMCC wind-speed maxima.")
    parser.add_argument("--storm-dir", default=str(_default_storm_txt_dir()))
    parser.add_argument("--cmcc-dir", default=str(_default_cmcc_txt_dir()))
    parser.add_argument("--wind-unit-in", default="m/s")
    parser.add_argument("--web-data-dir", default=str(REPO_ROOT / "web" / "data"))
    parser.add_argument("--basin-map-grid-cell-deg", type=float, default=0.05)
    parser.add_argument("--out-md", default=str(REPO_ROOT / "docs" / "diagnostic-vents-et-mailles.md"))
    args = parser.parse_args()
    _require_runtime_deps()

    basin_specs = [
        BasinSpec(
            key="na",
            label="Bassin NA complet",
            basin_id=1,
            storm_pattern="STORM_DATA_IBTRACS_NA_1000_YEARS_*.txt",
            cmcc_pattern="STORM_DATA_CMCC-CM2-VHR4_NA_1000_YEARS_*_IBTRACSDELTA.txt",
        ),
        BasinSpec(
            key="si",
            label="Bassin SI complet",
            basin_id=3,
            storm_pattern="STORM_DATA_IBTRACS_SI_1000_YEARS_*.txt",
            cmcc_pattern="STORM_DATA_CMCC-CM2-VHR4_SI_1000_YEARS_*_IBTRACSDELTA.txt",
        ),
        BasinSpec(
            key="sp",
            label="Bassin SP complet",
            basin_id=4,
            storm_pattern="STORM_DATA_IBTRACS_SP_1000_YEARS_*.txt",
            cmcc_pattern="STORM_DATA_CMCC-CM2-VHR4_SP_1000_YEARS_*_IBTRACSDELTA.txt",
        ),
    ]
    basin_regions = {
        "na": [
            RegionSpec(key="na", label="Bassin NA complet"),
            RegionSpec(key="guadeloupe", label="Zone Guadeloupe", **CASE_STUDY_BBOX["guadeloupe"]),
            RegionSpec(key="martinique", label="Zone Martinique", **CASE_STUDY_BBOX["martinique"]),
        ],
        "si": [RegionSpec(key="si", label="Bassin SI complet")],
        "sp": [RegionSpec(key="sp", label="Bassin SP complet")],
    }

    stats: dict[str, dict[str, dict[str, Any]]] = {}
    for basin in basin_specs:
        storm_files = _iter_files(Path(args.storm_dir), basin.storm_pattern)
        cmcc_files = _iter_files(Path(args.cmcc_dir), basin.cmcc_pattern)
        regions = basin_regions[basin.key]
        storm_stats = _compute_stats_by_region(
            storm_files,
            basin_id=basin.basin_id,
            wind_unit_in=args.wind_unit_in,
            regions=regions,
        )
        cmcc_stats = _compute_stats_by_region(
            cmcc_files,
            basin_id=basin.basin_id,
            wind_unit_in=args.wind_unit_in,
            regions=regions,
        )
        for region in regions:
            stats[region.key] = {
                "storm": storm_stats[region.key],
                "cmcc": cmcc_stats[region.key],
            }

    web_data_dir = Path(args.web_data_dir)
    guadeloupe_wind_map = _load_json(web_data_dir / "guadeloupe-wind-maps.json")
    martinique_wind_map = _load_json(web_data_dir / "martinique-wind-maps.json")
    guadeloupe_landslide_map = _load_json(web_data_dir / "guadeloupe-landslide-maps.json")
    martinique_landslide_map = _load_json(web_data_dir / "martinique-landslide-maps.json")
    guadeloupe_complete = _load_json(web_data_dir / "guadeloupe-complete-analysis.json")
    martinique_complete = _load_json(web_data_dir / "martinique-complete-analysis.json")

    guadeloupe_wind_meta = guadeloupe_wind_map.get("meta", {})
    martinique_wind_meta = martinique_wind_map.get("meta", {})
    guadeloupe_landslide_meta = guadeloupe_landslide_map.get("meta", {})
    martinique_landslide_meta = martinique_landslide_map.get("meta", {})
    guadeloupe_modeling = (guadeloupe_complete.get("meta", {}) or {}).get("modeling", {})
    martinique_modeling = (martinique_complete.get("meta", {}) or {}).get("modeling", {})
    guadeloupe_matching_qa = guadeloupe_modeling.get("hazard_exposure_matching_qa", {})
    martinique_matching_qa = martinique_modeling.get("hazard_exposure_matching_qa", {})

    output_regions = [
        RegionSpec(key="na", label="Bassin NA complet"),
        RegionSpec(key="si", label="Bassin SI complet"),
        RegionSpec(key="sp", label="Bassin SP complet"),
        RegionSpec(key="guadeloupe", label="Zone Guadeloupe", **CASE_STUDY_BBOX["guadeloupe"]),
        RegionSpec(key="martinique", label="Zone Martinique", **CASE_STUDY_BBOX["martinique"]),
    ]

    lines: list[str] = []
    lines.append("# Diagnostic vents et mailles (auto-genere)")
    lines.append("")
    lines.append(f"- Genere le: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("- Unite vent normalisee: km/h")
    lines.append(
        "- Regeneration: `python scripts/build_wind_speed_comparison_doc.py` "
        "(met a jour automatiquement tableaux et mailles)."
    )
    lines.append(
        "- Verification mailles `complete analysis`: lecture des payloads publies "
        "`guadeloupe-complete-analysis.json` et `martinique-complete-analysis.json`."
    )
    lines.append("")

    for region in output_regions:
        lines.append(f"## Comparaison vitesses max - {region.label}")
        if region.lat_min is not None:
            lines.append(
                f"- BBox: lat [{region.lat_min}, {region.lat_max}] ; lon [{region.lon_min}, {region.lon_max}]"
            )
            lines.append("- Note: le nombre d annees correspond aux annees actives avec au moins un passage dans la zone.")
        lines.append("")
        lines.append(_table_region(stats[region.key]["storm"], stats[region.key]["cmcc"]))
        lines.append("")

    lines.append("## Mailles utilisees")
    lines.append("")
    lines.append("| Couche | Valeur |")
    lines.append("|---|---|")
    lines.append(
        "| Hazard vent dans `complete analysis` | "
        "Pas de grille reguliere fixe: chargement dynamique STORM/STORM_CMCC sur points d exposition "
        "(`hazard_source=dynamic_parquet`) |"
    )
    lines.append(
        "| Points hazard/exposition dans `complete analysis` | "
        f"Guadeloupe: {int(guadeloupe_matching_qa.get('point_count', 0)):,} points ; "
        f"Martinique: {int(martinique_matching_qa.get('point_count', 0)):,} points |".replace(",", " ")
    )
    lines.append(
        "| Maille d agregation territoriale dans `complete analysis` | "
        f"{_fmt(float(guadeloupe_modeling.get('territory_grid_deg', 0.0)), 3)} deg "
        "(meme valeur dans les payloads Guadeloupe et Martinique) |"
    )
    lines.append(
        "| Maille points d exposition dans `complete analysis` | "
        f"{_fmt(float(guadeloupe_modeling.get('sampling_spacing_m', 0.0)), 0)} m (pas nominal), "
        f"max {int(guadeloupe_modeling.get('max_points_per_feature', 0))} points/feature |"
    )
    lines.append(
        "| Maille cartes vents web Guadeloupe / Martinique | "
        f"Guadeloupe: {_fmt(float(guadeloupe_wind_meta.get('grid_cell_deg', 0.0)), 3)} deg ; "
        f"Martinique: {_fmt(float(martinique_wind_meta.get('grid_cell_deg', 0.0)), 3)} deg "
        "(restitution web, hors `complete analysis`) |"
    )
    lines.append(
        "| Maille aleas pluie web Guadeloupe / Martinique | "
        f"Guadeloupe: {_fmt(float(guadeloupe_wind_meta.get('grid_cell_deg', 0.0)), 3)} deg ; "
        f"Martinique: {_fmt(float(martinique_wind_meta.get('grid_cell_deg', 0.0)), 3)} deg "
        "(meme maille de publication que le vent dans les artefacts actuels) |"
    )
    lines.append(
        "| Maille aleas surge web Guadeloupe / Martinique | "
        f"Guadeloupe: {_fmt(float(guadeloupe_wind_meta.get('surge_native_cell_deg', guadeloupe_wind_meta.get('grid_cell_deg', 0.0))), 3)} deg ; "
        f"Martinique: {_fmt(float(martinique_wind_meta.get('surge_native_cell_deg', martinique_wind_meta.get('grid_cell_deg', 0.0))), 3)} deg "
        "(pas de sous-maille differente publiee actuellement) |"
    )
    lines.append(
        "| Maille aleas landslide web Guadeloupe / Martinique | "
        f"Guadeloupe: {_fmt(float(guadeloupe_landslide_meta.get('grid_cell_deg', 0.0)), 3)} deg ; "
        f"Martinique: {_fmt(float(martinique_landslide_meta.get('grid_cell_deg', 0.0)), 3)} deg "
        "(meme maille de publication que le vent dans les artefacts actuels) |"
    )
    lines.append(
        "| Maille cartes vents bassin NA / SI / SP | "
        f"{_fmt(float(args.basin_map_grid_cell_deg), 3)} deg "
        "(`scripts/build_basin_wind_maps.py`, restitution web, hors `complete analysis`) |"
    )
    lines.append(
        "| Maille dependance elec -> eau | "
        f"{_fmt(float(ELECTRIC_DEPENDENCY_GRID_DEG), 3)} deg "
        "(`fixed_grid_0p1deg`, aggregation native des etats elec avant projection sur l eau) |"
    )
    lines.append("")
    lines.append("## Autres mailles ou pas reperes dans le projet")
    lines.append("")
    lines.append("| Element | Valeur |")
    lines.append("|---|---|")
    lines.append(
        "| Grille population / social impacts | "
        f"{_fmt(float(guadeloupe_modeling.get('territory_grid_deg', 0.0)), 3)} deg "
        "(meme logique que la maille territoriale `complete analysis`) |"
    )
    lines.append(
        "| Petit cas `hazard_loader.py` | "
        f"{_fmt(float(SMALL_SAMPLE_GRID_STEP_DEG), 3)} deg "
        "(maille utilitaire de sous-echantillonnage, pas une maille de publication courante) |"
    )
    lines.append(
        "| Fenetre spatiale du loader | 4,000 deg de padding "
        "(ce n est pas une maille, mais une fenetre de chargement autour des expositions) |"
    )
    lines.append("")

    out_path = Path(args.out_md)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
