#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import html
import json
import math
from pathlib import Path
import random
import sys
from typing import Any, Iterable

import numpy as np
import pandas as pd

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except Exception:  # pragma: no cover
    plt = None  # type: ignore[assignment]

try:
    import geopandas as gpd
    from shapely.geometry import LineString, Point, box
except Exception:  # pragma: no cover
    gpd = None  # type: ignore[assignment]
    LineString = None  # type: ignore[assignment]
    Point = None  # type: ignore[assignment]
    box = None  # type: ignore[assignment]

try:
    import contextily as cx
except Exception:  # pragma: no cover
    cx = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from app.config import load_settings  # noqa: E402
from app.risk_engine.exposure_disaggregation import summarize_disaggregation  # noqa: E402
from app.risk_engine.hazard_loader import (  # noqa: E402
    DEFAULT_BASIN_COVERAGES,
    DEFAULT_SPATIAL_PADDING_DEG,
    _basin_ids_for_points,
    _build_spatial_window,
    _convert_storm_wind_to_climada_mps,
    _read_filtered_track_dataframe,
    _with_track_instance_id,
)
from app.risk_engine.impact_runner import prepare_climada_exposure_bundle  # noqa: E402
from app.risk_engine.climada_engine import RETURN_PERIODS  # noqa: E402
from run_complete_analysis import build_complete_exposure  # noqa: E402


OUTPUT_ROOT = REPO_ROOT / "outputs" / "Échantillons Tracks_NA_Guadeloupe"
RUN_OUTPUTS_DIR = REPO_ROOT / "outputs" / "complete-analysis-runs"
SAMPLE_SIZES = (50, 100, 800, 1500)
PROVIDERS = {
    "storm": {"label": "STORM", "manifest_key": "storm"},
    "storm_cmcc": {"label": "STORM_CMCC", "manifest_key": "storm_cmcc"},
}
RP_TARGETS = (10, 50, 100, 1000)
CURVE_RP = RP_TARGETS
STRATUM_FACTORS = {
    "rank_001_010": 10.0,
    "rank_011_020": 8.0,
    "rank_021_050": 7.0,
    "rank_051_100": 6.0,
    "rank_101_200": 5.0,
    "rank_201_500": 3.5,
    "rank_501_1000": 2.7,
    "rank_1001_2000": 2.1,
    "rank_2001_5000": 1.5,
    "rank_5001_10000": 1.0,
    "rank_gt_10000": 0.8,
    "zero_loss": 0.35,
}
SAFFIR_COLORS = {
    -1: "#64748b",
    0: "#38bdf8",
    1: "#fde047",
    2: "#fb923c",
    3: "#ef4444",
    4: "#a855f7",
    5: "#581c87",
}


@dataclass(frozen=True)
class PopulationContext:
    point_coords: list[tuple[float, float]]
    center_lat: float
    center_lon: float
    basin_ids: tuple[int, ...]
    spatial_window: Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _track_instance_id(year: Any, track_id: Any, provider_key: str | None = None) -> str:
    base_id = f"{int(year)}|{str(track_id)}"
    return f"{provider_key}|{base_id}" if provider_key else base_id


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0088
    lat1r = math.radians(lat1)
    lat2r = math.radians(lat2)
    dlat = lat2r - lat1r
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2.0) ** 2 + math.cos(lat1r) * math.cos(lat2r) * math.sin(dlon / 2.0) ** 2
    return radius_km * (2.0 * math.asin(math.sqrt(a)))


def _quadrant(lat: float, lon: float, center_lat: float, center_lon: float) -> str:
    ns = "N" if float(lat) >= float(center_lat) else "S"
    ew = "E" if float(lon) >= float(center_lon) else "W"
    return ns + ew


def _rank_stratum(rank: int | None, selection_score: float) -> str:
    if selection_score <= 0.0 or rank is None:
        return "zero_loss"
    if rank <= 10:
        return "rank_001_010"
    if rank <= 20:
        return "rank_011_020"
    if rank <= 50:
        return "rank_021_050"
    if rank <= 100:
        return "rank_051_100"
    if rank <= 200:
        return "rank_101_200"
    if rank <= 500:
        return "rank_201_500"
    if rank <= 1000:
        return "rank_501_1000"
    if rank <= 2000:
        return "rank_1001_2000"
    if rank <= 5000:
        return "rank_2001_5000"
    if rank <= 10000:
        return "rank_5001_10000"
    return "rank_gt_10000"


def _selection_metric(record: dict[str, Any]) -> float:
    raw = record.get("selection_score")
    if raw is None:
        raw = record.get("loss_eur")
    try:
        return max(0.0, float(raw))
    except Exception:
        return 0.0


def _physical_selection_score(max_wind_mps: float, min_distance_km: float, category: int) -> float:
    wind = max(0.0, float(max_wind_mps))
    distance = max(0.0, float(min_distance_km))
    cat_factor = 1.0 + max(0, int(category)) * 0.16
    # Pure catalog score: strong winds close to the territory dominate, but
    # distant intense tracks still keep a non-zero chance in the tail.
    attenuation = 0.18 + math.exp(-distance / 120.0)
    return float((wind ** 3) * attenuation * cat_factor)


def _prepare_population_context(territory: str) -> PopulationContext:
    settings = load_settings()
    exposure, _ = build_complete_exposure(territory=territory)
    disagg = summarize_disaggregation(
        exposure,
        spacing_m=float(settings.default_sampling_spacing_m),
        metric_crs=settings.climada_metric_crs,
        max_points_per_feature=int(settings.climada_max_points_per_feature),
    )
    bundle = prepare_climada_exposure_bundle(exposure, disagg, settings)
    point_coords = [
        (float(rec.get("lat")), float(rec.get("lon")))
        for rec in list(bundle.point_records or [])
        if rec.get("lat") is not None and rec.get("lon") is not None
    ]
    if not point_coords:
        raise RuntimeError(f"No CLIMADA point coordinates resolved for territory={territory}")
    basin_ids = _basin_ids_for_points(point_coords, DEFAULT_BASIN_COVERAGES)
    spatial_window = _build_spatial_window(point_coords, padding_deg=DEFAULT_SPATIAL_PADDING_DEG)
    center_lat = float(spatial_window.center_lat)
    center_lon = float(spatial_window.center_lon)
    return PopulationContext(
        point_coords=point_coords,
        center_lat=center_lat,
        center_lon=center_lon,
        basin_ids=basin_ids,
        spatial_window=spatial_window,
    )


def _provider_parquet_path(provider_key: str) -> Path:
    settings = load_settings()
    return settings.storm_cmcc_parquet_path if provider_key == "storm_cmcc" else settings.storm_parquet_path


def _load_provider_dataframe(provider_key: str, context: PopulationContext) -> pd.DataFrame:
    df = _read_filtered_track_dataframe(
        _provider_parquet_path(provider_key),
        basin_ids=context.basin_ids,
        spatial_window=context.spatial_window,
        columns=[
            "Basin ID",
            "Category",
            "Year",
            "track_id",
            "time_step",
            "Time step",
            "lat",
            "Latitude",
            "lon",
            "Longitude",
            "p_c",
            "Minimum pressure",
            "wind_max",
            "Maximum wind speed",
            "rmax",
            "Radius to maximum winds",
        ],
    )
    return _with_track_instance_id(df, provider_key=provider_key)


def _load_loss_ledger_from_checkpoints(run_id: str | None, territory: str, provider_key: str) -> dict[str, float]:
    if not run_id:
        return {}
    root = RUN_OUTPUTS_DIR / str(run_id) / "territories" / territory / "checkpoints" / "dynamic-hazard-shards" / provider_key
    if not root.exists():
        return {}

    total_loss: np.ndarray | None = None
    event_names: list[str] | None = None
    provider_label = PROVIDERS[provider_key]["label"]
    for component in ("wind", "rain", "surge"):
        component_loss: np.ndarray | None = None
        component_event_names: list[str] | None = None
        paths = sorted((root / component).glob(f"hazard-*/{provider_key}/{component}/results/*.npz"))
        paths.extend(sorted((root / component).glob("hazard-*/summary.npz")))
        for path in paths:
            try:
                with np.load(path, allow_pickle=False) as payload:
                    at_event = np.asarray(payload["at_event_loss"], dtype=float).reshape(-1)
                    if component_loss is None:
                        component_loss = np.zeros(at_event.size, dtype=float)
                        component_event_names = [str(value) for value in list(payload.get("event_name", []))]
                    if component_loss.size == at_event.size:
                        component_loss += at_event
            except Exception:
                continue
        if component_loss is None:
            continue
        if total_loss is None:
            total_loss = np.zeros(component_loss.size, dtype=float)
            event_names = component_event_names
        if total_loss.size == component_loss.size:
            total_loss += component_loss

    if total_loss is None or event_names is None:
        return {}

    prefix = f"{provider_label}_"
    ledger: dict[str, float] = {}
    for name, loss in zip(event_names, total_loss.tolist()):
        text = str(name)
        if text.startswith(prefix):
            text = text[len(prefix) :]
        if "|" not in text:
            continue
        ledger[text] = max(0.0, float(loss))
        ledger[_track_instance_id(text.split("|", 1)[0], text.split("|", 1)[1], provider_key)] = max(0.0, float(loss))
    return ledger


def _build_population_records(
    provider_key: str,
    df: pd.DataFrame,
    context: PopulationContext,
    loss_ledger: dict[str, float],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    settings = load_settings()
    wind_mps = _convert_storm_wind_to_climada_mps(
        df["wind_max"],
        settings.storm_wind_unit_in,
        convert_10min_to_1min=bool(settings.storm_convert_10min_to_1min),
    )
    df = df.assign(_wind_mps=wind_mps)
    for track_instance_id, grp in df.groupby("_track_instance_id", sort=False):
        grp = grp.sort_values("time_step")
        distances = [
            _haversine_km(float(row.lat), float(row.lon), context.center_lat, context.center_lon)
            for row in grp.itertuples(index=False)
        ]
        min_idx = int(np.argmin(np.asarray(distances, dtype=float))) if distances else 0
        closest = grp.iloc[min_idx]
        category_raw = float(grp["Category"].max()) if "Category" in grp.columns else 0.0
        category = int(category_raw) if math.isfinite(category_raw) else 0
        loss = float(loss_ledger.get(str(track_instance_id), 0.0))
        max_wind_mps = float(grp["_wind_mps"].max())
        selection_score = loss if loss > 0.0 else _physical_selection_score(
            max_wind_mps,
            float(min(distances) if distances else 0.0),
            int(max(-1, min(5, category))),
        )
        records.append(
            {
                "provider_key": provider_key,
                "provider_name": PROVIDERS[provider_key]["label"],
                "track_instance_id": str(track_instance_id),
                "year": int(grp["Year"].iloc[0]),
                "track_id": str(grp["track_id"].iloc[0]),
                "loss_eur": max(0.0, loss),
                "selection_score": max(0.0, selection_score),
                "selection_score_kind": "damage_eur" if loss > 0.0 else "physical_risk_proxy",
                "max_wind_mps": max_wind_mps,
                "category": int(max(-1, min(5, category))),
                "min_distance_km": float(min(distances) if distances else 0.0),
                "closest_lat": float(closest["lat"]),
                "closest_lon": float(closest["lon"]),
                "quadrant": _quadrant(float(closest["lat"]), float(closest["lon"]), context.center_lat, context.center_lon),
            }
        )

    ordered = sorted(records, key=_selection_metric, reverse=True)
    for rank, item in enumerate(ordered, start=1):
        item["rank"] = rank if _selection_metric(item) > 0.0 else None
        item["stratum"] = _rank_stratum(item["rank"], _selection_metric(item))
    return records


def _physical_bucket(record: dict[str, Any]) -> tuple[Any, ...]:
    wind_bin = int(min(5, max(0, float(record["max_wind_mps"]) // 12.0)))
    distance_bin = int(min(5, max(0, float(record["min_distance_km"]) // 75.0)))
    return (int(record.get("category") or 0), str(record.get("quadrant") or ""), wind_bin, distance_bin)


def _balanced_order(records: Iterable[dict[str, Any]], seed: int) -> list[str]:
    rng = random.Random(int(seed))
    buckets: dict[tuple[Any, ...], list[str]] = {}
    for record in records:
        buckets.setdefault(_physical_bucket(record), []).append(str(record["track_instance_id"]))
    for values in buckets.values():
        rng.shuffle(values)
    bucket_keys = list(buckets.keys())
    rng.shuffle(bucket_keys)
    out: list[str] = []
    while bucket_keys:
        next_keys: list[tuple[Any, ...]] = []
        for key in bucket_keys:
            values = buckets[key]
            if values:
                out.append(values.pop())
            if values:
                next_keys.append(key)
        bucket_keys = next_keys
    return out


def _skeleton_ids(records: list[dict[str, Any]], target_size: int) -> set[str]:
    ordered = sorted(records, key=_selection_metric, reverse=True)
    ids: list[str] = [str(item["track_instance_id"]) for item in ordered[:10]]
    for rank in (100, 200, 1000):
        if len(ordered) >= rank:
            ids.append(str(ordered[rank - 1]["track_instance_id"]))
    if len(ids) > target_size:
        ids = ids[:target_size]
    return set(ids)


def _allocate_quotas(
    strata_records: dict[str, list[dict[str, Any]]],
    orders: dict[str, list[str]],
    skeleton: set[str],
    target_size: int,
    previous: dict[str, int],
) -> dict[str, int]:
    quotas = dict(previous)
    selected_count = len(skeleton) + sum(quotas.values())
    remaining = max(0, int(target_size) - selected_count)
    if remaining <= 0:
        return quotas

    scores: dict[str, float] = {}
    capacities: dict[str, int] = {}
    for stratum, records in strata_records.items():
        capacity = len([item for item in orders.get(stratum, []) if item not in skeleton]) - int(quotas.get(stratum, 0))
        capacities[stratum] = max(0, capacity)
        if capacity > 0:
            factor = float(STRATUM_FACTORS.get(stratum, 1.0))
            scores[stratum] = math.sqrt(max(1, len(records))) * factor

    if not scores:
        return quotas

    total_score = sum(scores.values())
    raw = {key: remaining * (value / total_score) for key, value in scores.items()}
    additions = {
        key: min(capacities[key], int(math.floor(value)))
        for key, value in raw.items()
    }
    used = sum(additions.values())
    remainders = sorted(
        ((raw[key] - math.floor(raw[key]), key) for key in raw.keys()),
        reverse=True,
    )
    while used < remaining and remainders:
        progressed = False
        for _, key in remainders:
            if additions[key] < capacities[key]:
                additions[key] += 1
                used += 1
                progressed = True
                if used >= remaining:
                    break
        if not progressed:
            break

    for key, value in additions.items():
        quotas[key] = int(quotas.get(key, 0)) + int(value)
    return quotas


def build_nested_samples_for_seed(
    records: list[dict[str, Any]],
    *,
    seed: int,
    sample_sizes: tuple[int, ...] = SAMPLE_SIZES,
) -> dict[int, set[str]]:
    by_stratum: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_stratum.setdefault(str(record["stratum"]), []).append(record)
    orders = {
        stratum: _balanced_order(values, seed + index * 7919)
        for index, (stratum, values) in enumerate(sorted(by_stratum.items()))
    }
    global_order = _balanced_order(records, seed + 104729)
    samples: dict[int, set[str]] = {}
    previous_quotas: dict[str, int] = {}
    for size in sorted(sample_sizes):
        skeleton = _skeleton_ids(records, size)
        quotas = _allocate_quotas(by_stratum, orders, skeleton, size, previous_quotas)
        selected = set(skeleton)
        for stratum, quota in quotas.items():
            candidates = [item for item in orders.get(stratum, []) if item not in skeleton]
            selected.update(candidates[: int(quota)])
        if len(selected) < size:
            for track_id in global_order:
                selected.add(track_id)
                if len(selected) >= size:
                    break
        if len(selected) > size:
            keep = [item for item in global_order if item in selected]
            keep = [item for item in sorted(skeleton) if item in selected] + [item for item in keep if item not in skeleton]
            selected = set(keep[:size])
        samples[int(size)] = selected
        previous_quotas = quotas
    return samples


def _weighted_frequency_for_sample(records_by_id: dict[str, dict[str, Any]], selected: set[str], storm_years: int) -> dict[str, float]:
    counts_population: dict[str, int] = {}
    counts_sample: dict[str, int] = {}
    for record in records_by_id.values():
        counts_population[str(record["stratum"])] = counts_population.get(str(record["stratum"]), 0) + 1
    for track_id in selected:
        stratum = str(records_by_id[track_id]["stratum"])
        counts_sample[stratum] = counts_sample.get(stratum, 0) + 1
    weights: dict[str, float] = {}
    for track_id in selected:
        stratum = str(records_by_id[track_id]["stratum"])
        weight = float(counts_population[stratum]) / float(max(1, counts_sample[stratum]))
        weights[track_id] = weight / float(max(1, storm_years))
    return weights


def _pml_from_losses(losses: list[float], frequencies: list[float], rps: tuple[int, ...] = CURVE_RP) -> dict[int, float]:
    loss_arr = np.asarray(losses, dtype=float)
    freq_arr = np.asarray(frequencies, dtype=float)
    valid = (loss_arr > 0.0) & (freq_arr > 0.0)
    if not valid.any():
        return {int(rp): 0.0 for rp in rps}
    order = np.argsort(loss_arr[valid])[::-1]
    sorted_losses = loss_arr[valid][order]
    sorted_freq = freq_arr[valid][order]
    exceed = np.cumsum(sorted_freq)
    return_curve = np.divide(1.0, exceed, out=np.full(exceed.size, np.inf), where=exceed > 0.0)
    x = return_curve[::-1]
    y = sorted_losses[::-1]
    finite = np.isfinite(x) & (x > 0.0)
    if not finite.any():
        return {int(rp): 0.0 for rp in rps}
    return {int(rp): float(max(0.0, np.interp(float(rp), x[finite], y[finite]))) for rp in rps}


def _sample_score(records: list[dict[str, Any]], selected: set[str], storm_years: int) -> float:
    by_id = {str(item["track_instance_id"]): item for item in records}
    sample_freq = _weighted_frequency_for_sample(by_id, selected, storm_years)
    population_pml = _pml_from_losses(
        [_selection_metric(item) for item in records],
        [1.0 / float(max(1, storm_years)) for _ in records],
    )
    sample_pml = _pml_from_losses(
        [_selection_metric(by_id[track_id]) for track_id in selected],
        [sample_freq[track_id] for track_id in selected],
    )
    score = 0.0
    for rp in (10, 50, 100, 1000):
        ref = max(1.0, float(population_pml.get(rp, 0.0)))
        score += abs(float(sample_pml.get(rp, 0.0)) - ref) / ref

    pop_loss = np.log1p(np.asarray([_selection_metric(item) for item in records], dtype=float))
    sample_loss = np.log1p(np.asarray([_selection_metric(by_id[track_id]) for track_id in selected], dtype=float))
    pop_max = float(pop_loss.max()) if pop_loss.size else 0.0
    sample_max = float(sample_loss.max()) if sample_loss.size else 0.0
    bins = np.linspace(0.0, float(max(pop_max, sample_max, 1.0)), 12)
    pop_hist, _ = np.histogram(pop_loss, bins=bins, density=True)
    sample_hist, _ = np.histogram(sample_loss, bins=bins, density=True)
    score += 0.25 * float(np.abs(pop_hist - sample_hist).sum())
    return float(score)


def _choose_best_samples(records: list[dict[str, Any]], storm_years: int, seed_base: int, candidates: int) -> tuple[int, dict[int, set[str]], float]:
    best_seed = int(seed_base)
    best_samples = build_nested_samples_for_seed(records, seed=best_seed)
    best_score = sum(_sample_score(records, selected, storm_years) for selected in best_samples.values())
    for offset in range(1, max(1, int(candidates))):
        seed = int(seed_base) + offset
        samples = build_nested_samples_for_seed(records, seed=seed)
        score = sum(_sample_score(records, selected, storm_years) for selected in samples.values())
        if score < best_score:
            best_seed = seed
            best_samples = samples
            best_score = score
    return best_seed, best_samples, float(best_score)


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _event_rows_for_sample(records: list[dict[str, Any]], selected: set[str], storm_years: int) -> list[dict[str, Any]]:
    by_id = {str(item["track_instance_id"]): item for item in records}
    freqs = _weighted_frequency_for_sample(by_id, selected, storm_years)
    rows = []
    cumulative = 0.0
    for track_id in sorted(selected, key=lambda value: _selection_metric(by_id[value]), reverse=True):
        cumulative += float(freqs[track_id])
        record = by_id[track_id]
        row = dict(record)
        row["sample_weight"] = round(float(freqs[track_id]) * float(storm_years), 8)
        row["frequency_annual"] = float(freqs[track_id])
        row["return_period_years_approx"] = (1.0 / cumulative) if cumulative > 0.0 else None
        rows.append(row)
    return rows


def _representative_rows(records: list[dict[str, Any]], selected: set[str], storm_years: int) -> list[dict[str, Any]]:
    event_rows = _event_rows_for_sample(records, selected, storm_years)
    out: list[dict[str, Any]] = []
    for rp in RP_TARGETS:
        if not event_rows:
            continue
        chosen = min(
            event_rows,
            key=lambda row: abs(math.log(max(1.0, float(row.get("return_period_years_approx") or 1.0))) - math.log(float(rp))),
        )
        item = dict(chosen)
        item["target_rp"] = int(rp)
        out.append(item)
    return out


def _plot_damage_curve(path: Path, curve_rows: list[dict[str, Any]]) -> None:
    if plt is None:
        return
    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    periods = [
        int(rp)
        for rp in RP_TARGETS
        if any(int(float(row.get("return_period_years") or 0)) == int(rp) for row in curve_rows)
    ]
    if not periods:
        periods = list(RP_TARGETS)
    period_position = {int(rp): idx for idx, rp in enumerate(periods)}
    for provider_key in PROVIDERS:
        for source, style in (("population", "-"), ("sample", "--")):
            rows = [row for row in curve_rows if row["provider"] == provider_key and row["source"] == source]
            if not rows:
                continue
            rows = sorted(rows, key=lambda row: int(float(row.get("return_period_years") or 0)))
            ax.plot(
                [period_position[int(float(row["return_period_years"]))] for row in rows],
                [float(row["damage_eur"]) for row in rows],
                style,
                marker="o",
                label=f"{PROVIDERS[provider_key]['label']} {source}",
            )
    ax.set_xlabel("Return period (years)")
    ax.set_xticks(list(range(len(periods))))
    ax.set_xticklabels([str(int(rp)) for rp in periods])
    ylabel = "Damage (EUR)" if any(str(row.get("metric") or "") == "damage_eur" for row in curve_rows) else "Physical selection score"
    ax.set_ylabel(ylabel)
    from matplotlib.ticker import FuncFormatter

    def _compact_axis_value(value: float, _pos: int) -> str:
        value = float(value)
        abs_value = abs(value)
        if abs_value >= 1_000_000:
            return f"{value / 1_000_000:.2f} M"
        if abs_value >= 1_000:
            return f"{value / 1_000:.0f} k"
        if abs_value >= 10:
            return f"{value:.0f}"
        return f"{value:.2f}"

    ax.yaxis.set_major_formatter(FuncFormatter(_compact_axis_value))
    ax.yaxis.get_offset_text().set_visible(False)
    ax.grid(True, which="major", alpha=0.25)
    ax.legend(fontsize=8)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)


def _render_track_map(
    path: Path,
    df: pd.DataFrame,
    track_instance_id: str,
    title: str,
    context: PopulationContext,
) -> None:
    if plt is None or gpd is None or LineString is None or box is None:
        return
    track_df = df[df["_track_instance_id"] == track_instance_id].sort_values("time_step")
    if track_df.shape[0] < 2:
        return
    segments = []
    for idx in range(track_df.shape[0] - 1):
        row_a = track_df.iloc[idx]
        row_b = track_df.iloc[idx + 1]
        cat_a = float(row_a.get("Category", 0.0))
        cat_b = float(row_b.get("Category", 0.0))
        category_raw = max(cat_a if math.isfinite(cat_a) else 0.0, cat_b if math.isfinite(cat_b) else 0.0)
        category = int(max(-1, min(5, int(category_raw))))
        segments.append(
            {
                "category": category,
                "geometry": LineString([(float(row_a["lon"]), float(row_a["lat"])), (float(row_b["lon"]), float(row_b["lat"]))]),
            }
        )
    gdf = gpd.GeoDataFrame(segments, crs="EPSG:4326").to_crs("EPSG:3857")
    bbox_geom = gpd.GeoDataFrame(
        [{"geometry": box(context.spatial_window.lon_min, context.spatial_window.lat_min, context.spatial_window.lon_max, context.spatial_window.lat_max)}],
        crs="EPSG:4326",
    ).to_crs("EPSG:3857")
    center = gpd.GeoDataFrame(
        [{"geometry": Point(context.center_lon, context.center_lat)}],
        crs="EPSG:4326",
    ).to_crs("EPSG:3857")

    fig, ax = plt.subplots(figsize=(7.2, 6.5))
    bbox_geom.boundary.plot(ax=ax, color="#111827", linewidth=1.2, linestyle="--")
    center.plot(ax=ax, color="#111827", markersize=28, zorder=5)
    for category, color in SAFFIR_COLORS.items():
        subset = gdf[gdf["category"] == category]
        if not subset.empty:
            subset.plot(ax=ax, color=color, linewidth=3.0, label=f"Cat {category}" if category > 0 else "TS/TD")
    minx, miny, maxx, maxy = gdf.total_bounds
    padx = max(50_000.0, (maxx - minx) * 0.15)
    pady = max(50_000.0, (maxy - miny) * 0.15)
    ax.set_xlim(minx - padx, maxx + padx)
    ax.set_ylim(miny - pady, maxy + pady)
    if cx is not None:
        try:
            cx.add_basemap(ax, source=cx.providers.CartoDB.Positron, attribution_size=6)
        except Exception:
            pass
    ax.set_axis_off()
    ax.set_title(title, fontsize=11)
    ax.legend(loc="lower left", fontsize=7)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)


def _write_sample_outputs(
    *,
    size: int,
    out_dir: Path,
    population_by_provider: dict[str, list[dict[str, Any]]],
    dataframes_by_provider: dict[str, pd.DataFrame],
    samples_by_provider: dict[str, set[str]],
    seeds_by_provider: dict[str, int],
    scores_by_provider: dict[str, float],
    context: PopulationContext,
    storm_years: int,
    full_run_id: str | None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "sample_id": f"guadeloupe_sample_{size:04d}",
        "territory": "guadeloupe",
        "sample_size": int(size),
        "storm_years": int(storm_years),
        "created_at": _utc_now(),
        "source_full_run_id": full_run_id,
        "source_catalog": "STORM/STORM_CMCC parquet filtered by NA basin and Guadeloupe spatial window",
        "basin": "NA",
        "spatial_window": {
            "lat_min": float(context.spatial_window.lat_min),
            "lat_max": float(context.spatial_window.lat_max),
            "lon_min": float(context.spatial_window.lon_min),
            "lon_max": float(context.spatial_window.lon_max),
            "center_lat": float(context.spatial_window.center_lat),
            "center_lon": float(context.spatial_window.center_lon),
        },
        "nested_sample_sizes": list(SAMPLE_SIZES),
        "selection_method": "seeded_stratified_damage_with_physical_balancing",
        "providers": {},
    }
    selected_rows: list[dict[str, Any]] = []
    curve_rows: list[dict[str, Any]] = []
    representative_rows: list[dict[str, Any]] = []
    rp1000_rows: list[dict[str, Any]] = []

    for provider_key, records in population_by_provider.items():
        selected = samples_by_provider[provider_key]
        by_id = {str(item["track_instance_id"]): item for item in records}
        event_rows = _event_rows_for_sample(records, selected, storm_years)
        selected_rows.extend(event_rows)
        provider_rep_rows = _representative_rows(records, selected, storm_years)
        representative_rows.extend(provider_rep_rows)
        rp1000_rows.extend([row for row in event_rows if float(row.get("return_period_years_approx") or 0.0) >= 1000.0])
        freqs = {row["track_instance_id"]: float(row["frequency_annual"]) for row in event_rows}

        population_pml = _pml_from_losses(
            [_selection_metric(item) for item in records],
            [1.0 / float(max(1, storm_years)) for _ in records],
        )
        sample_pml = _pml_from_losses(
            [_selection_metric(by_id[track_id]) for track_id in selected],
            [freqs[track_id] for track_id in selected],
        )
        metric_kind = str(next((item.get("selection_score_kind") for item in records if item.get("selection_score_kind")), "physical_risk_proxy"))
        for rp in CURVE_RP:
            curve_rows.append({"provider": provider_key, "source": "population", "return_period_years": rp, "damage_eur": population_pml[rp], "metric": metric_kind})
            curve_rows.append({"provider": provider_key, "source": "sample", "return_period_years": rp, "damage_eur": sample_pml[rp], "metric": metric_kind})

        manifest["providers"][provider_key] = {
            "provider_name": PROVIDERS[provider_key]["label"],
            "sample_size": int(size),
            "population_track_count": int(len(records)),
            "seed": int(seeds_by_provider[provider_key]),
            "score": float(scores_by_provider[provider_key]),
            "tracks": [
                {
                    "year": int(row["year"]),
                    "track_id": str(row["track_id"]),
                    "track_instance_id": str(row["track_instance_id"]),
                    "sample_weight": float(row["sample_weight"]),
                    "frequency_annual": float(row["frequency_annual"]),
                    "stratum": str(row["stratum"]),
                    "loss_eur": float(row.get("loss_eur") or 0.0),
                    "selection_score": float(row.get("selection_score") or _selection_metric(row)),
                    "selection_score_kind": str(row.get("selection_score_kind") or "physical_risk_proxy"),
                    "rank": row.get("rank"),
                    "max_wind_mps": float(row["max_wind_mps"]),
                    "category": int(row["category"]),
                    "min_distance_km": float(row["min_distance_km"]),
                    "closest_lat": float(row["closest_lat"]),
                    "closest_lon": float(row["closest_lon"]),
                    "quadrant": str(row["quadrant"]),
                }
                for row in event_rows
            ],
        }

        for row in provider_rep_rows:
            rp = int(row["target_rp"])
            _render_track_map(
                out_dir / "maps" / f"{provider_key}_rp{rp}.png",
                dataframes_by_provider[provider_key],
                str(row["track_instance_id"]),
                f"{PROVIDERS[provider_key]['label']} RP{rp} representative track",
                context,
            )

    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    common_fields = [
        "provider_key",
        "provider_name",
        "track_instance_id",
        "year",
        "track_id",
        "rank",
        "stratum",
        "loss_eur",
        "selection_score",
        "selection_score_kind",
        "sample_weight",
        "frequency_annual",
        "return_period_years_approx",
        "max_wind_mps",
        "category",
        "min_distance_km",
        "closest_lat",
        "closest_lon",
        "quadrant",
    ]
    _write_csv(out_dir / "selected_tracks.csv", selected_rows, common_fields)
    _write_csv(out_dir / "representative_rp_tracks.csv", representative_rows, ["target_rp", *common_fields])
    _write_csv(out_dir / "rp1000_tracks.csv", rp1000_rows, common_fields)
    _write_csv(out_dir / "damage_curve.csv", curve_rows, ["provider", "source", "return_period_years", "damage_eur", "metric"])
    _write_csv(out_dir / "selection_score_curve.csv", curve_rows, ["provider", "source", "return_period_years", "damage_eur", "metric"])
    _plot_damage_curve(out_dir / "damage_curve.png", curve_rows)
    _plot_damage_curve(out_dir / "selection_score_curve.png", curve_rows)
    _write_report(out_dir / "representativeness_report.html", manifest, curve_rows)


def _write_report(path: Path, manifest: dict[str, Any], curve_rows: list[dict[str, Any]]) -> None:
    rows = []
    metric_label = (
        "Damage EUR"
        if any(str(row.get("metric") or "") == "damage_eur" for row in curve_rows)
        else "Selection score"
    )
    for provider_key in PROVIDERS:
        for rp in CURVE_RP:
            population = next(
                (
                    row
                    for row in curve_rows
                    if row["provider"] == provider_key
                    and row["source"] == "population"
                    and int(float(row["return_period_years"])) == int(rp)
                ),
                None,
            )
            sample = next(
                (
                    row
                    for row in curve_rows
                    if row["provider"] == provider_key
                    and row["source"] == "sample"
                    and int(float(row["return_period_years"])) == int(rp)
                ),
                None,
            )
            if not population or not sample:
                continue
            ref = max(1.0, float(population["damage_eur"]))
            err = (float(sample["damage_eur"]) - ref) / ref
            rows.append(
                "<tr>"
                f"<td>{html.escape(PROVIDERS[provider_key]['label'])}</td>"
                f"<td>RP{rp}</td>"
                f"<td>{float(population['damage_eur']):,.0f}</td>"
                f"<td>{float(sample['damage_eur']):,.0f}</td>"
                f"<td>{err * 100.0:+.1f}%</td>"
                "</tr>"
            )
    body = "\n".join(rows)
    path.write_text(
        "<!doctype html><meta charset='utf-8'>"
        "<title>Track sample representativeness</title>"
        "<style>body{font-family:system-ui,sans-serif;margin:32px}table{border-collapse:collapse}"
        "td,th{border:1px solid #ddd;padding:6px 9px;text-align:right}td:first-child,th:first-child{text-align:left}</style>"
        f"<h1>{html.escape(str(manifest.get('sample_id')))}</h1>"
        f"<p>Metric: {html.escape(metric_label)}</p>"
        f"<table><thead><tr><th>Provider</th><th>RP</th><th>Population {html.escape(metric_label)}</th><th>Sample {html.escape(metric_label)}</th><th>Error</th></tr></thead>"
        f"<tbody>{body}</tbody></table>",
        encoding="utf-8",
    )


def build_track_samples(args: argparse.Namespace) -> Path:
    territory = "guadeloupe"
    output_root = Path(args.output_root)
    context = _prepare_population_context(territory)
    storm_years = int(args.storm_years or load_settings().storm_years)
    population_by_provider: dict[str, list[dict[str, Any]]] = {}
    dataframes_by_provider: dict[str, pd.DataFrame] = {}
    samples_by_provider_size: dict[int, dict[str, set[str]]] = {size: {} for size in SAMPLE_SIZES}
    seeds_by_provider: dict[str, int] = {}
    scores_by_provider: dict[str, float] = {}

    for provider_key in PROVIDERS:
        df = _load_provider_dataframe(provider_key, context)
        ledger = _load_loss_ledger_from_checkpoints(args.full_run_id, territory, provider_key)
        records = _build_population_records(provider_key, df, context, ledger)
        best_seed, nested, score = _choose_best_samples(
            records,
            storm_years=storm_years,
            seed_base=int(args.seed_base) + (17_000 if provider_key == "storm_cmcc" else 0),
            candidates=int(args.candidate_seeds),
        )
        population_by_provider[provider_key] = records
        dataframes_by_provider[provider_key] = df
        seeds_by_provider[provider_key] = best_seed
        scores_by_provider[provider_key] = score
        for size, selected in nested.items():
            samples_by_provider_size[size][provider_key] = selected

    for size in SAMPLE_SIZES:
        _write_sample_outputs(
            size=size,
            out_dir=output_root / f"sample_{size:04d}",
            population_by_provider=population_by_provider,
            dataframes_by_provider=dataframes_by_provider,
            samples_by_provider=samples_by_provider_size[size],
            seeds_by_provider=seeds_by_provider,
            scores_by_provider=scores_by_provider,
            context=context,
            storm_years=storm_years,
            full_run_id=args.full_run_id,
        )
    return output_root


def main() -> int:
    parser = argparse.ArgumentParser(description="Build prefabricated weighted Guadeloupe track samples.")
    parser.add_argument("--full-run-id", default=None, help="Optional complete-analysis run id used only if you explicitly want damage ledgers.")
    parser.add_argument("--output-root", default=str(OUTPUT_ROOT), help="Output directory for sample manifests and visualizations.")
    parser.add_argument("--candidate-seeds", type=int, default=500, help="Number of candidate seeds to score per provider.")
    parser.add_argument("--seed-base", type=int, default=240710, help="Base seed for reproducible random sampling.")
    parser.add_argument("--storm-years", type=int, default=None, help="Synthetic catalog duration. Defaults to settings.storm_years.")
    args = parser.parse_args()

    output_root = build_track_samples(args)
    print(f"Wrote track samples to {output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
