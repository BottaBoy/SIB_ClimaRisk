#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT
    / "outputs"
    / "run-comparisons"
    / "guadeloupe-track-sampling"
    / "20260711_071243_vs_20260711_074032"
)

BLUE = "#2563eb"
ORANGE = "#f97316"
TEXT = "#111827"
MUTED = "#475569"
GRID = "#d1d5db"
BORDER = "#374151"

HAZARDS = ("storm", "storm_cmcc")
HAZARD_LABELS = {"storm": "STORM", "storm_cmcc": "STORM_CMCC"}

PORTFOLIO_ITEMS = (
    ("EAI total", "eai_eur"),
    ("EAI direct", "eai_direct_eur"),
    ("EAI indirect", "eai_indirect_eur"),
    ("PML 10 ans", "pml_10_eur"),
    ("PML 20 ans", "pml_20_eur"),
    ("PML 50 ans", "pml_50_eur"),
    ("PML 100 ans", "pml_100_eur"),
    ("PML 200 ans", "pml_200_eur"),
    ("PML 1000 ans", "pml_1000_eur"),
)
COMPONENT_ITEMS = (
    ("Vent", "wind"),
    ("Pluie", "rain"),
    ("Total plafonne", "combined_capped"),
)
METRIC_LABELS = {
    "damage_eur": "Dommage",
    "total_damage_eur": "Dommage total",
    "blocking_ouvrage_eur": "Blocage ouvrages",
    "indirect_damage_eur": "Dommage indirect",
    "direct_damage_eur": "Dommage direct",
    "damage_component_eur": "Dommage composant",
    "eai_eur": "EAI total",
    "eai_direct_eur": "EAI direct",
    "eai_indirect_eur": "EAI indirect",
    "percentile_99_loss_eur": "P99 pertes",
    "pml_10_eur": "PML 10 ans",
    "pml_20_eur": "PML 20 ans",
    "pml_50_eur": "PML 50 ans",
    "pml_100_eur": "PML 100 ans",
    "pml_200_eur": "PML 200 ans",
    "pml_1000_eur": "PML 1000 ans",
    "tvar_95_eur": "TVaR 95",
}


def _as_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8", newline="") as fp:
        return list(csv.DictReader(fp))


def _zero_to_zero_pct(row: dict[str, str], sample_column: str, delta_column: str) -> float | None:
    full_value = _as_float(row.get("full_value"))
    sample_value = _as_float(row.get(sample_column))
    delta_value = _as_float(row.get(delta_column))
    if full_value == 0.0 and sample_value == 0.0 and delta_value == 0.0:
        return 0.0
    return None


def _pct_pair(row: dict[str, str] | None) -> tuple[float | None, float | None]:
    if row is None:
        return (None, None)
    v1 = _as_float(row.get("delta_pct"))
    v2 = _as_float(row.get("v2_delta_pct"))
    if v1 is None:
        v1 = _zero_to_zero_pct(row, "sample_v1_value", "delta_abs")
    if v2 is None:
        v2 = _zero_to_zero_pct(row, "sample_v2_value", "v2_delta_abs")
    return (v1, v2)


def _pct_label(value: float | None) -> str:
    if value is None:
        return "n/a"
    absolute = abs(value)
    if absolute >= 1_000_000:
        return f"{value / 1_000_000:+.2f}M%"
    if absolute >= 10_000:
        return f"{value / 1000:+.0f}k%"
    if absolute >= 1_000:
        return f"{value / 1000:+.1f}k%"
    if absolute >= 100:
        return f"{value:+.0f}%"
    return f"{value:+.1f}%"


def _tick_label(value: float, _pos: int) -> str:
    absolute = abs(value)
    sign = "-" if value < 0 else ""
    if absolute >= 1_000_000:
        return f"{sign}{absolute / 1_000_000:.0f}M"
    if absolute >= 1_000:
        return f"{sign}{absolute / 1_000:.0f}k"
    if absolute >= 10:
        return f"{value:.0f}"
    return f"{value:g}"


def _clean_spines(ax: plt.Axes) -> None:
    for spine in ax.spines.values():
        spine.set_color(BORDER)
        spine.set_linewidth(0.9)


def _symmetric_xlim(values: list[float | None], *, min_abs: float = 1.0, pad: float = 1.28) -> tuple[float, float]:
    finite = [abs(float(value)) for value in values if value is not None and math.isfinite(float(value))]
    maximum = max(finite) if finite else min_abs
    maximum = max(maximum, min_abs)
    return (-maximum * pad, maximum * pad)


def _annotate_bars(ax: plt.Axes, bars: Any, values: list[float | None], *, fontsize: int = 10) -> None:
    for bar, value in zip(bars, values):
        if value is None:
            continue
        y_pos = bar.get_y() + bar.get_height() / 2
        offset = (6, 0) if value >= 0 else (-6, 0)
        align = "left" if value >= 0 else "right"
        ax.annotate(
            _pct_label(value),
            xy=(value, y_pos),
            xytext=offset,
            textcoords="offset points",
            va="center",
            ha=align,
            fontsize=fontsize,
            color="#1f2937",
            clip_on=False,
        )


def _draw_grouped_panel(
    ax: plt.Axes,
    labels: list[str],
    v1_values: list[float | None],
    v2_values: list[float | None],
    *,
    title: str,
    xlim: tuple[float, float],
    symlog: bool = False,
    show_y: bool = True,
) -> None:
    y_values = np.arange(len(labels))
    bar_height = 0.34
    v1_plot = [0.0 if value is None else value for value in v1_values]
    v2_plot = [0.0 if value is None else value for value in v2_values]
    bars1 = ax.barh(
        y_values - bar_height / 2,
        v1_plot,
        bar_height,
        color=BLUE,
        edgecolor="#1e40af",
        linewidth=0.6,
    )
    bars2 = ax.barh(
        y_values + bar_height / 2,
        v2_plot,
        bar_height,
        color=ORANGE,
        edgecolor="#c2410c",
        linewidth=0.6,
    )
    ax.axvline(0, color="#111827", linewidth=0.95)
    ax.set_yticks(y_values)
    ax.set_yticklabels(labels if show_y else [""] * len(labels), fontsize=11)
    ax.invert_yaxis()
    ax.set_title(title, fontsize=15, fontweight="bold", color=TEXT, pad=7)
    ax.grid(axis="x", color=GRID, alpha=0.55, linewidth=0.75)
    ax.set_axisbelow(True)
    ax.set_xlabel("Ecart vs full tracks (%)", fontsize=11)
    if symlog:
        ax.set_xscale("symlog", linthresh=10, linscale=1.0)
        ax.xaxis.set_major_formatter(FuncFormatter(_tick_label))
    ax.set_xlim(*xlim)
    ax.tick_params(axis="x", labelsize=10, colors=TEXT)
    ax.tick_params(axis="y", colors=TEXT, length=0 if not show_y else 3.5)
    _clean_spines(ax)
    _annotate_bars(ax, bars1, v1_values, fontsize=10)
    _annotate_bars(ax, bars2, v2_values, fontsize=10)


def _add_header(fig: plt.Figure, title: str, subtitle: str | None = None, legend_y: float = 0.91) -> None:
    fig.suptitle(title, x=0.5, y=0.985, fontsize=20, fontweight="normal", color=TEXT)
    if subtitle:
        fig.text(0.5, 0.945, subtitle, ha="center", va="center", fontsize=11, color=MUTED)
        legend_y = min(legend_y, 0.912)
    handles = [Patch(color=BLUE, label="Sample V1 5000"), Patch(color=ORANGE, label="Sample V2 5000")]
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, legend_y), ncol=2, frameon=False, fontsize=12)


def _find_metric(
    rows: list[dict[str, str]],
    *,
    category: str,
    hazard: str,
    metric: str,
    component: str = "",
) -> dict[str, str] | None:
    for row in rows:
        if (
            row.get("category") == category
            and row.get("hazard") == hazard
            and row.get("metric") == metric
            and row.get("component", "") == component
            and row.get("scenario") == "all"
        ):
            return row
    return None


def _save(fig: plt.Figure, path: Path) -> None:
    fig.savefig(path, dpi=160, facecolor="white")
    plt.close(fig)


def _plot_portfolio(rows: list[dict[str, str]], output_dir: Path) -> Path:
    labels = [label for label, _metric in PORTFOLIO_ITEMS]
    data: dict[str, tuple[list[float | None], list[float | None]]] = {}
    all_values: list[float | None] = []
    for hazard in HAZARDS:
        v1_values = []
        v2_values = []
        for _label, metric in PORTFOLIO_ITEMS:
            v1, v2 = _pct_pair(_find_metric(rows, category="portfolio", hazard=hazard, metric=metric))
            v1_values.append(v1)
            v2_values.append(v2)
            all_values.extend([v1, v2])
        data[hazard] = (v1_values, v2_values)

    fig, axes = plt.subplots(1, 2, figsize=(16.2, 9.0), sharey=False)
    _add_header(fig, "Guadeloupe - impacts portefeuille vs full tracks", "Delta en % par rapport au run full tracks")
    xlim = _symmetric_xlim(all_values, min_abs=10.0, pad=1.45)
    for index, hazard in enumerate(HAZARDS):
        _draw_grouped_panel(
            axes[index],
            labels,
            data[hazard][0],
            data[hazard][1],
            title=HAZARD_LABELS[hazard],
            xlim=xlim,
            show_y=index == 0,
        )
    fig.subplots_adjust(left=0.22, right=0.975, top=0.79, bottom=0.10, wspace=0.08)
    path = output_dir / "guadeloupe_track_sampling_tornado_impacts_portefeuille.png"
    _save(fig, path)
    return path


def _plot_components(rows: list[dict[str, str]], output_dir: Path) -> Path:
    labels = [label for label, _component in COMPONENT_ITEMS]
    data: dict[str, tuple[list[float | None], list[float | None]]] = {}
    all_values: list[float | None] = []
    for hazard in HAZARDS:
        v1_values = []
        v2_values = []
        for _label, component in COMPONENT_ITEMS:
            v1, v2 = _pct_pair(
                _find_metric(
                    rows,
                    category="portfolio_component",
                    hazard=hazard,
                    metric="direct_eai_component_eur",
                    component=component,
                )
            )
            v1_values.append(v1)
            v2_values.append(v2)
            all_values.extend([v1, v2])
        data[hazard] = (v1_values, v2_values)

    fig, axes = plt.subplots(1, 2, figsize=(16.2, 7.0), sharey=False)
    _add_header(fig, "Guadeloupe - composants EAI direct vs full tracks", "Delta en % par rapport au run full tracks")
    xlim = _symmetric_xlim(all_values, min_abs=20.0, pad=1.45)
    for index, hazard in enumerate(HAZARDS):
        _draw_grouped_panel(
            axes[index],
            labels,
            data[hazard][0],
            data[hazard][1],
            title=HAZARD_LABELS[hazard],
            xlim=xlim,
            show_y=index == 0,
        )
    fig.subplots_adjust(left=0.22, right=0.955, top=0.78, bottom=0.13, wspace=0.08)
    path = output_dir / "guadeloupe_track_sampling_tornado_composants_eai_direct.png"
    _save(fig, path)
    return path


def _object_label(row: dict[str, str]) -> str:
    for key in ("label", "service", "class_key", "component"):
        value = (row.get(key) or "").strip()
        if value:
            return value.replace("_", " ").title() if key != "label" else value
    return ""


def _top_label(row: dict[str, str]) -> str:
    hazard = HAZARD_LABELS.get(row.get("hazard", ""), row.get("hazard", "")).replace("_", " ")
    scenario = (row.get("scenario") or "").upper()
    obj = _object_label(row)
    metric = METRIC_LABELS.get(row.get("metric", ""), (row.get("metric") or "").replace("_", " "))
    return " - ".join(part for part in (hazard, scenario, obj, metric) if part)


def _plot_top10(top_rows: list[dict[str, str]], output_dir: Path) -> Path:
    selected = [
        row
        for row in top_rows
        if row.get("comparison") == "v1_vs_full" and row.get("ranking_basis") == "abs"
    ]
    selected.sort(key=lambda row: int(float(row.get("rank") or 0)))
    selected = selected[:10]
    labels = [_top_label(row) for row in selected]
    v1_values = [_as_float(row.get("delta_pct")) for row in selected]
    v2_values = [_as_float(row.get("v2_delta_pct")) for row in selected]
    xlim = _symmetric_xlim([*v1_values, *v2_values], min_abs=50.0, pad=1.35)

    fig, ax = plt.subplots(1, 1, figsize=(17.6, 8.2))
    _add_header(
        fig,
        "Guadeloupe - 10 plus grands ecarts vs full tracks",
        "Selection: 10 premieres lignes V1 vs full classees par ecart absolu dans top_deltas.csv",
    )
    _draw_grouped_panel(
        ax,
        labels,
        v1_values,
        v2_values,
        title="Top 10 des ecarts absolus",
        xlim=xlim,
        show_y=True,
    )
    fig.subplots_adjust(left=0.36, right=0.965, top=0.77, bottom=0.12)
    path = output_dir / "guadeloupe_track_sampling_tornado_top_10_ecarts.png"
    _save(fig, path)
    return path


def generate_graphs(output_dir: Path) -> list[Path]:
    metrics_rows = _load_csv(output_dir / "metrics_comparison.csv")
    top_rows = _load_csv(output_dir / "top_deltas.csv")
    return [
        _plot_portfolio(metrics_rows, output_dir),
        _plot_components(metrics_rows, output_dir),
        _plot_top10(top_rows, output_dir),
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate tornado-style V1/V2 percentage-delta graphs for the Guadeloupe track-sampling comparison."
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    paths = generate_graphs(output_dir)
    print("[ok] Guadeloupe track-sampling tornado graphs generated")
    for path in paths:
        print(f"  - {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
