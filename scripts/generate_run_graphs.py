#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import html
import json
import math
from pathlib import Path
import shutil
import sys
import textwrap
import webbrowser
from typing import Any

from case_study_sources import HYDRAULIC_ZONING_V2_DIR, territory_label
try:  # pragma: no cover - import path depends on module vs CLI execution
    from scripts.scientific_publication_contract import PUBLIC_SERVICE_KEYS, SCIENTIFIC_SCENARIOS  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    from scientific_publication_contract import PUBLIC_SERVICE_KEYS, SCIENTIFIC_SCENARIOS  # type: ignore
try:  # pragma: no cover - import path depends on module vs CLI execution
    from scripts.build_population_decision_table import build_population_decision_rows  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    from build_population_decision_table import build_population_decision_rows  # type: ignore

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPLETE_RUN_OUTPUTS_DIR = REPO_ROOT / "outputs" / "complete-analysis-runs"
TARGETED_RUN_OUTPUTS_DIR = REPO_ROOT / "outputs" / "targeted-cyclone-runs"
RUN_FAMILY_OUTPUT_DIRS = {
    "complete-analysis": COMPLETE_RUN_OUTPUTS_DIR,
    "targeted-cyclone": TARGETED_RUN_OUTPUTS_DIR,
}
RUN_OUTPUTS_DIR = COMPLETE_RUN_OUTPUTS_DIR
WEB_DATA_DIR = REPO_ROOT / "web" / "data"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "outputs" / "Graphs"
UTC = timezone.utc
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.risk_engine.png_label_layout import (
    grouped_bar_figure_size,
    label_text_color_for_face,
    line_chart_figure_size,
    place_grouped_bar_labels,
    place_line_annotations,
    text_line_count,
)

POPULATION_OVERLAYS_PATH = REPO_ROOT / "web" / "hazard-maps" / "population-overlays.json"
POPULATION_RASTER_PATHS = {
    "guadeloupe": Path("/home/ubuntu/uploads/Population/glp_pop_2020_CN_100m_R2025A_v1.tif"),
}
POPULATION_OVERLAY_COLORS = [
    "#ffffff",
    "#fff7bc",
    "#fee391",
    "#fec44f",
    "#fb923c",
    "#ef4444",
    "#b91c1c",
]
HYDRAULIC_ZONE_BUNDLE_PATHS = {
    "guadeloupe": HYDRAULIC_ZONING_V2_DIR / "guadeloupe_hydraulic_zones_estimate.gpkg",
}
TERRITORY_GRID_DEG = 0.2
HOTSPOT_GRID_DEG = 0.05
ELECTRIC_DECISION_GRID_DEG = 0.1

SUPPORTED_HAZARDS = ("storm", "storm_cmcc")
PML_PERIODS = (10, 20, 50, 100, 200, 1000)

TERRITORY_ALIASES = {
    "gua": "guadeloupe",
    "guadeloupe": "guadeloupe",
    "mar": "martinique",
    "martinique": "martinique",
    "mq": "martinique",
    "mtq": "martinique",
    "stb": "saint-barthelemy",
    "blm": "saint-barthelemy",
    "saintbarth": "saint-barthelemy",
    "saint_barth": "saint-barthelemy",
    "saint-barthelemy": "saint-barthelemy",
    "saint_barthelemy": "saint-barthelemy",
}

HAZARD_ALIASES = {
    "storm": "storm",
    "present": "storm",
    "storm_cmcc": "storm_cmcc",
    "cmcc": "storm_cmcc",
    "future": "storm_cmcc",
}

HAZARD_LABELS = {
    "storm": "STORM",
    "storm_cmcc": "STORM_CMCC",
}
STORM_CMCC_LAYOUT_CHOICES = ("harmonized", "legacy")
STORM_CMCC_LAYOUT = "harmonized"
MATRIX_PERCENT_LABEL_SCALE_DEFAULT = 3.0
MATRIX_PERCENT_LABEL_SCALE = MATRIX_PERCENT_LABEL_SCALE_DEFAULT

HAZARD_COLORS = {
    "storm": "#0f766e",
    "storm_cmcc": "#c2410c",
    "direct": "#1d4ed8",
    "indirect": "#be123c",
    "s1": "#f59e0b",
    "s2": "#ef4444",
    "s3": "#000000",
    "health": "#166534",
}

STATE_COLORS = {
    "S0": "#68b66e",
    "S1": "#fde68a",
    "S2": "#fb923c",
    "S3": "#000000",
}
STATE_SEQUENCE = ("S0", "S1", "S2", "S3")
STATE_LABEL_STYLE_CHOICES = ("code", "descriptive")
STATE_CODE_LABELS = {state: state for state in STATE_SEQUENCE}
STATE_DESCRIPTIVE_LABELS = {
    "S0": "Opérationnel (S0)",
    "S1": "Dégradé (S1)",
    "S2": "Critique (S2)",
    "S3": "Hors service (S3)",
}
STATE_DESCRIPTIVE_SHORT_LABELS = {
    "S0": "Opérationnel",
    "S1": "Dégradé",
    "S2": "Critique",
    "S3": "Hors service",
}
STATE_LABELS = dict(STATE_CODE_LABELS)
STATE_SHORT_LABELS = dict(STATE_CODE_LABELS)
SURGE_COLORS = ["#f7fcfd", "#d0eff2", "#a6dbe4", "#72c5d6", "#3eaac4", "#167f96", "#0a596e", "#04384a"]
LANDSLIDE_COLORS = ["#f7efe8", "#e8c9ae", "#d39b6f", "#ac6940", "#734127"]
WIND_MAP_COLORS = ["#f8e45c", "#f9b24b", "#f2643c", "#c81e5b", "#6d28d9", "#2e1065"]
ELECTRIC_NETWORK_MAP_COLOR = "#FFD744"
LEGACY_ELECTRIC_STATE_LAYER_KEYS = (
    "elec_bt_aerien",
    "elec_bt_souterrain",
    "elec_hta_aerien",
    "elec_hta_souterrain",
)
AGGREGATED_ELECTRIC_STATE_LAYER_KEYS = ("elec_grid_0p1deg",)
ELECTRIC_STATE_LAYER_KEYS = AGGREGATED_ELECTRIC_STATE_LAYER_KEYS + LEGACY_ELECTRIC_STATE_LAYER_KEYS
NETWORK_EXPOSURE_ORDER = (
    "eau_aep",
    "eau_eu",
    "elec_bt_souterrain",
    "elec_bt_aerien",
    "elec_hta_souterrain",
    "elec_hta_aerien",
)
NETWORK_EXPOSURE_LABELS = {
    "eau_aep": "Eau AEP",
    "eau_eu": "Eau EU",
    "elec_bt_souterrain": "Elec BT souterrain",
    "elec_bt_aerien": "Elec BT aerien",
    "elec_hta_souterrain": "Elec HTA souterrain",
    "elec_hta_aerien": "Elec HTA aerien",
}
OUVRAGE_EXPOSURE_LABELS = {
    "eau_aep_ouvrages": "Ouvrages eau AEP",
    "eau_eu_pr": "Postes de refoulement EU",
    "eau_eu_step": "STEP",
}
NETWORK_STATE_MATRIX_SCENARIOS = (
    ("rp10", "RP10"),
    ("rp50", "RP50"),
    ("rp100", "RP100"),
    ("rp1000", "RP1000"),
)
NETWORK_STATE_MATRIX_COLUMNS = (
    ("eau_aep", "Etat reseaux AEP", ("eau_aep",)),
    ("eau_eu", "Etat reseaux EU", ("eau_eu",)),
    ("elec", "Etat reseaux elec", ("elec",)),
)
ECONOMIC_DAMAGE_MATRIX_COLUMNS = (
    ("eau_aep", "Criticite AEP", ("eau_aep",)),
    ("eau_eu", "Criticite EU", ("eau_eu",)),
    ("elec_aerien", "Criticite elec aerien", ("elec_bt_aerien", "elec_hta_aerien")),
    ("elec_souterrain", "Criticite elec souterrain", ("elec_bt_souterrain", "elec_hta_souterrain")),
)

COMPONENT_ORDER = ("wind", "rain", "surge", "landslide")
COMPONENT_LABELS = {
    "wind": "Vent",
    "rain": "Pluie",
    "surge": "Submersion",
    "landslide": "Mouvement de terrain",
}
COMPONENT_COLORS = {
    "wind": "#2563eb",
    "rain": "#0f766e",
    "surge": "#ea580c",
    "landslide": "#7c3aed",
}
DAMAGE_FAMILY_ORDER = ("water", "electric")
DAMAGE_FAMILY_LABELS = {
    "water": "Eau",
    "electric": "Elec",
}
DAMAGE_FAMILY_COLORS = {
    "water": "#0ea5e9",
    "electric": "#f59e0b",
}
DAMAGE_DETAIL_SUBCLASS_ORDER = (
    "eau_aep_reseaux",
    "eau_aep_ouvrages",
    "eau_eu_reseaux",
    "eau_eu_ouvrages",
    "elec_aerien",
    "elec_souterrain",
)
DAMAGE_DETAIL_SUBCLASS_LABELS = {
    "eau_aep_reseaux": "Reseaux AEP",
    "eau_aep_ouvrages": "Ouvrages AEP",
    "eau_eu_reseaux": "Reseaux EU",
    "eau_eu_ouvrages": "Ouvrages EU",
    "elec_aerien": "Reseaux elec aeriens",
    "elec_souterrain": "Reseaux elec souterrains",
}
DAMAGE_DETAIL_SUBCLASS_CLASS_KEYS = {
    "eau_aep_reseaux": ("eau_aep",),
    "eau_aep_ouvrages": ("eau_aep_ouvrages",),
    "eau_eu_reseaux": ("eau_eu",),
    "eau_eu_ouvrages": ("eau_eu_pr", "eau_eu_step"),
    "elec_aerien": ("elec_bt_aerien", "elec_hta_aerien"),
    "elec_souterrain": ("elec_bt_souterrain", "elec_hta_souterrain"),
}
DAMAGE_DETAIL_SUBCLASS_COLORS = {
    "eau_aep_reseaux": "#1d4ed8",
    "eau_aep_ouvrages": "#93c5fd",
    "eau_eu_reseaux": "#0891b2",
    "eau_eu_ouvrages": "#67e8f9",
    "elec_aerien": "#b45309",
    "elec_souterrain": "#f59e0b",
}
DAMAGE_ZONE_OUTPUT_DIRNAME = "Damages_Zones"
DAMAGE_ZONE_HAZARD = "storm"
DAMAGE_ZONE_SCENARIOS = NETWORK_STATE_MATRIX_SCENARIOS
DAMAGE_ZONE_FAMILY_ORDER = ("aep", "eu", "elec")
DAMAGE_ZONE_FAMILY_LABELS = {
    "aep": "AEP",
    "eu": "EU",
    "elec": "Elec",
}
DAMAGE_ZONE_FAMILY_NETWORK_KIND = {
    "aep": "AEP",
    "eu": "EU",
    "elec": "ELEC",
}
DAMAGE_ZONE_FAMILY_CLASS_KEYS = {
    "aep": ("eau_aep", "eau_aep_ouvrages"),
    "eu": ("eau_eu", "eau_eu_pr", "eau_eu_step"),
    "elec": (
        "elec_bt_souterrain",
        "elec_bt_aerien",
        "elec_hta_souterrain",
        "elec_hta_aerien",
    ),
}
DAMAGE_ZONE_MAP_COLORS = ["#fff7bc", "#fee391", "#fec44f", "#fb923c", "#ef4444", "#b91c1c"]
POPULATION_DECISION_PERIODS = ("RP50", "RP100", "RP1000")
POPULATION_DECISION_SERVICES = ("eau_aep", "eau_eu", "elec")
POPULATION_DECISION_SERVICE_LABELS = {
    "eau_aep": "AEP",
    "eau_eu": "EU",
    "elec": "Électricité",
}
POPULATION_DECISION_SERVICE_COLORS = {
    "eau_aep": DAMAGE_DETAIL_SUBCLASS_COLORS["eau_aep_reseaux"],
    "eau_eu": DAMAGE_DETAIL_SUBCLASS_COLORS["eau_eu_reseaux"],
    "elec": DAMAGE_DETAIL_SUBCLASS_COLORS["elec_souterrain"],
}
POPULATION_DECISION_FAILURE_SYMBOLS = {
    "asset": "◆",
    "network": "■",
    "mixed": "◆■",
}
HAZARD_COMPARISON_COLORS = {
    "storm": "#2563eb",
    "storm_cmcc": "#60a5fa",
}
SERVICE_HAZARD_COLORS = {
    ("water", "storm"): "#2563eb",
    ("water", "storm_cmcc"): "#60a5fa",
    ("electric", "storm"): "#b45309",
    ("electric", "storm_cmcc"): "#f59e0b",
}
SERVICE_HAZARD_EDGE_COLORS = {
    ("water", "storm_cmcc"): "#2563eb",
    ("electric", "storm_cmcc"): "#b45309",
}
HAZARD_LINESTYLES = {
    "storm": "solid",
    "storm_cmcc": "dashed",
}
HAZARD_ECHARTS_LINE_TYPES = {
    "storm": "solid",
    "storm_cmcc": "dashed",
}
HAZARD_BAR_HATCHES = {
    "storm": "",
    "storm_cmcc": "...",
}
HAZARD_BAR_EDGE_COLORS = {
    "storm": "#ffffff",
    "storm_cmcc": "#334155",
}
OUTAGE_CAUSE_LABELS = {
    "direct": "Direct",
    "indirect": "Indirect",
}
OUTAGE_CAUSE_TITLE = "Origine\nHS"
OUTAGE_CAUSE_LEGEND_PREFIX = "Origine des hors services"
OUTAGE_CAUSE_COLORS = {
    "direct": "#2563eb",
    "indirect": "#be123c",
}
TARGETED_TRAJECTORY_CATEGORY_COLORS = {
    "-1": "#94a3b8",
    "0": "#38bdf8",
    "1": "#22c55e",
    "2": "#facc15",
    "3": "#fb923c",
    "4": "#ef4444",
    "5": "#7f1d1d",
}
TARGETED_TRAJECTORY_CATEGORY_LABELS = {
    "-1": "Tropical Depression",
    "0": "Tropical Storm",
    "1": "Cat 1",
    "2": "Cat 2",
    "3": "Cat 3",
    "4": "Cat 4",
    "5": "Cat 5",
}
ANNUAL_FEC_COMBO_COLORS = {
    ("guadeloupe", "storm"): "#2563eb",
    ("guadeloupe", "storm_cmcc"): "#60a5fa",
    ("martinique", "storm"): "#0f766e",
    ("martinique", "storm_cmcc"): "#5eead4",
    ("saint-barthelemy", "storm"): "#7c3aed",
    ("saint-barthelemy", "storm_cmcc"): "#c4b5fd",
}
LIFETIME_EXTRA_RETURN_PERIODS = (400, 600, 800)
EXTENDED_PML_PERIODS = tuple(sorted({*PML_PERIODS, *LIFETIME_EXTRA_RETURN_PERIODS}))
RETURN_PERIOD_SCENARIO_BY_PERIOD = {
    10: "rp10",
    50: "rp50",
    100: "rp100",
    1000: "rp1000",
}
EVENT_LOSS_HISTOGRAM_BINS_EUR = (
    (0.0, 50_000_000.0, "0-50 M"),
    (50_000_000.0, 100_000_000.0, "50-100 M"),
    (100_000_000.0, 200_000_000.0, "100-200 M"),
    (200_000_000.0, 300_000_000.0, "200-300 M"),
    (300_000_000.0, 400_000_000.0, "300-400 M"),
    (400_000_000.0, 500_000_000.0, "400-500 M"),
    (500_000_000.0, 600_000_000.0, "500-600 M"),
    (600_000_000.0, 700_000_000.0, "600-700 M"),
    (700_000_000.0, 800_000_000.0, "700-800 M"),
    (800_000_000.0, 900_000_000.0, "800-900 M"),
    (900_000_000.0, 1_000_000_000.0, "900 M-1 B"),
    (1_000_000_000.0, math.inf, ">1 B"),
)

GRAPH_TYPE_ORDER = (
    "run_overview_summary",
    "hazard_metric_scorecard",
    "targeted_event_scorecard",
    "lifetime_fec_by_territory_hazard",
    "pml_ladder_by_territory_hazard",
    "pml_ladder_detail_by_territory_hazard",
    "pml_ladder_detail_key_periods_by_territory_hazard",
    "top_events_by_hazard",
    "wind_year_hist_by_hazard",
    "hazard_component_share_by_return_period",
    "direct_vs_indirect_eai_by_hazard",
)

GRAPH_TYPE_LABELS = {
    "run_overview_summary": "Resume du run",
    "hazard_metric_scorecard": "Scorecard alea",
    "targeted_event_scorecard": "Scorecard evenementiel",
    "lifetime_fec_by_territory_hazard": "FEC duree de vie",
    "pml_ladder_by_territory_hazard": "Echelle PML",
    "pml_ladder_detail_by_territory_hazard": "Echelle PML detaillee",
    "pml_ladder_detail_key_periods_by_territory_hazard": "Echelle PML detaillee periodes principales",
    "top_events_by_hazard": "Top evenements",
    "wind_year_hist_by_hazard": "Histogramme vent max par annee",
    "hazard_component_share_by_return_period": "Contribution aleas par temps de retour",
    "direct_vs_indirect_eai_by_hazard": "Direct vs indirect",
}

SECTION_LABELS = {
    "overview": "Vue d'ensemble",
    "comparison": "Comparaisons",
    "fec": "Courbes FEC",
    "loss": "Metriques de pertes",
    "events": "Evenements majeurs",
    "wind": "Distributions du vent",
    "health": "Sante et dependances",
}


def _display_territory_name(territory: str | None) -> str:
    if not territory:
        return ""
    return territory_label(str(territory))


def _display_territories(territories: list[str]) -> str:
    return ", ".join(_display_territory_name(territory) for territory in territories)


@dataclass
class RunRecord:
    run_id: str
    status: str
    created_at: str | None
    updated_at: str | None
    territories: list[str]
    dynamic_max_tracks: int | None
    memory_budget_gb: float | None
    manifest_path: str
    manifest: dict[str, Any]
    archived_ready_count: int
    run_family: str = "complete-analysis"


@dataclass
class TerritoryPayload:
    territory: str
    payload_path: str
    payload: dict[str, Any]
    source_kind: str
    warning: str | None = None


@dataclass
class GraphSpec:
    graph_id: str
    graph_type: str
    title: str
    section: str
    territory: str | None
    hazard: str | None
    kind: str
    description: str
    echarts_option: dict[str, Any] | None = None
    table_headers: list[str] | None = None
    table_rows: list[list[str]] | None = None
    png_payload: dict[str, Any] | None = None
    warning: str | None = None


@dataclass
class ArchivedArtifact:
    payload_path: str
    payload: dict[str, Any]


@dataclass
class AuxiliaryArtifacts:
    territory: str
    complete_analysis: ArchivedArtifact
    page7_analysis: ArchivedArtifact | None
    case_study_analysis: ArchivedArtifact | None
    wind_maps: ArchivedArtifact | None
    landslide_maps: ArchivedArtifact | None
    network_states_path: str | None
    water_infra_path: str | None
    scientific_web_summary: ArchivedArtifact | None = None
    population_overlays: ArchivedArtifact | None = None
    population_raster_path: str | None = None
    hydraulic_zones_path: str | None = None


_NATIVE_PML_CACHE: dict[tuple[str, str, str], dict[int, float] | None] = {}
_SERVICE_RP_CACHE: dict[tuple[str, str], dict[str, Any] | None] = {}
_WIND_MAP_CACHE: dict[tuple[str, str], tuple[dict[str, Any], str] | None] = {}
_REAL_WIND_TRACK_HIST_CACHE: dict[tuple[str, str, str], tuple[list[float], list[float], str] | None] = {}
_DYNAMIC_HAZARD_BUNDLE_CACHE: dict[tuple[str, str, int], Any] = {}
_BACKEND_RUNTIME: tuple[Any, Any] | None = None
_GEODATAFRAME_CACHE: dict[str, Any] = {}
_GEODATAFRAME_LAYER_CACHE: dict[tuple[str, str | None], Any] = {}


def _count_outputs_by_category(output_dir: Path, paths: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for raw_path in paths:
        path = Path(raw_path)
        try:
            relative = path.relative_to(output_dir)
            category = relative.parts[0] if relative.parts else "root"
        except ValueError:
            category = path.parent.name or "root"
        counts[category] = counts.get(category, 0) + 1
    return dict(sorted(counts.items()))


def _standard_graph_family(graph: GraphSpec) -> str:
    if graph.graph_type == "run_overview_summary":
        return "synthese"
    if graph.section == "wind":
        return "alea"
    return "impact"


def _auxiliary_output_classification(output_dir: Path, raw_path: str) -> tuple[str, str, str]:
    path = Path(raw_path)
    relative = path.relative_to(output_dir)
    category = relative.parts[0] if relative.parts else "root"
    file_name = relative.name.lower()
    if category == "Population":
        technical_type = "chart" if "matrice_" in file_name else "map"
    elif category == DAMAGE_ZONE_OUTPUT_DIRNAME:
        technical_type = "map"
    else:
        technical_type = {"charts": "chart", "maps": "map", "tables": "table"}.get(category, "file")
    if category == "maps":
        if any(token in file_name for token in ("storm_vent", "pluie", "inondation_cotiere", "mouvements_de_terrain", "bassin_")):
            family = "alea"
        elif any(token in file_name for token in ("aep_canalisations", "haute_tension_souterrain")):
            family = "exposition"
        else:
            family = "impact"
    elif category == "Population":
        family = "impact"
    elif category == DAMAGE_ZONE_OUTPUT_DIRNAME:
        family = "impact"
    elif category == "charts":
        if "vent_max" in file_name:
            family = "alea"
        else:
            family = "impact"
    elif category == "tables":
        if "comparaison_aleas" in file_name:
            family = "alea"
        else:
            family = "impact"
    else:
        family = "autre"
    return str(relative), technical_type, family


def _build_generated_output_records(
    output_dir: Path,
    graphs: list[GraphSpec],
    png_paths: list[str],
    auxiliary_output_paths: list[str],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for graph, raw_path in zip(graphs, png_paths):
        path = Path(raw_path)
        relative = str(path.relative_to(output_dir))
        records.append(
            {
                "path": relative,
                "technical_type": graph.kind,
                "family": _standard_graph_family(graph),
                "source": "standard",
                "graph_type": graph.graph_type,
                "territory": graph.territory,
                "hazard": graph.hazard,
            }
        )
    for raw_path in auxiliary_output_paths:
        relative, technical_type, family = _auxiliary_output_classification(output_dir, raw_path)
        records.append(
            {
                "path": relative,
                "technical_type": technical_type,
                "family": family,
                "source": "integrated_auxiliary",
                "graph_type": None,
                "territory": None,
                "hazard": None,
            }
        )
    return records


def _count_generated_outputs(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        value = str(record.get(key) or "autre")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _parse_timestamp(raw_value: Any) -> datetime | None:
    value = str(raw_value or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _timestamp_sort_key(payload: dict[str, Any]) -> datetime:
    updated = _parse_timestamp(payload.get("updated_at"))
    created = _parse_timestamp(payload.get("created_at"))
    return updated or created or datetime.fromtimestamp(0, tz=UTC)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid JSON payload at {path}")
    return payload


def _slugify(value: str) -> str:
    out = []
    for char in str(value or "").lower():
        if char.isalnum():
            out.append(char)
        else:
            out.append("-")
    cleaned = "".join(out).strip("-")
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned or "graph"


def _format_eur(value: Any) -> str:
    return f"{_safe_float(value):,.2f} EUR".replace(",", " ")


def _format_number(value: Any) -> str:
    return f"{_safe_float(value):,.2f}".replace(",", " ")


def _format_compact_number(value: Any) -> str:
    numeric = _safe_float(value)
    magnitude = abs(numeric)
    if magnitude >= 1_000_000_000:
        return f"{numeric / 1_000_000_000:.2f} B"
    if magnitude >= 1_000_000:
        return f"{numeric / 1_000_000:.2f} M"
    if magnitude >= 1_000:
        return f"{numeric / 1_000:.2f} k"
    return f"{numeric:.2f}"


def _format_compact_eur(value: Any) -> str:
    return f"{_format_compact_number(value)} EUR"


def _stringify_value(value: Any) -> str:
    if isinstance(value, float):
        return _format_number(value)
    if isinstance(value, (int, str, bool)) or value is None:
        return str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _format_percent(value: Any) -> str:
    return f"{_safe_float(value):.2f}%"


def _format_compact_percent_label(value: Any) -> str:
    text = f"{_safe_float(value):.2f}".rstrip("0").rstrip(".")
    return f"{text}%"


def _format_million_label(value_eur: Any) -> str:
    return f"{_safe_float(value_eur) / 1_000_000.0:.2f}"


def _format_pml_total_side_label(value_eur: Any) -> str:
    numeric = _safe_float(value_eur)
    if abs(numeric) >= 1_000_000_000.0:
        return f"{numeric / 1_000_000_000.0:.2f}B"
    return _format_million_label(numeric)


def _format_side_segment_label(value_eur: Any, pct_value: Any) -> str:
    return f"{_format_million_label(value_eur)} ({_format_compact_percent_label(pct_value)})"


def set_state_label_style(style: str) -> None:
    normalized = str(style or "code").strip().lower()
    if normalized not in STATE_LABEL_STYLE_CHOICES:
        raise ValueError(f"Unsupported state label style: {style!r}")
    if normalized == "descriptive":
        labels = STATE_DESCRIPTIVE_LABELS
        short_labels = STATE_DESCRIPTIVE_SHORT_LABELS
    else:
        labels = STATE_CODE_LABELS
        short_labels = STATE_CODE_LABELS
    STATE_LABELS.clear()
    STATE_LABELS.update(labels)
    STATE_SHORT_LABELS.clear()
    STATE_SHORT_LABELS.update(short_labels)


def set_storm_cmcc_layout(layout: str) -> None:
    global STORM_CMCC_LAYOUT
    normalized = str(layout or "harmonized").strip().lower()
    if normalized not in STORM_CMCC_LAYOUT_CHOICES:
        raise ValueError(f"Unsupported storm/cmcc layout: {layout!r}")
    STORM_CMCC_LAYOUT = normalized


def set_matrix_percent_label_scale(scale: Any) -> None:
    global MATRIX_PERCENT_LABEL_SCALE
    MATRIX_PERCENT_LABEL_SCALE = max(_safe_float(scale, default=MATRIX_PERCENT_LABEL_SCALE_DEFAULT), 0.1)


def _matrix_percent_label_scale(payload: dict[str, Any] | None = None) -> float:
    if isinstance(payload, dict) and "percent_label_scale" in payload:
        return max(_safe_float(payload.get("percent_label_scale"), default=MATRIX_PERCENT_LABEL_SCALE), 0.1)
    return MATRIX_PERCENT_LABEL_SCALE


def _matrix_percent_label_fontsize(base_fontsize: int | float, scale: float) -> int:
    return max(1, int(round(float(base_fontsize) * max(scale, 0.1))))


def _hazard_comparison_color(hazard: str, family: str | None = None) -> str:
    normalized_hazard = _normalize_hazard(hazard)
    normalized_family = str(family or "").strip().lower() or None
    if STORM_CMCC_LAYOUT == "legacy":
        return HAZARD_COLORS.get(normalized_hazard, "#64748b")
    if normalized_family:
        service_color = SERVICE_HAZARD_COLORS.get((normalized_family, normalized_hazard))
        if service_color:
            return service_color
    return HAZARD_COMPARISON_COLORS.get(normalized_hazard, HAZARD_COLORS.get(normalized_hazard, "#64748b"))


def _hazard_line_series_style(hazard: str, family: str | None = None) -> dict[str, str]:
    normalized_hazard = _normalize_hazard(hazard)
    return {
        "color": _hazard_comparison_color(normalized_hazard, family=family),
        "linestyle": HAZARD_LINESTYLES.get(normalized_hazard, "solid"),
    }


def _hazard_bar_series_style(hazard: str, family: str | None = None) -> dict[str, Any]:
    normalized_hazard = _normalize_hazard(hazard)
    style: dict[str, Any] = {
        "color": _hazard_comparison_color(normalized_hazard, family=family),
    }
    if STORM_CMCC_LAYOUT != "legacy":
        hatch = HAZARD_BAR_HATCHES.get(normalized_hazard, "")
        if hatch:
            style["hatch"] = hatch
            style["edgecolor"] = (
                SERVICE_HAZARD_EDGE_COLORS.get((str(family or "").strip().lower(), normalized_hazard))
                or HAZARD_BAR_EDGE_COLORS.get(normalized_hazard)
                or "#334155"
            )
            style["linewidth"] = 0.7
    return style


def _hazard_group_hatch(hazard: str) -> str:
    normalized_hazard = _normalize_hazard(hazard)
    if STORM_CMCC_LAYOUT == "legacy":
        return "///" if normalized_hazard == "storm_cmcc" else ""
    return HAZARD_BAR_HATCHES.get(normalized_hazard, "")


def _matplotlib_bar_kwargs(item: dict[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"color": item.get("color") or "#0f766e"}
    hatch = str(item.get("hatch") or "")
    if hatch:
        kwargs["hatch"] = hatch
        kwargs["edgecolor"] = item.get("edgecolor") or "#334155"
        kwargs["linewidth"] = _safe_float(item.get("linewidth"), default=0.7)
    return kwargs


def _state_label(state: str) -> str:
    return STATE_LABELS.get(str(state or "").upper(), str(state or ""))


def _state_short_label(state: str) -> str:
    return STATE_SHORT_LABELS.get(str(state or "").upper(), str(state or ""))


def _state_join_label(states: tuple[str, ...]) -> str:
    return " / ".join(_state_label(state) for state in states)


def _state_range_label(first_state: str, last_state: str) -> str:
    return f"{_state_label(first_state)} a {_state_label(last_state)}"


def _format_damage_share_label(damage_eur: float, total_value_eur: float) -> str:
    damage_text = _format_compact_eur(damage_eur)
    denominator = _safe_float(total_value_eur, default=0.0)
    if denominator <= 0.0:
        return damage_text
    damage_pct = (max(float(damage_eur), 0.0) / denominator) * 100.0
    return f"{damage_text}\n({_format_percent(damage_pct)} valeur)"


def _damage_family_for_class_key(class_key: Any) -> str | None:
    key = str(class_key or "").strip().lower()
    if key.startswith("eau_"):
        return "water"
    if key.startswith("elec_"):
        return "electric"
    return None


def _graph_inputs_have_required_scenarios(inputs: Any) -> bool:
    graph_inputs = inputs if isinstance(inputs, dict) else {}
    if list(graph_inputs.get("scenarios") or []) != list(SCIENTIFIC_SCENARIOS):
        return False
    state_tables = graph_inputs.get("state_damage_tables")
    breakdowns = graph_inputs.get("damage_breakdown_by_scenario")
    return isinstance(state_tables, dict) and isinstance(breakdowns, dict)


def _scientific_inputs_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    strict_inputs = payload.get("scientific_graph_inputs")
    if _graph_inputs_have_required_scenarios(strict_inputs):
        return strict_inputs if isinstance(strict_inputs, dict) else {}
    pml_inputs = payload.get("pml_network_graph_inputs")
    if _graph_inputs_have_required_scenarios(pml_inputs):
        return pml_inputs if isinstance(pml_inputs, dict) else {}
    return strict_inputs if isinstance(strict_inputs, dict) else {}


def _damage_breakdown_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    breakdown = _scientific_inputs_from_payload(payload).get("damage_breakdown_by_scenario")
    return breakdown if isinstance(breakdown, dict) else {}


def _state_damage_tables_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    tables = _scientific_inputs_from_payload(payload).get("state_damage_tables")
    return tables if isinstance(tables, dict) else {}


def _nearest_return_period_scenario(period: int) -> str | None:
    if period in RETURN_PERIOD_SCENARIO_BY_PERIOD:
        return RETURN_PERIOD_SCENARIO_BY_PERIOD[period]
    available = sorted(RETURN_PERIOD_SCENARIO_BY_PERIOD)
    if not available:
        return None
    nearest = min(available, key=lambda candidate: abs(candidate - int(period)))
    return RETURN_PERIOD_SCENARIO_BY_PERIOD[nearest]


def _family_damage_totals_from_rows(rows: list[Any]) -> dict[str, float]:
    totals = {family: 0.0 for family in DAMAGE_FAMILY_ORDER}
    for row in rows:
        if not isinstance(row, dict):
            continue
        family = _damage_family_for_class_key(row.get("class_key"))
        if family is None:
            continue
        totals[family] += max(_safe_float(row.get("damage_eur")), 0.0)
    return totals


def _family_damage_shares_from_rows(rows: list[Any]) -> dict[str, float]:
    totals = _family_damage_totals_from_rows(rows)
    denominator = sum(totals.values())
    if denominator <= 0.0:
        return {family: (100.0 if index == 0 else 0.0) for index, family in enumerate(DAMAGE_FAMILY_ORDER)}
    return {family: totals[family] / denominator for family in DAMAGE_FAMILY_ORDER}


def _family_damage_shares_for_payload(
    payload: dict[str, Any],
    hazard: str,
    *,
    scenario_key: str | None = None,
) -> dict[str, float]:
    damage_by_scenario = _damage_breakdown_from_payload(payload)
    rows: list[Any] = []
    if scenario_key:
        scenario_block = damage_by_scenario.get(scenario_key) if isinstance(damage_by_scenario.get(scenario_key), dict) else {}
        hazard_rows = scenario_block.get(hazard) if isinstance(scenario_block.get(hazard), list) else []
        rows.extend(hazard_rows)
    else:
        for scenario_block in damage_by_scenario.values():
            if not isinstance(scenario_block, dict):
                continue
            hazard_rows = scenario_block.get(hazard) if isinstance(scenario_block.get(hazard), list) else []
            rows.extend(hazard_rows)
    return _family_damage_shares_from_rows(rows)


def _damage_detail_subclass_for_class_key(class_key: Any) -> str | None:
    key = str(class_key or "").strip().lower()
    if not key:
        return None
    for subclass_key, class_keys in DAMAGE_DETAIL_SUBCLASS_CLASS_KEYS.items():
        if key in class_keys:
            return subclass_key
    return None


def _damage_detail_subclass_totals_from_rows(rows: list[Any]) -> tuple[dict[str, float], dict[str, float]]:
    damage_totals = {subclass_key: 0.0 for subclass_key in DAMAGE_DETAIL_SUBCLASS_ORDER}
    exposure_totals = {subclass_key: 0.0 for subclass_key in DAMAGE_DETAIL_SUBCLASS_ORDER}
    for row in rows:
        if not isinstance(row, dict):
            continue
        subclass_key = _damage_detail_subclass_for_class_key(row.get("class_key"))
        if subclass_key is None:
            continue
        damage_totals[subclass_key] += max(_safe_float(row.get("damage_eur")), 0.0)
        exposure_totals[subclass_key] += max(_safe_float(row.get("exposure_eur")), 0.0)
    return damage_totals, exposure_totals


def _hazard_damage_detail_rows_for_payload(
    payload: dict[str, Any],
    hazard: str,
    scenario_key: str | None,
) -> list[Any]:
    if not scenario_key:
        return []
    damage_by_scenario = _damage_breakdown_from_payload(payload)
    scenario_block = damage_by_scenario.get(scenario_key) if isinstance(damage_by_scenario.get(scenario_key), dict) else {}
    rows = scenario_block.get(hazard) if isinstance(scenario_block.get(hazard), list) else []
    return list(rows)


def _component_damage_totals_for_scenario(
    payload: dict[str, Any],
    scenario_key: str,
    hazard: str,
) -> dict[str, float]:
    scenario_block = _damage_breakdown_from_payload(payload).get(scenario_key)
    if not isinstance(scenario_block, dict):
        return {}
    rows = scenario_block.get(hazard) if isinstance(scenario_block.get(hazard), list) else []
    totals = {component: 0.0 for component in COMPONENT_ORDER}
    for row in rows:
        if not isinstance(row, dict):
            continue
        components = row.get("damage_components_eur") if isinstance(row.get("damage_components_eur"), dict) else {}
        for component, value in components.items():
            component_key = str(component or "").strip()
            if component_key not in totals:
                totals[component_key] = 0.0
            totals[component_key] += max(_safe_float(value), 0.0)
    return totals


def _outage_cause_shares_from_state_tables(
    payload: dict[str, Any],
    scenario_key: str,
    hazard: str,
    class_key: str,
) -> dict[str, float] | None:
    rows = _state_damage_tables_from_payload(payload).get(scenario_key)
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict) or str(row.get("class_key") or "") != class_key:
            continue
        hazard_block = row.get(hazard) if isinstance(row.get(hazard), dict) else {}
        direct = max(_safe_float(hazard_block.get("direct_damage_eur")), 0.0)
        indirect = max(_safe_float(hazard_block.get("indirect_damage_eur")), 0.0)
        total = direct + indirect
        if total <= 0.0:
            return {"direct": 0.0, "indirect": 0.0}
        return {
            "direct": round((direct / total) * 100.0, 4),
            "indirect": round((indirect / total) * 100.0, 4),
        }
    return None


def _canonical_outage_cause_key(value: Any) -> str | None:
    cause = str(value or "").strip().lower()
    if cause == "direct_damage":
        return "direct"
    if cause in {"blocking_ouvrage", "electric_dependency"}:
        return "indirect"
    return None


def _rebin_loss_histogram_percentages(
    bin_values: list[float],
    percentages: list[float],
) -> list[float]:
    rebinned = [0.0 for _low, _high, _label in EVENT_LOSS_HISTOGRAM_BINS_EUR]
    for raw_value, raw_percent in zip(bin_values, percentages):
        value = _safe_float(raw_value)
        percent = max(_safe_float(raw_percent), 0.0)
        for idx, (low, high, _label) in enumerate(EVENT_LOSS_HISTOGRAM_BINS_EUR):
            if value >= low and value < high:
                rebinned[idx] += percent
                break
    return [round(value, 4) for value in rebinned]


def _split_cli_values(values: list[str] | None) -> list[str]:
    out: list[str] = []
    for item in values or []:
        for part in str(item).split(","):
            token = part.strip()
            if token:
                out.append(token)
    return out


def _normalize_territory(value: str) -> str:
    normalized = TERRITORY_ALIASES.get(str(value or "").strip().lower())
    if not normalized:
        raise ValueError(f"Unsupported territory: {value}")
    return normalized


def _archived_web_data_dir(record: RunRecord, territory: str) -> Path:
    if _record_is_graph_pack_manifest(record):
        entry = _territory_entry(record, territory)
        payload_path = Path(str(entry.get("payload_path") or ""))
        if payload_path.exists():
            return payload_path.parent
        return Path(record.manifest_path).parent
    return RUN_OUTPUTS_DIR / record.run_id / "territories" / territory / "web" / "data"


def _load_optional_archived_json(path: Path) -> ArchivedArtifact | None:
    if not path.exists():
        return None
    return ArchivedArtifact(payload_path=str(path), payload=_load_json(path))


def _load_case_study_analysis(base_dir: Path, territory: str) -> ArchivedArtifact | None:
    for candidate in sorted(base_dir.glob(f"{territory}-page*-analysis.json")):
        loaded = _load_optional_archived_json(candidate)
        if loaded is not None:
            return loaded
    return None


def _load_auxiliary_artifacts(record: RunRecord, bundle: TerritoryPayload) -> AuxiliaryArtifacts:
    territory = bundle.territory
    base_dir = _archived_web_data_dir(record, territory)
    population_overlays = _load_optional_archived_json(POPULATION_OVERLAYS_PATH)
    population_raster_path = POPULATION_RASTER_PATHS.get(territory)
    hydraulic_zones_path = HYDRAULIC_ZONE_BUNDLE_PATHS.get(territory)
    complete_analysis = ArchivedArtifact(payload_path=bundle.payload_path, payload=bundle.payload)
    scientific_web_summary = _load_optional_archived_json(base_dir / f"{territory}-scientific-web-summary.json")
    bundle_payload_path = Path(bundle.payload_path)
    if bundle_payload_path.name == f"{territory}-scientific-web-summary.json":
        scientific_web_summary = ArchivedArtifact(payload_path=bundle.payload_path, payload=bundle.payload)
        sibling_complete = bundle_payload_path.with_name(f"{territory}-complete-analysis.json")
        if sibling_complete.exists():
            complete_analysis = ArchivedArtifact(payload_path=str(sibling_complete), payload=_load_json(sibling_complete))

    network_states_candidates = [
        base_dir / f"{territory}-network-states.geojson",
        bundle_payload_path.parent / f"{territory}-network-states.geojson",
    ]
    water_infra_candidates = [
        base_dir / f"{territory}-water-infra.geojson",
        bundle_payload_path.parent / f"{territory}-water-infra.geojson",
    ]
    if _record_is_graph_pack_manifest(record):
        network_states_candidates.append(WEB_DATA_DIR / f"{territory}-network-states.geojson")
        water_infra_candidates.append(WEB_DATA_DIR / f"{territory}-water-infra.geojson")
    network_states_path = next((path for path in network_states_candidates if path.exists()), None)
    water_infra_path = next((path for path in water_infra_candidates if path.exists()), None)
    return AuxiliaryArtifacts(
        territory=territory,
        complete_analysis=complete_analysis,
        scientific_web_summary=scientific_web_summary,
        page7_analysis=_load_optional_archived_json(base_dir / f"{territory}-page7-analysis.json"),
        case_study_analysis=_load_case_study_analysis(base_dir, territory),
        wind_maps=_load_optional_archived_json(base_dir / f"{territory}-wind-maps.json"),
        landslide_maps=_load_optional_archived_json(base_dir / f"{territory}-landslide-maps.json"),
        network_states_path=str(network_states_path) if network_states_path else None,
        water_infra_path=str(water_infra_path) if water_infra_path else None,
        population_overlays=population_overlays,
        population_raster_path=str(population_raster_path) if population_raster_path and population_raster_path.exists() else None,
        hydraulic_zones_path=str(hydraulic_zones_path) if hydraulic_zones_path and hydraulic_zones_path.exists() else None,
    )


def _normalize_hazard(value: str) -> str:
    normalized = HAZARD_ALIASES.get(str(value or "").strip().lower())
    if not normalized:
        raise ValueError(f"Unsupported hazard: {value}")
    return normalized


def _normalize_graph_type(value: str) -> str:
    candidate = str(value or "").strip().lower()
    if candidate in GRAPH_TYPE_ORDER:
        return candidate
    raise ValueError(f"Unsupported graph type: {value}")


def _graph_id(graph_type: str, territory: str | None = None, hazard: str | None = None) -> str:
    parts = [graph_type]
    if territory:
        parts.append(territory)
    if hazard:
        parts.append(hazard)
    return "__".join(parts)


def _resolve_latest_manifest_run_id() -> str:
    latest_manifest = RUN_OUTPUTS_DIR / "latest-manifest.json"
    if not latest_manifest.exists():
        raise FileNotFoundError(f"Latest manifest not found: {latest_manifest}")
    payload = _load_json(latest_manifest)
    run_id = str(payload.get("run_id") or "").strip()
    if not run_id:
        raise ValueError(f"Latest manifest does not expose run_id: {latest_manifest}")
    return run_id


def _count_archived_payloads(manifest: dict[str, Any]) -> int:
    territories = manifest.get("territories") if isinstance(manifest.get("territories"), dict) else {}
    count = 0
    for territory, entry in territories.items():
        if not isinstance(entry, dict):
            continue
        export_phase = entry.get("phases") if isinstance(entry.get("phases"), dict) else {}
        export_phase = export_phase.get("export") if isinstance(export_phase.get("export"), dict) else {}
        candidates = [
            entry.get("archived_complete_analysis_path"),
            export_phase.get("archived_output_file"),
        ]
        for candidate in candidates:
            if candidate and Path(str(candidate)).exists():
                count += 1
                break
        else:
            default_archived = RUN_OUTPUTS_DIR / str(manifest.get("run_id") or "") / "territories" / str(territory) / "web" / "data" / f"{territory}-complete-analysis.json"
            if default_archived.exists():
                count += 1
    return count


def _resolve_run_family(raw_value: str | None) -> str:
    value = str(raw_value or "complete-analysis").strip().lower()
    aliases = {
        "complete-analysis": "complete-analysis",
        "complete_analysis": "complete-analysis",
        "complete": "complete-analysis",
        "targeted-cyclone": "targeted-cyclone",
        "targeted_cyclone": "targeted-cyclone",
        "targeted": "targeted-cyclone",
    }
    if value not in aliases:
        raise ValueError(f"Unsupported run family: {raw_value!r}")
    return aliases[value]


def _infer_record_run_family(manifest: dict[str, Any]) -> str:
    explicit = str(manifest.get("run_family") or "").strip().lower()
    if explicit:
        return _resolve_run_family(explicit)
    parameters = manifest.get("parameters") if isinstance(manifest.get("parameters"), dict) else {}
    return _resolve_run_family(parameters.get("run_family"))


def _record_is_graph_pack_manifest(record: RunRecord) -> bool:
    return Path(record.manifest_path).name == "graphs-manifest.json"


def list_run_records() -> list[RunRecord]:
    records: list[RunRecord] = []
    if not RUN_OUTPUTS_DIR.exists():
        return records
    for child in sorted(RUN_OUTPUTS_DIR.iterdir()):
        if not child.is_dir():
            continue
        manifest_path = child / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            manifest = _load_json(manifest_path)
        except Exception as exc:
            print(f"[warn] Skipping invalid manifest {manifest_path}: {exc}", file=sys.stderr)
            continue
        territories = manifest.get("territories") if isinstance(manifest.get("territories"), dict) else {}
        params = manifest.get("parameters") if isinstance(manifest.get("parameters"), dict) else {}
        records.append(
            RunRecord(
                run_id=str(manifest.get("run_id") or child.name),
                status=str(manifest.get("status") or "unknown"),
                created_at=str(manifest.get("created_at") or "") or None,
                updated_at=str(manifest.get("updated_at") or "") or None,
                territories=sorted(str(key) for key in territories.keys()),
                dynamic_max_tracks=_safe_int(params.get("dynamic_max_tracks"), default=0) or None,
                memory_budget_gb=_safe_float(params.get("memory_budget_gb"), default=0.0) or None,
                manifest_path=str(manifest_path),
                manifest=manifest,
                archived_ready_count=_count_archived_payloads(manifest),
                run_family=_infer_record_run_family(manifest),
            )
        )
    records.sort(key=lambda item: _timestamp_sort_key(item.manifest), reverse=True)
    return records


def print_runs(records: list[RunRecord]) -> None:
    if not records:
        print(f"No runs found under {RUN_OUTPUTS_DIR}")
        return
    headers = (
        "run_id",
        "family",
        "status",
        "updated_at",
        "territories",
        "tracks",
        "archived",
    )
    rows: list[tuple[str, ...]] = []
    for record in records:
        rows.append(
            (
                record.run_id,
                record.run_family,
                record.status,
                record.updated_at or record.created_at or "",
                ",".join(record.territories),
                str(record.dynamic_max_tracks or ""),
                f"{record.archived_ready_count}/{len(record.territories)}",
            )
        )
    widths = [len(header) for header in headers]
    for row in rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))
    fmt = "  ".join(f"{{:{width}}}" for width in widths)
    print(fmt.format(*headers))
    print(fmt.format(*["-" * width for width in widths]))
    for row in rows:
        print(fmt.format(*row))


def resolve_run_record(run_id: str | None, latest_success: bool, records: list[RunRecord]) -> RunRecord:
    normalized_run_id = str(run_id or "").strip().lower()
    if normalized_run_id in {"latest-success", "latest_success", "latest-successful"}:
        run_id = None
        latest_success = True

    if run_id:
        if str(run_id).strip().lower() == "latest":
            selected_id = _resolve_latest_manifest_run_id()
        else:
            selected_id = str(run_id).strip()
        for record in records:
            if record.run_id == selected_id:
                return record
        manifest_path = RUN_OUTPUTS_DIR / selected_id / "manifest.json"
        if not manifest_path.exists():
            graph_manifest_path = DEFAULT_OUTPUT_ROOT / selected_id / "graphs-manifest.json"
            if graph_manifest_path.exists():
                manifest = _load_json(graph_manifest_path)
                territories = manifest.get("territories") if isinstance(manifest.get("territories"), dict) else {}
                return RunRecord(
                    run_id=str(manifest.get("run_id") or selected_id),
                    status=str(manifest.get("status") or "success"),
                    created_at=str(manifest.get("created_at") or "") or None,
                    updated_at=str(manifest.get("updated_at") or "") or None,
                    territories=sorted(str(key) for key in territories.keys()),
                    dynamic_max_tracks=None,
                    memory_budget_gb=None,
                    manifest_path=str(graph_manifest_path),
                    manifest=manifest,
                    archived_ready_count=sum(
                        1
                        for entry in territories.values()
                        if isinstance(entry, dict)
                        and str(entry.get("payload_path") or "").strip()
                        and Path(str(entry.get("payload_path"))).exists()
                    ),
                    run_family=_infer_record_run_family(manifest),
                )
        if not manifest_path.exists():
            raise FileNotFoundError(f"Run manifest not found for run_id={selected_id}")
        manifest = _load_json(manifest_path)
        territories = manifest.get("territories") if isinstance(manifest.get("territories"), dict) else {}
        params = manifest.get("parameters") if isinstance(manifest.get("parameters"), dict) else {}
        return RunRecord(
            run_id=str(manifest.get("run_id") or selected_id),
            status=str(manifest.get("status") or "unknown"),
            created_at=str(manifest.get("created_at") or "") or None,
            updated_at=str(manifest.get("updated_at") or "") or None,
            territories=sorted(str(key) for key in territories.keys()),
            dynamic_max_tracks=_safe_int(params.get("dynamic_max_tracks"), default=0) or None,
            memory_budget_gb=_safe_float(params.get("memory_budget_gb"), default=0.0) or None,
            manifest_path=str(manifest_path),
            manifest=manifest,
            archived_ready_count=_count_archived_payloads(manifest),
            run_family=_infer_record_run_family(manifest),
        )
    if latest_success or not run_id:
        successful = [record for record in records if record.status == "success"]
        if not successful:
            raise RuntimeError(f"No successful run found under {RUN_OUTPUTS_DIR}")
        return successful[0]
    raise RuntimeError("Unable to resolve run selection")


def _resolve_selected_territories(record: RunRecord, requested: list[str]) -> list[str]:
    available = [territory for territory in record.territories]
    if not requested:
        return available
    wanted = [_normalize_territory(item) for item in requested]
    selected = [territory for territory in available if territory in wanted]
    if not selected:
        raise RuntimeError(f"No matching territories found in run {record.run_id}: {', '.join(wanted)}")
    return selected


def _resolve_selected_hazards(requested: list[str]) -> list[str]:
    if not requested:
        return list(SUPPORTED_HAZARDS)
    out = []
    seen: set[str] = set()
    for item in requested:
        normalized = _normalize_hazard(item)
        if normalized not in seen:
            out.append(normalized)
            seen.add(normalized)
    return out


def _default_graph_types_for_run_family(run_family: str) -> list[str]:
    if run_family == "targeted-cyclone":
        return [
            "run_overview_summary",
            "targeted_event_scorecard",
            "direct_vs_indirect_eai_by_hazard",
            "top_events_by_hazard",
        ]
    return [
        "run_overview_summary",
        "pml_ladder_by_territory_hazard",
        "pml_ladder_detail_by_territory_hazard",
        "pml_ladder_detail_key_periods_by_territory_hazard",
        "wind_year_hist_by_hazard",
        "hazard_component_share_by_return_period",
    ]


def _resolve_selected_graph_types(requested: list[str]) -> list[str]:
    if not requested:
        return list(GRAPH_TYPE_ORDER)
    out = []
    seen: set[str] = set()
    for item in requested:
        normalized = _normalize_graph_type(item)
        if normalized not in seen:
            out.append(normalized)
            seen.add(normalized)
    return out


def _territory_payload_candidates(record: RunRecord, territory: str) -> list[tuple[Path, str]]:
    run_id = record.run_id
    territory_entry = record.manifest.get("territories") if isinstance(record.manifest.get("territories"), dict) else {}
    territory_entry = territory_entry.get(territory) if isinstance(territory_entry.get(territory), dict) else {}
    if _record_is_graph_pack_manifest(record):
        payload_path = str(territory_entry.get("payload_path") or "").strip()
        return [(Path(payload_path), str(territory_entry.get("source_kind") or "graph_pack_payload"))] if payload_path else []
    phases = territory_entry.get("phases") if isinstance(territory_entry.get("phases"), dict) else {}
    export_phase = phases.get("export") if isinstance(phases.get("export"), dict) else {}
    candidates: list[tuple[Path, str]] = []
    raw_candidates = [
        (territory_entry.get("archived_complete_analysis_path"), "archived_complete_analysis_path"),
        (export_phase.get("archived_output_file"), "archived_output_file"),
        (
            RUN_OUTPUTS_DIR / run_id / "territories" / territory / "web" / "data" / f"{territory}-complete-analysis.json",
            "default_archived_path",
        ),
    ]
    seen: set[str] = set()
    for raw_path, label in raw_candidates:
        if not raw_path:
            continue
        path = Path(str(raw_path))
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        candidates.append((path, label))
    return candidates


def load_territory_payload(record: RunRecord, territory: str) -> TerritoryPayload:
    for candidate_path, label in _territory_payload_candidates(record, territory):
        if not candidate_path.exists():
            continue
        payload = _load_json(candidate_path)
        return TerritoryPayload(
            territory=territory,
            payload_path=str(candidate_path),
            payload=payload,
            source_kind=label if _record_is_graph_pack_manifest(record) else "archived",
            warning=None,
        )
    raise FileNotFoundError(
        f"No archived complete-analysis JSON found for territory={territory} in run {record.run_id}"
    )


def _extract_graph_block(payload: dict[str, Any], hazard: str, block_name: str) -> dict[str, Any] | None:
    graphs = payload.get("graphs") if isinstance(payload.get("graphs"), dict) else {}
    hazard_block = graphs.get(hazard) if isinstance(graphs.get(hazard), dict) else {}
    block = hazard_block.get(block_name) if isinstance(hazard_block.get(block_name), dict) else None
    if block:
        return block
    portfolio = payload.get("portfolio_results") if isinstance(payload.get("portfolio_results"), dict) else {}
    fec_block = portfolio.get("fec_curve") if isinstance(portfolio.get("fec_curve"), dict) else {}
    if isinstance(fec_block.get(hazard), dict):
        nested = fec_block.get(hazard)
        if isinstance(nested.get(block_name), dict):
            return nested.get(block_name)
        if block_name == "annual_fec" and {"return_period_years", "damage_eur"}.issubset(set(nested.keys())):
            return nested
    if block_name == "annual_fec" and {"return_period_years", "damage_eur"}.issubset(set(fec_block.keys())):
        return fec_block
    return None


def _extract_event_list(payload: dict[str, Any], hazard: str) -> list[dict[str, Any]]:
    portfolio = payload.get("portfolio_results") if isinstance(payload.get("portfolio_results"), dict) else {}
    event_summary = portfolio.get("event_summary") if isinstance(portfolio.get("event_summary"), dict) else {}
    key = "storm_top_events" if hazard == "storm" else "storm_cmcc_top_events"
    events = event_summary.get(key)
    if isinstance(events, list):
        return [item for item in events if isinstance(item, dict)]
    return []


def _extract_hazard_metrics(payload: dict[str, Any], hazard: str) -> dict[str, Any]:
    portfolio = payload.get("portfolio_results") if isinstance(payload.get("portfolio_results"), dict) else {}
    hazard_block = portfolio.get(hazard) if isinstance(portfolio.get(hazard), dict) else {}
    return hazard_block


def _payload_run_family(payload: dict[str, Any]) -> str:
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    explicit = str(meta.get("run_family") or "").strip().lower()
    if explicit:
        return _resolve_run_family(explicit)
    return "complete-analysis"


def _payload_report_semantics(payload: dict[str, Any]) -> str:
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    return str(meta.get("report_semantics") or "").strip().lower() or "probabilistic"


def _available_hazards_for_payload(payload: dict[str, Any]) -> list[str]:
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    hazard_names = meta.get("hazards") if isinstance(meta.get("hazards"), list) else []
    resolved: list[str] = []
    seen: set[str] = set()
    for raw_value in hazard_names:
        normalized = str(raw_value or "").strip().lower()
        if normalized == "storm":
            key = "storm"
        elif normalized in {"storm_cmcc", "cmcc"}:
            key = "storm_cmcc"
        elif normalized == "storm_cmcc".lower():
            key = "storm_cmcc"
        else:
            key = HAZARD_ALIASES.get(normalized)
        if key and key not in seen:
            resolved.append(key)
            seen.add(key)
    portfolio = payload.get("portfolio_results") if isinstance(payload.get("portfolio_results"), dict) else {}
    for hazard in SUPPORTED_HAZARDS:
        if isinstance(portfolio.get(hazard), dict) and hazard not in seen:
            resolved.append(hazard)
            seen.add(hazard)
    return resolved or list(SUPPORTED_HAZARDS)


def _available_hazards_for_payloads(payloads: dict[str, TerritoryPayload]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for bundle in payloads.values():
        for hazard in _available_hazards_for_payload(bundle.payload):
            if hazard not in seen:
                out.append(hazard)
                seen.add(hazard)
    return out or list(SUPPORTED_HAZARDS)


def _extract_component_metric_map(payload: dict[str, Any], hazard: str, metric_key: str) -> dict[str, float]:
    hazard_metrics = _extract_hazard_metrics(payload, hazard)
    raw_map = hazard_metrics.get(metric_key) if isinstance(hazard_metrics.get(metric_key), dict) else {}
    out: dict[str, float] = {}
    for component in COMPONENT_ORDER:
        out[component] = _safe_float(raw_map.get(component))
    return out


def _dict_path_get(data: Any, *keys: str) -> Any:
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _load_backend_runtime() -> tuple[Any, Any]:
    global _BACKEND_RUNTIME
    if _BACKEND_RUNTIME is not None:
        return _BACKEND_RUNTIME

    backend_root_str = str(BACKEND_ROOT)
    if backend_root_str not in sys.path:
        sys.path.insert(0, backend_root_str)

    from app.config import load_settings  # type: ignore
    from app.risk_engine.hazard_loader import load_storm_hazards_from_parquet_for_points  # type: ignore

    _BACKEND_RUNTIME = (load_settings, load_storm_hazards_from_parquet_for_points)
    return _BACKEND_RUNTIME


def _territory_entry(record: RunRecord, territory: str) -> dict[str, Any]:
    territories = record.manifest.get("territories") if isinstance(record.manifest.get("territories"), dict) else {}
    entry = territories.get(territory)
    return entry if isinstance(entry, dict) else {}


def _territory_modeling(record: RunRecord, territory: str) -> dict[str, Any]:
    phases = _territory_entry(record, territory).get("phases")
    if not isinstance(phases, dict):
        return {}
    impacts = phases.get("impacts")
    if not isinstance(impacts, dict):
        return {}
    modeling = impacts.get("modeling")
    return modeling if isinstance(modeling, dict) else {}


def _resolve_enabled_components(record: RunRecord, territory: str, payload: dict[str, Any], hazard: str) -> list[str]:
    candidates = _dict_path_get(payload, "meta", "modeling", "multi_hazard_components_by_hazard", hazard)
    if not isinstance(candidates, list):
        candidates = _dict_path_get(_territory_modeling(record, territory), "multi_hazard_components_by_hazard", hazard)
    if not isinstance(candidates, list):
        candidates = ["wind", "rain", "surge"]
    out: list[str] = []
    for component in candidates:
        component_name = str(component or "").strip().lower()
        if component_name and component_name not in out:
            out.append(component_name)
    return out or ["wind", "rain", "surge"]


def _resolve_total_exposure_value(record: RunRecord, territory: str, payload: dict[str, Any]) -> float:
    candidates = (
        _dict_path_get(payload, "meta", "modeling", "hazard_exposure_matching_qa", "point_value_total_eur"),
        _dict_path_get(payload, "matching_qa", "point_value_total_eur"),
        _dict_path_get(_territory_modeling(record, territory), "hazard_exposure_matching_qa", "point_value_total_eur"),
    )
    for candidate in candidates:
        numeric = _safe_float(candidate, default=0.0)
        if numeric > 0.0:
            return numeric
    return 0.0


def _resolve_hazard_scaler(payload: dict[str, Any], hazard: str) -> float:
    hazard_metrics = _extract_hazard_metrics(payload, hazard)
    direct = _safe_float(hazard_metrics.get("eai_direct_eur"), default=0.0)
    total = _safe_float(hazard_metrics.get("eai_eur"), default=0.0)
    if direct <= 0.0:
        return 1.0
    return max(total / direct, 1.0)


def _resolve_checkpoint_dir(record: RunRecord, territory: str) -> Path | None:
    modeling = _territory_modeling(record, territory)
    raw_checkpoint_dir = modeling.get("sharding_checkpoint_dir")
    if raw_checkpoint_dir:
        checkpoint_dir = Path(str(raw_checkpoint_dir))
        if checkpoint_dir.exists():
            return checkpoint_dir
    fallback = RUN_OUTPUTS_DIR / record.run_id / "territories" / territory / "checkpoints"
    if fallback.exists():
        return fallback
    return None


def _compute_pml_from_arrays(losses: Any, frequency: Any, return_periods: tuple[int, ...]) -> dict[int, float]:
    import numpy as np

    losses_arr = np.asarray(losses, dtype=float).reshape(-1)
    freq_arr = np.asarray(frequency, dtype=float).reshape(-1)
    valid = (losses_arr > 0.0) & (freq_arr > 0.0)
    if not valid.any():
        return {int(rp): 0.0 for rp in return_periods}

    losses_valid = losses_arr[valid]
    freq_valid = freq_arr[valid]
    sort_idxs = np.argsort(losses_valid)[::-1]
    exceed_freq = np.cumsum(freq_valid[sort_idxs])
    impact_curve = losses_valid[sort_idxs][::-1]
    return_curve = np.divide(
        1.0,
        exceed_freq[::-1],
        out=np.full(exceed_freq.size, np.inf, dtype=float),
        where=exceed_freq[::-1] > 0.0,
    )
    finite = np.isfinite(return_curve) & (return_curve > 0.0)
    if not finite.any():
        return {int(rp): 0.0 for rp in return_periods}

    interpolated = np.interp(
        np.asarray(return_periods, dtype=float),
        return_curve[finite],
        impact_curve[finite],
    )
    return {
        int(rp): float(max(0.0, interpolated[idx]))
        for idx, rp in enumerate(return_periods)
    }


def _checkpoint_service_from_point_id(point_id: Any) -> str:
    text = str(point_id or "").split("::", 1)[0].strip().lower().replace("_", "-")
    if "elec" in text:
        return "electric"
    if "eau" in text or text.startswith("aep") or text.startswith("eu-") or "-eu-" in text:
        return "water"
    return "other"


def _compute_service_rp_curves_from_checkpoints(record: RunRecord, artifacts: AuxiliaryArtifacts) -> dict[str, Any] | None:
    territory = artifacts.territory
    cache_key = (record.run_id, territory)
    if cache_key in _SERVICE_RP_CACHE:
        return _SERVICE_RP_CACHE[cache_key]

    checkpoint_dir = _resolve_checkpoint_dir(record, territory)
    if checkpoint_dir is None:
        _SERVICE_RP_CACHE[cache_key] = None
        return None

    import numpy as np

    payload = artifacts.complete_analysis.payload
    rows: list[dict[str, Any]] = []
    series_data: dict[tuple[str, str], dict[int, float]] = {}
    overall_quality: dict[str, int] = {"total_shards": 0, "mixed_shards": 0, "approximate_shards": 0}

    for hazard in _available_hazards_for_payload(payload):
        hazard_quality: dict[str, int] = {"total_shards": 0, "mixed_shards": 0, "approximate_shards": 0}
        combined_by_service: dict[str, Any] = {}
        combined_frequency: Any | None = None
        available_components = 0
        for component in _resolve_enabled_components(record, territory, payload, hazard):
            component_root = checkpoint_dir / "dynamic-hazard-shards" / hazard / component
            result_paths = sorted(component_root.glob("**/results/*.npz"))
            if not result_paths:
                continue
            component_by_service: dict[str, Any] = {}
            component_frequency: Any | None = None
            for result_path in result_paths:
                with np.load(result_path, allow_pickle=False) as checkpoint:
                    if "at_event_loss" not in checkpoint.files or "event_frequency" not in checkpoint.files:
                        continue
                    shard_at_event = np.asarray(checkpoint["at_event_loss"], dtype=float).reshape(-1)
                    shard_frequency = np.asarray(checkpoint["event_frequency"], dtype=float).reshape(-1)
                    point_ids = [str(value) for value in list(checkpoint["point_id"])] if "point_id" in checkpoint.files else []
                if shard_at_event.size == 0:
                    continue
                services: dict[str, int] = {}
                for point_id in point_ids:
                    service = _checkpoint_service_from_point_id(point_id)
                    if service in {"water", "electric"}:
                        services[service] = services.get(service, 0) + 1
                if not services:
                    continue
                hazard_quality["total_shards"] += 1
                overall_quality["total_shards"] += 1
                if len(services) > 1:
                    hazard_quality["mixed_shards"] += 1
                    hazard_quality["approximate_shards"] += 1
                    overall_quality["mixed_shards"] += 1
                    overall_quality["approximate_shards"] += 1
                total_points = float(max(1, sum(services.values())))
                if component_frequency is None:
                    component_frequency = shard_frequency
                if component_frequency.size != shard_at_event.size:
                    _SERVICE_RP_CACHE[cache_key] = None
                    return None
                for service, count in services.items():
                    weight = float(count) / total_points
                    if service not in component_by_service:
                        component_by_service[service] = np.zeros_like(shard_at_event, dtype=float)
                    component_by_service[service] += shard_at_event * weight
            if component_frequency is None or not component_by_service:
                continue
            available_components += 1
            if combined_frequency is None:
                combined_frequency = component_frequency
            if combined_frequency.size != component_frequency.size:
                _SERVICE_RP_CACHE[cache_key] = None
                return None
            for service, component_losses in component_by_service.items():
                if service not in combined_by_service:
                    combined_by_service[service] = np.zeros_like(component_losses, dtype=float)
                combined_by_service[service] += component_losses

        if available_components <= 0 or combined_frequency is None:
            continue
        scaler = _resolve_hazard_scaler(payload, hazard)
        for service, losses in combined_by_service.items():
            pml = _compute_pml_from_arrays(losses, combined_frequency, PML_PERIODS)
            scaled = {int(rp): round(float(value) * scaler, 2) for rp, value in pml.items()}
            series_data[(service, hazard)] = scaled
            for rp in PML_PERIODS:
                rows.append(
                    {
                        "territory": territory,
                        "service": service,
                        "hazard": hazard,
                        "return_period_years": int(rp),
                        "damage_eur": float(scaled.get(int(rp), 0.0)),
                        "mixed_shards": int(hazard_quality["mixed_shards"]),
                        "total_shards": int(hazard_quality["total_shards"]),
                        "quality": "approximate_mixed_shards" if int(hazard_quality["mixed_shards"]) else "exact_service_shards",
                    }
                )

    if not rows:
        _SERVICE_RP_CACHE[cache_key] = None
        return None
    result = {"rows": rows, "series_data": series_data, "quality": overall_quality}
    _SERVICE_RP_CACHE[cache_key] = result
    return result


def _build_service_rp_curve_payload(record: RunRecord, artifacts: AuxiliaryArtifacts, title: str) -> dict[str, Any] | None:
    computed = _compute_service_rp_curves_from_checkpoints(record, artifacts)
    if not computed:
        return None
    labels = {
        "water": "Eau",
        "electric": "Elec",
    }
    series = []
    rp_axis_positions = list(range(len(PML_PERIODS)))
    for service in ("water", "electric"):
        for hazard in SUPPORTED_HAZARDS:
            pml = computed["series_data"].get((service, hazard))
            if not pml:
                continue
            y_values = [float(pml.get(int(rp), 0.0)) for rp in PML_PERIODS]
            style = _hazard_line_series_style(hazard, family=service)
            series.append(
                {
                    "name": f"{labels[service]} {HAZARD_LABELS[hazard]}",
                    "x": list(rp_axis_positions),
                    "y": y_values,
                    "color": style["color"],
                    "linestyle": style["linestyle"],
                    "annotations": [_format_compact_eur(value) if value > 0.0 else "" for value in y_values],
                }
            )
    quality = computed.get("quality") if isinstance(computed.get("quality"), dict) else {}
    note = (
        f"Diagnostic approximatif : {int(quality.get('mixed_shards') or 0)} shards sur "
        f"{int(quality.get('total_shards') or 0)} melangent eau/elec; les pertes y sont reparties au prorata des points."
        if int(quality.get("mixed_shards") or 0)
        else "Diagnostic exact : les checkpoints sont homogenes par service eau/elec."
    )
    return {
        "type": "line",
        "title": title,
        "xlabel": "Temps de retour (ans)",
        "ylabel": "Dommages directs (EUR)",
        "series": series,
        "legacy_line_layout": True,
        "xticks": list(rp_axis_positions),
        "xtick_labels": [str(int(period)) for period in PML_PERIODS],
        "yaxis_format": "compact_eur",
        "note": note,
    }


def _build_hist_percent(values: list[float], bins_count: int = 7) -> tuple[list[float], list[float]]:
    cleaned = [max(0.0, float(value)) for value in values if isinstance(value, (int, float))]
    if not cleaned:
        return [0.0] * bins_count, [0.0] * bins_count
    value_min = min(cleaned)
    value_max = max(cleaned)
    if value_max <= value_min:
        return [round(value_max, 4)] * bins_count, ([100.0] + [0.0] * (bins_count - 1))
    width = (value_max - value_min) / bins_count
    bins = [value_min + width * (idx + 1) for idx in range(bins_count)]
    counts = [0] * bins_count
    for value in cleaned:
        idx = int((value - value_min) / width)
        if idx >= bins_count:
            idx = bins_count - 1
        counts[idx] += 1
    total = max(1, sum(counts))
    percent = [round((count / total) * 100.0, 2) for count in counts]
    return [round(bin_edge, 4) for bin_edge in bins], percent


def _load_native_pml_map(record: RunRecord, territory: str, payload: dict[str, Any], hazard: str) -> dict[int, float] | None:
    cache_key = (record.run_id, territory, hazard)
    if cache_key in _NATIVE_PML_CACHE:
        return _NATIVE_PML_CACHE[cache_key]

    checkpoint_dir = _resolve_checkpoint_dir(record, territory)
    if checkpoint_dir is None:
        _NATIVE_PML_CACHE[cache_key] = None
        return None

    import numpy as np

    combined_at_event: Any | None = None
    combined_frequency: Any | None = None
    available_components = 0
    for component in _resolve_enabled_components(record, territory, payload, hazard):
        component_root = checkpoint_dir / "dynamic-hazard-shards" / hazard / component
        if not component_root.exists():
            continue
        component_at_event: Any | None = None
        component_frequency: Any | None = None
        result_paths = sorted(component_root.glob("**/results/*.npz"))
        if not result_paths:
            continue
        for result_path in result_paths:
            with np.load(result_path, allow_pickle=False) as checkpoint:
                if "at_event_loss" not in checkpoint.files or "event_frequency" not in checkpoint.files:
                    continue
                shard_at_event = np.asarray(checkpoint["at_event_loss"], dtype=float).reshape(-1)
                shard_frequency = np.asarray(checkpoint["event_frequency"], dtype=float).reshape(-1)
                if component_at_event is None:
                    component_at_event = np.zeros_like(shard_at_event, dtype=float)
                    component_frequency = shard_frequency
                if shard_at_event.size != component_at_event.size or shard_frequency.size != component_at_event.size:
                    _NATIVE_PML_CACHE[cache_key] = None
                    return None
                component_at_event += shard_at_event
        if component_at_event is None or component_frequency is None:
            continue
        available_components += 1
        if combined_at_event is None:
            combined_at_event = component_at_event
            combined_frequency = component_frequency
            continue
        if component_at_event.size != combined_at_event.size or component_frequency.size != combined_at_event.size:
            _NATIVE_PML_CACHE[cache_key] = None
            return None
        combined_at_event += component_at_event

    if available_components == 0 or combined_at_event is None or combined_frequency is None:
        _NATIVE_PML_CACHE[cache_key] = None
        return None

    scaler = _resolve_hazard_scaler(payload, hazard)
    native_pml = _compute_pml_from_arrays(combined_at_event, combined_frequency, EXTENDED_PML_PERIODS)
    resolved = {int(period): round(float(value) * scaler, 2) for period, value in native_pml.items()}
    _NATIVE_PML_CACHE[cache_key] = resolved
    return resolved


def _resolve_annual_fec_curve(
    record: RunRecord,
    territory: str,
    payload: dict[str, Any],
    hazard: str,
) -> tuple[list[float], list[float], list[int], str | None]:
    block = _extract_graph_block(payload, hazard, "annual_fec")
    if not block:
        return [], [], [], None
    rp_values = [int(round(float(item))) for item in block.get("return_period_years") or []]
    damage_values = [round(float(item), 2) for item in block.get("damage_eur") or []]
    if not rp_values or len(rp_values) != len(damage_values):
        return [], [], [], None

    combined = {rp_values[idx]: damage_values[idx] for idx in range(len(rp_values))}
    native_added: list[int] = []
    warning = None
    native_pml = _load_native_pml_map(record, territory, payload, hazard)
    if native_pml is None:
        warning = (
            "Native 400/600/800-year losses could not be recomputed from archived checkpoints; "
            "the graph falls back to the published backend support points only."
        )
    else:
        for return_period in LIFETIME_EXTRA_RETURN_PERIODS:
            if return_period in combined or return_period not in native_pml:
                continue
            combined[return_period] = round(float(native_pml[return_period]), 2)
            native_added.append(return_period)
    ordered_periods = sorted(combined)
    return [float(period) for period in ordered_periods], [float(combined[period]) for period in ordered_periods], native_added, warning


def _build_point_labels(return_periods: list[float], damages: list[float], total_value_eur: float) -> list[str]:
    labels: list[str] = []
    denominator = max(total_value_eur, 0.0)
    for idx in range(min(len(return_periods), len(damages))):
        loss = float(damages[idx])
        if denominator > 0.0:
            labels.append(
                f"{int(round(return_periods[idx]))}y\\n{_format_compact_eur(loss)}\\n{_format_percent((loss / denominator) * 100.0)}"
            )
        else:
            labels.append(f"{int(round(return_periods[idx]))}y\\n{_format_compact_eur(loss)}")
    return labels


def _build_compact_point_labels(return_periods: list[float], damages: list[float]) -> list[str]:
    labels: list[str] = []
    for idx in range(min(len(return_periods), len(damages))):
        labels.append(f"{int(round(return_periods[idx]))}y\n{_format_compact_eur(float(damages[idx]))}")
    return labels


def _build_labeled_line_points(x_values: list[float], y_values: list[float], labels: list[str]) -> list[Any]:
    points: list[Any] = []
    if not x_values:
        return points
    min_x = min(float(value) for value in x_values)
    max_x = max(float(value) for value in x_values)
    span_x = max(max_x - min_x, 1.0)
    for idx in range(min(len(x_values), len(y_values))):
        label = labels[idx] if idx < len(labels) else ""
        if label:
            x_value = float(x_values[idx])
            position = "top" if idx % 2 == 0 else "bottom"
            if x_value <= (min_x + 0.08 * span_x):
                position = "right"
            elif x_value >= (max_x - 0.05 * span_x):
                position = "left"
            points.append(
                {
                    "value": [x_value, float(y_values[idx])],
                    "label": {
                        "show": True,
                        "formatter": label,
                        "fontSize": 9,
                        "position": position,
                    },
                }
            )
        else:
            points.append([float(x_values[idx]), float(y_values[idx])])
    return points


def _estimate_lifetime_factor(
    annual_map: dict[int, float],
    series_periods: list[float],
    series_damages: list[float],
) -> float | None:
    for idx in range(min(len(series_periods), len(series_damages))):
        period = int(round(float(series_periods[idx])))
        annual_value = float(annual_map.get(period, 0.0))
        series_value = float(series_damages[idx])
        if annual_value > 0.0 and series_value > 0.0:
            return series_value / annual_value
    return None


def _resolve_wind_map_payload(record: RunRecord, territory: str) -> tuple[dict[str, Any], str] | None:
    cache_key = (record.run_id, territory)
    if cache_key in _WIND_MAP_CACHE:
        return _WIND_MAP_CACHE[cache_key]

    candidates = [
        RUN_OUTPUTS_DIR / record.run_id / "territories" / territory / "web" / "data" / f"{territory}-wind-maps.json",
        WEB_DATA_DIR / f"{territory}-wind-maps.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            resolved = (_load_json(candidate), str(candidate))
            _WIND_MAP_CACHE[cache_key] = resolved
            return resolved
    _WIND_MAP_CACHE[cache_key] = None
    return None


def _resolve_track_count(record: RunRecord, territory: str, hazard: str, wind_map_payload: dict[str, Any]) -> int:
    modeling = _territory_modeling(record, territory)
    manifest_key = "hazard_track_count_storm" if hazard == "storm" else "hazard_track_count_storm_cmcc"
    candidates = [
        modeling.get(manifest_key),
        _dict_path_get(wind_map_payload, hazard, "native_tracks_used"),
        _dict_path_get(wind_map_payload, hazard, "tracks_approx"),
        _dict_path_get(wind_map_payload, "meta", "track_journal", hazard, "n_events"),
        record.dynamic_max_tracks,
    ]
    for candidate in candidates:
        track_count = _safe_int(candidate, default=0)
        if track_count > 0:
            return track_count
    return 0


def _load_dynamic_hazard_bundle(record: RunRecord, territory: str, max_tracks: int, point_coords: list[tuple[float, float]]) -> Any:
    cache_key = (record.run_id, territory, int(max_tracks))
    if cache_key in _DYNAMIC_HAZARD_BUNDLE_CACHE:
        return _DYNAMIC_HAZARD_BUNDLE_CACHE[cache_key]

    load_settings, load_storm_hazards_from_parquet_for_points = _load_backend_runtime()
    settings = load_settings()
    modeling = _territory_modeling(record, territory)
    storm_years = _safe_int(modeling.get("storm_years"), default=_safe_int(getattr(settings, "storm_years", 10000), default=10000))
    bundle = load_storm_hazards_from_parquet_for_points(
        storm_parquet_path=Path(getattr(settings, "storm_parquet_path")),
        cmcc_parquet_path=Path(getattr(settings, "storm_cmcc_parquet_path")),
        point_coords=point_coords,
        storm_years=storm_years,
        max_tracks=int(max_tracks),
        track_cache_max_entries=_safe_int(getattr(settings, "hazard_track_cache_max_entries", 8), default=8),
        wind_unit_in=str(getattr(settings, "storm_wind_unit_in", "m/s")),
        convert_10min_to_1min=bool(getattr(settings, "storm_convert_10min_to_1min", True)),
        radius_unit_in=str(getattr(settings, "storm_radius_unit_in", "km")),
        env_pressure_hpa=_safe_float(getattr(settings, "storm_env_pressure_hpa", 1010.0), default=1010.0),
    )
    _DYNAMIC_HAZARD_BUNDLE_CACHE[cache_key] = bundle
    return bundle


def _build_real_wind_track_hist(record: RunRecord, territory: str, hazard: str) -> tuple[list[float], list[float], str] | None:
    cache_key = (record.run_id, territory, hazard)
    if cache_key in _REAL_WIND_TRACK_HIST_CACHE:
        return _REAL_WIND_TRACK_HIST_CACHE[cache_key]

    resolved_wind_map = _resolve_wind_map_payload(record, territory)
    if resolved_wind_map is None:
        _REAL_WIND_TRACK_HIST_CACHE[cache_key] = None
        return None

    wind_map_payload, wind_map_path = resolved_wind_map
    hazard_block = wind_map_payload.get(hazard) if isinstance(wind_map_payload.get(hazard), dict) else {}
    cells = hazard_block.get("cells") if isinstance(hazard_block.get("cells"), list) else []
    point_coords: list[tuple[float, float]] = []
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        lat = cell.get("grid_lat", cell.get("lat"))
        lon = cell.get("grid_lon", cell.get("lon"))
        if lat is None or lon is None:
            continue
        point_coords.append((float(lat), float(lon)))
    if not point_coords:
        _REAL_WIND_TRACK_HIST_CACHE[cache_key] = None
        return None

    track_count = _resolve_track_count(record, territory, hazard, wind_map_payload)
    if track_count <= 0:
        _REAL_WIND_TRACK_HIST_CACHE[cache_key] = None
        return None

    bundle = _load_dynamic_hazard_bundle(record, territory, track_count, point_coords)
    hazard_obj = getattr(bundle, "storm", None) if hazard == "storm" else getattr(bundle, "storm_cmcc", None)
    if hazard_obj is None or getattr(hazard_obj, "intensity", None) is None:
        _REAL_WIND_TRACK_HIST_CACHE[cache_key] = None
        return None

    intensity = hazard_obj.intensity.tocsr()
    maxima: list[float] = []
    for row in range(intensity.shape[0]):
        start = int(intensity.indptr[row])
        end = int(intensity.indptr[row + 1])
        if start >= end:
            continue
        values = intensity.data[start:end]
        positives = [float(value) for value in values if math.isfinite(float(value)) and float(value) > 0.0]
        if positives:
            maxima.append(max(positives))
    if not maxima:
        _REAL_WIND_TRACK_HIST_CACHE[cache_key] = None
        return None

    bins_mps, percent = _build_hist_percent(maxima, bins_count=7)
    result = (bins_mps, percent, wind_map_path)
    _REAL_WIND_TRACK_HIST_CACHE[cache_key] = result
    return result


def _resolve_component_order(payload: dict[str, Any], selected_hazards: list[str], metric_key: str) -> list[str]:
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    modeling = meta.get("modeling") if isinstance(meta.get("modeling"), dict) else {}
    by_hazard = modeling.get("multi_hazard_components_by_hazard") if isinstance(modeling.get("multi_hazard_components_by_hazard"), dict) else {}
    active: set[str] = set()
    for hazard in selected_hazards:
        configured = by_hazard.get(hazard)
        if isinstance(configured, list):
            active.update(str(item) for item in configured)
        for component, value in _extract_component_metric_map(payload, hazard, metric_key).items():
            if value > 0.0:
                active.add(component)
    ordered = [component for component in COMPONENT_ORDER if component in active]
    return ordered or list(COMPONENT_ORDER)


def _interpolate_log_x(x_values: list[float], y_values: list[float], target_x: float) -> float | None:
    if len(x_values) != len(y_values) or len(x_values) < 2:
        return None
    for idx in range(len(x_values) - 1):
        left_x = float(x_values[idx])
        right_x = float(x_values[idx + 1])
        if not (left_x < target_x < right_x):
            continue
        left_log = math.log10(left_x)
        right_log = math.log10(right_x)
        target_log = math.log10(target_x)
        ratio = (target_log - left_log) / max(right_log - left_log, 1e-12)
        left_y = float(y_values[idx])
        right_y = float(y_values[idx + 1])
        return left_y + ratio * (right_y - left_y)
    return None


def _extend_curve_with_return_periods(
    x_values: list[float],
    y_values: list[float],
    target_periods: tuple[int, ...],
) -> tuple[list[float], list[float], list[int]]:
    if len(x_values) != len(y_values):
        return x_values, y_values, []
    pairs = sorted((float(x_values[idx]), float(y_values[idx])) for idx in range(len(x_values)))
    x_sorted = [pair[0] for pair in pairs]
    y_sorted = [pair[1] for pair in pairs]
    inserted: dict[int, float] = {}
    existing = {int(round(value)): idx for idx, value in enumerate(x_sorted)}
    for target in target_periods:
        if target in existing:
            continue
        interpolated = _interpolate_log_x(x_sorted, y_sorted, float(target))
        if interpolated is None:
            continue
        inserted[target] = round(interpolated, 2)
    if not inserted:
        return x_sorted, y_sorted, []
    combined = list(zip(x_sorted, y_sorted)) + [(float(x), y) for x, y in inserted.items()]
    combined.sort(key=lambda item: item[0])
    return [item[0] for item in combined], [item[1] for item in combined], sorted(inserted.keys())


def _build_annotated_line_points(
    x_values: list[float],
    y_values: list[float],
    annotate_x_values: list[int] | tuple[int, ...] | None = None,
) -> list[Any]:
    annotate = {int(value) for value in (annotate_x_values or [])}
    points: list[Any] = []
    for idx in range(len(x_values)):
        x_value = float(x_values[idx])
        y_value = float(y_values[idx])
        x_key = int(round(x_value))
        if x_key in annotate:
            points.append(
                {
                    "value": [x_value, y_value],
                    "label": {
                        "show": True,
                        "formatter": f"{x_key}y\\n{_format_compact_eur(y_value)}",
                        "fontSize": 10,
                        "position": "top",
                    },
                }
            )
        else:
            points.append([x_value, y_value])
    return points


def _build_line_option(title: str, x_name: str, y_name: str, series: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "title": {"text": title},
        "tooltip": {"trigger": "axis"},
        "legend": {"top": 28},
        "grid": {"left": 72, "right": 28, "top": 72, "bottom": 56},
        "xAxis": {"type": "value", "name": x_name, "nameLocation": "middle", "nameGap": 32},
        "yAxis": {"type": "value", "name": y_name, "nameLocation": "middle", "nameGap": 54},
        "series": series,
    }


def _build_bar_option(
    title: str,
    categories: list[str],
    series: list[dict[str, Any]],
    *,
    horizontal: bool = False,
    secondary_axis: bool = False,
) -> dict[str, Any]:
    x_axis: dict[str, Any]
    y_axis: list[dict[str, Any]] | dict[str, Any]
    if horizontal:
        x_axis = {"type": "value"}
        y_axis = {"type": "category", "data": categories}
    else:
        x_axis = {"type": "category", "data": categories, "axisLabel": {"rotate": 22}}
        if secondary_axis:
            y_axis = [{"type": "value"}, {"type": "value", "max": 100}]
        else:
            y_axis = {"type": "value"}
    return {
        "title": {"text": title},
        "tooltip": {"trigger": "axis"},
        "legend": {"top": 28},
        "grid": {"left": 96 if horizontal else 72, "right": 28, "top": 72, "bottom": 72},
        "xAxis": x_axis,
        "yAxis": y_axis,
        "series": series,
    }


def _build_grouped_stacked_bar_option(title: str, categories: list[str], groups: list[dict[str, Any]]) -> dict[str, Any]:
    flat_categories: list[str] = []
    series_by_segment: dict[str, dict[str, Any]] = {}
    for category_idx, category in enumerate(categories):
        for group in groups:
            group_name = str(group.get("name") or "")
            flat_categories.append(f"{category}\n{group_name}")
            for segment in [item for item in (group.get("segments") or []) if isinstance(item, dict)]:
                name = str(segment.get("name") or "")
                values = list(segment.get("values") or [])
                bucket = series_by_segment.setdefault(
                    name,
                    {
                        "name": name,
                        "type": "bar",
                        "stack": "family",
                        "data": [],
                        "itemStyle": {"color": segment.get("color") or "#64748b"},
                    },
                )
                bucket["data"].append(_safe_float(values[category_idx] if category_idx < len(values) else 0.0))
    return _build_bar_option(title, flat_categories, list(series_by_segment.values()))


def _make_table_graph(
    graph_type: str,
    title: str,
    section: str,
    description: str,
    headers: list[str],
    rows: list[list[str]],
    *,
    territory: str | None = None,
    hazard: str | None = None,
    warning: str | None = None,
) -> GraphSpec:
    return GraphSpec(
        graph_id=_graph_id(graph_type, territory, hazard),
        graph_type=graph_type,
        title=title,
        section=section,
        territory=territory,
        hazard=hazard,
        kind="table",
        description=description,
        table_headers=headers,
        table_rows=rows,
        png_payload={"type": "table", "headers": headers, "rows": rows, "title": title},
        warning=warning,
    )


def build_run_overview_graph(record: RunRecord, payloads: dict[str, TerritoryPayload]) -> GraphSpec:
    rows = [
        ["Run ID", record.run_id],
        ["Famille de run", record.run_family],
        ["Statut", record.status],
        ["Cree le", record.created_at or ""],
        ["Mis a jour le", record.updated_at or ""],
        ["dynamic_max_tracks", str(record.dynamic_max_tracks or "")],
        ["memory_budget_gb", _format_number(record.memory_budget_gb or 0.0)],
        ["Territoires", _display_territories(record.territories)],
    ]
    for territory, bundle in payloads.items():
        display_name = _display_territory_name(territory)
        rows.append([f"Source {display_name}", f"{bundle.source_kind}: {bundle.payload_path}"])
        rows.append([f"Rapport {display_name}", _payload_report_semantics(bundle.payload)])
    return _make_table_graph(
        "run_overview_summary",
        f"Resume du run - {record.run_id}",
        "overview",
        "Resume operateur du run selectionne et des sources chargees.",
        ["Champ", "Valeur"],
        rows,
    )


def build_hazard_metric_scorecard(territory: str, payload: dict[str, Any], selected_hazards: list[str]) -> GraphSpec:
    territory_name = _display_territory_name(territory)
    categories = ["PML10", "PML50", "PML100", "PML1000", "TVaR95"]
    series: list[dict[str, Any]] = []
    for hazard in selected_hazards:
        metrics = _extract_hazard_metrics(payload, hazard)
        style = _hazard_bar_series_style(hazard)
        series.append(
            {
                "name": HAZARD_LABELS[hazard],
                "type": "bar",
                "data": [
                    _safe_float(metrics.get("pml_10_eur")),
                    _safe_float(metrics.get("pml_50_eur")),
                    _safe_float(metrics.get("pml_100_eur")),
                    _safe_float(metrics.get("pml_1000_eur")),
                    _safe_float(metrics.get("tvar_95_eur")),
                ],
                "itemStyle": {"color": style["color"]},
            }
        )
    return GraphSpec(
        graph_id=_graph_id("hazard_metric_scorecard", territory),
        graph_type="hazard_metric_scorecard",
        title=f"Tableau de bord alea - {territory_name}",
        section="overview",
        territory=territory,
        hazard=None,
        kind="chart",
        description="Comparaison synthetique des principales metriques de pertes par alea, hors decomposition directe/indirecte retiree.",
        echarts_option=_build_bar_option(f"Tableau de bord alea - {territory_name}", categories, series),
        png_payload={
            "type": "grouped_bar",
            "title": f"Tableau de bord alea - {territory_name}",
            "categories": categories,
            "series": [
                {
                    "name": str(item.get("name") or ""),
                    "values": list(item.get("data") or []),
                    **_hazard_bar_series_style(str(item.get("name") or "")),
                }
                for item in series
            ],
            "ylabel": "Pertes (EUR)",
        },
    )


def build_storm_vs_cmcc_comparison(territory: str, payload: dict[str, Any], selected_hazards: list[str]) -> GraphSpec | None:
    if set(selected_hazards) != set(SUPPORTED_HAZARDS):
        return None
    territory_name = _display_territory_name(territory)
    comparison = payload.get("graphs") if isinstance(payload.get("graphs"), dict) else {}
    comparison = comparison.get("comparison") if isinstance(comparison.get("comparison"), dict) else {}
    side_by_side = comparison.get("side_by_side") if isinstance(comparison.get("side_by_side"), dict) else {}
    metrics = list(side_by_side.get("metrics") or []) if isinstance(side_by_side.get("metrics"), list) else []
    values = side_by_side.get("values") if isinstance(side_by_side.get("values"), dict) else {}
    if metrics and values:
        categories = [str(item).replace("_", " ").upper() for item in metrics]
        storm_values = [_safe_float(values.get(metric, [0.0, 0.0])[0]) for metric in metrics]
        cmcc_values = [_safe_float(values.get(metric, [0.0, 0.0])[1]) for metric in metrics]
    else:
        storm = _extract_hazard_metrics(payload, "storm")
        cmcc = _extract_hazard_metrics(payload, "storm_cmcc")
        categories = ["ANNUAL EAI", "PML 1000"]
        storm_values = [_safe_float(storm.get("eai_eur")), _safe_float(storm.get("pml_1000_eur"))]
        cmcc_values = [_safe_float(cmcc.get("eai_eur")), _safe_float(cmcc.get("pml_1000_eur"))]
    option = _build_bar_option(
        f"Comparaison STORM / STORM_CMCC - {territory_name}",
        categories,
        [
            {"name": "STORM", "type": "bar", "data": storm_values, "itemStyle": {"color": _hazard_comparison_color("storm")}},
            {"name": "STORM_CMCC", "type": "bar", "data": cmcc_values, "itemStyle": {"color": _hazard_comparison_color("storm_cmcc")}},
        ],
    )
    return GraphSpec(
        graph_id=_graph_id("storm_vs_cmcc_eai_pml1000", territory),
        graph_type="storm_vs_cmcc_eai_pml1000",
        title=f"Comparaison STORM / STORM_CMCC - {territory_name}",
        section="comparison",
        territory=territory,
        hazard=None,
        kind="chart",
        description="Comparaison frontale des metriques annual_eai et pml_1000.",
        echarts_option=option,
        png_payload={
            "type": "grouped_bar",
            "title": f"Comparaison STORM / STORM_CMCC - {territory_name}",
            "categories": categories,
            "series": [
                {"name": "STORM", "values": storm_values, **_hazard_bar_series_style("storm")},
                {"name": "STORM_CMCC", "values": cmcc_values, **_hazard_bar_series_style("storm_cmcc")},
            ],
            "ylabel": "Pertes (EUR)",
        },
    )


def build_tvar95_comparison(territory: str, payload: dict[str, Any], selected_hazards: list[str]) -> GraphSpec:
    territory_name = _display_territory_name(territory)
    categories = [HAZARD_LABELS[hazard] for hazard in selected_hazards]
    values = [_safe_float(_extract_hazard_metrics(payload, hazard).get("tvar_95_eur")) for hazard in selected_hazards]
    option = _build_bar_option(
        f"TVaR95 - {territory_name}",
        categories,
        [{"name": "TVaR95", "type": "bar", "data": values, "itemStyle": {"color": "#7c3aed"}}],
    )
    return GraphSpec(
        graph_id=_graph_id("tvar95_by_territory_hazard", territory),
        graph_type="tvar95_by_territory_hazard",
        title=f"TVaR95 - {territory_name}",
        section="loss",
        territory=territory,
        hazard=None,
        kind="chart",
        description="Comparaison du tail risk TVaR95 entre aleas selectionnes.",
        echarts_option=option,
        png_payload={
            "type": "bar",
            "title": f"TVaR95 - {territory_name}",
            "categories": categories,
            "values": values,
            "color": "#7c3aed",
            "ylabel": "TVaR95 (EUR)",
        },
    )


def build_annual_fec_graph(
    record: RunRecord,
    territory: str,
    payload: dict[str, Any],
    selected_hazards: list[str],
) -> GraphSpec | None:
    territory_name = _display_territory_name(territory)
    total_value_eur = _resolve_total_exposure_value(record, territory, payload)
    series: list[dict[str, Any]] = []
    png_series: list[dict[str, Any]] = []
    warnings: list[str] = []
    for hazard in selected_hazards:
        rp, damage, _, warning = _resolve_annual_fec_curve(record, territory, payload, hazard)
        if not rp or not damage or len(rp) != len(damage):
            continue
        if warning and warning not in warnings:
            warnings.append(warning)
        point_labels = _build_point_labels(rp, damage, total_value_eur)
        style = _hazard_line_series_style(hazard)
        series.append(
            {
                "name": HAZARD_LABELS[hazard],
                "type": "line",
                "smooth": False,
                "showSymbol": True,
                "symbolSize": 8,
                "labelLayout": {"hideOverlap": True},
                "lineStyle": {"width": 3, "color": style["color"], "type": HAZARD_ECHARTS_LINE_TYPES.get(hazard, "solid")},
                "itemStyle": {"color": style["color"]},
                "data": _build_labeled_line_points(rp, damage, point_labels),
            }
        )
        png_series.append(
            {
                "name": HAZARD_LABELS[hazard],
                "x": rp,
                "y": damage,
                "color": style["color"],
                "linestyle": style["linestyle"],
                "annotations": point_labels,
            }
        )
    if not series:
        return None
    option = _build_line_option(
        f"FEC annuelle - {territory_name}",
        "Temps de retour (ans)",
        "Dommages (EUR)",
        series,
    )
    return GraphSpec(
        graph_id=_graph_id("annual_fec_by_territory_hazard", territory),
        graph_type="annual_fec_by_territory_hazard",
        title=f"FEC annuelle - {territory_name}",
        section="fec",
        territory=territory,
        hazard=None,
        kind="chart",
        description=(
            "Courbes de depassement de frequence annuelle STORM/STORM_CMCC du territoire, "
            "avec toutes les composantes actives agregees. Chaque point annote le dommage en EUR et sa part du parc d'infrastructure."
        ),
        echarts_option=option,
        png_payload={
            "type": "line",
            "title": f"FEC annuelle - {territory_name}",
            "series": png_series,
            "xlabel": "Temps de retour (ans)",
            "ylabel": "Dommages (EUR)",
            "legacy_line_layout": True,
            "note": (
                "Les pertes totales des scenarios STORM et STORM_CMCC sont rassemblees sur un meme graphe. "
                "Les etiquettes montrent les dommages en EUR et leur part de la valeur totale d'infrastructure."
            ),
        },
        warning=" | ".join(warnings) if warnings else None,
    )


def build_annual_fec_all_territories_graph(
    record: RunRecord,
    payloads: dict[str, TerritoryPayload],
    selected_territories: list[str],
    selected_hazards: list[str],
) -> GraphSpec | None:
    series: list[dict[str, Any]] = []
    png_series: list[dict[str, Any]] = []
    graph_warnings: list[str] = []
    territory_labels = [territory_label(territory) for territory in selected_territories]
    title_suffix = " + ".join(territory_labels)
    for territory in selected_territories:
        payload = payloads[territory].payload
        for hazard in selected_hazards:
            rp, damage, _, warning = _resolve_annual_fec_curve(record, territory, payload, hazard)
            if not rp or not damage or len(rp) != len(damage):
                continue
            if warning and warning not in graph_warnings:
                graph_warnings.append(warning)
            name = f"{territory_label(territory)} - {HAZARD_LABELS[hazard]}"
            color = ANNUAL_FEC_COMBO_COLORS.get((territory, hazard), HAZARD_COLORS[hazard])
            line_type = HAZARD_LINESTYLES.get(hazard, "solid")
            series.append(
                {
                    "name": name,
                    "type": "line",
                    "smooth": False,
                    "showSymbol": True,
                    "lineStyle": {"width": 3, "color": color, "type": HAZARD_ECHARTS_LINE_TYPES.get(hazard, "solid")},
                    "itemStyle": {"color": color},
                    "data": [[rp[idx], damage[idx]] for idx in range(len(rp))],
                }
            )
            png_series.append({"name": name, "x": rp, "y": damage, "color": color, "linestyle": line_type})
    if len(series) < 2:
        return None
    option = _build_line_option(
        f"FEC annuelle - {title_suffix}",
        "Temps de retour (ans)",
        "Dommages (EUR)",
        series,
    )
    return GraphSpec(
        graph_id=_graph_id("annual_fec_all_territories"),
        graph_type="annual_fec_all_territories",
        title=f"FEC annuelle - {title_suffix}",
        section="fec",
        territory=None,
        hazard=None,
        kind="chart",
        description=f"Vue consolidee sur un seul graphe des courbes annuelles {title_suffix} x STORM/STORM_CMCC.",
        echarts_option=option,
        png_payload={
            "type": "line",
            "title": f"FEC annuelle - {title_suffix}",
            "series": png_series,
            "xlabel": "Temps de retour (ans)",
            "ylabel": "Dommages (EUR)",
            "legacy_line_layout": True,
            "note": "Une courbe par couple territoire x scenario. Les courbes representent les pertes totales du scenario, pas les pertes de vent seules.",
        },
        warning=" | ".join(graph_warnings) if graph_warnings else None,
    )


def build_annual_fec_all_territories_pct_graph(
    record: RunRecord,
    payloads: dict[str, TerritoryPayload],
    selected_territories: list[str],
    selected_hazards: list[str],
) -> GraphSpec | None:
    series: list[dict[str, Any]] = []
    png_series: list[dict[str, Any]] = []
    graph_warnings: list[str] = []
    territory_labels = [territory_label(territory) for territory in selected_territories]
    title_suffix = " + ".join(territory_labels)
    for territory in selected_territories:
        payload = payloads[territory].payload
        total_exposure_value = _resolve_total_exposure_value(record, territory, payload)
        if total_exposure_value <= 0.0:
            warning = (
                f"Skipping percentage annual FEC for {territory}: point_value_total_eur is unavailable or zero."
            )
            if warning not in graph_warnings:
                graph_warnings.append(warning)
            continue
        for hazard in selected_hazards:
            rp, damage, _, warning = _resolve_annual_fec_curve(record, territory, payload, hazard)
            if not rp or not damage or len(rp) != len(damage):
                continue
            if warning and warning not in graph_warnings:
                graph_warnings.append(warning)
            damage_pct = [round((float(value) / total_exposure_value) * 100.0, 4) for value in damage]
            name = f"{territory_label(territory)} - {HAZARD_LABELS[hazard]}"
            color = ANNUAL_FEC_COMBO_COLORS.get((territory, hazard), HAZARD_COLORS[hazard])
            line_type = HAZARD_LINESTYLES.get(hazard, "solid")
            series.append(
                {
                    "name": name,
                    "type": "line",
                    "smooth": False,
                    "showSymbol": True,
                    "lineStyle": {"width": 3, "color": color, "type": HAZARD_ECHARTS_LINE_TYPES.get(hazard, "solid")},
                    "itemStyle": {"color": color},
                    "data": [[rp[idx], damage_pct[idx]] for idx in range(len(rp))],
                }
            )
            png_series.append({"name": name, "x": rp, "y": damage_pct, "color": color, "linestyle": line_type})
    if len(series) < 2:
        return None
    option = _build_line_option(
        f"FEC annuelle - {title_suffix} (%)",
        "Temps de retour (ans)",
        "Dommages (% de la valeur d'infrastructure du territoire)",
        series,
    )
    return GraphSpec(
        graph_id=_graph_id("annual_fec_all_territories_pct"),
        graph_type="annual_fec_all_territories_pct",
        title=f"FEC annuelle - {title_suffix} (%)",
        section="fec",
        territory=None,
        hazard=None,
        kind="chart",
        description=(
            f"Vue consolidee des courbes annuelles {title_suffix} x STORM/STORM_CMCC, "
            "avec un axe Y normalise en pourcentage de la valeur totale d'infrastructure de chaque territoire."
        ),
        echarts_option=option,
        png_payload={
            "type": "line",
            "title": f"FEC annuelle - {title_suffix} (%)",
            "series": png_series,
            "xlabel": "Temps de retour (ans)",
            "ylabel": "Dommages (% de la valeur d'infrastructure du territoire)",
            "legacy_line_layout": True,
            "note": (
                "Chaque courbe est normalisee par la valeur totale d'infrastructure de son propre territoire. "
                "Les courbes representent les pertes totales du scenario, pas les pertes de vent seules."
            ),
        },
        warning=" | ".join(graph_warnings) if graph_warnings else None,
    )


def _resolve_output_root(requested_output_dir: Any) -> tuple[Path, str | None]:
    enforced_output_root = DEFAULT_OUTPUT_ROOT.expanduser().resolve()
    requested = Path(str(requested_output_dir or DEFAULT_OUTPUT_ROOT)).expanduser().resolve()
    if requested != enforced_output_root:
        return enforced_output_root, (
            f"Ignoring requested output dir {requested}; graph packs are always written under {enforced_output_root}."
        )
    return enforced_output_root, None


def build_lifetime_fec_graph(record: RunRecord, territory: str, payload: dict[str, Any], hazard: str) -> GraphSpec | None:
    territory_name = _display_territory_name(territory)
    block = _extract_graph_block(payload, hazard, "lifetime_fec")
    if not block:
        return None
    annual_rp, annual_damage, _, annual_warning = _resolve_annual_fec_curve(record, territory, payload, hazard)
    annual_map = {int(round(float(annual_rp[idx]))): float(annual_damage[idx]) for idx in range(min(len(annual_rp), len(annual_damage)))}
    series_payload = block.get("series") if isinstance(block.get("series"), list) else []
    series = []
    png_series = []
    palette = ["#2563eb", "#9333ea", "#db2777", "#0f766e"]
    for idx, item in enumerate(series_payload):
        if not isinstance(item, dict):
            continue
        rp = [float(value) for value in item.get("return_period_years") or []]
        damage = [float(value) for value in item.get("damage_eur") or []]
        if not rp or not damage or len(rp) != len(damage):
            continue
        factor = _estimate_lifetime_factor(annual_map, rp, damage)
        combined = {int(round(rp[pos])): round(float(damage[pos]), 2) for pos in range(len(rp))}
        inserted_periods: list[int] = []
        if factor is not None:
            for return_period in LIFETIME_EXTRA_RETURN_PERIODS:
                if return_period in combined:
                    continue
                annual_native = annual_map.get(return_period)
                if annual_native is None:
                    continue
                combined[return_period] = round(float(annual_native) * factor, 2)
                inserted_periods.append(return_period)
        rp = [float(period) for period in sorted(combined)]
        damage = [float(combined[int(round(period))]) for period in rp]
        color = palette[idx % len(palette)]
        name = str(item.get("name") or f"Series {idx + 1}")
        series.append(
            {
                "name": name,
                "type": "line",
                "smooth": False,
                "showSymbol": True,
                "lineStyle": {"width": 3, "color": color},
                "itemStyle": {"color": color},
                "data": _build_annotated_line_points(rp, damage, inserted_periods),
            }
        )
        png_series.append(
            {
                "name": name,
                "x": rp,
                "y": damage,
                "color": color,
            }
        )
    if not series:
        return None
    option = _build_line_option(
        f"FEC duree de vie - {territory_name} - {HAZARD_LABELS[hazard]}",
        "Temps de retour (ans)",
        "Dommages (EUR)",
        series,
    )
    return GraphSpec(
        graph_id=_graph_id("lifetime_fec_by_territory_hazard", territory, hazard),
        graph_type="lifetime_fec_by_territory_hazard",
        title=f"FEC duree de vie - {territory_name} - {HAZARD_LABELS[hazard]}",
        section="fec",
        territory=territory,
        hazard=hazard,
        kind="chart",
        description=(
            "Courbes de depassement de frequence pour des durees de vie d'actif. "
            "Les points 400/600/800 ans sont derives des PML annuels recalcules depuis les checkpoints d'evenements archives, "
            "puis projetes avec le meme facteur de duree de vie que la serie backend 30y/50y."
        ),
        echarts_option=option,
        png_payload={
            "type": "line",
            "title": f"FEC duree de vie - {territory_name} - {HAZARD_LABELS[hazard]}",
            "series": png_series,
            "xlabel": "Temps de retour (ans)",
            "ylabel": "Dommages (EUR)",
            "legacy_line_layout": True,
            "note": (
                "Les points ajoutes 400/600/800 ans utilisent les valeurs PML annuelles recalculees a partir des checkpoints archives de pertes par evenement, "
                "puis appliquent le meme facteur de duree de vie que les series backend 30y/50y."
            ),
        },
        warning=annual_warning,
    )


def build_targeted_event_scorecard(territory: str, payload: dict[str, Any], selected_hazards: list[str]) -> GraphSpec:
    territory_name = _display_territory_name(territory)
    categories = ["Total scenario", "Direct", "Indirect", "Pire evenement", "TVaR95"]
    series: list[dict[str, Any]] = []
    for hazard in selected_hazards:
        metrics = _extract_hazard_metrics(payload, hazard)
        style = _hazard_bar_series_style(hazard)
        series.append(
            {
                "name": HAZARD_LABELS.get(hazard, hazard.upper()),
                "type": "bar",
                "data": [
                    _safe_float(metrics.get("eai_eur")),
                    _safe_float(metrics.get("eai_direct_eur")),
                    _safe_float(metrics.get("eai_indirect_eur")),
                    _safe_float(metrics.get("max_event_loss_eur")),
                    _safe_float(metrics.get("tvar_95_eur")),
                ],
                "itemStyle": {"color": style["color"]},
            }
        )
    return GraphSpec(
        graph_id=_graph_id("targeted_event_scorecard", territory),
        graph_type="targeted_event_scorecard",
        title=f"Tableau de bord evenement cible - {territory_name}",
        section="overview",
        territory=territory,
        hazard=None,
        kind="chart",
        description="Synthese evenementielle des pertes du scenario cible, sans lecture probabiliste de type FEC/PML.",
        echarts_option=_build_bar_option(f"Tableau de bord evenement cible - {territory_name}", categories, series),
        png_payload={
            "type": "grouped_bar",
            "title": f"Tableau de bord evenement cible - {territory_name}",
            "categories": categories,
            "series": [
                {
                    "name": str(item.get("name") or ""),
                    "values": list(item.get("data") or []),
                    **_hazard_bar_series_style(str(item.get("name") or "")),
                }
                for item in series
            ],
            "ylabel": "Pertes (EUR)",
            "show_labels": True,
            "label_format": "compact_eur",
        },
    )


def build_pml_ladder_graph(territory: str, payload: dict[str, Any], hazards: list[str]) -> GraphSpec | None:
    territory_name = _display_territory_name(territory)
    categories = [f"PML{period}" for period in PML_PERIODS]
    series: list[dict[str, Any]] = []
    png_groups: list[dict[str, Any]] = []
    for hazard in hazards:
        hazard_metrics = _extract_hazard_metrics(payload, hazard)
        values = [_safe_float(hazard_metrics.get(f"pml_{period}_eur")) for period in PML_PERIODS]
        if not any(value > 0.0 for value in values):
            continue
        series.append(
            {"name": HAZARD_LABELS[hazard], "type": "bar", "data": values, "itemStyle": {"color": _hazard_comparison_color(hazard)}}
        )
        segment_values = {family: [] for family in DAMAGE_FAMILY_ORDER}
        for period, total_value in zip(PML_PERIODS, values):
            scenario_key = _nearest_return_period_scenario(int(period))
            shares = _family_damage_shares_for_payload(payload, hazard, scenario_key=scenario_key)
            allocated = 0.0
            for family in DAMAGE_FAMILY_ORDER[:-1]:
                family_value = round(max(total_value, 0.0) * shares.get(family, 0.0), 2)
                segment_values[family].append(family_value)
                allocated += family_value
            last_family = DAMAGE_FAMILY_ORDER[-1]
            segment_values[last_family].append(round(max(total_value, 0.0) - allocated, 2))
        png_groups.append(
            {
                "name": HAZARD_LABELS[hazard],
                "hatch": _hazard_group_hatch(hazard),
                "segments": [
                    {
                        "name": DAMAGE_FAMILY_LABELS[family],
                        "values": segment_values[family],
                        "color": DAMAGE_FAMILY_COLORS[family],
                    }
                    for family in DAMAGE_FAMILY_ORDER
                ],
            }
        )
    if not series:
        return None
    option = _build_bar_option(
        f"Echelle PML - {territory_name}",
        categories,
        series,
    )
    return GraphSpec(
        graph_id=_graph_id("pml_ladder_by_territory_hazard", territory, "comparison"),
        graph_type="pml_ladder_by_territory_hazard",
        title=f"Echelle PML - {territory_name}",
        section="loss",
        territory=territory,
        hazard=None,
        kind="chart",
        description="Lecture rapide comparee de la queue de pertes sur les periodes de retour standard.",
        echarts_option=option,
        png_payload={
            "type": "grouped_stacked_bar",
            "title": f"Echelle PML - {territory_name}",
            "categories": categories,
            "groups": png_groups,
            "ylabel": "Pertes (EUR)",
            "show_labels": True,
            "label_format": "compact_eur",
            "note": (
                "Chaque barre garde le total PML du run ; la couleur interne repartit ce total entre eau et electricite "
                "a partir des scenarios scientifiques de degats par temps de retour. PML20 et PML200 utilisent la part du scenario RP le plus proche."
            ),
        },
    )


def build_pml_ladder_detail_graph(
    territory: str,
    payload: dict[str, Any],
    hazards: list[str],
    *,
    periods: tuple[int, ...] = PML_PERIODS,
    graph_type: str = "pml_ladder_detail_by_territory_hazard",
    title_prefix: str = "Echelle PML detaillee",
    label_fontsize: int = 8,
    label_layout: str = "callout",
    total_label_fontsize: int | None = None,
    x_tick_label_fontsize: int | None = None,
    note: str | None = None,
) -> GraphSpec | None:
    territory_name = _display_territory_name(territory)
    selected_periods = tuple(int(period) for period in periods)
    categories = [f"PML{period}" for period in selected_periods]
    png_groups: list[dict[str, Any]] = []
    for hazard in hazards:
        hazard_metrics = _extract_hazard_metrics(payload, hazard)
        pml_values = [_safe_float(hazard_metrics.get(f"pml_{period}_eur")) for period in selected_periods]
        if not any(value > 0.0 for value in pml_values):
            continue

        segment_values = {subclass_key: [] for subclass_key in DAMAGE_DETAIL_SUBCLASS_ORDER}
        segment_labels = {subclass_key: [] for subclass_key in DAMAGE_DETAIL_SUBCLASS_ORDER}
        segment_pcts = {subclass_key: [] for subclass_key in DAMAGE_DETAIL_SUBCLASS_ORDER}
        for period, total_value in zip(selected_periods, pml_values):
            scenario_key = _nearest_return_period_scenario(int(period))
            rows = _hazard_damage_detail_rows_for_payload(payload, hazard, scenario_key)
            raw_damage, exposure_totals = _damage_detail_subclass_totals_from_rows(rows)
            denominator = sum(raw_damage.values())
            if denominator <= 0.0:
                allocated = {subclass_key: 0.0 for subclass_key in DAMAGE_DETAIL_SUBCLASS_ORDER}
            else:
                allocated = {
                    subclass_key: round(max(total_value, 0.0) * (raw_damage[subclass_key] / denominator), 2)
                    for subclass_key in DAMAGE_DETAIL_SUBCLASS_ORDER
                }
                drift = round(max(total_value, 0.0) - sum(allocated.values()), 2)
                if abs(drift) >= 0.01:
                    target_key = max(DAMAGE_DETAIL_SUBCLASS_ORDER, key=lambda item: allocated[item])
                    allocated[target_key] = round(max(allocated[target_key] + drift, 0.0), 2)
            for subclass_key in DAMAGE_DETAIL_SUBCLASS_ORDER:
                value = allocated[subclass_key]
                exposure_value = exposure_totals[subclass_key]
                pct_value = (value / exposure_value) * 100.0 if exposure_value > 0.0 else 0.0
                segment_values[subclass_key].append(value)
                segment_pcts[subclass_key].append(pct_value)
                segment_labels[subclass_key].append(
                    _format_damage_share_label(value, exposure_value)
                    if value > 0.0
                    else ""
                )

        png_groups.append(
            {
                "name": HAZARD_LABELS[hazard],
                "hatch": _hazard_group_hatch(hazard),
                "segments": [
                    {
                        "name": DAMAGE_DETAIL_SUBCLASS_LABELS[subclass_key],
                        "values": segment_values[subclass_key],
                        "color": DAMAGE_DETAIL_SUBCLASS_COLORS[subclass_key],
                        "label_texts": segment_labels[subclass_key],
                        "label_pcts": segment_pcts[subclass_key],
                    }
                    for subclass_key in DAMAGE_DETAIL_SUBCLASS_ORDER
                ],
            }
        )

    if not png_groups:
        return None
    default_note = (
        "Chaque barre garde le total PML du run. Les segments utilisent les classes scientifiques de degats ; "
        "PML20 et PML200 reprennent la repartition du scenario RP le plus proche."
    )
    return GraphSpec(
        graph_id=_graph_id(graph_type, territory, "comparison"),
        graph_type=graph_type,
        title=f"{title_prefix} - {territory_name}",
        section="loss",
        territory=territory,
        hazard=None,
        kind="chart",
        description=(
            "Lecture detaillee des pertes PML par scenario, avec decomposition des familles eau et electricite "
            "en reseaux et ouvrages."
        ),
        echarts_option=None,
        png_payload={
            "type": "grouped_stacked_bar_segment_labels",
            "title": f"{title_prefix} - {territory_name}",
            "hide_title": label_layout == "side_by_segment",
            "categories": categories,
            "groups": png_groups,
            "ylabel": "Pertes (EUR)",
            "show_labels": True,
            "show_total_labels": True,
            "label_fontsize": label_fontsize,
            "label_layout": label_layout,
            "total_label_fontsize": total_label_fontsize or max(label_fontsize, 7),
            "x_tick_label_fontsize": x_tick_label_fontsize,
            "label_format": "compact_eur",
            "note": default_note if note is None and label_layout != "side_by_segment" else note,
        },
    )


def build_pml_ladder_detail_key_periods_graph(territory: str, payload: dict[str, Any], hazards: list[str]) -> GraphSpec | None:
    return build_pml_ladder_detail_graph(
        territory,
        payload,
        hazards,
        periods=(10, 50, 100, 1000),
        graph_type="pml_ladder_detail_key_periods_by_territory_hazard",
        title_prefix="Echelle PML detaillee - periodes principales",
        label_fontsize=12,
        label_layout="side_by_segment",
        total_label_fontsize=16,
        x_tick_label_fontsize=17,
        note=None,
    )


def build_top_events_graph(territory: str, payload: dict[str, Any], hazard: str) -> GraphSpec | None:
    territory_name = _display_territory_name(territory)
    events = _extract_event_list(payload, hazard)[:10]
    if not events:
        return None
    categories = []
    values = []
    for item in events:
        event_name = str(item.get("event_name") or item.get("event_id") or "event")
        rp = _safe_float(item.get("return_period_years_approx"))
        categories.append(f"{event_name} ({rp:.0f}y)" if rp else event_name)
        values.append(_safe_float(item.get("loss_eur")))
    option = _build_bar_option(
        f"Top evenements - {territory_name} - {HAZARD_LABELS[hazard]}",
        categories,
        [{"name": "Pertes", "type": "bar", "data": values, "itemStyle": {"color": _hazard_comparison_color(hazard)}}],
        horizontal=True,
    )
    style = _hazard_bar_series_style(hazard)
    return GraphSpec(
        graph_id=_graph_id("top_events_by_hazard", territory, hazard),
        graph_type="top_events_by_hazard",
        title=f"Top evenements - {territory_name} - {HAZARD_LABELS[hazard]}",
        section="events",
        territory=territory,
        hazard=hazard,
        kind="chart",
        description="Top 10 evenements les plus dommageables sur le portefeuille du territoire.",
        echarts_option=option,
        png_payload={
            "type": "horizontal_bar",
            "title": f"Top evenements - {territory_name} - {HAZARD_LABELS[hazard]}",
            "categories": categories,
            "values": values,
            **style,
            "xlabel": "Pertes (EUR)",
        },
    )


def build_wind_hist_graph(
    record: RunRecord,
    territory: str,
    payload: dict[str, Any],
    hazard: str,
    block_name: str,
    graph_type: str,
    title_prefix: str,
) -> GraphSpec | None:
    territory_name = _display_territory_name(territory)
    warning = None
    if block_name == "wind_track_hist":
        try:
            native_hist = _build_real_wind_track_hist(record, territory, hazard)
        except Exception as exc:
            native_hist = None
            warning = f"Falling back to the legacy loss proxy because native wind reconstruction failed: {type(exc).__name__}: {exc}"
        if native_hist is not None:
            bin_values, values, wind_map_path = native_hist
            categories = [f"{value:.1f}" for value in bin_values]
            title = f"{title_prefix} - {territory_name} - {HAZARD_LABELS[hazard]}"
            option = _build_bar_option(
                title,
                categories,
                [{"name": "%", "type": "bar", "data": values, "itemStyle": {"color": _hazard_comparison_color(hazard)}}],
            )
            style = _hazard_bar_series_style(hazard)
            return GraphSpec(
                graph_id=_graph_id(graph_type, territory, hazard),
                graph_type=graph_type,
                title=title,
                section="wind",
                territory=territory,
                hazard=hazard,
                kind="chart",
                description=(
                    "Histogramme reel du vent maximal par track, reconstruit a partir des intensites d'alea STORM/STORM_CMCC "
                    "sur les cellules archivees du territoire. L'axe X est en m/s."
                ),
                echarts_option=option,
                png_payload={
                    "type": "bar",
                    "title": title,
                    "categories": categories,
                    "values": values,
                    **style,
                    "ylabel": "Part des trajectoires (%)",
                    "xlabel": "Intensite maximale du vent par trajectoire sur les cellules archivees du territoire (m/s)",
                    "note": (
                        f"Reconstruit a partir des intensites d'alea sur les cellules archivees de la carte de vent, en utilisant la selection de catalogues STORM/STORM_CMCC du run. "
                        f"Artefact source de carte de vent : {wind_map_path}."
                    ),
                },
                warning=warning,
            )

    block = _extract_graph_block(payload, hazard, block_name)
    if not block:
        return None
    bin_values = [_safe_float(item) for item in block.get("bins_mps") or []]
    values = [_safe_float(item) for item in block.get("percent") or []]
    if not bin_values or not values or len(bin_values) != len(values):
        return None
    if block_name == "wind_year_hist":
        categories = [_format_compact_eur(value) for value in bin_values]
        x_label = "Classe de pertes par evenement (EUR)"
        description = (
            "Malgre son identifiant historique, ce graphe montre une distribution des pertes evenementielles du portefeuille. "
            "L'axe X est en EUR, pas une vitesse de vent."
        )
        note = "Identifiant de graphe legacy, mais le payload backend regroupe ici les pertes par evenement en EUR sur l'axe X."
    else:
        categories = [f"{value:.0f}" for value in bin_values]
        x_label = "Proxy d'intensite de perte evenementielle (sqrt(EUR))"
        description = (
            "Malgre son identifiant historique, ce graphe montre un proxy de pertes par evenement construit cote backend sur sqrt(loss). "
            "L'axe X n'est ni une vitesse de vent ni un nombre de tracks."
        )
        note = "Le backend construit cet axe X a partir de sqrt(perte evenementielle en EUR), et non d'une vitesse de vent ou d'un nombre de trajectoires."
    title = f"{title_prefix} - {territory_name} - {HAZARD_LABELS[hazard]}"
    option = _build_bar_option(
        title,
        categories,
        [{"name": "%", "type": "bar", "data": values, "itemStyle": {"color": _hazard_comparison_color(hazard)}}],
    )
    style = _hazard_bar_series_style(hazard)
    return GraphSpec(
        graph_id=_graph_id(graph_type, territory, hazard),
        graph_type=graph_type,
        title=title,
        section="wind",
        territory=territory,
        hazard=hazard,
        kind="chart",
        description=description,
        echarts_option=option,
        png_payload={
            "type": "bar",
            "title": title,
            "categories": categories,
            "values": values,
            **style,
            "ylabel": "Part (%)",
            "xlabel": x_label,
            "note": note,
        },
        warning=warning,
    )


def build_combined_event_loss_hist_graph(territory: str, payload: dict[str, Any], hazards: list[str]) -> GraphSpec | None:
    territory_name = _display_territory_name(territory)
    categories = [label for _low, _high, label in EVENT_LOSS_HISTOGRAM_BINS_EUR]
    groups: list[dict[str, Any]] = []
    for hazard in hazards:
        block = _extract_graph_block(payload, hazard, "wind_year_hist")
        if not isinstance(block, dict):
            continue
        bin_values = [_safe_float(item) for item in block.get("bins_mps") or []]
        percentages = [_safe_float(item) for item in block.get("percent") or []]
        if not bin_values or not percentages:
            continue
        rebinned = _rebin_loss_histogram_percentages(bin_values, percentages)
        shares = _family_damage_shares_for_payload(payload, hazard)
        segment_values = {family: [] for family in DAMAGE_FAMILY_ORDER}
        for total_value in rebinned:
            allocated = 0.0
            for family in DAMAGE_FAMILY_ORDER[:-1]:
                family_value = round(total_value * shares.get(family, 0.0), 4)
                segment_values[family].append(family_value)
                allocated += family_value
            last_family = DAMAGE_FAMILY_ORDER[-1]
            segment_values[last_family].append(round(max(total_value - allocated, 0.0), 4))
        groups.append(
            {
                "name": HAZARD_LABELS.get(hazard, hazard.upper()),
                "hatch": _hazard_group_hatch(hazard),
                "segments": [
                    {
                        "name": DAMAGE_FAMILY_LABELS[family],
                        "values": segment_values[family],
                        "color": DAMAGE_FAMILY_COLORS[family],
                    }
                    for family in DAMAGE_FAMILY_ORDER
                ],
            }
        )
    if not groups:
        return None
    title = f"Histogramme annuel des pertes - {territory_name} - STORM vs STORM_CMCC"
    return GraphSpec(
        graph_id=_graph_id("wind_year_hist_by_hazard", territory, "storm"),
        graph_type="wind_year_hist_by_hazard",
        title=title,
        section="wind",
        territory=territory,
        hazard=None,
        kind="chart",
        description=(
            "Distribution legacy des pertes evenementielles du portefeuille, reclassée dans des classes regulieres "
            "et affichee simultanement pour STORM et STORM_CMCC."
        ),
        echarts_option=_build_grouped_stacked_bar_option(title, categories, groups),
        png_payload={
            "type": "grouped_stacked_bar",
            "title": title,
            "categories": categories,
            "groups": groups,
            "ylabel": "Part des evenements (%)",
            "show_labels": True,
            "label_format": "percent",
            "note": (
                "Les classes de pertes sont reconstruites depuis l'histogramme evenementiel archive. "
                "La ventilation eau/elec utilise la repartition des degats scientifiques par scenario, l'archive ne portant pas la ventilation eau/elec par evenement."
            ),
        },
    )


def build_direct_vs_indirect_graph(territory: str, payload: dict[str, Any], selected_hazards: list[str]) -> GraphSpec:
    territory_name = _display_territory_name(territory)
    categories = [HAZARD_LABELS[hazard] for hazard in selected_hazards]
    direct_values = [_safe_float(_extract_hazard_metrics(payload, hazard).get("eai_direct_eur")) for hazard in selected_hazards]
    indirect_values = [_safe_float(_extract_hazard_metrics(payload, hazard).get("eai_indirect_eur")) for hazard in selected_hazards]
    option = _build_bar_option(
        f"EAI direct vs indirect - {territory_name}",
        categories,
        [
            {"name": "Direct", "type": "bar", "stack": "loss", "data": direct_values, "itemStyle": {"color": HAZARD_COLORS["direct"]}},
            {"name": "Indirect", "type": "bar", "stack": "loss", "data": indirect_values, "itemStyle": {"color": HAZARD_COLORS["indirect"]}},
        ],
    )
    return GraphSpec(
        graph_id=_graph_id("direct_vs_indirect_eai_by_hazard", territory),
        graph_type="direct_vs_indirect_eai_by_hazard",
        title=f"EAI direct vs indirect - {territory_name}",
        section="loss",
        territory=territory,
        hazard=None,
        kind="chart",
        description=(
            "Decomposition des pertes annuelles moyennes directes et indirectes pour le scenario complet "
            "STORM/STORM_CMCC. Les barres directes representent le total multi-aleas, pas le vent seul."
        ),
        echarts_option=option,
        png_payload={
            "type": "stacked_bar",
            "title": f"EAI direct vs indirect - {territory_name}",
            "categories": categories,
            "series": [
                {"name": "Direct", "values": direct_values, "color": HAZARD_COLORS["direct"]},
                {"name": "Indirect", "values": indirect_values, "color": HAZARD_COLORS["indirect"]},
            ],
            "ylabel": "EAI annuel (EUR)",
            "note": "Chaque barre STORM/STORM_CMCC correspond au total du scenario complet sur les composantes d'alea actives ; l'indirect correspond au surcroit elec -> eau.",
        },
    )


def build_hazard_component_share_graph(
    territory: str,
    payload: dict[str, Any],
    selected_hazards: list[str],
    *,
    metric_key: str,
    graph_type: str,
    title: str,
    description: str,
    note: str,
) -> GraphSpec | None:
    components = _resolve_component_order(payload, selected_hazards, metric_key)
    if not components:
        return None
    categories = [HAZARD_LABELS[hazard] for hazard in selected_hazards]
    series: list[dict[str, Any]] = []
    png_series: list[dict[str, Any]] = []
    has_non_zero = False
    for component in components:
        values: list[float] = []
        for hazard in selected_hazards:
            component_values = _extract_component_metric_map(payload, hazard, metric_key)
            total = sum(component_values.get(name, 0.0) for name in components)
            share = 0.0 if total <= 0.0 else (component_values.get(component, 0.0) / total) * 100.0
            values.append(round(share, 2))
        if max(values) > 0.0:
            has_non_zero = True
        series.append(
            {
                "name": COMPONENT_LABELS.get(component, component),
                "type": "bar",
                "stack": "share",
                "data": values,
                "itemStyle": {"color": COMPONENT_COLORS.get(component, "#64748b")},
            }
        )
        png_series.append(
            {
                "name": COMPONENT_LABELS.get(component, component),
                "values": values,
                "color": COMPONENT_COLORS.get(component, "#64748b"),
            }
        )
    if not has_non_zero:
        return None
    option = _build_bar_option(title, categories, series)
    if isinstance(option.get("yAxis"), dict):
        option["yAxis"]["max"] = 100
    return GraphSpec(
        graph_id=_graph_id(graph_type, territory),
        graph_type=graph_type,
        title=title,
        section="loss",
        territory=territory,
        hazard=None,
        kind="chart",
        description=description,
        echarts_option=option,
        png_payload={
            "type": "stacked_bar",
            "title": title,
            "categories": categories,
            "series": png_series,
            "ylabel": "Part du mix de pertes directes (%)",
            "note": note,
        },
    )


def build_hazard_component_share_by_return_period_graph(
    territory: str,
    payload: dict[str, Any],
    selected_hazards: list[str],
) -> GraphSpec | None:
    territory_name = _display_territory_name(territory)
    scenario_items = [(period, RETURN_PERIOD_SCENARIO_BY_PERIOD[period]) for period in (10, 50, 100, 1000)]
    categories: list[str] = []
    component_values: dict[str, list[float]] = {component: [] for component in COMPONENT_ORDER}
    has_non_zero = False
    for period, scenario_key in scenario_items:
        for hazard in selected_hazards:
            totals = _component_damage_totals_for_scenario(payload, scenario_key, hazard)
            if not totals:
                continue
            total_damage = sum(max(_safe_float(value), 0.0) for value in totals.values())
            categories.append(f"RP{period}\n{HAZARD_LABELS.get(hazard, hazard.upper())}")
            for component in COMPONENT_ORDER:
                share = 0.0 if total_damage <= 0.0 else (max(_safe_float(totals.get(component)), 0.0) / total_damage) * 100.0
                component_values.setdefault(component, [])
                component_values[component].append(round(share, 2))
                has_non_zero = has_non_zero or share > 0.0
            for component in totals:
                if component in COMPONENT_ORDER:
                    continue
                share = 0.0 if total_damage <= 0.0 else (max(_safe_float(totals.get(component)), 0.0) / total_damage) * 100.0
                component_values.setdefault(component, [0.0] * (len(categories) - 1))
                component_values[component].append(round(share, 2))
                has_non_zero = has_non_zero or share > 0.0
    if not categories or not has_non_zero:
        return None
    ordered_components = [component for component in COMPONENT_ORDER if any(component_values.get(component) or [])]
    ordered_components.extend(
        component
        for component in sorted(component_values)
        if component not in ordered_components and any(component_values.get(component) or [])
    )
    series = [
        {
            "name": COMPONENT_LABELS.get(component, component),
            "type": "bar",
            "stack": "share",
            "data": component_values.get(component, []),
            "itemStyle": {"color": COMPONENT_COLORS.get(component, "#64748b")},
        }
        for component in ordered_components
    ]
    option = _build_bar_option(
        f"Contribution des aleas aux degats - {territory_name}",
        categories,
        series,
    )
    if isinstance(option.get("yAxis"), dict):
        option["yAxis"]["max"] = 100
    return GraphSpec(
        graph_id=_graph_id("hazard_component_share_by_return_period", territory),
        graph_type="hazard_component_share_by_return_period",
        title=f"Contribution des aleas aux degats - {territory_name}",
        section="loss",
        territory=territory,
        hazard=None,
        kind="chart",
        description="Part en pourcentage de chaque composante d'alea dans les degats monetaires par temps de retour.",
        echarts_option=option,
        png_payload={
            "type": "stacked_bar",
            "title": f"Contribution des aleas aux degats - {territory_name}",
            "categories": categories,
            "series": [
                {
                    "name": COMPONENT_LABELS.get(component, component),
                    "values": component_values.get(component, []),
                    "color": COMPONENT_COLORS.get(component, "#64748b"),
                }
                for component in ordered_components
            ],
            "ylabel": "Contribution aux degats (%)",
            "ymax": 100.0,
        },
    )


def build_component_health_graph(territory: str, payload: dict[str, Any], hazard: str) -> GraphSpec | None:
    territory_name = _display_territory_name(territory)
    portfolio = payload.get("portfolio_results") if isinstance(payload.get("portfolio_results"), dict) else {}
    component_health = portfolio.get("component_health") if isinstance(portfolio.get("component_health"), dict) else {}
    hazard_block = component_health.get(hazard) if isinstance(component_health.get(hazard), dict) else {}
    if not hazard_block:
        return None
    categories = []
    s1_values = []
    s2_values = []
    s3_values = []
    health_values = []
    for component_name, component_metrics in hazard_block.items():
        if not isinstance(component_metrics, dict):
            continue
        total = _safe_float(component_metrics.get("L_total"))
        if total <= 0.0:
            total = 1.0
        categories.append(COMPONENT_LABELS.get(component_name, component_name))
        s1_values.append(100.0 * _safe_float(component_metrics.get("L_S1")) / total)
        s2_values.append(100.0 * _safe_float(component_metrics.get("L_S2")) / total)
        s3_values.append(100.0 * _safe_float(component_metrics.get("L_S3")) / total)
        health_values.append(100.0 * _safe_float(component_metrics.get("health"), default=0.0))
    if not categories:
        return None
    option = _build_bar_option(
        f"Sante des composants - {territory_name} - {HAZARD_LABELS[hazard]}",
        categories,
        [
            {"name": f"{_state_label('S1')} %", "type": "bar", "stack": "state", "data": s1_values, "itemStyle": {"color": HAZARD_COLORS["s1"]}},
            {"name": f"{_state_label('S2')} %", "type": "bar", "stack": "state", "data": s2_values, "itemStyle": {"color": HAZARD_COLORS["s2"]}},
            {"name": f"{_state_label('S3')} %", "type": "bar", "stack": "state", "data": s3_values, "itemStyle": {"color": HAZARD_COLORS["s3"]}},
            {"name": "Sante %", "type": "line", "yAxisIndex": 1, "data": health_values, "lineStyle": {"color": HAZARD_COLORS["health"], "width": 3}, "itemStyle": {"color": HAZARD_COLORS["health"]}},
        ],
        secondary_axis=True,
    )
    return GraphSpec(
        graph_id=_graph_id("component_health_by_territory", territory, hazard),
        graph_type="component_health_by_territory",
        title=f"Sante des composants - {territory_name} - {HAZARD_LABELS[hazard]}",
        section="health",
        territory=territory,
        hazard=hazard,
        kind="chart",
        description=(
            f"Synthese des etats finaux {_state_join_label(('S1', 'S2', 'S3'))} annualises pour le scenario complet, apres propagation elec->eau quand elle s'applique. "
            "Ce n'est pas un graphe de retour 100 ans / 1000 ans, mais une synthese ponderee par geometrie d'actif."
        ),
        echarts_option=option,
        png_payload={
            "type": "stacked_bar_with_line",
            "title": f"Sante des composants - {territory_name} - {HAZARD_LABELS[hazard]}",
            "categories": categories,
            "stacked_series": [
                {"name": f"{_state_label('S1')} %", "values": s1_values, "color": HAZARD_COLORS["s1"]},
                {"name": f"{_state_label('S2')} %", "values": s2_values, "color": HAZARD_COLORS["s2"]},
                {"name": f"{_state_label('S3')} %", "values": s3_values, "color": HAZARD_COLORS["s3"]},
            ],
            "line_series": {"name": "Sante %", "values": health_values, "color": HAZARD_COLORS["health"]},
            "ylabel": "Part des etats de service (%)",
            "line_ylabel": "Sante (%)",
            "note": (
                "Synthese annualisee des etats finaux pour le scenario selectionne ; elle n'est pas rattachee a un temps de retour unique. "
                "La ponderation utilise la geometrie des objets (km pour les lignes, nombre pour les points)."
            ),
        },
    )


def build_interdependency_summary_graph(territory: str, payload: dict[str, Any]) -> GraphSpec | None:
    portfolio = payload.get("portfolio_results") if isinstance(payload.get("portfolio_results"), dict) else {}
    interdependency = portfolio.get("interdependency") if isinstance(portfolio.get("interdependency"), dict) else {}
    if not interdependency:
        return None
    wanted_keys = [
        "electricity_to_water_enabled",
        "water_assets_dependency_assumption",
        "dependency_impacted_assets",
        "dependency_impacted_assets_by_hazard",
        "electric_health_global",
        "electric_health_resolution_rule",
        "electric_health_resolution_by_hazard",
        "state_thresholds",
        "dependency_state_thresholds",
        "uplift_by_state",
    ]
    rows = []
    for key in wanted_keys:
        if key in interdependency:
            rows.append([key, _stringify_value(interdependency.get(key))])
    if not rows:
        return None
    return _make_table_graph(
        "interdependency_summary_by_territory",
        f"Resume des interdependances - {_display_territory_name(territory)}",
        "health",
        "Resume des hypotheses et parametres de propagation electricite vers eau.",
        ["Champ", "Valeur"],
        rows,
        territory=territory,
    )


def build_graphs_for_territory(
    record: RunRecord,
    territory: str,
    bundle: TerritoryPayload,
    selected_hazards: list[str],
) -> list[GraphSpec]:
    territory_name = _display_territory_name(territory)
    payload = bundle.payload
    graphs: list[GraphSpec] = []
    graphs.append(build_hazard_metric_scorecard(territory, payload, selected_hazards))
    graphs.append(build_direct_vs_indirect_graph(territory, payload, selected_hazards))
    pml_ladder_graph = build_pml_ladder_graph(territory, payload, selected_hazards)
    if pml_ladder_graph is not None:
        graphs.append(pml_ladder_graph)
    pml_ladder_detail_graph = build_pml_ladder_detail_graph(territory, payload, selected_hazards)
    if pml_ladder_detail_graph is not None:
        graphs.append(pml_ladder_detail_graph)
    pml_ladder_detail_key_periods_graph = build_pml_ladder_detail_key_periods_graph(territory, payload, selected_hazards)
    if pml_ladder_detail_key_periods_graph is not None:
        graphs.append(pml_ladder_detail_key_periods_graph)
    component_share_graph = build_hazard_component_share_by_return_period_graph(territory, payload, selected_hazards)
    if component_share_graph is not None:
        graphs.append(component_share_graph)
    combined_loss_hist_graph = build_combined_event_loss_hist_graph(territory, payload, selected_hazards)
    if combined_loss_hist_graph is not None:
        graphs.append(combined_loss_hist_graph)
    for hazard in selected_hazards:
        for graph in (
            build_lifetime_fec_graph(record, territory, payload, hazard),
            build_top_events_graph(territory, payload, hazard),
        ):
            if graph is not None:
                graphs.append(graph)
    return graphs


def build_targeted_graphs_for_territory(
    territory: str,
    bundle: TerritoryPayload,
    selected_hazards: list[str],
) -> list[GraphSpec]:
    payload = bundle.payload
    graphs: list[GraphSpec] = [
        build_targeted_event_scorecard(territory, payload, selected_hazards),
        build_direct_vs_indirect_graph(territory, payload, selected_hazards),
    ]
    interdependency_graph = build_interdependency_summary_graph(territory, payload)
    if interdependency_graph is not None:
        graphs.append(interdependency_graph)
    for hazard in selected_hazards:
        top_events_graph = build_top_events_graph(territory, payload, hazard)
        if top_events_graph is not None:
            graphs.append(top_events_graph)
    return graphs


def _graph_sort_key(graph: GraphSpec) -> tuple[int, str, str, str]:
    try:
        idx = GRAPH_TYPE_ORDER.index(graph.graph_type)
    except ValueError:
        idx = len(GRAPH_TYPE_ORDER)
    return idx, graph.territory or "", graph.hazard or "", graph.graph_id


def filter_graphs(graphs: list[GraphSpec], selected_graph_types: list[str]) -> list[GraphSpec]:
    selected_set = set(selected_graph_types)
    return sorted([graph for graph in graphs if graph.graph_type in selected_set], key=_graph_sort_key)


def _render_table_html(headers: list[str], rows: list[list[str]]) -> str:
    head_html = "".join(f"<th>{html.escape(header)}</th>" for header in headers)
    body_rows = []
    for row in rows:
        body_rows.append("<tr>" + "".join(f"<td>{html.escape(str(cell))}</td>" for cell in row) + "</tr>")
    return (
        '<div class="table-wrap"><table><thead><tr>'
        + head_html
        + "</tr></thead><tbody>"
        + "".join(body_rows)
        + "</tbody></table></div>"
    )


def _render_index_html(
    record: RunRecord,
    payloads: dict[str, TerritoryPayload],
    graphs: list[GraphSpec],
    output_dir: Path,
    warnings: list[str],
) -> Path:
    chart_specs = []
    sections: dict[str, list[str]] = {section: [] for section in SECTION_LABELS}
    graph_sections_html: list[str] = []
    for idx, graph in enumerate(graphs, start=1):
        sections.setdefault(graph.section, [])
        meta_parts = []
        if graph.territory:
            meta_parts.append(f"territory={graph.territory}")
        if graph.hazard:
            meta_parts.append(f"hazard={graph.hazard}")
        if graph.warning:
            meta_parts.append(f"warning={graph.warning}")
        meta_html = "<p class=\"graph-meta\">" + html.escape(" | ".join(meta_parts)) + "</p>" if meta_parts else ""
        if graph.kind == "chart" and graph.echarts_option is not None:
            container_id = f"chart-{idx}"
            chart_specs.append({"containerId": container_id, "option": graph.echarts_option})
            body_html = f'<div id="{container_id}" class="chart"></div>'
        else:
            body_html = _render_table_html(graph.table_headers or [], graph.table_rows or [])
        section_html = (
            f'<section id="{html.escape(graph.graph_id)}" class="graph-card">'
            f"<h2>{html.escape(graph.title)}</h2>"
            f"<p class=\"graph-description\">{html.escape(graph.description)}</p>"
            f"{meta_html}"
            f"{body_html}"
            "</section>"
        )
        sections[graph.section].append(
            f'<li><a href="#{html.escape(graph.graph_id)}">{html.escape(graph.title)}</a></li>'
        )
        graph_sections_html.append(section_html)

    warnings_html = ""
    if warnings:
        warning_items = "".join(f"<li>{html.escape(item)}</li>" for item in warnings)
        warnings_html = f"<section class=\"warnings\"><h2>Avertissements</h2><ul>{warning_items}</ul></section>"

    nav_parts = []
    for section_key, label in SECTION_LABELS.items():
        if sections.get(section_key):
            nav_parts.append(
                f'<section class="nav-group"><h3>{html.escape(label)}</h3><ul>{"".join(sections[section_key])}</ul></section>'
            )
    payload_rows = "".join(
        f"<li><strong>{html.escape(_display_territory_name(name))}</strong>: {html.escape(bundle.source_kind)} - {html.escape(bundle.payload_path)}</li>"
        for name, bundle in payloads.items()
    )
    html_text = f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Graphes SIB - {html.escape(record.run_id)}</title>
  <style>
    :root {{
      --bg: #f4efe7;
      --surface: rgba(255, 255, 255, 0.92);
      --ink: #172033;
      --muted: #5f6b7a;
      --border: rgba(23, 32, 51, 0.12);
      --accent: #0f766e;
      --accent-2: #c2410c;
      --shadow: 0 18px 42px rgba(23, 32, 51, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "Helvetica Neue", sans-serif;
      color: var(--ink);
      background: radial-gradient(circle at top left, rgba(15, 118, 110, 0.16), transparent 24%),
                  radial-gradient(circle at top right, rgba(194, 65, 12, 0.14), transparent 22%),
                  var(--bg);
    }}
    header {{
      padding: 40px 32px 24px;
    }}
    header h1 {{ margin: 0 0 8px; font-size: 2rem; }}
    header p {{ margin: 4px 0; color: var(--muted); max-width: 1100px; }}
    .layout {{
      display: grid;
      grid-template-columns: minmax(280px, 320px) minmax(0, 1fr);
      gap: 24px;
      padding: 0 32px 40px;
      align-items: start;
    }}
    .sidebar, .content section, .warnings {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 22px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(10px);
    }}
    .sidebar {{ position: sticky; top: 20px; padding: 20px; }}
    .sidebar h2, .sidebar h3 {{ margin-top: 0; }}
    .sidebar ul {{ margin: 0; padding-left: 18px; }}
    .sidebar li {{ margin: 6px 0; }}
    .sidebar a {{ color: var(--accent); text-decoration: none; }}
    .sidebar a:hover {{ text-decoration: underline; }}
    .content {{ display: grid; gap: 20px; }}
    .graph-card {{ padding: 22px; }}
    .graph-card h2 {{ margin: 0 0 8px; }}
    .graph-description, .graph-meta {{ margin: 6px 0 0; color: var(--muted); }}
    .chart {{ width: 100%; min-height: 420px; margin-top: 16px; }}
    .table-wrap {{ overflow-x: auto; margin-top: 14px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }}
    th {{ font-size: 0.85rem; text-transform: uppercase; color: var(--muted); }}
    .warnings {{ padding: 18px 22px; }}
    .warnings h2 {{ margin-top: 0; }}
    @media (max-width: 1080px) {{
      .layout {{ grid-template-columns: 1fr; }}
      .sidebar {{ position: static; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Graphes du run SIB</h1>
    <p>Run <strong>{html.escape(record.run_id)}</strong> - statut={html.escape(record.status)} - territoires={html.escape(_display_territories(record.territories))}</p>
    <p>Sources chargees:</p>
    <ul>{payload_rows}</ul>
  </header>
  <div class="layout">
    <aside class="sidebar">
      <h2>Liste des graphes</h2>
      {''.join(nav_parts)}
    </aside>
    <main class="content">
      {warnings_html}
      {''.join(graph_sections_html)}
    </main>
  </div>
  <script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
  <script>
    const chartSpecs = {json.dumps(chart_specs, ensure_ascii=False)};
    for (const spec of chartSpecs) {{
      const el = document.getElementById(spec.containerId);
      if (!el || !window.echarts) continue;
      const chart = echarts.init(el, null, {{ renderer: 'canvas' }});
      chart.setOption(spec.option);
      window.addEventListener('resize', () => chart.resize());
    }}
  </script>
</body>
</html>
"""
    output_path = output_dir / "index.html"
    output_path.write_text(html_text, encoding="utf-8")
    return output_path


def _wrap_cell(value: str, width: int = 36) -> str:
    text = str(value)
    if len(text) <= width:
        return text
    return "\n".join(textwrap.wrap(text, width=width))


def _load_matplotlib() -> tuple[Any, Any]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "PNG export requires matplotlib in the Python environment used to run this script"
        ) from exc
    return matplotlib, plt


VALUE_LABEL_SCALE = 2.0


def _scaled_value_label_fontsize(
    base_fontsize: int | float,
    *,
    item_count: int = 1,
    density_cap: bool = True,
) -> int:
    base_size = max(float(base_fontsize), 1.0)
    scaled = max(base_size * VALUE_LABEL_SCALE, base_size + 2.0)
    if density_cap:
        if item_count >= 28:
            scaled = min(scaled, 12.0)
        elif item_count >= 18:
            scaled = min(scaled, 14.0)
        else:
            scaled = min(scaled, 16.0)
    return max(9, int(round(scaled)))


def _label_headroom_ratio(
    *,
    label_fontsize: int,
    max_label_lines: int = 1,
    rotation: int = 0,
) -> float:
    font_factor = max(float(label_fontsize) / 8.0, 1.0)
    line_factor = 1.0 + max(0, max_label_lines - 1) * 0.45
    rotation_factor = 1.35 if rotation else 1.0
    return 0.06 + (0.055 * font_factor * line_factor * rotation_factor)


def _line_label_texts_from_payload(payload: dict[str, Any], series_idx: int, x_values: list[Any], y_values: list[Any]) -> list[str]:
    annotations = payload.get("series")[series_idx].get("annotations") if isinstance(payload.get("series"), list) and series_idx < len(payload.get("series")) and isinstance(payload.get("series")[series_idx], dict) else []
    if isinstance(annotations, list) and annotations:
        return [str(value or "").replace("\\n", "\n").strip() for value in annotations[: min(len(x_values), len(y_values))]]
    annotate_x_values = {int(value) for value in (payload.get("annotate_x_values") or [])}
    labels: list[str] = []
    for point_idx in range(min(len(x_values), len(y_values))):
        x_value = float(x_values[point_idx])
        y_value = float(y_values[point_idx])
        if annotate_x_values and int(round(x_value)) in annotate_x_values:
            labels.append(f"{int(round(x_value))}y\n{_format_compact_eur(y_value)}")
        else:
            labels.append("")
    return labels


def _build_line_annotation_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    series_list = [item for item in (payload.get("series") or []) if isinstance(item, dict)]
    priority_x_values = {int(value) for value in (payload.get("annotation_priority_x_values") or [])}
    for series_idx, series in enumerate(series_list):
        x_values = list(series.get("x") or [])
        y_values = list(series.get("y") or [])
        if not x_values or not y_values:
            continue
        label_texts = _line_label_texts_from_payload(payload, series_idx, x_values, y_values)
        min_x = min((float(value) for value in x_values), default=0.0)
        max_x = max((float(value) for value in x_values), default=0.0)
        span_x = max(max_x - min_x, 1.0)
        for point_idx in range(min(len(x_values), len(y_values), len(label_texts))):
            label_text = label_texts[point_idx]
            if not label_text:
                continue
            x_value = float(x_values[point_idx])
            preferred_positions = ["top", "bottom", "top-right", "top-left", "right", "left"]
            if x_value <= (min_x + 0.08 * span_x):
                preferred_positions = ["right", "top-right", "bottom-right", "top", "bottom", "far-right"]
            elif x_value >= (max_x - 0.05 * span_x):
                preferred_positions = ["left", "top-left", "bottom-left", "top", "bottom", "far-left"]
            elif (series_idx + point_idx) % 2 == 1:
                preferred_positions = ["bottom", "top", "bottom-right", "bottom-left", "right", "left"]
            items.append(
                {
                    "x": x_value,
                    "y": float(y_values[point_idx]),
                    "text": label_text,
                    "color": series.get("color") or "#111827",
                    "priority": int(round(x_value)) in priority_x_values,
                    "preferred_positions": preferred_positions,
                }
            )
    return items


def _save_figure(fig: Any, output_path: Path, note: str | None = None) -> None:
    if note:
        fig.tight_layout(rect=(0, 0.06, 1, 1))
        fig.text(0.01, 0.01, note, ha="left", va="bottom", fontsize=8, color="#475569", wrap=True)
    else:
        fig.tight_layout()
    fig.savefig(output_path, dpi=180, bbox_inches="tight")


def _render_table_png(plt: Any, title: str, headers: list[str], rows: list[list[str]], output_path: Path) -> None:
    width = max(10.0, len(headers) * 2.4)
    height = max(3.0, len(rows) * 0.55 + 1.6)
    fig, ax = plt.subplots(figsize=(width, height))
    ax.axis("off")
    wrapped_rows = [[_wrap_cell(cell) for cell in row] for row in rows]
    table = ax.table(cellText=wrapped_rows, colLabels=headers, loc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.0, 1.35)
    ax.set_title(title, fontsize=13, pad=18)
    _save_figure(fig, output_path)
    plt.close(fig)


def _render_line_png(plt: Any, payload: dict[str, Any], output_path: Path) -> None:
    strategy = str(payload.get("label_strategy") or "").strip().lower()
    line_series = [item for item in (payload.get("series") or []) if isinstance(item, dict)]
    if bool(payload.get("legacy_line_layout")):
        fig, ax = plt.subplots(figsize=(11, 6))
        annotate_x_values = {int(value) for value in (payload.get("annotate_x_values") or [])}
        for series_idx, series in enumerate(line_series):
            x_values = list(series.get("x") or [])
            y_values = list(series.get("y") or [])
            min_x = min((float(value) for value in x_values), default=0.0)
            max_x = max((float(value) for value in x_values), default=0.0)
            span_x = max(max_x - min_x, 1.0)
            ax.plot(
                x_values,
                y_values,
                marker="o",
                linewidth=2.5,
                label=series.get("name"),
                color=series.get("color"),
                linestyle=series.get("linestyle") or "solid",
            )
            annotations = list(series.get("annotations") or [])
            if annotations:
                for point_idx in range(min(len(x_values), len(y_values), len(annotations))):
                    label = str(annotations[point_idx] or "").strip()
                    if not label:
                        continue
                    x_value = float(x_values[point_idx])
                    x_offset = 0
                    ha = "center"
                    if x_value <= (min_x + 0.08 * span_x):
                        x_offset = 16
                        ha = "left"
                    elif x_value >= (max_x - 0.05 * span_x):
                        x_offset = -16
                        ha = "right"
                    y_offset = 8 if (series_idx + point_idx) % 2 == 0 else -32
                    ax.annotate(
                        label.replace("\\n", "\n"),
                        (x_value, float(y_values[point_idx])),
                        textcoords="offset points",
                        xytext=(x_offset, y_offset),
                        ha=ha,
                        fontsize=8,
                        color=series.get("color") or "#111827",
                    )
            elif annotate_x_values:
                for point_idx in range(min(len(x_values), len(y_values))):
                    x_value = float(x_values[point_idx])
                    y_value = float(y_values[point_idx])
                    if int(round(x_value)) not in annotate_x_values:
                        continue
                    y_offset = 8 if (series_idx + point_idx) % 2 == 0 else -30
                    ax.annotate(
                        f"{int(round(x_value))}y\n{_format_compact_eur(y_value)}",
                        (x_value, y_value),
                        textcoords="offset points",
                        xytext=(0, y_offset),
                        ha="center",
                        fontsize=8,
                        color=series.get("color") or "#111827",
                    )
        ax.set_title(payload.get("title") or "")
        ax.set_xlabel(payload.get("xlabel") or "")
        ax.set_ylabel(payload.get("ylabel") or "")
        if payload.get("xscale"):
            ax.set_xscale(str(payload.get("xscale")))
        if payload.get("yscale"):
            ax.set_yscale(str(payload.get("yscale")))
        if str(payload.get("yaxis_format") or "").strip().lower() == "compact_eur":
            from matplotlib.ticker import FuncFormatter

            ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: _format_compact_eur(value).replace(" EUR", "")))
            ax.yaxis.get_offset_text().set_visible(False)
        xticks = [float(value) for value in (payload.get("xticks") or []) if isinstance(value, (int, float))]
        if xticks:
            ax.set_xticks(xticks)
            labels = list(payload.get("xtick_labels") or [])
            if len(labels) == len(xticks):
                ax.set_xticklabels([str(label) for label in labels])
            else:
                ax.set_xticklabels([str(int(value)) if float(value).is_integer() else str(value) for value in xticks])
        ax.grid(True, alpha=0.25)
        if line_series:
            ax.legend()
        _save_figure(fig, output_path, payload.get("note"))
        plt.close(fig)
        return

    annotation_items = _build_line_annotation_items(payload)
    point_count = sum(len(list(series.get("x") or [])) for series in line_series)
    label_fontsize = int(
        payload.get("label_fontsize_target")
        or _scaled_value_label_fontsize(8, item_count=max(point_count, len(line_series)))
    )
    max_label_lines = max((text_line_count(item.get("text")) for item in annotation_items), default=1)
    autoscale_mode = str(payload.get("figure_autoscale_mode") or "both").strip().lower() or "both"
    if strategy == "line_full_labels_with_callouts":
        width, height = line_chart_figure_size(
            point_count=point_count,
            series_count=max(len(line_series), 1),
            label_fontsize=label_fontsize,
            max_label_lines=max_label_lines,
            base_width=11.0,
            base_height=6.2,
            autoscale_mode=autoscale_mode,
        )
        for attempt in range(6):
            fig, ax = plt.subplots(figsize=(width, height))
            for series in line_series:
                x_values = list(series.get("x") or [])
                y_values = list(series.get("y") or [])
                ax.plot(
                    x_values,
                    y_values,
                    marker="o",
                    linewidth=2.5,
                    label=series.get("name"),
                    color=series.get("color"),
                    linestyle=series.get("linestyle") or "solid",
                )
            ax.set_title(payload.get("title") or "")
            ax.set_xlabel(payload.get("xlabel") or "")
            ax.set_ylabel(payload.get("ylabel") or "")
            if payload.get("xscale"):
                ax.set_xscale(str(payload.get("xscale")))
            if payload.get("yscale"):
                ax.set_yscale(str(payload.get("yscale")))
            if str(payload.get("yaxis_format") or "").strip().lower() == "compact_eur":
                from matplotlib.ticker import FuncFormatter

                ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: _format_compact_eur(value).replace(" EUR", "")))
                ax.yaxis.get_offset_text().set_visible(False)
            xticks = [float(value) for value in (payload.get("xticks") or []) if isinstance(value, (int, float))]
            if xticks:
                ax.set_xticks(xticks)
                labels = list(payload.get("xtick_labels") or [])
                if len(labels) == len(xticks):
                    ax.set_xticklabels([str(label) for label in labels])
                else:
                    ax.set_xticklabels([str(int(value)) if float(value).is_integer() else str(value) for value in xticks])
            ax.grid(True, alpha=0.25)
            if line_series:
                ax.legend()
            ax.margins(x=0.06, y=0.14 if annotation_items else 0.08)
            if annotation_items:
                result = place_line_annotations(
                    ax,
                    annotation_items,
                    label_fontsize=label_fontsize,
                    allow_leader_lines=bool(payload.get("allow_leader_lines", True)),
                )
                if result.success:
                    _save_figure(fig, output_path, payload.get("note"))
                    plt.close(fig)
                    return
            else:
                _save_figure(fig, output_path, payload.get("note"))
                plt.close(fig)
                return
            plt.close(fig)
            width *= 1.16
            if autoscale_mode == "both":
                height *= 1.12
        fig, ax = plt.subplots(figsize=(width, height))
        for series in line_series:
            ax.plot(
                list(series.get("x") or []),
                list(series.get("y") or []),
                marker="o",
                linewidth=2.5,
                label=series.get("name"),
                color=series.get("color"),
                linestyle=series.get("linestyle") or "solid",
            )
        ax.set_title(payload.get("title") or "")
        ax.set_xlabel(payload.get("xlabel") or "")
        ax.set_ylabel(payload.get("ylabel") or "")
        if payload.get("xscale"):
            ax.set_xscale(str(payload.get("xscale")))
        if payload.get("yscale"):
            ax.set_yscale(str(payload.get("yscale")))
        if str(payload.get("yaxis_format") or "").strip().lower() == "compact_eur":
            from matplotlib.ticker import FuncFormatter

            ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: _format_compact_eur(value).replace(" EUR", "")))
            ax.yaxis.get_offset_text().set_visible(False)
        xticks = [float(value) for value in (payload.get("xticks") or []) if isinstance(value, (int, float))]
        if xticks:
            ax.set_xticks(xticks)
            labels = list(payload.get("xtick_labels") or [])
            if len(labels) == len(xticks):
                ax.set_xticklabels([str(label) for label in labels])
            else:
                ax.set_xticklabels([str(int(value)) if float(value).is_integer() else str(value) for value in xticks])
        ax.grid(True, alpha=0.25)
        if line_series:
            ax.legend()
        _save_figure(fig, output_path, payload.get("note"))
        plt.close(fig)
        return

    fig, ax = plt.subplots(figsize=(11, 6))
    annotate_x_values = {int(value) for value in (payload.get("annotate_x_values") or [])}
    has_annotations = False
    for series_idx, series in enumerate(line_series):
        x_values = list(series.get("x") or [])
        y_values = list(series.get("y") or [])
        min_x = min((float(value) for value in x_values), default=0.0)
        max_x = max((float(value) for value in x_values), default=0.0)
        span_x = max(max_x - min_x, 1.0)
        annotation_fontsize = _scaled_value_label_fontsize(8, item_count=max(len(x_values), len(line_series)))
        ax.plot(
            x_values,
            y_values,
            marker="o",
            linewidth=2.5,
            label=series.get("name"),
            color=series.get("color"),
            linestyle=series.get("linestyle") or "solid",
        )
        annotations = list(series.get("annotations") or [])
        if annotations:
            for point_idx in range(min(len(x_values), len(y_values), len(annotations))):
                label = str(annotations[point_idx] or "").strip()
                if not label:
                    continue
                has_annotations = True
                x_value = float(x_values[point_idx])
                x_offset = 0
                ha = "center"
                if x_value <= (min_x + 0.08 * span_x):
                    x_offset = 16
                    ha = "left"
                elif x_value >= (max_x - 0.05 * span_x):
                    x_offset = -16
                    ha = "right"
                y_offset = 8 if (series_idx + point_idx) % 2 == 0 else -32
                ax.annotate(
                    label.replace("\\n", "\n"),
                    (x_value, float(y_values[point_idx])),
                    textcoords="offset points",
                    xytext=(x_offset, y_offset),
                    ha=ha,
                    fontsize=annotation_fontsize,
                    color=series.get("color") or "#111827",
                    annotation_clip=True,
                )
        elif annotate_x_values:
            for point_idx in range(min(len(x_values), len(y_values))):
                x_value = float(x_values[point_idx])
                y_value = float(y_values[point_idx])
                if int(round(x_value)) not in annotate_x_values:
                    continue
                has_annotations = True
                y_offset = 8 if (series_idx + point_idx) % 2 == 0 else -30
                ax.annotate(
                    f"{int(round(x_value))}y\n{_format_compact_eur(y_value)}",
                    (x_value, y_value),
                    textcoords="offset points",
                    xytext=(0, y_offset),
                    ha="center",
                    fontsize=annotation_fontsize,
                    color=series.get("color") or "#111827",
                    annotation_clip=True,
                )
        ax.set_title(payload.get("title") or "")
        ax.set_xlabel(payload.get("xlabel") or "")
        ax.set_ylabel(payload.get("ylabel") or "")
        if payload.get("xscale"):
            ax.set_xscale(str(payload.get("xscale")))
        if payload.get("yscale"):
            ax.set_yscale(str(payload.get("yscale")))
        if str(payload.get("yaxis_format") or "").strip().lower() == "compact_eur":
            from matplotlib.ticker import FuncFormatter

            ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: _format_compact_eur(value).replace(" EUR", "")))
            ax.yaxis.get_offset_text().set_visible(False)
        xticks = [float(value) for value in (payload.get("xticks") or []) if isinstance(value, (int, float))]
        if xticks:
            ax.set_xticks(xticks)
            labels = list(payload.get("xtick_labels") or [])
            if len(labels) == len(xticks):
                ax.set_xticklabels([str(label) for label in labels])
            else:
                ax.set_xticklabels([str(int(value)) if float(value).is_integer() else str(value) for value in xticks])
    ax.grid(True, alpha=0.25)
    if line_series:
        ax.legend()
    ax.margins(x=0.04, y=0.08)
    if has_annotations:
        y_min, y_max = ax.get_ylim()
        y_span = max(y_max - y_min, 1.0)
        ax.set_ylim(y_min - (0.04 * y_span), y_max + (0.20 * y_span))
    _save_figure(fig, output_path, payload.get("note"))
    plt.close(fig)


def _bar_label_text(value: float, label_format: str | None) -> str:
    fmt = str(label_format or "").strip().lower()
    if fmt == "compact_eur":
        return _format_compact_eur(value)
    if fmt == "percent":
        return _format_percent(value)
    return _format_number(value)


def _grouped_bar_label_text(
    payload: dict[str, Any],
    series_idx: int,
    value_idx: int,
    value: float,
) -> str:
    label_texts = payload.get("label_texts")
    if (
        isinstance(label_texts, list)
        and series_idx < len(label_texts)
        and isinstance(label_texts[series_idx], list)
        and value_idx < len(label_texts[series_idx])
    ):
        custom = str(label_texts[series_idx][value_idx] or "").strip()
        if custom:
            return custom
    return _bar_label_text(value, payload.get("label_format"))


def _resolve_grouped_bar_ymax(payload: dict[str, Any]) -> float:
    explicit = payload.get("ymax")
    series = payload.get("series") or []
    categories = payload.get("categories") or []
    base_label_fontsize = int(_safe_int(payload.get("label_fontsize"), default=8) or 8)
    scaled_label_fontsize = _scaled_value_label_fontsize(
        base_label_fontsize,
        item_count=max(len(categories), len(series)),
    )
    max_value = 0.0
    max_label_lines = 1
    for series_idx, item in enumerate(series):
        values = item.get("values") or []
        for value_idx, raw_value in enumerate(values):
            value = max(_safe_float(raw_value), 0.0)
            if value > max_value:
                max_value = value
            if payload.get("show_labels") and value > 0.0:
                label_text = _grouped_bar_label_text(payload, series_idx, value_idx, value)
                max_label_lines = max(max_label_lines, text_line_count(label_text))
    auto_ymax = max(max_value, 1.0)
    if payload.get("show_labels") and max_value > 0.0:
        headroom_ratio = _safe_float(payload.get("label_headroom_ratio"), default=0.0)
        if headroom_ratio <= 0.0:
            headroom_ratio = _label_headroom_ratio(
                label_fontsize=scaled_label_fontsize,
                max_label_lines=max_label_lines,
            )
        auto_ymax = max_value * (1.0 + headroom_ratio)
    elif max_value <= 0.0:
        auto_ymax = 1.0
    if explicit is not None:
        return max(float(explicit), auto_ymax)
    return auto_ymax


def _resolve_bar_ymax(
    payload: dict[str, Any],
    values: list[Any],
    *,
    label_fontsize: int,
) -> float:
    explicit = payload.get("ymax")
    numeric_values = [max(float(value or 0.0), 0.0) for value in values]
    max_value = max(numeric_values, default=0.0)
    auto_ymax = max(max_value, 1.0)
    if payload.get("show_labels") and max_value > 0.0:
        auto_ymax = max_value * (1.0 + _label_headroom_ratio(label_fontsize=label_fontsize))
    if explicit is not None:
        return max(float(explicit), auto_ymax)
    return auto_ymax


def _render_bar_png(plt: Any, payload: dict[str, Any], output_path: Path) -> None:
    categories = payload.get("categories") or []
    values = payload.get("values") or []
    show_labels = bool(payload.get("show_labels"))
    fig_width = max(11.0, len(categories) * 1.15 + (2.4 if show_labels else 1.6))
    fig_height = 6.6 if show_labels else 6.0
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))
    bars = ax.bar(categories, values, **_matplotlib_bar_kwargs(payload if isinstance(payload, dict) else {}))
    ax.set_title(payload.get("title") or "")
    if payload.get("xlabel"):
        ax.set_xlabel(payload.get("xlabel"))
    if payload.get("ylabel"):
        ax.set_ylabel(payload.get("ylabel"))
    label_fontsize = _scaled_value_label_fontsize(8, item_count=len(categories))
    ax.set_ylim(0, _resolve_bar_ymax(payload, values, label_fontsize=label_fontsize))
    ax.tick_params(axis="x", rotation=24)
    ax.grid(True, axis="y", alpha=0.2)
    ax.margins(x=0.06)
    if show_labels:
        label_format = payload.get("label_format")
        for bar, raw_value in zip(bars, values):
            value = float(raw_value or 0.0)
            y_pad = max((ax.get_ylim()[1] or 1.0) * 0.015, 0.5)
            ax.text(
                bar.get_x() + (bar.get_width() / 2.0),
                value + y_pad,
                _bar_label_text(value, label_format),
                ha="center",
                va="bottom",
                fontsize=label_fontsize,
                clip_on=True,
                bbox={"boxstyle": "round,pad=0.18", "facecolor": "white", "edgecolor": "none", "alpha": 0.82},
            )
    _save_figure(fig, output_path, payload.get("note"))
    plt.close(fig)


def _render_horizontal_bar_png(plt: Any, payload: dict[str, Any], output_path: Path) -> None:
    categories = payload.get("categories") or []
    values = payload.get("values") or []
    fig, ax = plt.subplots(figsize=(12, max(5, len(categories) * 0.5)))
    ax.barh(categories, values, **_matplotlib_bar_kwargs(payload if isinstance(payload, dict) else {}))
    ax.set_title(payload.get("title") or "")
    if payload.get("xlabel"):
        ax.set_xlabel(payload.get("xlabel"))
    ax.grid(True, axis="x", alpha=0.2)
    _save_figure(fig, output_path, payload.get("note"))
    plt.close(fig)


def _render_grouped_bar_png(plt: Any, payload: dict[str, Any], output_path: Path) -> None:
    categories = payload.get("categories") or []
    series = payload.get("series") or []
    strategy = str(payload.get("label_strategy") or "").strip().lower()
    if not categories or not series:
        fig, ax = plt.subplots(figsize=(11.5, 6.8))
        fig.savefig(output_path, dpi=180)
        plt.close(fig)
        return
    if strategy == "grouped_bar_full_labels":
        base_label_fontsize = int(_safe_int(payload.get("label_fontsize"), default=8) or 8)
        label_fontsize = int(
            payload.get("label_fontsize_target")
            or _scaled_value_label_fontsize(base_label_fontsize, item_count=max(len(categories), len(series)))
        )
        max_label_lines = 1
        label_groups: list[list[str]] = []
        for idx, item in enumerate(series):
            values = [float(value) for value in item.get("values") or []]
            labels: list[str] = []
            for value_idx, value in enumerate(values):
                label_text = _grouped_bar_label_text(payload, idx, value_idx, value) if payload.get("show_labels") and value > 0.0 else ""
                labels.append(label_text)
                max_label_lines = max(max_label_lines, text_line_count(label_text))
            label_groups.append(labels)
        width, height = grouped_bar_figure_size(
            category_count=len(categories),
            series_count=len(series),
            label_fontsize=label_fontsize,
            max_label_lines=max_label_lines,
            base_width=max(11.5, len(categories) * 1.2 + len(series) * 0.7 + 1.6),
            base_height=6.8,
        )
        for _attempt in range(6):
            fig, ax = plt.subplots(figsize=(width, height))
            ax.set_ylim(0, _resolve_grouped_bar_ymax(payload))
            bar_width = 0.8 / max(1, len(series))
            positions = list(range(len(categories)))
            bar_groups: list[list[Any]] = []
            for idx, item in enumerate(series):
                offset = (idx - (len(series) - 1) / 2.0) * bar_width
                shifted = [pos + offset for pos in positions]
                values = [float(value) for value in item.get("values") or []]
                bars = ax.bar(shifted, values, width=bar_width, label=item.get("name"), **_matplotlib_bar_kwargs(item))
                bar_groups.append(list(bars))
            ax.set_xticks(positions)
            ax.set_xticklabels(categories, rotation=20, ha="right")
            ax.set_title(payload.get("title") or "")
            if payload.get("ylabel"):
                ax.set_ylabel(payload.get("ylabel"))
            ymax = payload.get("ymax")
            if ymax is not None:
                ax.set_ylim(0, float(ymax))
            ax.legend()
            ax.grid(True, axis="y", alpha=0.2)
            ax.margins(x=0.06)
            if payload.get("show_labels"):
                result = place_grouped_bar_labels(
                    ax,
                    bar_groups,
                    label_groups,
                    label_fontsize=label_fontsize,
                    lane_gap_pts=float(payload.get("label_lane_gap_pts") or 6.0),
                )
                if result.success:
                    _save_figure(fig, output_path, payload.get("note"))
                    plt.close(fig)
                    return
            else:
                _save_figure(fig, output_path, payload.get("note"))
                plt.close(fig)
                return
            plt.close(fig)
            width *= 1.14
            height *= 1.12
        fig, ax = plt.subplots(figsize=(width, height))
        ax.set_ylim(0, _resolve_grouped_bar_ymax(payload))
        bar_width = 0.8 / max(1, len(series))
        positions = list(range(len(categories)))
        for idx, item in enumerate(series):
            offset = (idx - (len(series) - 1) / 2.0) * bar_width
            shifted = [pos + offset for pos in positions]
            values = [float(value) for value in item.get("values") or []]
            ax.bar(shifted, values, width=bar_width, label=item.get("name"), **_matplotlib_bar_kwargs(item))
        ax.set_xticks(positions)
        ax.set_xticklabels(categories, rotation=20, ha="right")
        ax.set_title(payload.get("title") or "")
        if payload.get("ylabel"):
            ax.set_ylabel(payload.get("ylabel"))
        ax.legend()
        ax.grid(True, axis="y", alpha=0.2)
        _save_figure(fig, output_path, payload.get("note"))
        plt.close(fig)
        return

    fig_width = max(11.5, len(categories) * 1.2 + len(series) * 0.7 + 1.6)
    fig, ax = plt.subplots(figsize=(fig_width, 6.8))
    ax.set_ylim(0, _resolve_grouped_bar_ymax(payload))
    width = 0.8 / max(1, len(series))
    positions = list(range(len(categories)))
    for idx, item in enumerate(series):
        offset = (idx - (len(series) - 1) / 2.0) * width
        shifted = [pos + offset for pos in positions]
        values = [float(value) for value in item.get("values") or []]
        bars = ax.bar(shifted, values, width=width, label=item.get("name"), **_matplotlib_bar_kwargs(item))
        if payload.get("show_labels"):
            base_label_fontsize = int(_safe_int(payload.get("label_fontsize"), default=8) or 8)
            label_fontsize = _scaled_value_label_fontsize(
                base_label_fontsize,
                item_count=max(len(categories), len(series)),
            )
            y_pad = max((ax.get_ylim()[1] or 1.0) * 0.015, max(max(values, default=0.0) * 0.02, 0.0), 0.5)
            for value_idx, (bar, value) in enumerate(zip(bars, values)):
                if value <= 0.0:
                    continue
                label_text = _grouped_bar_label_text(payload, idx, value_idx, value)
                ax.text(
                    bar.get_x() + (bar.get_width() / 2.0),
                    value + y_pad,
                    label_text,
                    ha="center",
                    va="bottom",
                    fontsize=label_fontsize,
                    rotation=0,
                    clip_on=True,
                    bbox={"boxstyle": "round,pad=0.2", "facecolor": "white", "edgecolor": "none", "alpha": 0.82},
                )
    ax.set_xticks(positions)
    ax.set_xticklabels(categories, rotation=20, ha="right")
    ax.set_title(payload.get("title") or "")
    if payload.get("ylabel"):
        ax.set_ylabel(payload.get("ylabel"))
    ymax = payload.get("ymax")
    if ymax is not None:
        ax.set_ylim(0, float(ymax))
    ax.legend()
    ax.grid(True, axis="y", alpha=0.2)
    ax.margins(x=0.05)
    _save_figure(fig, output_path, payload.get("note"))
    plt.close(fig)


def _render_grouped_stacked_bar_png(plt: Any, payload: dict[str, Any], output_path: Path) -> None:
    from matplotlib.patches import Patch

    categories = payload.get("categories") or []
    groups = [item for item in (payload.get("groups") or []) if isinstance(item, dict)]
    if not categories or not groups:
        fig, ax = plt.subplots(figsize=(11.5, 6.8))
        fig.savefig(output_path, dpi=180)
        plt.close(fig)
        return

    fig_width = max(12.0, len(categories) * max(len(groups), 1) * 0.62 + 3.0)
    fig, ax = plt.subplots(figsize=(fig_width, 7.0))
    positions = list(range(len(categories)))
    group_width = min(0.34, 0.82 / max(len(groups), 1))
    max_total = 0.0
    segment_legend: dict[str, str] = {}
    hatch_legend: dict[str, str] = {}
    for group_idx, group in enumerate(groups):
        offset = (group_idx - (len(groups) - 1) / 2.0) * group_width
        shifted = [position + offset for position in positions]
        bottoms = [0.0 for _category in categories]
        hatch = str(group.get("hatch") or "")
        hatch_legend[str(group.get("name") or f"Serie {group_idx + 1}")] = hatch
        for segment in [item for item in (group.get("segments") or []) if isinstance(item, dict)]:
            values = [max(_safe_float(value), 0.0) for value in (segment.get("values") or [])]
            if len(values) < len(categories):
                values.extend([0.0] * (len(categories) - len(values)))
            values = values[: len(categories)]
            color = str(segment.get("color") or "#64748b")
            label = str(segment.get("name") or "")
            if label and label not in segment_legend:
                segment_legend[label] = color
            ax.bar(
                shifted,
                values,
                width=group_width * 0.9,
                bottom=bottoms,
                color=color,
                edgecolor="#334155",
                linewidth=0.45,
                hatch=hatch,
            )
            bottoms = [bottoms[idx] + values[idx] for idx in range(len(categories))]
        max_total = max(max_total, max(bottoms, default=0.0))
        if payload.get("show_labels"):
            item_count = len(categories) * len(groups)
            label_fontsize = 8 if item_count >= 10 else 9
            label_rotation = 90 if item_count >= 10 else 0
            y_pad = max((max_total or 1.0) * 0.015, 0.5)
            for x_pos, total in zip(shifted, bottoms):
                if total <= 0.0:
                    continue
                ax.text(
                    x_pos,
                    total + y_pad,
                    _bar_label_text(total, payload.get("label_format")),
                    ha="center",
                    va="bottom",
                    fontsize=label_fontsize,
                    rotation=label_rotation,
                    clip_on=True,
                    color="#0f172a",
                )

    explicit_ymax = payload.get("ymax")
    auto_ymax = max(max_total * (1.32 if payload.get("show_labels") else 1.08), 1.0)
    if explicit_ymax is not None:
        auto_ymax = max(auto_ymax, _safe_float(explicit_ymax))
    ax.set_ylim(0, auto_ymax)
    ax.set_xticks(positions)
    ax.set_xticklabels(categories, rotation=24, ha="right")
    ax.set_title(payload.get("title") or "")
    if payload.get("ylabel"):
        ax.set_ylabel(payload.get("ylabel"))
    ax.grid(True, axis="y", alpha=0.2)
    ax.margins(x=0.04)

    segment_handles = [
        Patch(facecolor=color, edgecolor="#334155", label=label)
        for label, color in segment_legend.items()
    ]
    hatch_handles = [
        Patch(facecolor="white", edgecolor="#334155", hatch=hatch, label=label)
        for label, hatch in hatch_legend.items()
    ]
    if segment_handles:
        legend_one = ax.legend(handles=segment_handles, loc="lower left", bbox_to_anchor=(0.0, 1.01), frameon=False, title="Famille")
        ax.add_artist(legend_one)
    if hatch_handles:
        ax.legend(handles=hatch_handles, loc="lower right", bbox_to_anchor=(1.0, 1.01), frameon=False, title="Scenario")

    _save_figure(fig, output_path, payload.get("note"))
    plt.close(fig)


def _render_grouped_stacked_bar_side_segment_labels_png(plt: Any, payload: dict[str, Any], output_path: Path) -> None:
    from matplotlib.patches import Patch

    categories = payload.get("categories") or []
    groups = [item for item in (payload.get("groups") or []) if isinstance(item, dict)]
    if not categories or not groups:
        fig, ax = plt.subplots(figsize=(13.5, 8.5))
        fig.savefig(output_path, dpi=180)
        plt.close(fig)
        return

    positions = [idx * 3.25 for idx in range(len(categories))]
    group_width = min(0.36, 0.88 / max(len(groups), 1))
    totals_by_group: list[list[float]] = []
    for group in groups:
        group_totals = [0.0 for _category in categories]
        for segment in [item for item in (group.get("segments") or []) if isinstance(item, dict)]:
            values = [max(_safe_float(value), 0.0) for value in (segment.get("values") or [])]
            if len(values) < len(categories):
                values.extend([0.0] * (len(categories) - len(values)))
            for idx, value in enumerate(values[: len(categories)]):
                group_totals[idx] += value
        totals_by_group.append(group_totals)

    max_total = max((max(values, default=0.0) for values in totals_by_group), default=0.0)
    ymax = max(max_total * 1.24, 1.0)
    fig_width = max(18.2, len(categories) * 3.75 + 3.2)
    fig_height = max(10.4, 8.6 + (float(payload.get("label_fontsize") or 13) * 0.08))
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))
    ax.set_ylim(0, ymax)
    ax.set_xlim(min(positions) - 1.18, max(positions) + 1.18)

    label_fontsize = int(_safe_int(payload.get("label_fontsize"), default=13) or 13)
    total_label_fontsize = int(_safe_int(payload.get("total_label_fontsize"), default=17) or 17)
    x_tick_label_fontsize = int(_safe_int(payload.get("x_tick_label_fontsize"), default=18) or 18)
    side_label_gap = group_width * 0.76 + 0.14
    min_gap = ymax * 0.042
    lower_bound = ymax * 0.016
    upper_bound = ymax * 0.968
    segment_legend: dict[str, str] = {}
    hatch_legend: dict[str, str] = {}
    side_labels: dict[tuple[int, int], list[dict[str, Any]]] = {}

    for group_idx, group in enumerate(groups):
        offset = (group_idx - (len(groups) - 1) / 2.0) * group_width
        shifted = [position + offset for position in positions]
        bottoms = [0.0 for _category in categories]
        hatch = str(group.get("hatch") or "")
        hatch_legend[str(group.get("name") or f"Serie {group_idx + 1}")] = hatch
        for segment_idx, segment in enumerate([item for item in (group.get("segments") or []) if isinstance(item, dict)]):
            values = [max(_safe_float(value), 0.0) for value in (segment.get("values") or [])]
            if len(values) < len(categories):
                values.extend([0.0] * (len(categories) - len(values)))
            values = values[: len(categories)]
            color = str(segment.get("color") or "#64748b")
            label = str(segment.get("name") or "")
            label_pcts = [_safe_float(value) for value in (segment.get("label_pcts") or [])]
            if label and label not in segment_legend:
                segment_legend[label] = color
            bars = ax.bar(
                shifted,
                values,
                width=group_width * 0.88,
                bottom=bottoms,
                color=color,
                edgecolor="#334155",
                linewidth=0.55,
                hatch=hatch,
            )
            if payload.get("show_labels"):
                for category_idx, (bar, value) in enumerate(zip(bars, values)):
                    if value <= 0.0:
                        continue
                    pct_value = label_pcts[category_idx] if category_idx < len(label_pcts) else 0.0
                    side_labels.setdefault((category_idx, group_idx), []).append(
                        {
                            "x": float(bar.get_x() + (bar.get_width() / 2.0)),
                            "y": bottoms[category_idx] + (value / 2.0),
                            "segment_idx": segment_idx,
                            "label": _format_side_segment_label(value, pct_value),
                        }
                    )
            bottoms = [bottoms[idx] + values[idx] for idx in range(len(categories))]

        if payload.get("show_total_labels"):
            for x_pos, total in zip(shifted, bottoms):
                if total <= 0.0:
                    continue
                ax.text(
                    x_pos,
                    total + (ymax * 0.014),
                    _format_pml_total_side_label(total),
                    ha="center",
                    va="bottom",
                    rotation=90,
                    fontsize=total_label_fontsize,
                    color="#000000",
                    clip_on=False,
                )

    for (category_idx, group_idx), label_records in side_labels.items():
        side = -1 if group_idx == 0 else 1
        label_records.sort(key=lambda item: (float(item["y"]), int(item["segment_idx"])))
        placed_y: list[float] = []
        for item in label_records:
            target_y = min(max(float(item["y"]), lower_bound), upper_bound)
            if placed_y:
                target_y = max(target_y, placed_y[-1] + min_gap)
            placed_y.append(target_y)
        if placed_y and placed_y[-1] > upper_bound:
            shift = placed_y[-1] - upper_bound
            placed_y = [max(value - shift, lower_bound) for value in placed_y]
            for idx in range(len(placed_y) - 2, -1, -1):
                placed_y[idx] = min(placed_y[idx], placed_y[idx + 1] - min_gap)
        if placed_y and placed_y[0] < lower_bound:
            shift = lower_bound - placed_y[0]
            placed_y = [min(value + shift, upper_bound) for value in placed_y]

        for item, text_y in zip(label_records, placed_y):
            x_text = float(item["x"]) + (side * side_label_gap)
            ax.text(
                x_text,
                text_y,
                str(item["label"]),
                ha="right" if side < 0 else "left",
                va="center",
                fontsize=label_fontsize,
                color="#000000",
                clip_on=False,
            )

    ax.set_xticks(positions)
    ax.set_xticklabels(categories, rotation=36, ha="right", fontsize=x_tick_label_fontsize)
    if not payload.get("hide_title"):
        ax.set_title(payload.get("title") or "")
    if payload.get("ylabel"):
        ax.set_ylabel(payload.get("ylabel"))
    ax.grid(True, axis="y", alpha=0.16)
    ax.margins(x=0.02)

    segment_handles = [
        Patch(facecolor=color, edgecolor="#334155", label=label)
        for label, color in segment_legend.items()
    ]
    hatch_handles = [
        Patch(facecolor="white", edgecolor="#334155", hatch=hatch, label=label)
        for label, hatch in hatch_legend.items()
    ]
    if segment_handles:
        legend_one = ax.legend(
            handles=segment_handles,
            loc="lower left",
            bbox_to_anchor=(0.05, 1.01),
            frameon=False,
            title="Sous-classe",
            ncol=3,
            fontsize=11,
            title_fontsize=15,
        )
        ax.add_artist(legend_one)
    if hatch_handles:
        ax.legend(
            handles=hatch_handles,
            loc="lower right",
            bbox_to_anchor=(0.98, 1.01),
            frameon=False,
            title="Scenario",
            ncol=2,
            fontsize=11,
            title_fontsize=13,
        )

    _save_figure(fig, output_path, payload.get("note"))
    plt.close(fig)


def _render_grouped_stacked_bar_segment_labels_png(plt: Any, payload: dict[str, Any], output_path: Path) -> None:
    from matplotlib.patches import Patch

    if str(payload.get("label_layout") or "").strip().lower() == "side_by_segment":
        _render_grouped_stacked_bar_side_segment_labels_png(plt, payload, output_path)
        return

    categories = payload.get("categories") or []
    groups = [item for item in (payload.get("groups") or []) if isinstance(item, dict)]
    if not categories or not groups:
        fig, ax = plt.subplots(figsize=(13.0, 7.0))
        fig.savefig(output_path, dpi=180)
        plt.close(fig)
        return

    label_fontsize = int(_safe_int(payload.get("label_fontsize"), default=7) or 7)
    positions = [idx * (1.9 + (label_fontsize * 0.015)) for idx in range(len(categories))]
    group_width = min(0.36, 0.92 / max(len(groups), 1))
    totals_by_group: list[list[float]] = []
    for group in groups:
        group_totals = [0.0 for _category in categories]
        for segment in [item for item in (group.get("segments") or []) if isinstance(item, dict)]:
            values = [max(_safe_float(value), 0.0) for value in (segment.get("values") or [])]
            if len(values) < len(categories):
                values.extend([0.0] * (len(categories) - len(values)))
            for idx, value in enumerate(values[: len(categories)]):
                group_totals[idx] += value
        totals_by_group.append(group_totals)
    max_total = max((max(values, default=0.0) for values in totals_by_group), default=0.0)
    ymax = max(max_total * 1.26, 1.0)

    fig_width = max(20.0, len(categories) * (2.85 + label_fontsize * 0.08) + len(groups) * 1.35 + 4.5)
    fig_height = max(12.2, 10.4 + (label_fontsize * 0.55))
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))
    ax.set_ylim(0, ymax)
    ax.set_xlim(min(positions) - 1.02, max(positions) + 1.02)

    inside_min_height = ymax * (0.052 + max(label_fontsize - 6, 0) * 0.012)
    total_label_pad = ymax * 0.014
    outside_labels: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
    segment_legend: dict[str, str] = {}
    hatch_legend: dict[str, str] = {}

    for group_idx, group in enumerate(groups):
        offset = (group_idx - (len(groups) - 1) / 2.0) * group_width
        shifted = [position + offset for position in positions]
        bottoms = [0.0 for _category in categories]
        hatch = str(group.get("hatch") or "")
        hatch_legend[str(group.get("name") or f"Serie {group_idx + 1}")] = hatch
        for segment_idx, segment in enumerate([item for item in (group.get("segments") or []) if isinstance(item, dict)]):
            values = [max(_safe_float(value), 0.0) for value in (segment.get("values") or [])]
            if len(values) < len(categories):
                values.extend([0.0] * (len(categories) - len(values)))
            values = values[: len(categories)]
            color = str(segment.get("color") or "#64748b")
            label = str(segment.get("name") or "")
            label_texts = [str(value or "").strip() for value in (segment.get("label_texts") or [])]
            if label and label not in segment_legend:
                segment_legend[label] = color
            bars = ax.bar(
                shifted,
                values,
                width=group_width * 0.86,
                bottom=bottoms,
                color=color,
                edgecolor="#334155",
                linewidth=0.42,
                hatch=hatch,
            )
            if payload.get("show_labels"):
                for category_idx, (bar, value) in enumerate(zip(bars, values)):
                    if value <= 0.0:
                        continue
                    label_text = label_texts[category_idx] if category_idx < len(label_texts) else ""
                    if not label_text:
                        continue
                    x_center = float(bar.get_x() + (bar.get_width() / 2.0))
                    y_center = bottoms[category_idx] + (value / 2.0)
                    if value >= inside_min_height:
                        ax.text(
                            x_center,
                            y_center,
                            label_text,
                            ha="center",
                            va="center",
                            fontsize=label_fontsize,
                            color=label_text_color_for_face(bar.get_facecolor()),
                            fontweight="bold",
                            clip_on=True,
                        )
                    else:
                        side = -1 if group_idx == 0 else 1
                        outside_labels.setdefault((category_idx, group_idx, side), []).append(
                            {
                                "x": x_center,
                                "y": y_center,
                                "side": side,
                                "label": label_text,
                                "segment_idx": segment_idx,
                            }
                        )
            bottoms = [bottoms[idx] + values[idx] for idx in range(len(categories))]
        if payload.get("show_total_labels"):
            for x_pos, total in zip(shifted, bottoms):
                if total <= 0.0:
                    continue
                ax.text(
                    x_pos,
                    total + total_label_pad,
                    _format_compact_eur(total),
                    ha="center",
                    va="bottom",
                    rotation=90,
                    fontsize=7,
                    color="#0f172a",
                    clip_on=True,
                    bbox={"boxstyle": "round,pad=0.12", "facecolor": "white", "edgecolor": "none", "alpha": 0.78},
                )

    min_gap = ymax * (0.048 + max(label_fontsize - 6, 0) * 0.011)
    lower_bound = ymax * 0.035
    upper_bound = ymax * 0.965
    for (_category_idx, group_idx, side), label_records in outside_labels.items():
        label_records.sort(key=lambda item: (float(item["y"]), int(item["segment_idx"])))
        placed_y: list[float] = []
        for item in label_records:
            target_y = min(max(float(item["y"]), lower_bound), upper_bound)
            if placed_y:
                target_y = max(target_y, placed_y[-1] + min_gap)
            placed_y.append(target_y)
        if placed_y and placed_y[-1] > upper_bound:
            shift = placed_y[-1] - upper_bound
            placed_y = [max(value - shift, lower_bound) for value in placed_y]
            for idx in range(len(placed_y) - 2, -1, -1):
                placed_y[idx] = min(placed_y[idx], placed_y[idx + 1] - min_gap)
            if placed_y[0] < lower_bound:
                placed_y = [max(value, lower_bound) for value in placed_y]

        for item, text_y in zip(label_records, placed_y):
            x_anchor = float(item["x"])
            x_text = x_anchor + (side * (group_width * 0.95 + 0.18))
            ax.annotate(
                str(item["label"]),
                xy=(x_anchor, float(item["y"])),
                xytext=(x_text, text_y),
                ha="right" if side < 0 else "left",
                va="center",
                fontsize=label_fontsize,
                color="#0f172a",
                clip_on=False,
                arrowprops={
                    "arrowstyle": "-",
                    "color": "#64748b",
                    "linewidth": 0.55,
                    "shrinkA": 0,
                    "shrinkB": 2,
                    "connectionstyle": "angle3,angleA=0,angleB=90",
                },
                bbox={"boxstyle": "round,pad=0.16", "facecolor": "white", "edgecolor": "none", "alpha": 0.9},
            )

    ax.set_xticks(positions)
    ax.set_xticklabels(categories, rotation=22, ha="right")
    ax.set_title(payload.get("title") or "")
    if payload.get("ylabel"):
        ax.set_ylabel(payload.get("ylabel"))
    ax.grid(True, axis="y", alpha=0.2)
    ax.margins(x=0.03)

    segment_handles = [
        Patch(facecolor=color, edgecolor="#334155", label=label)
        for label, color in segment_legend.items()
    ]
    hatch_handles = [
        Patch(facecolor="white", edgecolor="#334155", hatch=hatch, label=label)
        for label, hatch in hatch_legend.items()
    ]
    if segment_handles:
        legend_one = ax.legend(
            handles=segment_handles,
            loc="lower left",
            bbox_to_anchor=(0.0, 1.01),
            frameon=False,
            title="Sous-classe",
            ncol=3,
            fontsize=8,
        )
        ax.add_artist(legend_one)
    if hatch_handles:
        ax.legend(
            handles=hatch_handles,
            loc="lower right",
            bbox_to_anchor=(1.0, 1.01),
            frameon=False,
            title="Scenario",
            ncol=2,
            fontsize=8,
        )

    _save_figure(fig, output_path, payload.get("note"))
    plt.close(fig)


def _render_stacked_bar_png(plt: Any, payload: dict[str, Any], output_path: Path) -> None:
    categories = payload.get("categories") or []
    series = payload.get("series") or []
    fig, ax = plt.subplots(figsize=(11, 6))
    bottoms = [0.0 for _ in categories]
    for item in series:
        values = [float(value) for value in item.get("values") or []]
        ax.bar(categories, values, bottom=bottoms, label=item.get("name"), color=item.get("color"))
        bottoms = [bottoms[idx] + values[idx] for idx in range(len(values))]
    ax.set_title(payload.get("title") or "")
    if payload.get("ylabel"):
        ax.set_ylabel(payload.get("ylabel"))
    ymax = payload.get("ymax")
    if ymax is not None:
        ax.set_ylim(0, float(ymax))
    ax.tick_params(axis="x", rotation=20)
    ax.legend()
    ax.grid(True, axis="y", alpha=0.2)
    _save_figure(fig, output_path, payload.get("note"))
    plt.close(fig)


def _render_stacked_bar_with_line_png(plt: Any, payload: dict[str, Any], output_path: Path) -> None:
    categories = payload.get("categories") or []
    stacked_series = payload.get("stacked_series") or []
    line_series = payload.get("line_series") or {}
    fig, ax = plt.subplots(figsize=(12, 6.5))
    bottoms = [0.0 for _ in categories]
    for item in stacked_series:
        values = [float(value) for value in item.get("values") or []]
        ax.bar(categories, values, bottom=bottoms, label=item.get("name"), color=item.get("color"))
        bottoms = [bottoms[idx] + values[idx] for idx in range(len(values))]
    ax.set_title(payload.get("title") or "")
    ax.set_ylabel(payload.get("ylabel") or "")
    ax.tick_params(axis="x", rotation=20)
    ax.grid(True, axis="y", alpha=0.2)
    ax2 = ax.twinx()
    ax2.plot(categories, line_series.get("values") or [], color=line_series.get("color"), marker="o", linewidth=2.5, label=line_series.get("name"))
    ax2.set_ylabel(payload.get("line_ylabel") or "")
    handles1, labels1 = ax.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(handles1 + handles2, labels1 + labels2, loc="upper right")
    _save_figure(fig, output_path, payload.get("note"))
    plt.close(fig)


def _render_network_state_matrix_png(plt: Any, payload: dict[str, Any], output_path: Path) -> None:
    from matplotlib.patches import Patch

    row_titles = payload.get("row_titles") or []
    column_titles = payload.get("column_titles") or []
    cells = payload.get("cells") or []
    outage_cause_cells = payload.get("outage_cause_cells") or []
    outage_cause_title = str(payload.get("outage_cause_title") or OUTAGE_CAUSE_TITLE)
    outage_cause_legend_prefix = str(payload.get("outage_cause_legend_prefix") or OUTAGE_CAUSE_LEGEND_PREFIX)
    cause_bar_requires_s3 = payload.get("cause_bar_requires_s3", True) is not False
    outage_cause_empty_label = str(payload.get("outage_cause_empty_label") or "HS\n0%")
    if not row_titles or not column_titles or not cells:
        fig, _ax = plt.subplots(figsize=(12, 8))
        _save_figure(fig, output_path, payload.get("note"))
        plt.close(fig)
        return

    nrows = len(row_titles)
    ncols = len(column_titles)
    percent_label_scale = _matrix_percent_label_scale(payload)
    state_label_fontsize = _matrix_percent_label_fontsize(10, percent_label_scale)
    cause_label_fontsize = _matrix_percent_label_fontsize(7, percent_label_scale)
    legend_fontsize = _matrix_percent_label_fontsize(9, percent_label_scale)
    fig_scale = 1.0 + (max(percent_label_scale - 1.0, 0.0) * 0.24)
    fig, axes = plt.subplots(nrows, ncols, figsize=(15.2 * fig_scale, 12.9 * fig_scale), sharey=True)
    if nrows == 1 and ncols == 1:
        axes_grid = [[axes]]
    elif nrows == 1:
        axes_grid = [list(axes)]
    elif ncols == 1:
        axes_grid = [[ax] for ax in axes]
    else:
        axes_grid = [list(row) for row in axes]

    state_palette = {
        "S0": STATE_COLORS["S0"],
        "S1": HAZARD_COLORS["s1"],
        "S2": HAZARD_COLORS["s2"],
        "S3": HAZARD_COLORS["s3"],
    }
    text_colors = {
        "S0": "#0f172a",
        "S1": "#0f172a",
        "S2": "#0f172a",
        "S3": "#ffffff",
    }

    for row_idx, row_title in enumerate(row_titles):
        row_cells = cells[row_idx] if row_idx < len(cells) and isinstance(cells[row_idx], list) else []
        row_cause_cells = outage_cause_cells[row_idx] if row_idx < len(outage_cause_cells) and isinstance(outage_cause_cells[row_idx], list) else []
        for col_idx, column_title in enumerate(column_titles):
            ax = axes_grid[row_idx][col_idx]
            cell = row_cells[col_idx] if col_idx < len(row_cells) and isinstance(row_cells[col_idx], dict) else {}
            cause_cell = row_cause_cells[col_idx] if col_idx < len(row_cause_cells) and isinstance(row_cause_cells[col_idx], dict) else None
            has_cause_bar = cause_cell is not None
            state_x = -0.23 if has_cause_bar else 0.0
            state_width = 0.46 if has_cause_bar else 0.62
            bottoms = 0.0
            for state in STATE_SEQUENCE:
                value = max(_safe_float(cell.get(state)), 0.0)
                ax.bar([state_x], [value], bottom=[bottoms], width=state_width, color=state_palette[state], edgecolor="white", linewidth=0.8)
                if value >= 10.0:
                    ax.text(
                        state_x,
                        bottoms + (value / 2.0),
                        f"{_state_short_label(state)}\n{value:.0f}%",
                        ha="center",
                        va="center",
                        fontsize=state_label_fontsize,
                        color=text_colors[state],
                        fontweight="bold",
                    )
                bottoms += value
            if cause_cell is not None:
                cause_x = 0.38
                cause_bottom = 0.0
                outage_share = max(_safe_float(cell.get("S3")), 0.0)
                cause_total = 0.0 if cause_bar_requires_s3 and outage_share <= 0.0 else sum(max(_safe_float(cause_cell.get(key)), 0.0) for key in OUTAGE_CAUSE_LABELS)
                if cause_total > 0.0:
                    for cause_key in ("direct", "indirect"):
                        value = max(_safe_float(cause_cell.get(cause_key)), 0.0)
                        ax.bar(
                            [cause_x],
                            [value],
                            bottom=[cause_bottom],
                            width=0.24,
                            color=OUTAGE_CAUSE_COLORS[cause_key],
                            edgecolor="white",
                            linewidth=0.7,
                        )
                        if value >= 18.0:
                            cause_label = (
                                f"{value:.0f}%"
                                if percent_label_scale >= 2.0
                                else f"{OUTAGE_CAUSE_LABELS[cause_key]}\n{value:.0f}%"
                            )
                            ax.text(
                                cause_x,
                                cause_bottom + (value / 2.0),
                                cause_label,
                                ha="center",
                                va="center",
                                fontsize=cause_label_fontsize,
                                color="#ffffff" if cause_key == "indirect" else "#0f172a",
                                fontweight="bold",
                            )
                        cause_bottom += value
                else:
                    ax.bar([cause_x], [100.0], width=0.24, color="none", edgecolor="#94a3b8", linewidth=0.8)
                    ax.text(cause_x, 50.0, outage_cause_empty_label, ha="center", va="center", fontsize=cause_label_fontsize, color="#64748b", fontweight="bold")
                ax.text(cause_x, -7.0, outage_cause_title, ha="center", va="top", fontsize=7, color="#475569")
            ax.set_ylim(-18, 122)
            ax.set_xlim(-0.65, 0.65)
            ax.set_xticks([])
            if col_idx == 0:
                ax.set_ylabel(row_title, rotation=0, labelpad=36, va="center", fontsize=11, fontweight="bold")
                ax.set_yticks([0, 50, 100])
            else:
                ax.set_yticks([0, 50, 100])
                ax.set_yticklabels([])
            if row_idx == 0:
                ax.set_title(column_title, fontsize=11, pad=20, fontweight="bold")
            ax.grid(True, axis="y", alpha=0.18)
            for spine in ("top", "right"):
                ax.spines[spine].set_visible(False)
            ax.spines["left"].set_alpha(0.25)
            ax.spines["bottom"].set_alpha(0.2)

    handles = [Patch(facecolor=state_palette[state], label=_state_label(state)) for state in STATE_SEQUENCE]
    handles.extend(Patch(facecolor=OUTAGE_CAUSE_COLORS[key], label=f"{outage_cause_legend_prefix} - {label}") for key, label in OUTAGE_CAUSE_LABELS.items())
    fig.legend(
        handles=handles,
        loc="lower center",
        ncol=3,
        bbox_to_anchor=(0.5, 0.018),
        frameon=False,
        fontsize=legend_fontsize,
        handlelength=1.35,
        columnspacing=1.1,
        labelspacing=0.7,
    )
    fig.suptitle(payload.get("title") or "", fontsize=18, y=0.989)
    fig.text(0.03, 0.5, str(payload.get("ylabel") or "% des reseaux"), rotation="vertical", va="center", fontsize=11)
    fig.tight_layout(rect=(0.05, 0.17, 1.0, 0.92))
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _render_scatter_map_png(
    plt: Any,
    payload: dict[str, Any],
    output_path: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(8.5, 7.5))
    _plot_scatter_map_axis(fig, ax, payload, add_colorbar=True)
    _save_figure(fig, output_path, payload.get("note"))
    plt.close(fig)


def _render_multi_scatter_map_png(
    plt: Any,
    payload: dict[str, Any],
    output_path: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(8.5, 7.5))
    gpd = _load_geopandas()
    from shapely.geometry import Point

    combined_frames = []
    for series in payload.get("series") or []:
        points = list(series.get("points") or [])
        if not points:
            continue
        gdf = gpd.GeoDataFrame(
            geometry=[Point(float(point["lon"]), float(point["lat"])) for point in points],
            crs="EPSG:4326",
        ).to_crs(epsg=3857)
        combined_frames.append(gdf)
        ax.scatter(
            gdf.geometry.x,
            gdf.geometry.y,
            label=series.get("name"),
            s=series.get("size") or 70,
            alpha=0.8,
            color=series.get("color"),
            zorder=3,
        )
    if combined_frames:
        frame = gpd.GeoDataFrame(geometry=[geom for gdf in combined_frames for geom in gdf.geometry], crs="EPSG:3857")
        _apply_map_extent(ax, frame)
        _add_light_basemap(ax)
    ax.set_title(payload.get("title") or "")
    ax.set_axis_off()
    if payload.get("series"):
        ax.legend()
    _save_figure(fig, output_path, payload.get("note"))
    plt.close(fig)


def _points_to_projected_gdf(points: list[dict[str, float]]) -> Any | None:
    if not points:
        return None
    gpd = _load_geopandas()
    from shapely.geometry import Point

    return gpd.GeoDataFrame(
        {
            "value": [float(point["value"]) for point in points],
        },
        geometry=[Point(float(point["lon"]), float(point["lat"])) for point in points],
        crs="EPSG:4326",
    ).to_crs(epsg=3857)


def _plot_scatter_map_axis(
    fig: Any,
    ax: Any,
    payload: dict[str, Any],
    *,
    extent_gdf: Any | None = None,
    add_colorbar: bool = False,
) -> Any | None:
    points = list(payload.get("points") or [])
    gdf = _points_to_projected_gdf(points)
    frame = gdf if gdf is not None else extent_gdf
    if frame is not None:
        _apply_map_extent(ax, frame)
        _add_light_basemap(ax)
    scatter = None
    if gdf is not None:
        scatter = ax.scatter(
            gdf.geometry.x,
            gdf.geometry.y,
            c=list(gdf["value"]),
            cmap=_resolve_map_cmap(payload),
            s=payload.get("size") or 130,
            marker="s",
            edgecolors="none",
            alpha=0.9,
            zorder=3,
            vmin=payload.get("vmin"),
            vmax=payload.get("vmax"),
        )
        if add_colorbar:
            cbar = fig.colorbar(scatter, ax=ax, shrink=0.8)
            cbar.set_label(payload.get("colorbar_label") or "")
    else:
        ax.text(
            0.5,
            0.5,
            str(payload.get("empty_label") or "Aucune donnee"),
            ha="center",
            va="center",
            fontsize=10,
            color="#475569",
            transform=ax.transAxes,
        )
    title = str(payload.get("title") or "").strip()
    if title:
        ax.set_title(title)
    ax.set_axis_off()
    return scatter


def _render_scatter_map_grid_png(
    plt: Any,
    payload: dict[str, Any],
    output_path: Path,
) -> None:
    import numpy as np

    rows = [item for item in (payload.get("rows") or []) if isinstance(item, dict)]
    columns = [item for item in (payload.get("columns") or []) if isinstance(item, dict)]
    cells = payload.get("cells") or []
    if not rows or not columns:
        raise RuntimeError("scatter_map_grid requires non-empty rows and columns")

    fig, axes = plt.subplots(len(rows), len(columns), figsize=(4.8 * len(columns), 4.4 * len(rows)))
    axes = np.atleast_2d(axes)

    combined_geometries = []
    for row_cells in cells:
        if not isinstance(row_cells, list):
            continue
        for cell_payload in row_cells:
            if not isinstance(cell_payload, dict):
                continue
            gdf = _points_to_projected_gdf(list(cell_payload.get("points") or []))
            if gdf is not None:
                combined_geometries.extend(list(gdf.geometry))

    extent_gdf = None
    if combined_geometries:
        gpd = _load_geopandas()
        extent_gdf = gpd.GeoDataFrame(geometry=combined_geometries, crs="EPSG:3857")

    column_mappables: list[Any | None] = [None for _ in columns]
    for row_index, row in enumerate(rows):
        for column_index, column in enumerate(columns):
            ax = axes[row_index, column_index]
            cell_payload = {}
            if row_index < len(cells) and isinstance(cells[row_index], list) and column_index < len(cells[row_index]) and isinstance(cells[row_index][column_index], dict):
                cell_payload = dict(cells[row_index][column_index])
            if column_index == 0:
                ax.text(
                    -0.12,
                    0.5,
                    str(row.get("label") or ""),
                    transform=ax.transAxes,
                    rotation=90,
                    ha="center",
                    va="center",
                    fontsize=11,
                    fontweight="bold",
                )
            scatter = _plot_scatter_map_axis(fig, ax, {**cell_payload, "title": ""}, extent_gdf=extent_gdf, add_colorbar=False)
            if row_index == 0:
                ax.set_title(str(column.get("label") or ""), fontsize=12, pad=14, fontweight="bold")
            if scatter is not None and column_mappables[column_index] is None:
                column_mappables[column_index] = scatter

    fig.suptitle(payload.get("title") or "", fontsize=16, y=0.98)
    fig.subplots_adjust(top=0.9, bottom=0.08, left=0.06, right=0.93, wspace=0.09, hspace=0.05)

    for column_index, column in enumerate(columns):
        mappable = column_mappables[column_index]
        if mappable is None:
            continue
        top_ax = axes[0, column_index]
        bottom_ax = axes[len(rows) - 1, column_index]
        top_box = top_ax.get_position()
        bottom_box = bottom_ax.get_position()
        next_left = axes[0, column_index + 1].get_position().x0 if column_index + 1 < len(columns) else 0.985
        gutter = max(next_left - top_box.x1, 0.02)
        cbar_width = min(0.012, gutter * 0.16)
        cbar_x = top_box.x1 + (gutter * 0.36)
        cax = fig.add_axes([cbar_x, bottom_box.y0, cbar_width, top_box.y1 - bottom_box.y0])
        cbar = fig.colorbar(mappable, cax=cax)
        cbar.ax.tick_params(labelsize=9, pad=3)
        cbar.set_label(str(column.get("colorbar_label") or ""))
    note = payload.get("note")
    if note:
        fig.text(0.01, 0.01, note, ha="left", va="bottom", fontsize=8, color="#475569", wrap=True)
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _load_geopandas():
    try:
        import geopandas as gpd
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("Integrated map export requires geopandas in the Python environment used to run this script") from exc
    return gpd


def _load_geodataframe_cached(path: str) -> Any:
    cache_key = str(path)
    if cache_key in _GEODATAFRAME_CACHE:
        return _GEODATAFRAME_CACHE[cache_key].copy()
    gpd = _load_geopandas()
    gdf = gpd.read_file(path)
    _GEODATAFRAME_CACHE[cache_key] = gdf
    return gdf.copy()


def _load_geodataframe_layer_cached(path: str, layer: str | None = None) -> Any:
    cache_key = (str(path), str(layer) if layer is not None else None)
    if cache_key in _GEODATAFRAME_LAYER_CACHE:
        return _GEODATAFRAME_LAYER_CACHE[cache_key].copy()
    gpd = _load_geopandas()
    gdf = gpd.read_file(path, layer=layer) if layer is not None else gpd.read_file(path)
    _GEODATAFRAME_LAYER_CACHE[cache_key] = gdf
    return gdf.copy()


def _load_rasterio() -> Any:
    try:
        import rasterio
        import rasterio.mask
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "Population outputs require rasterio in the Python environment used to run this script"
        ) from exc
    return rasterio


def _resolve_map_cmap(payload: dict[str, Any]) -> Any:
    cmap = payload.get("cmap")
    cmap_colors = payload.get("cmap_colors")
    if isinstance(cmap_colors, list) and cmap_colors:
        from matplotlib.colors import LinearSegmentedColormap

        return LinearSegmentedColormap.from_list(_slugify(str(payload.get("title") or "map")), list(cmap_colors))
    return cmap or "viridis"


def _apply_map_extent(ax: Any, gdf: Any, pad_ratio: float = 0.06) -> None:
    bounds = getattr(gdf, "total_bounds", None)
    if bounds is None or len(bounds) != 4:
        return
    min_x, min_y, max_x, max_y = [float(value) for value in bounds]
    span_x = max(max_x - min_x, 1.0)
    span_y = max(max_y - min_y, 1.0)
    ax.set_xlim(min_x - (span_x * pad_ratio), max_x + (span_x * pad_ratio))
    ax.set_ylim(min_y - (span_y * pad_ratio), max_y + (span_y * pad_ratio))


def _adaptive_geo_linewidth(gdf: Any, *, base_width: float) -> float:
    bounds = getattr(gdf, "total_bounds", None)
    if bounds is None or len(bounds) != 4:
        return base_width
    min_x, min_y, max_x, max_y = [float(value) for value in bounds]
    span_x_km = max((max_x - min_x) / 1000.0, 0.001)
    span_y_km = max((max_y - min_y) / 1000.0, 0.001)
    focus_span_km = max(min(span_x_km, span_y_km), 0.001)
    geom_types = {str(value) for value in getattr(gdf, "geom_type", [])}
    is_surface = bool(geom_types) and geom_types.issubset({"Polygon", "MultiPolygon"})

    if is_surface:
        if focus_span_km >= 3.0:
            return base_width
        if focus_span_km <= 1.5:
            return round(min(base_width, 0.22), 2)
        ratio = (focus_span_km - 1.5) / 1.5
        ratio = max(0.0, min(ratio, 1.0))
        return round(0.22 + ((base_width - 0.22) * ratio), 2)

    return base_width


def _surface_focus_span_km(gdf: Any) -> float | None:
    bounds = getattr(gdf, "total_bounds", None)
    if bounds is None or len(bounds) != 4:
        return None
    min_x, min_y, max_x, max_y = [float(value) for value in bounds]
    span_x_km = max((max_x - min_x) / 1000.0, 0.001)
    span_y_km = max((max_y - min_y) / 1000.0, 0.001)
    return max(min(span_x_km, span_y_km), 0.001)


def _state_layer_to_source_infra_types(filter_values: list[str] | None) -> list[str]:
    mapping = {
        "eau_aep": "aep_cana",
        "eau_eu": "eu_cana",
        "elec_bt_aerien": "elec_bt_aerien",
        "elec_bt_souterrain": "elec_bt_souterrain",
        "elec_hta_aerien": "elec_hta_aerien",
        "elec_hta_souterrain": "elec_hta_souterrain",
    }
    out: list[str] = []
    for value in filter_values or []:
        value_str = str(value)
        if value_str == "elec_grid_0p1deg":
            for infra_type in LEGACY_ELECTRIC_STATE_LAYER_KEYS:
                if infra_type not in out:
                    out.append(infra_type)
            continue
        infra_type = mapping.get(value_str)
        if infra_type and infra_type not in out:
            out.append(infra_type)
    return out


def _swap_state_surfaces_for_source_lines(
    gdf: Any,
    payload: dict[str, Any],
) -> Any:
    geom_types = {str(value) for value in getattr(gdf, "geom_type", [])}
    is_surface = bool(geom_types) and geom_types.issubset({"Polygon", "MultiPolygon"})
    if not is_surface:
        return gdf

    state_column = str(payload.get("state_column") or "").strip()
    source_geojson_path = str(payload.get("source_geojson_path") or "").strip()
    if not state_column or not source_geojson_path:
        return gdf

    source_filter_values = _state_layer_to_source_infra_types(payload.get("source_filter_values") or payload.get("filter_values"))
    if not source_filter_values:
        return gdf

    source_gdf = _load_geodataframe_cached(source_geojson_path)
    if "infra_type" not in source_gdf.columns or "feature_id" not in source_gdf.columns:
        return gdf
    source_gdf = source_gdf[source_gdf["infra_type"].isin(source_filter_values)].copy()
    if source_gdf.empty:
        return gdf

    target_crs = gdf.crs
    if source_gdf.crs is None:
        source_gdf = source_gdf.set_crs(epsg=4326)
    if target_crs is None:
        target_crs = "EPSG:3857"
    source_gdf = source_gdf.to_crs(target_crs)

    line_like = source_gdf.geom_type.isin(["LineString", "MultiLineString"])
    source_gdf = source_gdf[line_like].copy()
    if source_gdf.empty:
        return gdf

    if "feature_id" not in gdf.columns:
        return gdf
    state_columns = ["feature_id", state_column]
    state_frame = gdf[state_columns].drop_duplicates(subset=["feature_id"]).copy()
    merged = source_gdf.merge(state_frame, on="feature_id", how="inner")
    if not merged.empty:
        return merged

    aggregated_electric = any(str(value) in AGGREGATED_ELECTRIC_STATE_LAYER_KEYS for value in (payload.get("filter_values") or []))
    if not aggregated_electric:
        return gdf

    gpd = _load_geopandas()
    state_surfaces = gdf[[state_column, "geometry"]].copy()
    source_probes = source_gdf[["feature_id", "geometry"]].copy()
    # Representative points keep one spatial lookup per line feature without
    # requiring source and state feature IDs to match for aggregated grid layers.
    source_probes["geometry"] = source_probes.geometry.representative_point()
    spatial_matches = gpd.sjoin(source_probes, state_surfaces, how="inner", predicate="within")
    if spatial_matches.empty:
        spatial_matches = gpd.sjoin(source_probes, state_surfaces, how="inner", predicate="intersects")
    if spatial_matches.empty:
        return gdf
    state_lookup = spatial_matches[["feature_id", state_column]].drop_duplicates(subset=["feature_id"]).copy()
    spatial_merged = source_gdf.merge(state_lookup, on="feature_id", how="inner")
    if spatial_merged.empty:
        return gdf
    return spatial_merged


def _thin_zoomed_surface_network_geometries(gdf: Any) -> Any:
    geom_types = {str(value) for value in getattr(gdf, "geom_type", [])}
    is_surface = bool(geom_types) and geom_types.issubset({"Polygon", "MultiPolygon"})
    if not is_surface:
        return gdf

    focus_span_km = _surface_focus_span_km(gdf)
    if focus_span_km is None or focus_span_km >= 3.0:
        return gdf
    if focus_span_km <= 1.5:
        shrink_m = 22.0
    else:
        ratio = (3.0 - focus_span_km) / 1.5
        ratio = max(0.0, min(ratio, 1.0))
        shrink_m = round(22.0 * ratio, 2)
    if shrink_m <= 0.0:
        return gdf

    thinned = gdf.copy()
    thinned["geometry"] = thinned.geometry.buffer(-shrink_m)
    thinned = thinned[thinned.geometry.notna() & (~thinned.geometry.is_empty)].copy()
    if thinned.empty:
        return gdf
    return thinned


def _add_light_basemap(ax: Any) -> None:
    try:
        import contextily as cx
    except Exception:
        return
    try:
        cx.add_basemap(
            ax,
            source=cx.providers.CartoDB.Positron,
            attribution=False,
            zoom="auto",
        )
    except Exception:
        return


def _round_to_grid(coord: float, step: float = TERRITORY_GRID_DEG) -> float:
    scaled = float(coord) / float(step)
    if scaled >= 0:
        return round(math.floor(scaled + 0.5) * step, 2)
    return round(math.ceil(scaled - 0.5) * step, 2)


def _territory_cell_id_from_lat_lon(lat: float, lon: float, step: float = TERRITORY_GRID_DEG) -> str:
    lat_center = _round_to_grid(lat, step)
    lon_center = _round_to_grid(lon, step)
    return f"cell-{lat_center:+05.2f}_{lon_center:+06.2f}"


def _parse_territory_cell_id(cell_id: str) -> tuple[float, float] | None:
    text = str(cell_id or "").strip()
    if not text.startswith("cell-"):
        return None
    try:
        lat_raw, lon_raw = text[5:].split("_", 1)
        return float(lat_raw), float(lon_raw)
    except Exception:
        return None


def _service_key_from_layer_key(layer_key: str) -> str | None:
    key = str(layer_key or "").strip().lower()
    if key == "eau_aep":
        return "eau_aep"
    if key == "eau_eu":
        return "eau_eu"
    if key in {
        "elec_grid_0p1deg",
        "elec_bt_aerien",
        "elec_bt_souterrain",
        "elec_hta_aerien",
        "elec_hta_souterrain",
    }:
        return "elec"
    return None


def _state_severity(value: str) -> int:
    return {
        "S0": 0,
        "S1": 1,
        "S2": 2,
        "S3": 3,
    }.get(str(value or "S0").upper(), 0)


def _population_by_cell(complete_analysis_payload: dict[str, Any]) -> dict[str, float]:
    rows = complete_analysis_payload.get("territory_results")
    if not isinstance(rows, list):
        return {}
    out: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        cell_id = str(row.get("territory_id") or "").strip()
        if not cell_id:
            continue
        out[cell_id] = _safe_float(row.get("population_total"))
    return out


def _territory_cell_geodataframe(population_by_cell: dict[str, float]) -> Any:
    gpd = _load_geopandas()
    from shapely.geometry import box

    half_step = TERRITORY_GRID_DEG / 2.0
    records: list[dict[str, Any]] = []
    for cell_id, population in population_by_cell.items():
        parsed = _parse_territory_cell_id(cell_id)
        if parsed is None:
            continue
        lat, lon = parsed
        records.append(
            {
                "territory_id": cell_id,
                "population_total": float(population),
                "geometry": box(lon - half_step, lat - half_step, lon + half_step, lat + half_step),
            }
        )
    if not records:
        return gpd.GeoDataFrame(columns=["territory_id", "population_total", "geometry"], geometry="geometry", crs="EPSG:4326")
    return gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:4326")


def _aligned_grid_edges(min_coord: float, max_coord: float, step: float) -> list[float]:
    start = math.floor(float(min_coord) / float(step)) * float(step)
    stop = math.ceil(float(max_coord) / float(step)) * float(step)
    edges: list[float] = []
    current = start
    while current <= stop + 1e-9:
        edges.append(round(current, 6))
        current += float(step)
    if len(edges) < 2:
        edges.append(round(start + float(step), 6))
    return edges


def _population_overlay_territory_payload(artifacts: AuxiliaryArtifacts, code: str = "glp") -> dict[str, Any] | None:
    if artifacts.population_overlays is None:
        return None
    territories = artifacts.population_overlays.payload.get("territories")
    if not isinstance(territories, list):
        return None
    for item in territories:
        if not isinstance(item, dict):
            continue
        if str(item.get("code") or "").strip().lower() == code:
            return item
    return None


def _build_population_grid_geodataframe(
    raster_path: str,
    *,
    bounds: dict[str, Any],
    cell_size_deg: float,
) -> Any:
    gpd = _load_geopandas()
    rasterio = _load_rasterio()
    import numpy as np
    from rasterio.windows import from_bounds
    from shapely.geometry import box

    west = _safe_float(bounds.get("west"))
    east = _safe_float(bounds.get("east"))
    south = _safe_float(bounds.get("south"))
    north = _safe_float(bounds.get("north"))
    lon_edges = _aligned_grid_edges(west, east, cell_size_deg)
    lat_edges = _aligned_grid_edges(south, north, cell_size_deg)

    records: list[dict[str, Any]] = []
    with rasterio.open(raster_path) as src:
        nodata = src.nodata
        for lat_idx in range(len(lat_edges) - 1):
            cell_south = lat_edges[lat_idx]
            cell_north = lat_edges[lat_idx + 1]
            for lon_idx in range(len(lon_edges) - 1):
                cell_west = lon_edges[lon_idx]
                cell_east = lon_edges[lon_idx + 1]
                window = from_bounds(cell_west, cell_south, cell_east, cell_north, src.transform)
                window = window.round_offsets().round_lengths()
                arr = src.read(1, window=window, masked=True)
                values = arr.compressed() if hasattr(arr, "compressed") else np.asarray(arr).ravel()
                if nodata is not None:
                    values = values[values != nodata]
                values = values[np.isfinite(values)] if values.size else values
                values = values[values > 0.0] if values.size else values
                population = float(values.sum()) if values.size else 0.0
                center_lat = round((cell_south + cell_north) / 2.0, 4)
                center_lon = round((cell_west + cell_east) / 2.0, 4)
                records.append(
                    {
                        "grid_cell_id": _territory_cell_id_from_lat_lon(center_lat, center_lon, cell_size_deg),
                        "population_total": population,
                        "center_lat": center_lat,
                        "center_lon": center_lon,
                        "geometry": box(cell_west, cell_south, cell_east, cell_north),
                    }
                )
    return gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:4326")


def _network_state_feature_cell_id(feature: Any) -> str | None:
    geometry = feature.get("geometry")
    if geometry is None:
        return None
    point = geometry.representative_point()
    if point is None or point.is_empty:
        return None
    return _territory_cell_id_from_lat_lon(point.y, point.x)


def _compute_population_state_analysis(artifacts: AuxiliaryArtifacts) -> dict[str, Any] | None:
    if not artifacts.network_states_path:
        return None
    population_by_cell = _population_by_cell(artifacts.complete_analysis.payload)
    if not population_by_cell:
        return None
    gdf = _load_geodataframe_cached(artifacts.network_states_path)
    if gdf.empty:
        return None
    if gdf.crs is None:
        gdf = gdf.set_crs(epsg=4326)
    gdf = gdf.to_crs(epsg=4326)

    scenarios = [scenario_key for scenario_key, _label in NETWORK_STATE_MATRIX_SCENARIOS]
    hazards = list(SUPPORTED_HAZARDS)
    column_keys = [column_key for column_key, _label, _class_keys in NETWORK_STATE_MATRIX_COLUMNS]
    service_states: dict[str, dict[str, dict[str, dict[str, str]]]] = {
        scenario: {hazard: {} for hazard in hazards} for scenario in scenarios
    }
    column_states: dict[str, dict[str, dict[str, dict[str, str]]]] = {
        scenario: {hazard: {column_key: {} for column_key in column_keys} for hazard in hazards} for scenario in scenarios
    }
    column_causes: dict[str, dict[str, dict[str, dict[str, str]]]] = {
        scenario: {hazard: {column_key: {} for column_key in column_keys} for hazard in hazards} for scenario in scenarios
    }
    column_layers = {column_key: set(class_keys) for column_key, _label, class_keys in NETWORK_STATE_MATRIX_COLUMNS}

    for row in gdf.itertuples(index=False):
        row_dict = row._asdict()
        cell_id = _network_state_feature_cell_id(row_dict)
        if not cell_id or cell_id not in population_by_cell:
            continue
        layer_key = str(row_dict.get("layer_key") or "").strip()
        service_key = _service_key_from_layer_key(layer_key)
        for scenario in scenarios:
            for hazard in hazards:
                state_code = str(row_dict.get(f"state_{scenario}_{hazard}") or "S0").upper()
                cause_code = str(row_dict.get(f"cause_{scenario}_{hazard}") or "").strip()
                if service_key:
                    service_bucket = service_states[scenario][hazard].setdefault(
                        cell_id,
                        {"elec": "S0", "eau_aep": "S0", "eau_eu": "S0"},
                    )
                    if _state_severity(state_code) > _state_severity(service_bucket.get(service_key, "S0")):
                        service_bucket[service_key] = state_code
                for column_key, layers in column_layers.items():
                    if layer_key not in layers and service_key not in layers:
                        continue
                    current = str(column_states[scenario][hazard][column_key].get(cell_id) or "S0").upper()
                    if _state_severity(state_code) > _state_severity(current):
                        column_states[scenario][hazard][column_key][cell_id] = state_code
                        column_causes[scenario][hazard][column_key][cell_id] = cause_code

    total_population = sum(max(0.0, float(value)) for value in population_by_cell.values())
    return {
        "population_by_cell": population_by_cell,
        "service_states": service_states,
        "column_states": column_states,
        "column_causes": column_causes,
        "total_population": total_population,
    }


def _population_outage_cause_shares_from_analysis(
    analysis: dict[str, Any] | None,
    scenario_key: str,
    hazard: str,
    column_key: str,
) -> dict[str, float] | None:
    if analysis is None:
        return None
    population_by_cell = analysis.get("population_by_cell")
    column_states = _dict_path_get(analysis, "column_states", scenario_key, hazard, column_key)
    column_causes = _dict_path_get(analysis, "column_causes", scenario_key, hazard, column_key)
    if not isinstance(population_by_cell, dict) or not isinstance(column_states, dict) or not isinstance(column_causes, dict):
        return None
    totals = {"direct": 0.0, "indirect": 0.0}
    for cell_id, population in population_by_cell.items():
        if str(column_states.get(cell_id) or "S0").upper() != "S3":
            continue
        cause_key = _canonical_outage_cause_key(column_causes.get(cell_id))
        if cause_key is None:
            continue
        totals[cause_key] += max(_safe_float(population), 0.0)
    denominator = sum(totals.values())
    if denominator <= 0.0:
        return None
    return {
        key: round((value / denominator) * 100.0, 4)
        for key, value in totals.items()
    }


def _population_outage_cause_shares_from_graph_inputs(
    artifacts: AuxiliaryArtifacts,
    scenario_key: str,
    hazard: str,
    column_key: str,
    class_keys: tuple[str, ...],
) -> dict[str, float] | None:
    inputs = _scientific_inputs_from_payload(artifacts.complete_analysis.payload)
    cause_by_scenario = inputs.get("outage_cause_by_scenario")
    if not isinstance(cause_by_scenario, dict):
        pml_inputs = artifacts.complete_analysis.payload.get("pml_network_graph_inputs")
        if isinstance(pml_inputs, dict):
            cause_by_scenario = pml_inputs.get("outage_cause_by_scenario")
    if not isinstance(cause_by_scenario, dict) and artifacts.scientific_web_summary is not None:
        summary_inputs = artifacts.scientific_web_summary.payload.get("scientific_graph_inputs")
        if isinstance(summary_inputs, dict):
            cause_by_scenario = summary_inputs.get("outage_cause_by_scenario")
    if not isinstance(cause_by_scenario, dict):
        return None

    scenario_block = cause_by_scenario.get(scenario_key) if isinstance(cause_by_scenario.get(scenario_key), dict) else {}
    hazard_block = scenario_block.get(hazard) if isinstance(scenario_block.get(hazard), dict) else {}
    if not isinstance(hazard_block, dict):
        return None

    if column_key == "elec":
        candidate_keys = tuple(key for key in hazard_block if str(key).startswith("elec_"))
    else:
        candidate_keys = class_keys
    totals = {"direct": 0.0, "indirect": 0.0}
    for class_key in candidate_keys:
        item = hazard_block.get(class_key) if isinstance(hazard_block.get(class_key), dict) else {}
        totals["direct"] += max(_safe_float(item.get("direct_damage_eur")), 0.0)
        indirect = max(_safe_float(item.get("indirect_damage_eur")), 0.0)
        if indirect <= 0.0:
            indirect = max(_safe_float(item.get("blocking_ouvrage_eur")), 0.0) + max(_safe_float(item.get("dysfunction_eur")), 0.0)
        totals["indirect"] += indirect
    denominator = sum(totals.values())
    if denominator <= 0.0:
        return None
    return {key: round((value / denominator) * 100.0, 4) for key, value in totals.items()}


def _network_outage_cause_shares_from_geojson(
    artifacts: AuxiliaryArtifacts,
    scenario_key: str,
    hazard: str,
    column_key: str,
    class_keys: tuple[str, ...],
) -> dict[str, float] | None:
    if not artifacts.network_states_path:
        return None
    gdf = _load_geodataframe_cached(artifacts.network_states_path)
    if gdf.empty:
        return None
    state_column = f"state_{scenario_key}_{hazard}"
    cause_column = f"cause_{scenario_key}_{hazard}"
    if state_column not in gdf.columns or cause_column not in gdf.columns or "layer_key" not in gdf.columns:
        return None
    class_key_set = set(class_keys)
    totals = {"direct": 0.0, "indirect": 0.0}
    for row in gdf.itertuples(index=False):
        row_dict = row._asdict()
        layer_key = str(row_dict.get("layer_key") or "").strip()
        service_key = _service_key_from_layer_key(layer_key)
        if layer_key not in class_key_set and service_key != column_key:
            continue
        if str(row_dict.get(state_column) or "S0").upper() != "S3":
            continue
        cause_key = _canonical_outage_cause_key(row_dict.get(cause_column))
        if cause_key is None:
            continue
        totals[cause_key] += 1.0
    denominator = sum(totals.values())
    if denominator <= 0.0:
        return None
    return {
        key: round((value / denominator) * 100.0, 4)
        for key, value in totals.items()
    }


def _compute_hotspot_population_state_analysis(
    artifacts: AuxiliaryArtifacts,
    *,
    cell_size_deg: float = HOTSPOT_GRID_DEG,
) -> dict[str, Any] | None:
    if not artifacts.network_states_path or not artifacts.population_raster_path:
        return None
    territory_payload = _population_overlay_territory_payload(artifacts, "glp")
    bounds = territory_payload.get("bounds") if isinstance(territory_payload, dict) and isinstance(territory_payload.get("bounds"), dict) else None
    if bounds is None:
        return None
    grid = _build_population_grid_geodataframe(artifacts.population_raster_path, bounds=bounds, cell_size_deg=cell_size_deg)
    if grid.empty:
        return None
    gdf = _load_geodataframe_cached(artifacts.network_states_path)
    if gdf.empty:
        return None
    if gdf.crs is None:
        gdf = gdf.set_crs(epsg=4326)
    gdf = gdf.to_crs(epsg=4326)
    centroids = grid[["grid_cell_id", "population_total", "geometry"]].copy()
    centroids["geometry"] = centroids.geometry.representative_point()
    gpd = _load_geopandas()
    joined = gpd.sjoin(centroids, gdf, how="left", predicate="within")
    if joined.empty:
        joined = gpd.sjoin(centroids, gdf, how="left", predicate="intersects")

    scenarios = [scenario_key for scenario_key, _label in NETWORK_STATE_MATRIX_SCENARIOS]
    hazards = list(SUPPORTED_HAZARDS)
    service_states: dict[str, dict[str, dict[str, dict[str, str]]]] = {
        scenario: {hazard: {} for hazard in hazards} for scenario in scenarios
    }
    for row in joined.itertuples(index=False):
        cell_id = str(getattr(row, "grid_cell_id", "") or "").strip()
        if not cell_id:
            continue
        service_key = _service_key_from_layer_key(getattr(row, "layer_key", ""))
        if not service_key:
            continue
        for scenario in scenarios:
            for hazard in hazards:
                state_code = str(getattr(row, f"state_{scenario}_{hazard}", "S0") or "S0").upper()
                bucket = service_states[scenario][hazard].setdefault(
                    cell_id,
                    {"elec": "S0", "eau_aep": "S0", "eau_eu": "S0"},
                )
                if _state_severity(state_code) > _state_severity(bucket.get(service_key, "S0")):
                    bucket[service_key] = state_code
    return {
        "grid": grid,
        "service_states": service_states,
        "cell_size_deg": cell_size_deg,
    }


def _build_population_overlay_map_payload(artifacts: AuxiliaryArtifacts, title: str) -> dict[str, Any] | None:
    if artifacts.territory != "guadeloupe" or artifacts.population_overlays is None:
        return None
    payload = artifacts.population_overlays.payload
    territories = payload.get("territories")
    if not isinstance(territories, list):
        return None
    territory_payload = next((item for item in territories if str(item.get("code") or "").strip().lower() == "glp"), None)
    if not isinstance(territory_payload, dict):
        return None
    overlay_rel = str(territory_payload.get("overlay") or "").strip()
    bounds = territory_payload.get("bounds") if isinstance(territory_payload.get("bounds"), dict) else {}
    if not overlay_rel or not bounds:
        return None
    overlay_path = POPULATION_OVERLAYS_PATH.parent / overlay_rel
    if not overlay_path.exists():
        return None
    raster_path = str(territory_payload.get("source_tif") or artifacts.population_raster_path or "").strip()
    local_scale_max = _safe_float(_dict_path_get(territory_payload, "stats", "max_people_per_pixel"), default=0.0)
    if local_scale_max <= 0.0:
        local_scale_max = _safe_float(_dict_path_get(payload, "meta", "scale", "max_people_per_pixel"), default=1.0)
    return {
        "type": "raster_overlay_map",
        "title": title,
        "overlay_path": str(overlay_path),
        "raster_path": raster_path,
        "bounds": {
            "south": _safe_float(bounds.get("south")),
            "north": _safe_float(bounds.get("north")),
            "west": _safe_float(bounds.get("west")),
            "east": _safe_float(bounds.get("east")),
        },
        "scale_max": local_scale_max,
        "scale_norm": "sqrt",
        "cmap_colors": list(POPULATION_OVERLAY_COLORS),
        "legend_title": "Population (pers./pixel)",
        "note": "WorldPop 2020 - overlay rasterisee de population.",
    }


def _build_population_hotspot_superplot_payload(
    artifacts: AuxiliaryArtifacts,
    title: str,
) -> dict[str, Any] | None:
    analysis = _compute_hotspot_population_state_analysis(artifacts, cell_size_deg=HOTSPOT_GRID_DEG)
    if analysis is None:
        return None
    base_grid = analysis["grid"]
    if base_grid.empty:
        return None
    service_states = analysis["service_states"]
    rows = [
        {"key": "storm", "label": "STORM"},
        {"key": "storm_cmcc", "label": "STORM_CMCC"},
    ]
    columns = [
        {"key": "rp10", "label": "RP10"},
        {"key": "rp50", "label": "RP50"},
        {"key": "rp100", "label": "RP100"},
        {"key": "rp1000", "label": "RP1000"},
    ]
    cells: list[list[dict[str, Any]]] = []
    max_value = 0.0
    for row in rows:
        row_payloads: list[dict[str, Any]] = []
        for column in columns:
            cell_states = _dict_path_get(service_states, column["key"], row["key"])
            if not isinstance(cell_states, dict):
                return None
            gdf = base_grid.copy()
            values: list[float] = []
            for grid_row in gdf.itertuples(index=False):
                states = cell_states.get(
                    str(grid_row.grid_cell_id),
                    {"elec": "S0", "eau_aep": "S0", "eau_eu": "S0"},
                )
                affected = any(str(states.get(key) or "S0").upper() != "S0" for key in PUBLIC_SERVICE_KEYS)
                value = float(grid_row.population_total) if affected else 0.0
                max_value = max(max_value, value)
                values.append(value)
            gdf["affected_population"] = values
            row_payloads.append(
                {
                    "gdf": gdf,
                    "value_column": "affected_population",
                }
            )
        cells.append(row_payloads)
    return {
        "type": "choropleth_map_grid",
        "title": title,
        "rows": rows,
        "columns": columns,
        "cells": cells,
        "cmap_colors": ["#fff7bc", "#fee391", "#fec44f", "#fe9929", "#ec7014", "#cc4c02", "#993404"],
        "legend_title": f"Population affectee (pers.) - maille {HOTSPOT_GRID_DEG:.2f}°",
        "vmin": 0.0,
        "vmax": max(max_value, 1.0),
        "edgecolor": "#ffffff",
        "line_width": 0.2,
        "note": (
            f"Population affectee tous reseaux confondus. Resolution de visualisation: maille reguliere {HOTSPOT_GRID_DEG:.2f}° "
            f"(plus fine que la maille territoriale 0.20° du complete analysis)."
        ),
    }


def _build_hydraulic_population_importance_payload(
    artifacts: AuxiliaryArtifacts,
    title: str,
) -> dict[str, Any] | None:
    if not artifacts.hydraulic_zones_path or not artifacts.population_raster_path:
        return None
    zones = _load_geodataframe_layer_cached(artifacts.hydraulic_zones_path, layer="hydraulic_zones")
    if zones.empty:
        return None
    zones = zones[zones["network_kind"].astype(str).str.upper() == "AEP"].copy()
    if zones.empty or "zone_uid" not in zones.columns:
        return None
    if zones.crs is None:
        raise RuntimeError("Hydraulic zones layer has no CRS")
    rasterio = _load_rasterio()
    import numpy as np
    from shapely.geometry import mapping

    dissolved = zones[["zone_uid", "geometry"]].dissolve(by="zone_uid", as_index=False)
    metrics: dict[str, float] = {}
    with rasterio.open(artifacts.population_raster_path) as src:
        dissolved_for_sum = dissolved.to_crs(src.crs) if src.crs is not None else dissolved
        nodata = src.nodata
        for row in dissolved_for_sum.itertuples(index=False):
            geometry = row.geometry
            if geometry is None or geometry.is_empty:
                metrics[str(row.zone_uid)] = 0.0
                continue
            masked, _transform = rasterio.mask.mask(src, [mapping(geometry)], crop=True, filled=False)
            band = masked[0]
            values = band.compressed() if hasattr(band, "compressed") else np.asarray(band).ravel()
            if nodata is not None:
                values = values[values != nodata]
            if values.size == 0:
                metrics[str(row.zone_uid)] = 0.0
                continue
            values = values[np.isfinite(values)]
            values = values[values > 0.0]
            metrics[str(row.zone_uid)] = float(values.sum()) if values.size else 0.0
    zones = zones.copy()
    zones["dependent_population"] = zones["zone_uid"].map(lambda value: float(metrics.get(str(value), 0.0)))
    return {
        "type": "choropleth_map",
        "title": title,
        "gdf": zones,
        "value_column": "dependent_population",
        "cmap_colors": ["#fff7bc", "#fee391", "#fec44f", "#fb923c", "#ef4444", "#b91c1c"],
        "legend_title": "Population dependante (pers.)",
        "edgecolor": "#ffffff",
        "line_width": 0.35,
        "note": "Importance des zonages hydrauliques AEP - population totale couverte par zone logique.",
    }


def _damage_zone_family_from_class_key(class_key: Any) -> str | None:
    key = str(class_key or "").strip().lower()
    for family_key, class_keys in DAMAGE_ZONE_FAMILY_CLASS_KEYS.items():
        if key in class_keys:
            return family_key
    return None


def _damage_zone_breakdown_class_from_asset_type(asset_type: Any) -> str:
    key = str(asset_type or "").strip().lower()
    if key == "eau_aep_cana":
        return "eau_aep"
    if key == "eau_eu_cana":
        return "eau_eu"
    if key.startswith("eau_aep_ouvrage_"):
        return "eau_aep_ouvrages"
    return key


def _damage_zone_data_is_complete(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    for scenario_key, _scenario_label in DAMAGE_ZONE_SCENARIOS:
        scenario_block = data.get(scenario_key) if isinstance(data.get(scenario_key), dict) else {}
        hazard_block = scenario_block.get(DAMAGE_ZONE_HAZARD) if isinstance(scenario_block.get(DAMAGE_ZONE_HAZARD), dict) else {}
        for family_key in DAMAGE_ZONE_FAMILY_ORDER:
            if not isinstance(hazard_block.get(family_key), list):
                return False
    return True


def _damage_zone_graph_input_data(artifacts: AuxiliaryArtifacts) -> dict[str, Any] | None:
    payloads = []
    if artifacts.scientific_web_summary is not None:
        payloads.append(artifacts.scientific_web_summary.payload)
    payloads.append(artifacts.complete_analysis.payload)
    for payload in payloads:
        graph_inputs = _scientific_inputs_from_payload(payload)
        damage_zones = graph_inputs.get("damage_zones_by_scenario") if isinstance(graph_inputs, dict) else None
        if _damage_zone_data_is_complete(damage_zones):
            return damage_zones
    return None


def _feature_geometry_cell_lookup(payload: dict[str, Any]) -> dict[str, str]:
    feature_collection = payload.get("input_features_geojson") if isinstance(payload.get("input_features_geojson"), dict) else {}
    features = feature_collection.get("features") if isinstance(feature_collection.get("features"), list) else []
    if not features:
        return {}
    try:
        from shapely.geometry import shape
    except Exception:
        return {}
    lookup: dict[str, str] = {}
    for feature in features:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        asset_id = str(props.get("asset_id") or props.get("feature_id") or feature.get("id") or "").strip()
        geometry_payload = feature.get("geometry")
        if not asset_id or not isinstance(geometry_payload, dict):
            continue
        try:
            geometry = shape(geometry_payload)
            if geometry is None or geometry.is_empty:
                continue
            point = geometry.representative_point()
            lookup[asset_id] = _territory_cell_id_from_lat_lon(point.y, point.x, ELECTRIC_DECISION_GRID_DEG)
        except Exception:
            continue
    return lookup


def _damage_zone_unit_id_from_asset_row(row: dict[str, Any], family_key: str, feature_cell_lookup: dict[str, str]) -> str:
    if family_key in {"aep", "eu"}:
        return str(row.get("service_feature_id") or row.get("zone_component_key") or row.get("zone_uid") or "").strip()
    asset_id = str(row.get("asset_id") or row.get("feature_id") or "").strip()
    return str(feature_cell_lookup.get(asset_id) or "").strip()


def _damage_zone_hazard_weight(row: dict[str, Any], hazard: str) -> float:
    if hazard == "storm_cmcc":
        direct = _safe_float(row.get("eai_cmcc_direct_eur"), default=0.0)
    else:
        direct = _safe_float(row.get("eai_storm_direct_eur"), default=0.0)
    if direct > 0.0:
        return direct
    return max(_safe_float(row.get("exposure_eur"), default=0.0), 0.0)


def _damage_zone_breakdown_direct_totals(graph_inputs: dict[str, Any]) -> dict[str, dict[str, dict[str, float]]]:
    out: dict[str, dict[str, dict[str, float]]] = {}
    breakdowns = graph_inputs.get("damage_breakdown_by_scenario") if isinstance(graph_inputs.get("damage_breakdown_by_scenario"), dict) else {}
    for scenario_key, _scenario_label in DAMAGE_ZONE_SCENARIOS:
        out[scenario_key] = {}
        scenario_block = breakdowns.get(scenario_key) if isinstance(breakdowns.get(scenario_key), dict) else {}
        for hazard in SUPPORTED_HAZARDS:
            totals: dict[str, float] = {}
            rows = scenario_block.get(hazard) if isinstance(scenario_block.get(hazard), list) else []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                class_key = str(row.get("class_key") or "").strip()
                if class_key:
                    totals[class_key] = totals.get(class_key, 0.0) + max(_safe_float(row.get("direct_damage_eur")), 0.0)
            out[scenario_key][hazard] = totals
    return out


def _approximate_damage_zone_data_from_assets(artifacts: AuxiliaryArtifacts) -> dict[str, Any] | None:
    graph_inputs = _scientific_inputs_from_payload(artifacts.complete_analysis.payload)
    if not isinstance(graph_inputs, dict) or not isinstance(graph_inputs.get("damage_breakdown_by_scenario"), dict):
        return None
    asset_results = _complete_asset_results(artifacts)
    if not asset_results:
        return None

    feature_cell_lookup = _feature_geometry_cell_lookup(artifacts.complete_analysis.payload)
    direct_totals = _damage_zone_breakdown_direct_totals(graph_inputs)
    base_rows: dict[tuple[str, str], dict[str, Any]] = {}
    weights: dict[str, dict[str, dict[tuple[str, str], float]]] = {hazard: {} for hazard in SUPPORTED_HAZARDS}

    for row in asset_results:
        class_key = _damage_zone_breakdown_class_from_asset_type(row.get("asset_type"))
        family_key = _damage_zone_family_from_class_key(class_key)
        if family_key is None:
            continue
        unit_id = _damage_zone_unit_id_from_asset_row(row, family_key, feature_cell_lookup)
        if not unit_id:
            continue
        bucket_key = (family_key, unit_id)
        exposure = max(_safe_float(row.get("exposure_eur")), 0.0)
        base_bucket = base_rows.setdefault(
            bucket_key,
            {
                "family_key": family_key,
                "family_label": DAMAGE_ZONE_FAMILY_LABELS.get(family_key, family_key.upper()),
                "network_kind": DAMAGE_ZONE_FAMILY_NETWORK_KIND.get(family_key, ""),
                "spatial_unit_kind": "fixed_grid_0p1deg" if family_key == "elec" else "hydraulic_zone_component",
                "unit_id": unit_id,
                "zone_component_key": unit_id if family_key in {"aep", "eu"} else "",
                "zone_uid": str(row.get("zone_uid") or unit_id).strip(),
                "zone_label": str(row.get("zone_uid") or row.get("asset_label") or unit_id).strip(),
                "exposure_eur": 0.0,
                "asset_count": 0,
                "point_count": 0,
                "source_method": "approximate_asset_weighted_backfill",
            },
        )
        base_bucket["exposure_eur"] += exposure
        base_bucket["asset_count"] += 1
        for hazard in SUPPORTED_HAZARDS:
            weight = _damage_zone_hazard_weight(row, hazard)
            weights.setdefault(hazard, {}).setdefault(class_key, {})
            weights[hazard][class_key][bucket_key] = weights[hazard][class_key].get(bucket_key, 0.0) + weight

    if not base_rows:
        return None

    out: dict[str, dict[str, dict[str, list[dict[str, Any]]]]] = {
        scenario_key: {hazard: {family_key: [] for family_key in DAMAGE_ZONE_FAMILY_ORDER} for hazard in SUPPORTED_HAZARDS}
        for scenario_key, _scenario_label in DAMAGE_ZONE_SCENARIOS
    }
    for scenario_key, _scenario_label in DAMAGE_ZONE_SCENARIOS:
        for hazard in SUPPORTED_HAZARDS:
            direct_by_bucket = {bucket_key: 0.0 for bucket_key in base_rows}
            for class_key, class_total in direct_totals.get(scenario_key, {}).get(hazard, {}).items():
                family_key = _damage_zone_family_from_class_key(class_key)
                if family_key is None:
                    continue
                class_weights = weights.get(hazard, {}).get(class_key, {})
                denominator = sum(max(float(value), 0.0) for value in class_weights.values())
                if denominator <= 0.0:
                    class_bucket_keys = [
                        bucket_key
                        for bucket_key, base_bucket in base_rows.items()
                        if bucket_key[0] == family_key and _safe_float(base_bucket.get("exposure_eur")) > 0.0
                    ]
                    denominator = sum(_safe_float(base_rows[bucket_key].get("exposure_eur")) for bucket_key in class_bucket_keys)
                    class_weights = {
                        bucket_key: _safe_float(base_rows[bucket_key].get("exposure_eur"))
                        for bucket_key in class_bucket_keys
                    }
                if denominator <= 0.0:
                    continue
                for bucket_key, weight in class_weights.items():
                    direct_by_bucket[bucket_key] += max(_safe_float(class_total), 0.0) * max(float(weight), 0.0) / denominator

            for bucket_key, base_bucket in base_rows.items():
                family_key, _unit_id = bucket_key
                row = dict(base_bucket)
                row["exposure_eur"] = round(_safe_float(row.get("exposure_eur")), 2)
                row["direct_damage_eur"] = round(max(float(direct_by_bucket.get(bucket_key, 0.0)), 0.0), 2)
                out[scenario_key][hazard][family_key].append(row)

    for scenario_key, _scenario_label in DAMAGE_ZONE_SCENARIOS:
        for hazard in SUPPORTED_HAZARDS:
            for family_key in DAMAGE_ZONE_FAMILY_ORDER:
                out[scenario_key][hazard][family_key] = sorted(
                    out[scenario_key][hazard][family_key],
                    key=lambda row: (
                        -_safe_float(row.get("direct_damage_eur")),
                        str(row.get("unit_id") or ""),
                    ),
                )
    return out


def _damage_zone_data_from_artifacts(artifacts: AuxiliaryArtifacts) -> tuple[dict[str, Any], str] | None:
    graph_input_data = _damage_zone_graph_input_data(artifacts)
    if graph_input_data is not None:
        return graph_input_data, "postprocess_exact_point_losses"
    approximate = _approximate_damage_zone_data_from_assets(artifacts)
    if approximate is not None:
        return approximate, "approximate_asset_weighted_backfill"
    return None


def _damage_zone_rows(
    damage_zone_data: dict[str, Any],
    *,
    scenario_key: str,
    hazard: str,
    family_key: str,
) -> list[dict[str, Any]]:
    scenario_block = damage_zone_data.get(scenario_key) if isinstance(damage_zone_data.get(scenario_key), dict) else {}
    hazard_block = scenario_block.get(hazard) if isinstance(scenario_block.get(hazard), dict) else {}
    rows = hazard_block.get(family_key) if isinstance(hazard_block.get(family_key), list) else []
    return [row for row in rows if isinstance(row, dict)]


def _damage_zone_row_metric(rows: list[dict[str, Any]]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for row in rows:
        unit_id = str(row.get("unit_id") or row.get("zone_component_key") or row.get("zone_uid") or "").strip()
        if not unit_id:
            continue
        metrics[unit_id] = metrics.get(unit_id, 0.0) + max(_safe_float(row.get("direct_damage_eur")), 0.0)
    return metrics


def _build_damage_zone_gdf(
    artifacts: AuxiliaryArtifacts,
    *,
    family_key: str,
    rows: list[dict[str, Any]],
) -> Any | None:
    gpd = _load_geopandas()
    metrics = _damage_zone_row_metric(rows)
    if family_key in {"aep", "eu"}:
        if not artifacts.hydraulic_zones_path:
            return None
        zones = _load_geodataframe_layer_cached(artifacts.hydraulic_zones_path, layer="hydraulic_zones")
        if zones.empty or "network_kind" not in zones.columns:
            return None
        network_kind = DAMAGE_ZONE_FAMILY_NETWORK_KIND[family_key]
        zones = zones[zones["network_kind"].fillna("").astype(str).str.upper() == network_kind].copy()
        if zones.empty:
            return None
        join_column = "zone_component_key" if "zone_component_key" in zones.columns else "zone_uid"
        zones["damage_zone_unit_id"] = zones[join_column].fillna("").astype(str)
        zones["direct_damage_eur"] = zones["damage_zone_unit_id"].map(lambda value: metrics.get(str(value), 0.0))
        return zones

    records: list[dict[str, Any]] = []
    if artifacts.network_states_path:
        states = _load_geodataframe_cached(artifacts.network_states_path)
        if not states.empty and "layer_key" in states.columns and "feature_id" in states.columns:
            states = states[states["layer_key"].fillna("").astype(str) == "elec_grid_0p1deg"].copy()
            if not states.empty:
                states["damage_zone_unit_id"] = states["feature_id"].fillna("").astype(str)
                states["direct_damage_eur"] = states["damage_zone_unit_id"].map(lambda value: metrics.get(str(value), 0.0))
                return states

    for unit_id, damage in metrics.items():
        geometry = _electric_decision_cell_geometry(unit_id)
        if geometry is None or getattr(geometry, "is_empty", False):
            continue
        records.append(
            {
                "damage_zone_unit_id": unit_id,
                "direct_damage_eur": damage,
                "geometry": geometry,
            }
        )
    if not records:
        return None
    return gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:4326")


def _damage_zone_common_vmax(cells: dict[tuple[str, str], dict[str, Any]]) -> float:
    max_value = 0.0
    for cell in cells.values():
        gdf = cell.get("gdf")
        value_column = str(cell.get("value_column") or "")
        if gdf is None or not value_column or value_column not in getattr(gdf, "columns", []):
            continue
        try:
            max_value = max(max_value, _safe_float(gdf[value_column].max()))
        except Exception:
            continue
    return max(max_value, 1.0)


def _combined_damage_zone_extent_gdf(cells_by_hazard: dict[str, dict[tuple[str, str], dict[str, Any]]]) -> Any | None:
    gpd = _load_geopandas()
    geometries: list[Any] = []
    for cells in cells_by_hazard.values():
        for cell in cells.values():
            gdf = cell.get("gdf")
            if gdf is None or getattr(gdf, "empty", True):
                continue
            if gdf.crs is None:
                gdf = gdf.set_crs(epsg=4326)
            gdf = gdf.to_crs(epsg=4326)
            geometries.extend(
                geometry
                for geometry in list(gdf.geometry)
                if geometry is not None and not getattr(geometry, "is_empty", False)
            )
    if not geometries:
        return None
    return gpd.GeoDataFrame(geometry=geometries, crs="EPSG:4326")


def _build_damage_zone_output_specs(
    artifacts: AuxiliaryArtifacts,
    territory: str,
) -> tuple[list[tuple[str, dict[str, Any]]], list[str]]:
    data_with_source = _damage_zone_data_from_artifacts(artifacts)
    if data_with_source is None:
        return [], [_warning_message(territory, DAMAGE_ZONE_OUTPUT_DIRNAME, "missing damage_zones_by_scenario and asset backfill inputs")]
    damage_zone_data, source_method = data_with_source
    cells_by_hazard: dict[str, dict[tuple[str, str], dict[str, Any]]] = {
        hazard: {}
        for hazard in ("storm", "storm_cmcc")
    }
    warnings: list[str] = []
    for hazard in cells_by_hazard:
        for family_key in DAMAGE_ZONE_FAMILY_ORDER:
            for scenario_key, _scenario_label in DAMAGE_ZONE_SCENARIOS:
                rows = _damage_zone_rows(
                    damage_zone_data,
                    scenario_key=scenario_key,
                    hazard=hazard,
                    family_key=family_key,
                )
                gdf = _build_damage_zone_gdf(artifacts, family_key=family_key, rows=rows)
                if gdf is None or getattr(gdf, "empty", True):
                    warnings.append(_warning_message(territory, f"{hazard}_{family_key}_{scenario_key}", "missing spatial units for damage-zone map"))
                    continue
                cells_by_hazard[hazard][(family_key, scenario_key)] = {
                    "gdf": gdf,
                    "value_column": "direct_damage_eur",
                }
    if not any(cells_by_hazard.values()):
        return [], warnings or [_warning_message(territory, DAMAGE_ZONE_OUTPUT_DIRNAME, "no damage-zone maps could be built")]

    all_cells: dict[tuple[str, str], dict[str, Any]] = {}
    for hazard, cells in cells_by_hazard.items():
        for (family_key, scenario_key), cell in cells.items():
            all_cells[(f"{hazard}:{family_key}", scenario_key)] = cell
    vmax = _damage_zone_common_vmax(all_cells)
    extent_gdf = _combined_damage_zone_extent_gdf(cells_by_hazard)
    source_label = "pertes directes exactes du post-run" if source_method == "postprocess_exact_point_losses" else "backfill approxime pondere par EAI/exposition"
    note = f"Dommages directs STORM par zonage. Source: {source_label}. Echelle commune 0 - {_format_compact_eur(vmax)}."
    specs: list[tuple[str, dict[str, Any]]] = []
    storm_cells = cells_by_hazard.get(DAMAGE_ZONE_HAZARD, {})
    for family_key in DAMAGE_ZONE_FAMILY_ORDER:
        for scenario_key, scenario_label in DAMAGE_ZONE_SCENARIOS:
            cell = storm_cells.get((family_key, scenario_key))
            if cell is None:
                continue
            title = f"{territory_label(territory)} - Dommages directs {DAMAGE_ZONE_FAMILY_LABELS[family_key]} {scenario_label}"
            specs.append(
                (
                    f"dommages_directs_zonages_{family_key}_{scenario_key}.png",
                    {
                        "type": "choropleth_map",
                        "title": title,
                        "gdf": cell["gdf"],
                        "value_column": "direct_damage_eur",
                        "cmap_colors": list(DAMAGE_ZONE_MAP_COLORS),
                        "legend_title": "Dommages directs (EUR)",
                        "edgecolor": "#ffffff",
                        "line_width": 0.35 if family_key in {"aep", "eu"} else 0.28,
                        "vmin": 0.0,
                        "vmax": vmax,
                        "extent_gdf": extent_gdf,
                        "fixed_canvas": True,
                        "note": note,
                    },
                )
            )

    for hazard, file_name in (
        ("storm", "superplot_dommages_directs_zonages.png"),
        ("storm_cmcc", "superplot_dommages_directs_zonages_storm_cmcc.png"),
    ):
        hazard_cells = cells_by_hazard.get(hazard, {})
        if not hazard_cells:
            continue
        grid_cells: list[list[dict[str, Any]]] = []
        for family_key in DAMAGE_ZONE_FAMILY_ORDER:
            row_cells: list[dict[str, Any]] = []
            for scenario_key, _scenario_label in DAMAGE_ZONE_SCENARIOS:
                row_cells.append(hazard_cells.get((family_key, scenario_key), {}))
            grid_cells.append(row_cells)
        hazard_label = HAZARD_LABELS.get(hazard, hazard.upper())
        specs.append(
            (
                file_name,
                {
                    "type": "choropleth_map_grid",
                    "title": f"{territory_label(territory)} - Dommages directs par zonage {hazard_label}",
                    "rows": [
                        {"key": family_key, "label": DAMAGE_ZONE_FAMILY_LABELS[family_key]}
                        for family_key in DAMAGE_ZONE_FAMILY_ORDER
                    ],
                    "columns": [
                        {"key": scenario_key, "label": scenario_label}
                        for scenario_key, scenario_label in DAMAGE_ZONE_SCENARIOS
                    ],
                    "cells": grid_cells,
                    "cmap_colors": list(DAMAGE_ZONE_MAP_COLORS),
                    "legend_title": "Dommages directs (EUR)",
                    "edgecolor": "#ffffff",
                    "line_width": 0.22,
                    "vmin": 0.0,
                    "vmax": vmax,
                    "extent_gdf": extent_gdf,
                    "note": f"Dommages directs {hazard_label} par zonage. Source: {source_label}. Echelle commune 0 - {_format_compact_eur(vmax)}.",
                },
            )
        )
    return specs, warnings


def _population_decision_run_id_from_artifacts(artifacts: AuxiliaryArtifacts) -> str | None:
    for part in reversed(Path(artifacts.complete_analysis.payload_path).parts):
        cleaned = str(part).strip()
        if len(cleaned) == 15 and cleaned[8] == "_" and cleaned.replace("_", "").isdigit():
            return cleaned
    run_id = str(
        _dict_path_get(artifacts.complete_analysis.payload, "meta", "run_id")
        or artifacts.complete_analysis.payload.get("run_id")
        or ""
    ).strip()
    return run_id or None


def _population_decision_existing_csv_path(artifacts: AuxiliaryArtifacts) -> Path | None:
    run_id = _population_decision_run_id_from_artifacts(artifacts)
    if not run_id:
        return None
    path = DEFAULT_OUTPUT_ROOT / run_id / "tables" / "guadeloupe_tableau_synthese_zones_population_storm.csv"
    return path if path.exists() else None


def _read_population_decision_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _population_decision_source_rows(artifacts: AuxiliaryArtifacts) -> list[dict[str, str]]:
    if artifacts.territory != "guadeloupe":
        return []
    if artifacts.scientific_web_summary is not None and artifacts.network_states_path and artifacts.hydraulic_zones_path:
        return build_population_decision_rows(
            artifacts.complete_analysis.payload,
            artifacts.scientific_web_summary.payload,
            Path(artifacts.network_states_path),
            Path(artifacts.hydraulic_zones_path),
        )
    existing_csv = _population_decision_existing_csv_path(artifacts)
    if existing_csv is not None:
        return _read_population_decision_csv(existing_csv)
    return []


def _population_decision_population(row: dict[str, Any]) -> float:
    return max(_safe_float(row.get("population_potentiellement_affectee")), 0.0)


def _population_decision_failure_kind(row: dict[str, Any]) -> str:
    basis = str(row.get("state_basis") or "").strip().lower()
    if "mixed" in basis or ("blocking_asset" in basis and "direct" in basis):
        return "mixed"
    if "blocking_asset" in basis:
        return "asset"
    return "network"


def _population_decision_failure_symbol(row: dict[str, Any]) -> str:
    return POPULATION_DECISION_FAILURE_SYMBOLS[_population_decision_failure_kind(row)]


def _population_decision_short_zone_label(row: dict[str, Any]) -> str:
    label = str(row.get("zone_principale") or row.get("service_unit_id") or "").strip()
    prefixes = (
        "AEP - ",
        "EU - ",
        "Électricité - ",
        "Electricité - ",
        "Electricite - ",
    )
    for prefix in prefixes:
        if label.startswith(prefix):
            return label[len(prefix) :].strip()
    return label


def _format_population_decision_label(value: Any) -> str:
    numeric = _safe_float(value)
    if numeric >= 100_000.0:
        return f"{numeric / 1000.0:.0f} k"
    if numeric >= 10_000.0:
        return f"{numeric / 1000.0:.1f} k".replace(".", ",")
    rounded = int(round(numeric / 100.0) * 100)
    return f"{rounded:,}".replace(",", " ")


def _select_population_decision_rows(rows: list[dict[str, str]], top_n: int = 5) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    for period in POPULATION_DECISION_PERIODS:
        period_rows = [row for row in rows if str(row.get("periode") or "").strip().upper() == period]
        for service in POPULATION_DECISION_SERVICES:
            service_rows = [
                row
                for row in period_rows
                if str(row.get("service") or "").strip() == service
                and _population_decision_population(row) > 0.0
                and str(row.get("etat") or "").strip().upper() != "S0"
            ]
            selected.extend(
                sorted(
                    service_rows,
                    key=lambda row: (
                        -_population_decision_population(row),
                        str(row.get("zone_principale") or ""),
                    ),
                )[:top_n]
            )
    return selected


def _build_population_decision_bar_payload(
    artifacts: AuxiliaryArtifacts,
    title: str,
) -> dict[str, Any] | None:
    rows = _select_population_decision_rows(_population_decision_source_rows(artifacts), top_n=5)
    if not rows:
        return None
    chart_rows = []
    for row in rows:
        service = str(row.get("service") or "").strip()
        if service not in POPULATION_DECISION_SERVICE_LABELS:
            continue
        population = _population_decision_population(row)
        chart_rows.append(
            {
                "period": str(row.get("periode") or "").strip().upper(),
                "service": service,
                "service_label": POPULATION_DECISION_SERVICE_LABELS[service],
                "zone_label": _population_decision_short_zone_label(row),
                "zone_principale": str(row.get("zone_principale") or "").strip(),
                "population": population,
                "population_label": _format_population_decision_label(population),
                "failure_kind": _population_decision_failure_kind(row),
                "failure_symbol": _population_decision_failure_symbol(row),
                "service_unit_id": str(row.get("service_unit_id") or "").strip(),
            }
        )
    if not chart_rows:
        return None
    return {
        "type": "population_decision_grouped_bar",
        "title": title,
        "periods": list(POPULATION_DECISION_PERIODS),
        "services": [
            {
                "key": service,
                "label": POPULATION_DECISION_SERVICE_LABELS[service],
                "color": POPULATION_DECISION_SERVICE_COLORS[service],
            }
            for service in POPULATION_DECISION_SERVICES
        ],
        "rows": chart_rows,
        "ylabel": "Population potentiellement affectee",
        "note": (
            "Top 5 zones par service et temps de retour STORM. Les populations ne sont pas additives: "
            "une meme population peut dependre de plusieurs services."
        ),
    }


def _population_decision_geometry_union(gdf: Any) -> Any:
    geometry = getattr(gdf, "geometry", None)
    if geometry is None:
        return None
    if hasattr(geometry, "union_all"):
        return geometry.union_all()
    return geometry.unary_union


def _geodataframe_string_series(gdf: Any, column: str, default: str = "") -> Any:
    if column in getattr(gdf, "columns", []):
        return gdf[column].fillna("").astype(str)
    return gdf.geometry.map(lambda _geometry: default)


def _electric_decision_cell_geometry(cell_id: str) -> Any | None:
    parsed = _parse_territory_cell_id(cell_id)
    if parsed is None:
        return None
    from shapely.geometry import box

    lat, lon = parsed
    half_step = ELECTRIC_DECISION_GRID_DEG / 2.0
    return box(lon - half_step, lat - half_step, lon + half_step, lat + half_step)


def _dedupe_population_decision_map_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    best_by_key: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        key = (str(row.get("service") or ""), str(row.get("service_unit_id") or ""))
        if not key[0] or not key[1]:
            continue
        current = best_by_key.get(key)
        if current is None or _population_decision_population(row) > _population_decision_population(current):
            best_by_key[key] = row
    return sorted(
        best_by_key.values(),
        key=lambda row: (
            POPULATION_DECISION_SERVICES.index(str(row.get("service") or "")),
            -_population_decision_population(row),
            str(row.get("zone_principale") or ""),
        ),
    )


def _build_population_decision_zone_map_payload(
    artifacts: AuxiliaryArtifacts,
    title: str,
) -> dict[str, Any] | None:
    rows = _dedupe_population_decision_map_rows(
        _select_population_decision_rows(_population_decision_source_rows(artifacts), top_n=5)
    )
    if not rows:
        return None

    gpd = _load_geopandas()
    records: list[dict[str, Any]] = []

    zones = None
    if artifacts.hydraulic_zones_path:
        zones = _load_geodataframe_layer_cached(artifacts.hydraulic_zones_path, layer="hydraulic_zones")
        if zones.crs is None:
            zones = zones.set_crs(epsg=4326)
        zones = zones.to_crs(epsg=4326)

    network_states = None
    if artifacts.network_states_path:
        network_states = _load_geodataframe_cached(artifacts.network_states_path)
        if network_states.crs is None:
            network_states = network_states.set_crs(epsg=4326)
        network_states = network_states.to_crs(epsg=4326)

    for row in rows:
        service = str(row.get("service") or "").strip()
        service_unit_id = str(row.get("service_unit_id") or "").strip()
        if not service or not service_unit_id:
            continue
        geometry = None
        if service in {"eau_aep", "eau_eu"} and zones is not None and not zones.empty:
            service_kind = "AEP" if service == "eau_aep" else "EU"
            zone_component_keys = _geodataframe_string_series(zones, "zone_component_key")
            zone_uids = _geodataframe_string_series(zones, "zone_uid")
            network_kinds = _geodataframe_string_series(zones, "network_kind", service_kind).str.upper()
            matches = zones[
                (
                    (zone_component_keys == service_unit_id)
                    | (zone_uids == service_unit_id)
                )
                & (network_kinds == service_kind)
            ].copy()
            if not matches.empty:
                geometry = _population_decision_geometry_union(matches)
        elif service == "elec":
            if network_states is not None and not network_states.empty:
                layer_keys = _geodataframe_string_series(network_states, "layer_key")
                feature_ids = _geodataframe_string_series(network_states, "feature_id")
                matches = network_states[
                    (layer_keys == "elec_grid_0p1deg")
                    & (feature_ids == service_unit_id)
                ].copy()
                if not matches.empty:
                    geometry = _population_decision_geometry_union(matches)
            if geometry is None or getattr(geometry, "is_empty", False):
                geometry = _electric_decision_cell_geometry(service_unit_id)

        if geometry is None or getattr(geometry, "is_empty", False):
            continue
        records.append(
            {
                "service": service,
                "service_label": POPULATION_DECISION_SERVICE_LABELS.get(service, service),
                "service_unit_id": service_unit_id,
                "zone_label": _population_decision_short_zone_label(row),
                "population": _population_decision_population(row),
                "color": POPULATION_DECISION_SERVICE_COLORS.get(service, "#64748b"),
                "geometry": geometry,
            }
        )

    if not records:
        return None
    return {
        "type": "population_decision_zone_map",
        "title": title,
        "gdf": gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:4326"),
        "services": [
            {
                "key": service,
                "label": POPULATION_DECISION_SERVICE_LABELS[service],
                "color": POPULATION_DECISION_SERVICE_COLORS[service],
            }
            for service in POPULATION_DECISION_SERVICES
        ],
        "note": "Zones uniques reprises du graphe decisionnel population STORM; labels dedupliques par service et unite.",
    }


def _graph_population_state_distribution(artifacts: AuxiliaryArtifacts) -> dict[str, Any]:
    inputs = _scientific_inputs_from_payload(artifacts.complete_analysis.payload)
    distribution = inputs.get("social_population_state_distribution_by_scenario")
    if isinstance(distribution, dict) and distribution:
        return distribution
    if artifacts.scientific_web_summary is not None:
        summary_inputs = artifacts.scientific_web_summary.payload.get("scientific_graph_inputs")
        if isinstance(summary_inputs, dict):
            distribution = summary_inputs.get("social_population_state_distribution_by_scenario")
            if isinstance(distribution, dict) and distribution:
                return distribution
        distribution = _dict_path_get(
            artifacts.scientific_web_summary.payload,
            "social_impact",
            "scenario_population_state_distribution",
        )
        if isinstance(distribution, dict) and distribution:
            return distribution
    return {}


def _population_state_service_block(
    distribution: dict[str, Any],
    scenario: str,
    hazard: str,
    service_key: str,
) -> dict[str, Any]:
    scenario_block = distribution.get(scenario) if isinstance(distribution.get(scenario), dict) else {}
    hazard_block = scenario_block.get(hazard) if isinstance(scenario_block.get(hazard), dict) else {}
    aliases = {
        "eau_aep": ("eau_aep", "water_aep"),
        "eau_eu": ("eau_eu", "water_eu"),
        "elec": ("elec",),
    }
    for alias in aliases.get(service_key, (service_key,)):
        block = hazard_block.get(alias)
        if isinstance(block, dict):
            return block
    return {}


def _build_population_state_matrix_from_graph_inputs(
    artifacts: AuxiliaryArtifacts,
    hazard: str,
    title: str,
    population_state_analysis: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    distribution = _graph_population_state_distribution(artifacts)
    if not distribution:
        return None
    total_population = max(sum(_population_by_cell(artifacts.complete_analysis.payload).values()), 0.0)
    for scenario_key, _scenario_label in NETWORK_STATE_MATRIX_SCENARIOS:
        for column_key, _column_label, _class_keys in NETWORK_STATE_MATRIX_COLUMNS:
            service_block = _population_state_service_block(distribution, scenario_key, hazard, column_key)
            service_total = sum(max(_safe_float(service_block.get(state)), 0.0) for state in STATE_SEQUENCE)
            total_population = max(total_population, service_total)
    if total_population <= 0.0:
        return None

    cells: list[list[dict[str, float]]] = []
    outage_cause_cells: list[list[dict[str, float] | None]] = []
    has_distribution = False
    for scenario_key, _scenario_label in NETWORK_STATE_MATRIX_SCENARIOS:
        scenario_cells: list[dict[str, float]] = []
        scenario_cause_cells: list[dict[str, float] | None] = []
        for column_key, _column_label, _class_keys in NETWORK_STATE_MATRIX_COLUMNS:
            service_block = _population_state_service_block(distribution, scenario_key, hazard, column_key)
            values = {
                state: max(_safe_float(service_block.get(state)), 0.0)
                for state in STATE_SEQUENCE
            }
            if any(value > 0.0 for value in values.values()):
                has_distribution = True
            scenario_cells.append(
                {
                    state: round((value / total_population) * 100.0, 4)
                    for state, value in values.items()
                }
            )
            if _safe_float(scenario_cells[-1].get("S3")) > 0.0:
                cause_shares = _population_outage_cause_shares_from_analysis(
                    population_state_analysis,
                    scenario_key,
                    hazard,
                    column_key,
                )
                if cause_shares is None:
                    cause_shares = _population_outage_cause_shares_from_graph_inputs(
                        artifacts,
                        scenario_key,
                        hazard,
                        column_key,
                        _class_keys,
                    )
                scenario_cause_cells.append(cause_shares)
            else:
                scenario_cause_cells.append(None)
        cells.append(scenario_cells)
        outage_cause_cells.append(scenario_cause_cells)
    if not has_distribution:
        return None
    return {
        "type": "population_state_matrix",
        "title": title,
        "column_titles": [label for _column_key, label, _class_keys in NETWORK_STATE_MATRIX_COLUMNS],
        "row_titles": [label for scenario_key, label in NETWORK_STATE_MATRIX_SCENARIOS],
        "cells": cells,
        "outage_cause_cells": outage_cause_cells,
        "legend_title": "% de la population totale",
        "percent_label_scale": MATRIX_PERCENT_LABEL_SCALE,
        "note": (
            "Chaque camembert montre la repartition de la population totale de Guadeloupe entre les etats S0 a S3 pour un scenario et un zonage reseau. "
            "Source: distribution de population par etats de service derivee de network-states.geojson."
        ),
    }


def _build_population_state_matrix_payload(
    artifacts: AuxiliaryArtifacts,
    hazard: str,
    title: str,
) -> dict[str, Any] | None:
    analysis = _compute_population_state_analysis(artifacts)
    graph_inputs_payload = _build_population_state_matrix_from_graph_inputs(
        artifacts,
        hazard,
        title,
        population_state_analysis=analysis,
    )
    if graph_inputs_payload is not None:
        return graph_inputs_payload
    if analysis is None:
        return None
    population_by_cell = analysis["population_by_cell"]
    column_states = _dict_path_get(analysis, "column_states")
    total_population = max(_safe_float(analysis.get("total_population")), 0.0)
    if not isinstance(column_states, dict) or total_population <= 0.0:
        return None
    cells: list[list[dict[str, float]]] = []
    outage_cause_cells: list[list[dict[str, float] | None]] = []
    has_non_zero = False
    for scenario_key, _scenario_label in NETWORK_STATE_MATRIX_SCENARIOS:
        hazard_columns = _dict_path_get(column_states, scenario_key, hazard)
        if not isinstance(hazard_columns, dict):
            return None
        scenario_cells: list[dict[str, float]] = []
        scenario_cause_cells: list[dict[str, float] | None] = []
        for column_key, _column_label, _class_keys in NETWORK_STATE_MATRIX_COLUMNS:
            totals = {state: 0.0 for state in STATE_SEQUENCE}
            cell_states = hazard_columns.get(column_key) if isinstance(hazard_columns.get(column_key), dict) else {}
            for cell_id, population in population_by_cell.items():
                state = str(cell_states.get(cell_id) or "S0").upper()
                if state not in totals:
                    state = "S0"
                totals[state] += float(population)
            percentages = {state: round((value / total_population) * 100.0, 4) for state, value in totals.items()}
            if any(percentages[state] > 0.0 for state in ("S1", "S2", "S3")):
                has_non_zero = True
            scenario_cells.append(percentages)
            if _safe_float(percentages.get("S3")) > 0.0:
                cause_shares = _population_outage_cause_shares_from_analysis(
                    analysis,
                    scenario_key,
                    hazard,
                    column_key,
                )
                if cause_shares is None:
                    cause_shares = _population_outage_cause_shares_from_graph_inputs(
                        artifacts,
                        scenario_key,
                        hazard,
                        column_key,
                        _class_keys,
                    )
                scenario_cause_cells.append(cause_shares)
            else:
                scenario_cause_cells.append(None)
        cells.append(scenario_cells)
        outage_cause_cells.append(scenario_cause_cells)
    if not has_non_zero and not cells:
        return None
    return {
        "type": "population_state_matrix",
        "title": title,
        "column_titles": [label for _column_key, label, _class_keys in NETWORK_STATE_MATRIX_COLUMNS],
        "row_titles": [label for scenario_key, label in NETWORK_STATE_MATRIX_SCENARIOS],
        "cells": cells,
        "outage_cause_cells": outage_cause_cells,
        "legend_title": "% de la population totale",
        "percent_label_scale": MATRIX_PERCENT_LABEL_SCALE,
        "note": (
            "Chaque camembert montre la repartition de la population totale de Guadeloupe entre les etats S0 a S3 pour un scenario et un zonage reseau. "
            "Source: croisement local network-states.geojson / population. "
            "Pour les reseaux d'eau, la petite barre a droite ventile l'origine directe/indirecte des hors services quand cette decomposition est disponible."
        ),
    }


def _render_geojson_map_png(
    plt: Any,
    payload: dict[str, Any],
    output_path: Path,
) -> None:
    path = payload.get("geojson_path")
    if not path:
        raise RuntimeError("geojson_path is required for geojson map rendering")
    gdf = _load_geodataframe_cached(str(path))
    filter_column = payload.get("filter_column")
    filter_values = payload.get("filter_values")
    if filter_column and filter_values:
        gdf = gdf[gdf[filter_column].isin(filter_values)]
    if gdf.empty:
        raise RuntimeError(f"No features left after filtering {path}")
    if gdf.crs is None:
        gdf = gdf.set_crs(epsg=4326)
    gdf = gdf.to_crs(epsg=3857)
    gdf = _swap_state_surfaces_for_source_lines(gdf, payload)
    gdf = _thin_zoomed_surface_network_geometries(gdf)

    fig, ax = plt.subplots(figsize=(8.5, 7.5))
    _apply_map_extent(ax, gdf)
    _add_light_basemap(ax)
    line_width = _adaptive_geo_linewidth(gdf, base_width=1.4)
    fill_line_width = _adaptive_geo_linewidth(gdf, base_width=1.6)
    state_column = payload.get("state_column")
    color_column = payload.get("color_column")
    categorical_column = state_column or color_column
    if categorical_column:
        from matplotlib.lines import Line2D
        from matplotlib.patches import Patch

        raw_colors = payload.get("state_colors") or payload.get("color_map") or STATE_COLORS
        raw_labels = payload.get("legend_labels") or STATE_LABELS
        category_order = [str(item) for item in (payload.get("category_order") or list(raw_colors.keys()))]
        state_colors = {str(key): str(value) for key, value in dict(raw_colors).items()}
        legend_labels = {str(key): str(value) for key, value in dict(raw_labels).items()}
        gdf = gdf.copy()
        gdf["_plot_color"] = gdf[categorical_column].map(lambda value: state_colors.get(str(value), "#94a3b8"))
        geom_types = {str(value) for value in getattr(gdf, "geom_type", [])}
        is_surface = bool(geom_types) and geom_types.issubset({"Polygon", "MultiPolygon"})
        if is_surface:
            gdf.plot(ax=ax, color=gdf["_plot_color"], linewidth=0.0, edgecolor="none", alpha=0.92, zorder=3)
        else:
            gdf.plot(ax=ax, color=gdf["_plot_color"], linewidth=payload.get("line_width") or line_width, alpha=0.92, zorder=3)
        legend_handles = []
        for key in category_order:
            color = state_colors.get(key)
            if not color:
                continue
            label = legend_labels.get(key, key)
            if is_surface:
                legend_handles.append(Patch(facecolor=color, edgecolor=color, label=label))
            else:
                legend_handles.append(Line2D([0], [0], color=color, lw=3.0, label=label))
        if legend_handles:
            ax.legend(handles=legend_handles, title=payload.get("legend_title") or "Etat de service", loc="upper right")
    else:
        color = payload.get("color") or "#0f766e"
        geom_types = {str(value) for value in getattr(gdf, "geom_type", [])}
        is_surface = bool(geom_types) and geom_types.issubset({"Polygon", "MultiPolygon"})
        if is_surface:
            gdf.plot(ax=ax, color=color, linewidth=0.0, edgecolor="none", alpha=0.95, zorder=3)
        else:
            gdf.plot(ax=ax, color=color, linewidth=fill_line_width, alpha=0.95, zorder=3)
    ax.set_title(payload.get("title") or "")
    ax.set_axis_off()
    _save_figure(fig, output_path, payload.get("note"))
    plt.close(fig)


def _render_raster_overlay_map_png(
    plt: Any,
    payload: dict[str, Any],
    output_path: Path,
) -> None:
    from matplotlib import cm, colors as mcolors
    import numpy as np

    overlay_path = str(payload.get("overlay_path") or "").strip()
    bounds = payload.get("bounds") if isinstance(payload.get("bounds"), dict) else {}
    if not overlay_path or not bounds:
        raise RuntimeError("overlay_path and bounds are required for raster_overlay_map rendering")
    gpd = _load_geopandas()
    from shapely.geometry import box

    bounds_gdf = gpd.GeoDataFrame(
        [{"geometry": box(_safe_float(bounds.get("west")), _safe_float(bounds.get("south")), _safe_float(bounds.get("east")), _safe_float(bounds.get("north")))}],
        geometry="geometry",
        crs="EPSG:4326",
    ).to_crs(epsg=3857)
    min_x, min_y, max_x, max_y = [float(value) for value in bounds_gdf.total_bounds]

    fig, ax = plt.subplots(figsize=(8.5, 7.5))
    _apply_map_extent(ax, bounds_gdf)
    _add_light_basemap(ax)
    scale_max = max(_safe_float(payload.get("scale_max"), default=1.0), 1.0)
    cmap = _resolve_map_cmap(payload)
    norm = (
        mcolors.PowerNorm(gamma=0.5, vmin=0.0, vmax=scale_max)
        if str(payload.get("scale_norm") or "").strip().lower() == "sqrt"
        else mcolors.Normalize(vmin=0.0, vmax=scale_max)
    )
    image_cmap = plt.get_cmap(cmap) if isinstance(cmap, str) else cmap
    if hasattr(image_cmap, "copy"):
        image_cmap = image_cmap.copy()
        image_cmap.set_bad((0.0, 0.0, 0.0, 0.0))

    raster_path = str(payload.get("raster_path") or "").strip()
    if raster_path and Path(raster_path).exists():
        rasterio = _load_rasterio()
        with rasterio.open(raster_path) as src:
            raster_values = src.read(1, masked=True).astype("float32")
            nodata = src.nodata
        values = np.ma.asarray(raster_values)
        values = np.ma.masked_invalid(values)
        if nodata is not None and np.isfinite(float(nodata)):
            values = np.ma.masked_where(values == np.float32(nodata), values)
        values = np.ma.masked_where(values <= 0.0, values)
        ax.imshow(values, extent=(min_x, max_x, min_y, max_y), zorder=3, alpha=0.96, cmap=image_cmap, norm=norm)
    else:
        image = plt.imread(overlay_path)
        ax.imshow(image, extent=(min_x, max_x, min_y, max_y), zorder=3, alpha=0.96)
    ax.set_title(payload.get("title") or "")
    ax.set_axis_off()

    mappable = cm.ScalarMappable(norm=norm, cmap=cmap)
    cbar = fig.colorbar(mappable, ax=ax, fraction=0.035, pad=0.02)
    cbar.set_label(str(payload.get("legend_title") or "Valeur"))

    _save_figure(fig, output_path, payload.get("note"))
    plt.close(fig)


def _render_choropleth_map_png(
    plt: Any,
    payload: dict[str, Any],
    output_path: Path,
) -> None:
    from matplotlib import cm, colors as mcolors

    gdf = payload.get("gdf")
    value_column = str(payload.get("value_column") or "").strip()
    if gdf is None or not value_column:
        raise RuntimeError("gdf and value_column are required for choropleth_map rendering")
    if getattr(gdf, "empty", True):
        raise RuntimeError("No geometries available for choropleth_map rendering")
    if value_column not in gdf.columns:
        raise RuntimeError(f"Missing value column for choropleth_map: {value_column}")
    if gdf.crs is None:
        gdf = gdf.set_crs(epsg=4326)
    gdf = gdf.to_crs(epsg=3857)
    extent_gdf = payload.get("extent_gdf")
    if extent_gdf is not None and not getattr(extent_gdf, "empty", True):
        if extent_gdf.crs is None:
            extent_gdf = extent_gdf.set_crs(epsg=4326)
        extent_gdf = extent_gdf.to_crs(epsg=3857)
    values = gdf[value_column].map(lambda value: max(_safe_float(value), 0.0))
    gdf = gdf.copy()
    gdf[value_column] = values

    fig, ax = plt.subplots(figsize=(8.5, 7.5))
    _apply_map_extent(ax, extent_gdf if extent_gdf is not None and not getattr(extent_gdf, "empty", True) else gdf)
    _add_light_basemap(ax)

    cmap = _resolve_map_cmap(payload)
    vmin = _safe_float(payload.get("vmin"), default=0.0)
    vmax = _safe_float(payload.get("vmax"), default=max(_safe_float(values.max()), 0.0))
    if vmax <= vmin:
        vmax = vmin + 1.0
    norm = mcolors.Normalize(vmin=vmin, vmax=vmax)
    colors = [cmap(norm(value)) for value in values]
    line_width = _safe_float(payload.get("line_width"), default=0.45)
    gdf.plot(
        ax=ax,
        color=colors,
        edgecolor=str(payload.get("edgecolor") or "#ffffff"),
        linewidth=line_width,
        alpha=0.9,
        zorder=3,
    )
    ax.set_title(payload.get("title") or "")
    ax.set_axis_off()

    mappable = cm.ScalarMappable(norm=norm, cmap=cmap)
    cbar = fig.colorbar(mappable, ax=ax, fraction=0.035, pad=0.02)
    cbar.set_label(str(payload.get("legend_title") or "Valeur"))

    if payload.get("fixed_canvas"):
        fig.subplots_adjust(left=0.02, right=0.87, top=0.92, bottom=0.09)
        note = payload.get("note")
        if note:
            fig.text(0.01, 0.015, note, ha="left", va="bottom", fontsize=8, color="#475569", wrap=True)
        fig.savefig(output_path, dpi=180)
    else:
        _save_figure(fig, output_path, payload.get("note"))
    plt.close(fig)


def _render_choropleth_map_grid_png(
    plt: Any,
    payload: dict[str, Any],
    output_path: Path,
) -> None:
    from matplotlib import cm, colors as mcolors

    rows = payload.get("rows") or []
    columns = payload.get("columns") or []
    cells = payload.get("cells") or []
    if not rows or not columns or not cells:
        raise RuntimeError("choropleth_map_grid requires non-empty rows, columns and cells")

    nrows = len(rows)
    ncols = len(columns)
    fig, axes = plt.subplots(nrows, ncols, figsize=(18, 9.6), sharex=False, sharey=False)
    if nrows == 1 and ncols == 1:
        axes_grid = [[axes]]
    elif nrows == 1:
        axes_grid = [list(axes)]
    elif ncols == 1:
        axes_grid = [[ax] for ax in axes]
    else:
        axes_grid = [list(row) for row in axes]

    cmap = _resolve_map_cmap(payload)
    norm = mcolors.Normalize(vmin=_safe_float(payload.get("vmin"), 0.0), vmax=max(_safe_float(payload.get("vmax"), 1.0), 1.0))
    edgecolor = str(payload.get("edgecolor") or "#ffffff")
    line_width = _safe_float(payload.get("line_width"), 0.2)
    extent_gdf = payload.get("extent_gdf")
    if extent_gdf is not None and not getattr(extent_gdf, "empty", True):
        if extent_gdf.crs is None:
            extent_gdf = extent_gdf.set_crs(epsg=4326)
        extent_gdf = extent_gdf.to_crs(epsg=3857)

    for row_idx, row_cfg in enumerate(rows):
        row_cells = cells[row_idx] if row_idx < len(cells) and isinstance(cells[row_idx], list) else []
        for col_idx, column_cfg in enumerate(columns):
            ax = axes_grid[row_idx][col_idx]
            cell = row_cells[col_idx] if col_idx < len(row_cells) and isinstance(row_cells[col_idx], dict) else {}
            gdf = cell.get("gdf")
            value_column = str(cell.get("value_column") or "").strip()
            if gdf is None or not value_column or getattr(gdf, "empty", True):
                ax.set_axis_off()
                continue
            if gdf.crs is None:
                gdf = gdf.set_crs(epsg=4326)
            gdf = gdf.to_crs(epsg=3857)
            _apply_map_extent(ax, extent_gdf if extent_gdf is not None and not getattr(extent_gdf, "empty", True) else gdf)
            _add_light_basemap(ax)
            values = gdf[value_column].map(lambda value: max(_safe_float(value), 0.0))
            colors = [cmap(norm(value)) for value in values]
            gdf.plot(ax=ax, color=colors, edgecolor=edgecolor, linewidth=line_width, alpha=0.92, zorder=3)
            ax.set_axis_off()
            if row_idx == 0:
                ax.set_title(str(column_cfg.get("label") or column_cfg.get("key") or ""), fontsize=11, pad=10, fontweight="bold")
            if col_idx == 0:
                ax.text(-0.08, 0.5, str(row_cfg.get("label") or row_cfg.get("key") or ""), transform=ax.transAxes, rotation=90, va="center", ha="center", fontsize=11, fontweight="bold")

    fig.subplots_adjust(top=0.9, bottom=0.08, left=0.07, right=0.88, wspace=0.08, hspace=0.07)
    mappable = cm.ScalarMappable(norm=norm, cmap=cmap)
    cax = fig.add_axes([0.905, 0.18, 0.018, 0.64])
    cbar = fig.colorbar(mappable, cax=cax)
    cbar.set_label(str(payload.get("legend_title") or "Valeur"))
    fig.suptitle(payload.get("title") or "", fontsize=18, y=0.985)
    note = payload.get("note")
    if note:
        fig.text(0.01, 0.01, note, ha="left", va="bottom", fontsize=8, color="#475569", wrap=True)
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _render_population_state_matrix_png(
    plt: Any,
    payload: dict[str, Any],
    output_path: Path,
) -> None:
    from matplotlib.patches import Patch

    row_titles = payload.get("row_titles") or []
    column_titles = payload.get("column_titles") or []
    cells = payload.get("cells") or []
    outage_cause_cells = payload.get("outage_cause_cells") or []
    if not row_titles or not column_titles or not cells:
        fig, _ax = plt.subplots(figsize=(12, 8))
        _save_figure(fig, output_path, payload.get("note"))
        plt.close(fig)
        return

    nrows = len(row_titles)
    ncols = len(column_titles)
    percent_label_scale = _matrix_percent_label_scale(payload)
    pie_label_fontsize = _matrix_percent_label_fontsize(12, percent_label_scale)
    cause_label_fontsize = _matrix_percent_label_fontsize(6, percent_label_scale)
    legend_fontsize = _matrix_percent_label_fontsize(9, percent_label_scale)
    fig_scale = 1.0 + (max(percent_label_scale - 1.0, 0.0) * 0.24)
    fig, axes = plt.subplots(nrows, ncols, figsize=(15.2 * fig_scale, 12.9 * fig_scale), subplot_kw={"aspect": "equal"})
    if nrows == 1 and ncols == 1:
        axes_grid = [[axes]]
    elif nrows == 1:
        axes_grid = [list(axes)]
    elif ncols == 1:
        axes_grid = [[ax] for ax in axes]
    else:
        axes_grid = [list(row) for row in axes]

    state_palette = [STATE_COLORS[state] if state == "S0" else HAZARD_COLORS[state.lower()] for state in STATE_SEQUENCE]
    for row_idx, row_title in enumerate(row_titles):
        row_cells = cells[row_idx] if row_idx < len(cells) and isinstance(cells[row_idx], list) else []
        row_cause_cells = outage_cause_cells[row_idx] if row_idx < len(outage_cause_cells) and isinstance(outage_cause_cells[row_idx], list) else []
        for col_idx, column_title in enumerate(column_titles):
            ax = axes_grid[row_idx][col_idx]
            cell = row_cells[col_idx] if col_idx < len(row_cells) and isinstance(row_cells[col_idx], dict) else {}
            cause_cell = row_cause_cells[col_idx] if col_idx < len(row_cause_cells) and isinstance(row_cause_cells[col_idx], dict) else None
            values = [max(_safe_float(cell.get(state)), 0.0) for state in STATE_SEQUENCE]
            total = sum(values)
            if total > 0.0:
                ax.pie(
                    values,
                    colors=state_palette,
                    startangle=90,
                    counterclock=False,
                    wedgeprops={"linewidth": 0.8, "edgecolor": "white"},
                )
                impacted = sum(values[1:])
                dominant_state = STATE_SEQUENCE[values.index(max(values))]
                center_label_color = "#ffffff" if dominant_state == "S3" else "#0f172a"
                ax.text(0, 0, f"{impacted:.0f}%", ha="center", va="center", fontsize=pie_label_fontsize, fontweight="bold", color=center_label_color)
            else:
                ax.text(0.5, 0.5, "0%", transform=ax.transAxes, ha="center", va="center", fontsize=pie_label_fontsize, fontweight="bold", color="#64748b")
            if cause_cell is not None:
                inset_width = min(0.24, 0.12 * (1.0 + max(percent_label_scale - 1.0, 0.0) * 0.38))
                inset = ax.inset_axes([0.94 - inset_width, 0.14, inset_width, 0.72])
                cause_bottom = 0.0
                outage_share = max(_safe_float(cell.get("S3")), 0.0)
                cause_total = 0.0 if outage_share <= 0.0 else sum(max(_safe_float(cause_cell.get(key)), 0.0) for key in OUTAGE_CAUSE_LABELS)
                if cause_total > 0.0:
                    for cause_key in ("direct", "indirect"):
                        value = max(_safe_float(cause_cell.get(cause_key)), 0.0)
                        inset.bar(
                            [0],
                            [value],
                            bottom=[cause_bottom],
                            width=0.8,
                            color=OUTAGE_CAUSE_COLORS[cause_key],
                            edgecolor="white",
                            linewidth=0.5,
                        )
                        cause_bottom += value
                else:
                    inset.bar([0], [100.0], width=0.8, color="none", edgecolor="#94a3b8", linewidth=0.8)
                    inset.text(0, 50.0, "HS\n0%", ha="center", va="center", fontsize=cause_label_fontsize, color="#64748b", fontweight="bold")
                inset.set_ylim(0, 100)
                inset.set_xlim(-0.8, 0.8)
                inset.set_xticks([])
                inset.set_yticks([])
                inset.set_title(OUTAGE_CAUSE_TITLE, fontsize=6, color="#475569", pad=1)
                for spine in inset.spines.values():
                    spine.set_visible(False)
            if col_idx == 0:
                ax.set_ylabel(row_title, rotation=0, labelpad=40, va="center", fontsize=11, fontweight="bold")
            if row_idx == 0:
                ax.set_title(column_title, fontsize=11, pad=20, fontweight="bold")
            ax.set_xticks([])
            ax.set_yticks([])

    handles = [Patch(facecolor=state_palette[idx], label=_state_label(state)) for idx, state in enumerate(STATE_SEQUENCE)]
    handles.extend(Patch(facecolor=OUTAGE_CAUSE_COLORS[key], label=f"{OUTAGE_CAUSE_LEGEND_PREFIX} - {label}") for key, label in OUTAGE_CAUSE_LABELS.items())
    fig.legend(
        handles=handles,
        loc="lower center",
        ncol=3,
        bbox_to_anchor=(0.5, 0.018),
        frameon=False,
        fontsize=legend_fontsize,
        handlelength=1.35,
        columnspacing=1.1,
        labelspacing=0.7,
    )
    fig.suptitle(payload.get("title") or "", fontsize=18, y=0.991)
    fig.text(0.03, 0.5, str(payload.get("legend_title") or "%"), rotation="vertical", va="center", fontsize=11)
    fig.tight_layout(rect=(0.05, 0.17, 1.0, 0.92))
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _render_population_decision_grouped_bar_png(
    plt: Any,
    payload: dict[str, Any],
    output_path: Path,
) -> None:
    from matplotlib.patches import Patch

    rows = list(payload.get("rows") or [])
    periods = list(payload.get("periods") or POPULATION_DECISION_PERIODS)
    services = list(payload.get("services") or [])
    if not rows or not periods or not services:
        raise RuntimeError("population_decision_grouped_bar requires rows, periods and services")

    service_by_key = {str(item.get("key") or ""): item for item in services if isinstance(item, dict)}
    x_positions: list[float] = []
    bar_values: list[float] = []
    bar_colors: list[str] = []
    tick_labels: list[str] = []
    bar_symbols: list[str] = []
    bar_value_labels: list[str] = []
    period_centers: list[tuple[float, str]] = []
    service_centers: list[tuple[float, str, str]] = []
    separators: list[float] = []

    x_cursor = 0.0
    for period in periods:
        period_start = x_cursor
        period_has_rows = False
        for service in POPULATION_DECISION_SERVICES:
            service_rows = [
                row
                for row in rows
                if str(row.get("period") or "") == period and str(row.get("service") or "") == service
            ]
            if not service_rows:
                continue
            service_start = x_cursor
            for row in service_rows:
                x_positions.append(x_cursor)
                value = _population_decision_population({"population_potentiellement_affectee": row.get("population")})
                bar_values.append(value)
                bar_colors.append(str(service_by_key.get(service, {}).get("color") or "#64748b"))
                tick_labels.append(_wrap_cell(str(row.get("zone_label") or ""), width=16))
                bar_symbols.append(str(row.get("failure_symbol") or ""))
                bar_value_labels.append(str(row.get("population_label") or _format_population_decision_label(value)))
                x_cursor += 1.0
                period_has_rows = True
            service_end = x_cursor - 1.0
            service_centers.append(
                (
                    (service_start + service_end) / 2.0,
                    str(service_by_key.get(service, {}).get("label") or service),
                    str(service_by_key.get(service, {}).get("color") or "#64748b"),
                )
            )
            x_cursor += 0.65
        if period_has_rows:
            period_end = x_cursor - 1.65
            period_centers.append(((period_start + period_end) / 2.0, str(period)))
            separators.append(x_cursor - 0.95)
            x_cursor += 1.25

    if not x_positions:
        raise RuntimeError("No population decision bars available")

    max_value = max(bar_values) if bar_values else 1.0
    fig_width = max(14.0, min(22.0, 0.47 * len(x_positions) + 7.5))
    fig, ax = plt.subplots(figsize=(fig_width, 9.2))
    ax.bar(x_positions, bar_values, width=0.78, color=bar_colors, edgecolor="#ffffff", linewidth=0.8, zorder=3)
    ax.set_title(payload.get("title") or "", fontsize=16, pad=16, fontweight="bold")
    ax.set_ylabel(str(payload.get("ylabel") or "Population potentiellement affectee"))
    ax.set_xticks(x_positions)
    ax.set_xticklabels(tick_labels, rotation=55, ha="right", fontsize=7.5)
    ax.set_ylim(0.0, max(max_value * 1.22, 1.0))
    ax.grid(axis="y", color="#e2e8f0", linewidth=0.8, zorder=0)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#cbd5e1")
    ax.spines["bottom"].set_color("#cbd5e1")
    ax.tick_params(axis="y", labelsize=9)

    label_offset = max_value * 0.018
    for x_value, value, symbol, value_label in zip(x_positions, bar_values, bar_symbols, bar_value_labels):
        ax.text(
            x_value,
            value + label_offset,
            f"{symbol}\n{value_label}".strip(),
            ha="center",
            va="bottom",
            fontsize=7.2,
            color="#111827",
            fontweight="bold",
            linespacing=0.95,
        )

    for separator in separators[:-1]:
        ax.axvline(separator, color="#cbd5e1", linewidth=0.9, linestyle="--", zorder=1)

    for center, label, color in service_centers:
        ax.text(
            center,
            max_value * 1.08,
            label,
            ha="center",
            va="center",
            fontsize=9,
            fontweight="bold",
            color=color,
            bbox={"facecolor": "white", "alpha": 0.72, "edgecolor": "none", "boxstyle": "round,pad=0.15"},
        )
    for center, label in period_centers:
        ax.text(
            center,
            max_value * 1.17,
            label,
            ha="center",
            va="center",
            fontsize=11,
            fontweight="bold",
            color="#0f172a",
            bbox={"facecolor": "white", "alpha": 0.84, "edgecolor": "#cbd5e1", "boxstyle": "round,pad=0.18"},
        )

    service_handles = [
        Patch(facecolor=str(item.get("color") or "#64748b"), edgecolor="none", label=str(item.get("label") or item.get("key") or ""))
        for item in services
    ]
    ax.legend(handles=service_handles, loc="upper right", frameon=False, ncol=3, fontsize=9)
    fig.text(
        0.012,
        0.018,
        "Symboles: ◆ defaillance d'ouvrage candidat; ■ defaillance reseau; ◆■ defaillance mixte. "
        + str(payload.get("note") or ""),
        ha="left",
        va="bottom",
        fontsize=8,
        color="#475569",
        wrap=True,
    )
    fig.tight_layout(rect=(0.02, 0.08, 1.0, 0.96))
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _render_population_decision_zone_map_png(
    plt: Any,
    payload: dict[str, Any],
    output_path: Path,
) -> None:
    from matplotlib import patheffects as path_effects
    from matplotlib.patches import Patch

    gdf = payload.get("gdf")
    if gdf is None or getattr(gdf, "empty", True):
        raise RuntimeError("population_decision_zone_map requires a non-empty gdf")
    if gdf.crs is None:
        gdf = gdf.set_crs(epsg=4326)
    gdf = gdf.to_crs(epsg=3857)

    fig, ax = plt.subplots(figsize=(8.5, 7.5))
    _apply_map_extent(ax, gdf, pad_ratio=0.08)
    _add_light_basemap(ax)

    for zorder, service in enumerate(POPULATION_DECISION_SERVICES, start=3):
        service_gdf = gdf[gdf["service"].astype(str) == service].copy()
        if service_gdf.empty:
            continue
        color = POPULATION_DECISION_SERVICE_COLORS.get(service, "#64748b")
        service_gdf.plot(
            ax=ax,
            color=color,
            edgecolor="#ffffff",
            linewidth=0.9,
            alpha=0.52,
            zorder=zorder,
        )

    label_offsets = {
        "eau_aep": [(-18, 18), (-22, 8), (-18, -12), (-26, 24), (-18, -22)],
        "eau_eu": [(18, 14), (36, 22), (34, 28), (20, -38), (40, -36)],
        "elec": [(0, 34), (56, -36), (0, 44), (-52, 4), (56, -42)],
    }
    service_label_counts = {service: 0 for service in POPULATION_DECISION_SERVICES}
    for idx, row in enumerate(gdf.itertuples(index=False)):
        geometry = getattr(row, "geometry", None)
        if geometry is None or geometry.is_empty:
            continue
        point = geometry.representative_point()
        service = str(getattr(row, "service", "") or "")
        offsets = label_offsets.get(service, [(0, 0)])
        service_idx = service_label_counts.get(service, 0)
        service_label_counts[service] = service_idx + 1
        offset_x, offset_y = offsets[service_idx % len(offsets)]
        label = _wrap_cell(str(getattr(row, "zone_label", "") or ""), width=18)
        ax.annotate(
            label,
            xy=(point.x, point.y),
            xytext=(offset_x, offset_y),
            textcoords="offset points",
            ha="center",
            va="center",
            fontsize=7.2,
            color="#0f172a",
            zorder=10,
            bbox={"facecolor": "white", "alpha": 0.78, "edgecolor": "none", "boxstyle": "round,pad=0.18"},
            path_effects=[path_effects.withStroke(linewidth=1.5, foreground="white")],
            arrowprops={"arrowstyle": "-", "color": "#64748b", "linewidth": 0.55, "alpha": 0.55},
        )

    services = list(payload.get("services") or [])
    handles = [
        Patch(facecolor=str(item.get("color") or "#64748b"), edgecolor="#ffffff", label=str(item.get("label") or item.get("key") or ""), alpha=0.62)
        for item in services
    ]
    if handles:
        ax.legend(handles=handles, loc="lower left", frameon=True, framealpha=0.88, fontsize=8)
    ax.set_title(payload.get("title") or "", fontsize=14, pad=12, fontweight="bold")
    ax.set_axis_off()
    _save_figure(fig, output_path, payload.get("note"))
    plt.close(fig)


def _clean_output_categories(output_dir: Path) -> None:
    for category in ("charts", "maps", "tables", "Population", DAMAGE_ZONE_OUTPUT_DIRNAME):
        category_dir = output_dir / category
        if category_dir.exists():
            shutil.rmtree(category_dir)


def _warning_message(territory: str | None, artifact: str, detail: str) -> str:
    if territory:
        return f"[{territory}] {artifact}: {detail}"
    return f"[global] {artifact}: {detail}"


def _page7_block(artifacts: AuxiliaryArtifacts, *keys: str) -> Any:
    if artifacts.page7_analysis is not None:
        data = artifacts.page7_analysis.payload
    elif artifacts.case_study_analysis is not None:
        data = artifacts.case_study_analysis.payload
    else:
        data = None
    return _dict_path_get(data, *keys)


def _strict_graph_source_error(
    artifacts: AuxiliaryArtifacts,
    *,
    graph_name: str,
    key_path: str,
    detail: str,
) -> RuntimeError:
    payload_path = Path(artifacts.complete_analysis.payload_path)
    path_parts = list(payload_path.parts)
    derived_run_id = None
    if "complete-analysis-runs" in path_parts:
        idx = path_parts.index("complete-analysis-runs")
        if idx + 1 < len(path_parts):
            derived_run_id = path_parts[idx + 1]
    run_id = str(
        _dict_path_get(artifacts.complete_analysis.payload, "meta", "run_id")
        or artifacts.complete_analysis.payload.get("run_id")
        or derived_run_id
        or "unknown-run"
    )
    territory = artifacts.territory
    return RuntimeError(
        f"Strict scientific graph input missing or forbidden: run_id={run_id}, territory={territory}, "
        f"graph={graph_name}, key={key_path}, detail={detail}"
    )


def _scientific_summary_payload(artifacts: AuxiliaryArtifacts) -> dict[str, Any]:
    if artifacts.scientific_web_summary is None:
        raise _strict_graph_source_error(
            artifacts,
            graph_name="scientific_summary",
            key_path="scientific_web_summary",
            detail="missing required *-scientific-web-summary.json",
        )
    payload = artifacts.scientific_web_summary.payload
    if not isinstance(payload, dict):
        raise _strict_graph_source_error(
            artifacts,
            graph_name="scientific_summary",
            key_path="scientific_web_summary",
            detail="invalid summary payload",
        )
    return payload


def _scientific_graph_inputs(artifacts: AuxiliaryArtifacts, *, graph_name: str) -> dict[str, Any]:
    summary_payload = _scientific_summary_payload(artifacts)
    summary_graph_inputs = summary_payload.get("scientific_graph_inputs")
    complete_graph_inputs = artifacts.complete_analysis.payload.get("scientific_graph_inputs")
    complete_pml_inputs = artifacts.complete_analysis.payload.get("pml_network_graph_inputs")
    if _graph_inputs_have_required_scenarios(summary_graph_inputs):
        return summary_graph_inputs
    if _graph_inputs_have_required_scenarios(complete_graph_inputs):
        return complete_graph_inputs
    if _graph_inputs_have_required_scenarios(complete_pml_inputs):
        return complete_pml_inputs
    if isinstance(summary_graph_inputs, dict):
        return summary_graph_inputs
    if isinstance(complete_graph_inputs, dict):
        return complete_graph_inputs
    raise _strict_graph_source_error(
        artifacts,
        graph_name=graph_name,
        key_path="scientific_graph_inputs|pml_network_graph_inputs",
        detail="missing complete-analysis graph contract",
    )


def _scientific_graph_scenario_rows(
    artifacts: AuxiliaryArtifacts,
    *,
    graph_name: str,
    scenario: str,
    key: str,
) -> Any:
    graph_inputs = _scientific_graph_inputs(artifacts, graph_name=graph_name)
    block = graph_inputs.get(key) if isinstance(graph_inputs.get(key), dict) else {}
    value = block.get(scenario)
    if key == "state_damage_tables":
        if not isinstance(value, list) or not value:
            raise _strict_graph_source_error(
                artifacts,
                graph_name=graph_name,
                key_path=f"scientific_graph_inputs.{key}.{scenario}",
                detail="strict scientific rows are unavailable; page-analysis is forbidden",
            )
    elif key == "damage_breakdown_by_scenario":
        if not isinstance(value, dict) or (
            not isinstance(value.get("storm"), list) and not isinstance(value.get("storm_cmcc"), list)
        ):
            raise _strict_graph_source_error(
                artifacts,
                graph_name=graph_name,
                key_path=f"scientific_graph_inputs.{key}.{scenario}",
                detail="strict scientific breakdown is unavailable; page-analysis is forbidden",
            )
    return value


def _complete_asset_results(artifacts: AuxiliaryArtifacts) -> list[dict[str, Any]]:
    asset_results = artifacts.complete_analysis.payload.get("asset_results")
    return [item for item in asset_results if isinstance(item, dict)] if isinstance(asset_results, list) else []


def _wind_map_block(artifacts: AuxiliaryArtifacts, hazard: str) -> dict[str, Any] | None:
    if artifacts.wind_maps is None:
        return None
    block = artifacts.wind_maps.payload.get(hazard)
    return block if isinstance(block, dict) else None


def _landslide_map_block(artifacts: AuxiliaryArtifacts, hazard: str = "storm") -> dict[str, Any] | None:
    if artifacts.landslide_maps is None:
        return None
    block = artifacts.landslide_maps.payload.get(hazard)
    return block if isinstance(block, dict) else None


def _state_counts_for_metric(
    artifacts: AuxiliaryArtifacts,
    *,
    layer_keys: list[str] | None,
    network_kinds: list[str] | None,
    metric_suffix: str,
    hazard: str,
) -> dict[str, int]:
    if not artifacts.network_states_path:
        return {}
    gdf = _load_geodataframe_cached(artifacts.network_states_path)
    if layer_keys:
        gdf = gdf[gdf["layer_key"].isin(layer_keys)]
    if network_kinds:
        gdf = gdf[gdf["network_kind"].isin(network_kinds)]
    state_column = f"state_{metric_suffix}_{hazard}"
    if state_column not in gdf.columns:
        return {}
    counts = {state: 0 for state in STATE_SEQUENCE}
    for value in gdf[state_column].fillna("S0"):
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _state_percentages(counts: dict[str, int]) -> dict[str, float]:
    total = sum(max(0, int(counts.get(state, 0))) for state in STATE_SEQUENCE)
    if total <= 0:
        return {state: 0.0 for state in STATE_SEQUENCE}
    return {
        state: round((max(0, int(counts.get(state, 0))) / total) * 100.0, 2)
        for state in STATE_SEQUENCE
    }


def _network_filter_config(network_key: str) -> tuple[list[str] | None, list[str] | None]:
    if network_key == "aep":
        return ["eau_aep"], ["AEP"]
    if network_key == "eu":
        return ["eau_eu"], ["EU"]
    if network_key == "elec":
        return list(ELECTRIC_STATE_LAYER_KEYS), None
    return None, None


def _summary_service_key_for_network(network_key: str) -> str | None:
    if network_key == "aep":
        return "eau_aep"
    if network_key == "eu":
        return "eau_eu"
    if network_key == "elec":
        return "elec"
    return None


def _network_state_counts_from_summary(
    artifacts: AuxiliaryArtifacts,
    *,
    metric_suffix: str,
    hazard: str,
    service_key: str,
) -> dict[str, int]:
    scientific_summary = _scientific_summary_payload(artifacts)
    scenario_distribution = _dict_path_get(scientific_summary, "network_states", "scenario_service_state_distribution")
    if not isinstance(scenario_distribution, dict):
        raise _strict_graph_source_error(
            artifacts,
            graph_name=f"network_state_counts_{service_key}_{metric_suffix}_{hazard}",
            key_path="network_states.scenario_service_state_distribution",
            detail="missing strict scientific network-state distribution",
        )
    scenario_hazard = _dict_path_get(scenario_distribution, metric_suffix, hazard)
    if not isinstance(scenario_hazard, dict):
        raise _strict_graph_source_error(
            artifacts,
            graph_name=f"network_state_counts_{service_key}_{metric_suffix}_{hazard}",
            key_path=f"network_states.scenario_service_state_distribution.{metric_suffix}.{hazard}",
            detail="missing strict scientific network-state scenario",
        )
    service_counts = scenario_hazard.get(service_key)
    if not isinstance(service_counts, dict):
        raise _strict_graph_source_error(
            artifacts,
            graph_name=f"network_state_counts_{service_key}_{metric_suffix}_{hazard}",
            key_path=f"network_states.scenario_service_state_distribution.{metric_suffix}.{hazard}.{service_key}",
            detail="missing strict scientific service state counts",
        )
    return {state: int(service_counts.get(state, 0) or 0) for state in STATE_SEQUENCE}


def _render_auxiliary_output(
    plt: Any,
    output_path: Path,
    payload: dict[str, Any],
) -> None:
    plot_type = str(payload.get("type") or "")
    if plot_type == "table":
        _render_table_png(plt, payload.get("title") or output_path.stem, payload.get("headers") or [], payload.get("rows") or [], output_path)
    elif plot_type == "line":
        _render_line_png(plt, payload, output_path)
    elif plot_type == "bar":
        _render_bar_png(plt, payload, output_path)
    elif plot_type == "grouped_bar":
        _render_grouped_bar_png(plt, payload, output_path)
    elif plot_type == "grouped_stacked_bar":
        _render_grouped_stacked_bar_png(plt, payload, output_path)
    elif plot_type == "grouped_stacked_bar_segment_labels":
        _render_grouped_stacked_bar_segment_labels_png(plt, payload, output_path)
    elif plot_type == "stacked_bar":
        _render_stacked_bar_png(plt, payload, output_path)
    elif plot_type == "network_state_matrix":
        _render_network_state_matrix_png(plt, payload, output_path)
    elif plot_type == "population_state_matrix":
        _render_population_state_matrix_png(plt, payload, output_path)
    elif plot_type == "population_decision_grouped_bar":
        _render_population_decision_grouped_bar_png(plt, payload, output_path)
    elif plot_type == "population_decision_zone_map":
        _render_population_decision_zone_map_png(plt, payload, output_path)
    elif plot_type == "geojson_map":
        _render_geojson_map_png(plt, payload, output_path)
    elif plot_type == "raster_overlay_map":
        _render_raster_overlay_map_png(plt, payload, output_path)
    elif plot_type == "choropleth_map":
        _render_choropleth_map_png(plt, payload, output_path)
    elif plot_type == "choropleth_map_grid":
        _render_choropleth_map_grid_png(plt, payload, output_path)
    elif plot_type == "scatter_map":
        _render_scatter_map_png(plt, payload, output_path)
    elif plot_type == "scatter_map_grid":
        _render_scatter_map_grid_png(plt, payload, output_path)
    elif plot_type == "multi_scatter_map":
        _render_multi_scatter_map_png(plt, payload, output_path)
    else:
        raise RuntimeError(f"Unsupported auxiliary payload type: {plot_type}")


def _select_evenly_spaced_indices(point_count: int, target_count: int) -> list[int]:
    if point_count <= 0:
        return []
    if target_count >= point_count:
        return list(range(point_count))
    if target_count <= 1:
        return [0]
    return [math.floor(position * (point_count - 1) / (target_count - 1)) for position in range(target_count)]


def _downsample_line_series(series: dict[str, Any], divisor: int) -> dict[str, Any]:
    if divisor <= 1:
        return dict(series)
    x_values = list(series.get("x") or [])
    y_values = list(series.get("y") or [])
    point_count = min(len(x_values), len(y_values))
    if point_count < 4:
        return dict(series)
    target_count = max(2, math.ceil(point_count / divisor))
    if target_count >= point_count:
        return dict(series)
    indices = _select_evenly_spaced_indices(point_count, target_count)
    output = dict(series)
    output["x"] = [x_values[idx] for idx in indices]
    output["y"] = [y_values[idx] for idx in indices]
    annotations = list(series.get("annotations") or [])
    if annotations:
        output["annotations"] = [annotations[idx] if idx < len(annotations) else "" for idx in indices]
    return output


def _build_wind_hist_payload(
    artifacts: AuxiliaryArtifacts,
    hist_key: str,
    title: str,
    point_divisor: int = 1,
) -> dict[str, Any] | None:
    histograms = _page7_block(artifacts, "hazard", "wind_histograms")
    if not isinstance(histograms, dict):
        return None
    storm_block = _dict_path_get(histograms, "storm", hist_key)
    cmcc_block = _dict_path_get(histograms, "storm_cmcc", hist_key)
    if not isinstance(storm_block, dict) or not isinstance(cmcc_block, dict):
        return None
    storm_bins_mps = [_safe_float(value) for value in storm_block.get("bins_mps") or []]
    cmcc_bins_mps = [_safe_float(value) for value in cmcc_block.get("bins_mps") or []]
    storm_bins = [round(value * 3.6, 1) for value in storm_bins_mps]
    cmcc_bins = [round(value * 3.6, 1) for value in cmcc_bins_mps]
    if not storm_bins or storm_bins != cmcc_bins:
        return None
    storm_values = [_safe_float(value) for value in storm_block.get("percent") or []]
    cmcc_values = [_safe_float(value) for value in cmcc_block.get("percent") or []]
    if len(storm_bins) != len(storm_values) or len(cmcc_bins) != len(cmcc_values):
        return None

    def _point_labels(values: list[float]) -> list[str]:
        labels: list[str] = []
        for value in values:
            labels.append("" if value <= 0.0 else f"{value:.4g} %")
        return labels

    series = [
        {
            "name": HAZARD_LABELS["storm"],
            "x": storm_bins,
            "y": storm_values,
            **_hazard_line_series_style("storm"),
            "annotations": _point_labels(storm_values),
        },
        {
            "name": HAZARD_LABELS["storm_cmcc"],
            "x": cmcc_bins,
            "y": cmcc_values,
            **_hazard_line_series_style("storm_cmcc"),
            "annotations": _point_labels(cmcc_values),
        },
    ]
    if point_divisor > 1:
        series = [_downsample_line_series(item, point_divisor) for item in series]

    return {
        "type": "line",
        "title": title,
        "xlabel": "Vent maximum (km/h)",
        "ylabel": "Part des observations (%)",
        "series": series,
        "legacy_line_layout": True,
        "note": "Version allégée : un point sur deux est conservé pour améliorer la lisibilité." if point_divisor > 1 else None,
    }


def _build_damage_scenario_payload(artifacts: AuxiliaryArtifacts, family: str, title: str) -> dict[str, Any] | None:
    entries = _scientific_graph_scenario_rows(
        artifacts,
        graph_name=title,
        scenario="rp10",
        key="damage_breakdown_by_scenario",
    )
    if not isinstance(entries, dict):
        return None
    prefix = "eau_" if family == "water" else "elec_"
    storm_entries = entries.get("storm") if isinstance(entries.get("storm"), list) else []
    cmcc_entries = entries.get("storm_cmcc") if isinstance(entries.get("storm_cmcc"), list) else []
    storm_map = {
        str(item.get("class_key") or ""): item
        for item in storm_entries
        if isinstance(item, dict) and str(item.get("class_key") or "").startswith(prefix)
    }
    cmcc_map = {
        str(item.get("class_key") or ""): item
        for item in cmcc_entries
        if isinstance(item, dict) and str(item.get("class_key") or "").startswith(prefix)
    }
    class_keys = sorted(set(storm_map) | set(cmcc_map))
    if not class_keys:
        return None
    categories = [
        str(
            (storm_map.get(class_key) or cmcc_map.get(class_key) or {}).get("class_label")
            or class_key
        )
        for class_key in class_keys
    ]
    storm_values = [_safe_float((storm_map.get(class_key) or {}).get("damage_eur")) for class_key in class_keys]
    cmcc_values = [_safe_float((cmcc_map.get(class_key) or {}).get("damage_eur")) for class_key in class_keys]
    storm_label_texts = [
        _format_damage_share_label(
            _safe_float((storm_map.get(class_key) or {}).get("damage_eur")),
            _safe_float((storm_map.get(class_key) or {}).get("exposure_eur")),
        )
        for class_key in class_keys
    ]
    cmcc_label_texts = [
        _format_damage_share_label(
            _safe_float((cmcc_map.get(class_key) or {}).get("damage_eur")),
            _safe_float((cmcc_map.get(class_key) or {}).get("exposure_eur")),
        )
        for class_key in class_keys
    ]
    return {
        "type": "grouped_bar",
        "title": title,
        "categories": categories,
        "series": [
            {"name": HAZARD_LABELS["storm"], "values": storm_values, **_hazard_bar_series_style("storm", family=family)},
            {"name": HAZARD_LABELS["storm_cmcc"], "values": cmcc_values, **_hazard_bar_series_style("storm_cmcc", family=family)},
        ],
        "ylabel": "Degats directs (EUR)",
        "show_labels": True,
        "label_format": "compact_eur",
        "label_texts": [storm_label_texts, cmcc_label_texts],
        "label_fontsize": 7,
        "label_headroom_ratio": 0.26,
        "label_strategy": "grouped_bar_full_labels",
        "label_fontsize_target": 13,
        "allow_figure_autoscale": True,
        "label_lane_gap_pts": 6,
    }


def _collect_total_damage_by_return_period(
    artifacts: AuxiliaryArtifacts,
    family: str,
    graph_name: str,
) -> dict[str, Any] | None:
    damage_by_scenario = _scientific_graph_inputs(artifacts, graph_name=graph_name).get("damage_breakdown_by_scenario")
    if not isinstance(damage_by_scenario, dict):
        raise _strict_graph_source_error(
            artifacts,
            graph_name=graph_name,
            key_path="scientific_graph_inputs.damage_breakdown_by_scenario",
            detail="missing strict scientific scenario damage breakdown",
        )
    prefix = "eau_" if family == "water" else "elec_"
    scenario_labels = {
        "rp10": "RP10",
        "rp50": "RP50",
        "rp100": "RP100",
        "rp1000": "RP1000",
    }
    scenario_keys = [(scenario, scenario_labels[scenario]) for scenario in SCIENTIFIC_SCENARIOS]
    storm_values: list[float] = []
    cmcc_values: list[float] = []
    categories: list[str] = []
    for scenario_key, label in scenario_keys:
        scenario_block = damage_by_scenario.get(scenario_key) if isinstance(damage_by_scenario.get(scenario_key), dict) else {}
        if not scenario_block or (
            not isinstance(scenario_block.get("storm"), list)
            and not isinstance(scenario_block.get("storm_cmcc"), list)
        ):
            raise _strict_graph_source_error(
                artifacts,
                graph_name=graph_name,
                key_path=f"scientific_graph_inputs.damage_breakdown_by_scenario.{scenario_key}",
                detail="strict scientific return-period breakdown is unavailable; page-analysis is forbidden",
            )
        storm_entries = scenario_block.get("storm") if isinstance(scenario_block.get("storm"), list) else []
        cmcc_entries = scenario_block.get("storm_cmcc") if isinstance(scenario_block.get("storm_cmcc"), list) else []
        storm_total = sum(
            _safe_float(item.get("damage_eur"))
            for item in storm_entries
            if isinstance(item, dict) and str(item.get("class_key") or "").startswith(prefix)
        )
        cmcc_total = sum(
            _safe_float(item.get("damage_eur"))
            for item in cmcc_entries
            if isinstance(item, dict) and str(item.get("class_key") or "").startswith(prefix)
        )
        categories.append(label)
        storm_values.append(round(storm_total, 2))
        cmcc_values.append(round(cmcc_total, 2))
    if not any(value > 0.0 for value in [*storm_values, *cmcc_values]):
        return None
    family_total_value_eur = _resolve_family_total_value_eur(artifacts, family)
    return {
        "categories": categories,
        "values": {
            "storm": storm_values,
            "storm_cmcc": cmcc_values,
        },
        "family_total_value_eur": family_total_value_eur,
    }


def _line_series_for_return_period_damage(
    family: str,
    hazard: str,
    values: list[float],
    family_total_value_eur: float,
) -> dict[str, Any]:
    style = _hazard_line_series_style(hazard, family=family)
    return {
        "name": f"{DAMAGE_FAMILY_LABELS[family]} {HAZARD_LABELS[hazard]}",
        "x": list(range(len(values))),
        "y": values,
        "color": style["color"],
        "linestyle": style["linestyle"],
        "annotations": [_format_damage_share_label(value, family_total_value_eur) for value in values],
    }


def _build_total_damage_by_return_period_payload(artifacts: AuxiliaryArtifacts, family: str, title: str) -> dict[str, Any] | None:
    collected = _collect_total_damage_by_return_period(artifacts, family, title)
    if collected is None:
        return None
    categories = [str(value) for value in collected["categories"]]
    values = collected["values"]
    family_total_value_eur = _safe_float(collected.get("family_total_value_eur"))
    return {
        "type": "grouped_bar",
        "title": title,
        "categories": categories,
        "series": [
            {"name": HAZARD_LABELS["storm"], "values": values["storm"], **_hazard_bar_series_style("storm", family=family)},
            {"name": HAZARD_LABELS["storm_cmcc"], "values": values["storm_cmcc"], **_hazard_bar_series_style("storm_cmcc", family=family)},
        ],
        "ylabel": "Degats directs (EUR)",
        "show_labels": True,
        "label_format": "compact_eur",
        "label_texts": [
            [_format_damage_share_label(value, family_total_value_eur) for value in values["storm"]],
            [_format_damage_share_label(value, family_total_value_eur) for value in values["storm_cmcc"]],
        ],
        "label_fontsize": 7,
        "label_headroom_ratio": 0.26,
        "label_strategy": "grouped_bar_full_labels",
        "label_fontsize_target": 13,
        "allow_figure_autoscale": True,
        "label_lane_gap_pts": 6,
    }


def _build_total_damage_water_electric_by_return_period_payload(
    artifacts: AuxiliaryArtifacts,
    title: str,
) -> dict[str, Any] | None:
    water = _collect_total_damage_by_return_period(artifacts, "water", f"{title} - eau")
    electric = _collect_total_damage_by_return_period(artifacts, "electric", f"{title} - elec")
    if water is None and electric is None:
        return None

    categories = [str(value) for value in ((water or electric or {}).get("categories") or [])]
    series: list[dict[str, Any]] = []
    for family, collected in (("water", water), ("electric", electric)):
        if collected is None:
            continue
        values = collected["values"]
        family_total_value_eur = _safe_float(collected.get("family_total_value_eur"))
        for hazard in SUPPORTED_HAZARDS:
            series.append(
                _line_series_for_return_period_damage(
                    family,
                    hazard,
                    values[hazard],
                    family_total_value_eur,
                )
            )
    if not series:
        return None
    return {
        "type": "line",
        "title": title,
        "series": series,
        "xlabel": "Temps de retour",
        "ylabel": "Degats directs (EUR)",
        "label_strategy": "line_full_labels_with_callouts",
        "label_fontsize_target": 9,
        "figure_autoscale_mode": "both",
        "allow_leader_lines": True,
        "xticks": list(range(len(categories))),
        "xtick_labels": categories,
        "yaxis_format": "compact_eur",
        "note": "Courbes combinees eau/electricite; STORM est en trait plein et STORM_CMCC en pointille plus clair.",
    }


def _resolve_family_total_value_eur(artifacts: AuxiliaryArtifacts, family: str) -> float:
    prefix = "eau_" if family == "water" else "elec_"
    total_value = sum(
        _safe_float(item.get("exposure_eur"))
        for item in _complete_asset_results(artifacts)
        if str(item.get("asset_type") or "").startswith(prefix)
    )
    if total_value > 0.0:
        return round(total_value, 2)
    state_tables = _scientific_graph_inputs(artifacts, graph_name=f"{family}_family_total_value").get("state_damage_tables", {})
    if isinstance(state_tables, dict):
        for scenario in SCIENTIFIC_SCENARIOS:
            rows = state_tables.get(scenario)
            if not isinstance(rows, list):
                continue
            scenario_total = sum(
                _safe_float(_dict_path_get(item, "storm", "exposure_eur"))
                for item in rows
                if isinstance(item, dict) and str(item.get("class_key") or "").startswith(prefix)
            )
            if scenario_total > 0.0:
                return round(scenario_total, 2)
    return 0.0


def _network_state_length_weights(artifacts: AuxiliaryArtifacts) -> dict[str, float]:
    exposition = _page7_block(artifacts, "exposition")
    lengths = exposition.get("lengths_km") if isinstance(exposition, dict) and isinstance(exposition.get("lengths_km"), dict) else {}
    return {
        str(key): _safe_float(value)
        for key, value in lengths.items()
    }


def _aggregate_state_distribution_rows(
    rows: list[dict[str, Any]],
    *,
    hazard: str,
    class_keys: tuple[str, ...],
    length_weights: dict[str, float],
) -> dict[str, float]:
    rows_by_class = {
        str(item.get("class_key") or ""): item
        for item in rows
        if isinstance(item, dict)
    }
    totals = {state: 0.0 for state in STATE_SEQUENCE}
    total_weight = 0.0
    for class_key in class_keys:
        row = rows_by_class.get(class_key)
        if not isinstance(row, dict):
            continue
        hazard_block = row.get(hazard) if isinstance(row.get(hazard), dict) else {}
        state_pct = hazard_block.get("state_pct") if isinstance(hazard_block.get("state_pct"), dict) else {}
        weight = _safe_float(length_weights.get(class_key))
        if weight <= 0.0:
            weight = _safe_float(hazard_block.get("exposure_eur"))
        if weight <= 0.0:
            weight = 1.0
        total_weight += weight
        for state in STATE_SEQUENCE:
            totals[state] += weight * _safe_float(state_pct.get(state))
    if total_weight <= 0.0:
        return {state: 0.0 for state in STATE_SEQUENCE}
    return {
        state: round(totals[state] / total_weight, 3)
        for state in STATE_SEQUENCE
    }


def _damage_origin_shares_from_state_rows(
    rows: list[dict[str, Any]],
    *,
    hazard: str,
    class_keys: tuple[str, ...],
) -> dict[str, float] | None:
    rows_by_class = {
        str(item.get("class_key") or ""): item
        for item in rows
        if isinstance(item, dict)
    }
    direct = 0.0
    indirect = 0.0
    for class_key in class_keys:
        row = rows_by_class.get(class_key)
        if not isinstance(row, dict):
            continue
        hazard_block = row.get(hazard) if isinstance(row.get(hazard), dict) else {}
        direct += max(_safe_float(hazard_block.get("direct_damage_eur")), 0.0)
        indirect += max(_safe_float(hazard_block.get("indirect_damage_eur")), 0.0)
    total = direct + indirect
    if total <= 0.0:
        return None
    return {
        "direct": round((direct / total) * 100.0, 4),
        "indirect": round((indirect / total) * 100.0, 4),
    }


def _build_network_economic_damage_matrix_payload(
    artifacts: AuxiliaryArtifacts,
    hazard: str,
    title: str,
) -> dict[str, Any] | None:
    graph_inputs = _scientific_graph_inputs(artifacts, graph_name=title)
    state_tables = graph_inputs.get("state_damage_tables")
    if not isinstance(state_tables, dict):
        raise _strict_graph_source_error(
            artifacts,
            graph_name=title,
            key_path="scientific_graph_inputs.state_damage_tables",
            detail="missing strict scientific state damage tables",
        )
    cells: list[list[dict[str, float]]] = []
    damage_origin_cells: list[list[dict[str, float] | None]] = []
    has_non_zero = False
    for scenario_key, _scenario_label in NETWORK_STATE_MATRIX_SCENARIOS:
        rows = state_tables.get(scenario_key)
        if not isinstance(rows, list):
            raise _strict_graph_source_error(
                artifacts,
                graph_name=title,
                key_path=f"scientific_graph_inputs.state_damage_tables.{scenario_key}",
                detail="missing strict scientific state damage scenario",
            )
        scenario_cells: list[dict[str, float]] = []
        scenario_origin_cells: list[dict[str, float] | None] = []
        for _column_key, _column_label, class_keys in ECONOMIC_DAMAGE_MATRIX_COLUMNS:
            aggregated = _aggregate_state_distribution_rows(
                rows,
                hazard=hazard,
                class_keys=class_keys,
                length_weights={},
            )
            if any(_safe_float(aggregated.get(state)) > 0.0 for state in ("S1", "S2", "S3")):
                has_non_zero = True
            scenario_cells.append(aggregated)
            scenario_origin_cells.append(
                _damage_origin_shares_from_state_rows(
                    rows,
                    hazard=hazard,
                    class_keys=class_keys,
                )
            )
        cells.append(scenario_cells)
        damage_origin_cells.append(scenario_origin_cells)
    if not has_non_zero and not cells:
        return None
    return {
        "type": "network_state_matrix",
        "title": title,
        "column_titles": [label for _column_key, label, _class_keys in ECONOMIC_DAMAGE_MATRIX_COLUMNS],
        "row_titles": [label for _scenario_key, label in NETWORK_STATE_MATRIX_SCENARIOS],
        "cells": cells,
        "outage_cause_cells": damage_origin_cells,
        "ylabel": "% valeur exposee",
        "outage_cause_title": "Origine\ndommages",
        "outage_cause_legend_prefix": "Origine des dommages",
        "outage_cause_empty_label": "Dom.\n0%",
        "cause_bar_requires_s3": False,
        "percent_label_scale": MATRIX_PERCENT_LABEL_SCALE,
        "note": (
            "Matrice de criticite economique reconstruite depuis les state_damage_tables. "
            "Les etats S0-S3 sont agreges par valeur exposee pour les groupes multi-classes; cette figure ne represente pas un etat de service spatialise. "
            "Les petites barres ventilent les dommages entre dommages directs reseau et dommages indirects depuis ouvrages/dependances quand disponible."
        ),
    }


def _build_network_state_matrix_payload(
    artifacts: AuxiliaryArtifacts,
    hazard: str,
    title: str,
) -> dict[str, Any] | None:
    graph_inputs = _scientific_graph_inputs(artifacts, graph_name=title)
    scenario_distribution = graph_inputs.get("network_state_service_distribution_by_scenario")
    if not isinstance(scenario_distribution, dict):
        scientific_summary = _scientific_summary_payload(artifacts)
        scenario_distribution = _dict_path_get(scientific_summary, "network_states", "scenario_service_state_distribution")
    if not isinstance(scenario_distribution, dict):
        raise _strict_graph_source_error(
            artifacts,
            graph_name=title,
            key_path="scientific_graph_inputs.network_state_service_distribution_by_scenario",
            detail="missing strict scientific network-state service distribution",
        )
    cells: list[list[dict[str, float]]] = []
    outage_cause_cells: list[list[dict[str, float] | None]] = []
    has_non_zero = False
    for scenario_key, _scenario_label in NETWORK_STATE_MATRIX_SCENARIOS:
        scenario_hazard = _dict_path_get(scenario_distribution, scenario_key, hazard)
        if not isinstance(scenario_hazard, dict):
            raise _strict_graph_source_error(
                artifacts,
                graph_name=title,
                key_path=f"scientific_graph_inputs.network_state_service_distribution_by_scenario.{scenario_key}.{hazard}",
                detail="missing strict scientific network-state scenario",
            )
        scenario_cells: list[dict[str, float]] = []
        scenario_cause_cells: list[dict[str, float] | None] = []
        for column_key, _column_label, class_keys in NETWORK_STATE_MATRIX_COLUMNS:
            service_key = next(
                (
                    key
                    for key in class_keys
                    if isinstance(scenario_hazard.get(key), dict)
                ),
                class_keys[0],
            )
            counts = {
                state: int(_dict_path_get(scenario_hazard, service_key, state) or 0)
                for state in STATE_SEQUENCE
            }
            aggregated = _state_percentages(counts)
            if any(_safe_float(aggregated.get(state)) > 0.0 for state in ("S1", "S2", "S3")):
                has_non_zero = True
            scenario_cells.append(aggregated)
            if column_key in {"eau_aep", "eau_eu"} and _safe_float(aggregated.get("S3")) > 0.0:
                scenario_cause_cells.append(
                    _network_outage_cause_shares_from_geojson(
                        artifacts,
                        scenario_key,
                        hazard,
                        column_key,
                        class_keys,
                    )
                )
            else:
                scenario_cause_cells.append(None)
        cells.append(scenario_cells)
        outage_cause_cells.append(scenario_cause_cells)
    if not has_non_zero and not cells:
        return None
    return {
        "type": "network_state_matrix",
        "title": title,
        "column_titles": [label for _column_key, label, _class_keys in NETWORK_STATE_MATRIX_COLUMNS],
        "row_titles": [label for _scenario_key, label in NETWORK_STATE_MATRIX_SCENARIOS],
        "cells": cells,
        "outage_cause_cells": outage_cause_cells,
        "percent_label_scale": MATRIX_PERCENT_LABEL_SCALE,
        "note": (
            f"Chaque vignette montre la repartition des etats de service issus de network-states.geojson, de {_state_range_label('S0', 'S3')}, pour un scenario et un type d'infrastructure. "
            "Pour les reseaux d'eau, la petite barre a droite ventile l'origine directe/indirecte des hors services depuis les causes GeoJSON quand cette decomposition est disponible."
        ),
    }


def _build_network_state_chart_payload(artifacts: AuxiliaryArtifacts, network_key: str, metric_suffix: str, title: str) -> dict[str, Any] | None:
    service_key = _summary_service_key_for_network(network_key)
    if service_key is None:
        return None
    storm_counts = _network_state_counts_from_summary(
        artifacts,
        metric_suffix=metric_suffix,
        hazard="storm",
        service_key=service_key,
    )
    cmcc_counts = _network_state_counts_from_summary(
        artifacts,
        metric_suffix=metric_suffix,
        hazard="storm_cmcc",
        service_key=service_key,
    )
    if not storm_counts and not cmcc_counts:
        return None
    storm_pct = _state_percentages(storm_counts)
    cmcc_pct = _state_percentages(cmcc_counts)
    return {
        "type": "stacked_bar",
        "title": title,
        "categories": [HAZARD_LABELS["storm"], HAZARD_LABELS["storm_cmcc"]],
        "series": [
            {"name": _state_label("S0"), "values": [storm_pct.get("S0", 0.0), cmcc_pct.get("S0", 0.0)], "color": STATE_COLORS["S0"]},
            {"name": _state_label("S1"), "values": [storm_pct.get("S1", 0.0), cmcc_pct.get("S1", 0.0)], "color": HAZARD_COLORS["s1"]},
            {"name": _state_label("S2"), "values": [storm_pct.get("S2", 0.0), cmcc_pct.get("S2", 0.0)], "color": HAZARD_COLORS["s2"]},
            {"name": _state_label("S3"), "values": [storm_pct.get("S3", 0.0), cmcc_pct.get("S3", 0.0)], "color": HAZARD_COLORS["s3"]},
        ],
        "ylabel": "% des reseaux",
        "ymax": 100.0,
        "label_format": "percent",
    }


def _build_network_state_distribution_payload(artifacts: AuxiliaryArtifacts, metric_suffix: str, title: str) -> dict[str, Any] | None:
    categories = ["ELEC", "AEP", "EU"]
    series = []
    non_zero = False
    counts_by_network: dict[str, dict[str, float]] = {}
    for network_key in ("elec", "aep", "eu"):
        service_key = _summary_service_key_for_network(network_key)
        if service_key is None:
            continue
        counts = _network_state_counts_from_summary(
            artifacts,
            metric_suffix=metric_suffix,
            hazard="storm",
            service_key=service_key,
        )
        counts_by_network[network_key] = _state_percentages(counts)
    for state, color in (("S0", STATE_COLORS["S0"]), ("S1", HAZARD_COLORS["s1"]), ("S2", HAZARD_COLORS["s2"]), ("S3", HAZARD_COLORS["s3"])):
        values = []
        for network_key in ("elec", "aep", "eu"):
            values.append(counts_by_network.get(network_key, {}).get(state, 0.0))
        non_zero = non_zero or any(value > 0 for value in values)
        series.append({"name": _state_label(state), "values": values, "color": color})
    if not non_zero:
        return None
    return {
        "type": "stacked_bar",
        "title": title,
        "categories": categories,
        "series": series,
        "ylabel": "% des reseaux",
        "ymax": 100.0,
        "label_format": "percent",
        "note": "Distribution par reseau sur le scenario STORM (climat actuel).",
    }


def _build_state_summary_rows(entries: list[dict[str, Any]], metric_key: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for item in entries:
        class_label = str(item.get("class_label") or item.get("class_key") or "")
        storm = item.get("storm") if isinstance(item.get("storm"), dict) else {}
        cmcc = item.get("storm_cmcc") if isinstance(item.get("storm_cmcc"), dict) else {}
        storm_value = _safe_float(storm.get(metric_key))
        cmcc_value = _safe_float(cmcc.get(metric_key))
        ratio = f"{(cmcc_value / storm_value):.2f}x" if storm_value > 0.0 else "n/a"
        rows.append(
            [
                class_label,
                _format_compact_eur(storm_value),
                _format_compact_eur(cmcc_value),
                ratio,
            ]
        )
    return rows


def _build_impact_table_payload(artifacts: AuxiliaryArtifacts, table_kind: str, title: str) -> dict[str, Any] | None:
    if table_kind == "rp1000":
        entries = _scientific_graph_scenario_rows(
            artifacts,
            graph_name=title,
            scenario="rp1000",
            key="state_damage_tables",
        )
        metric_key = "damage_eur"
    else:
        entries = _scientific_graph_scenario_rows(
            artifacts,
            graph_name=title,
            scenario="rp100",
            key="state_damage_tables",
        )
        metric_key = "damage_eur"
    if not isinstance(entries, list):
        return None
    rows = _build_state_summary_rows([item for item in entries if isinstance(item, dict)], metric_key)
    if not rows:
        return None
    return {
        "type": "table",
        "title": title,
        "headers": ["Classe", "STORM", "STORM_CMCC", "Ratio CMCC/STORM"],
        "rows": rows,
    }


def _build_hazard_comparison_csv_rows(artifacts: AuxiliaryArtifacts) -> tuple[list[str], list[list[str]]] | None:
    rows = _page7_block(artifacts, "hazard", "zone_wind_comparison_table")
    if not isinstance(rows, list):
        return None
    output_rows: list[list[str]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        output_rows.append(
            [
                str(item.get("indicator") or ""),
                _format_number(item.get("storm")),
                _format_number(item.get("storm_cmcc")),
                _format_number(item.get("delta")),
            ]
        )
    if not output_rows:
        return None
    return ["indicator", "storm", "storm_cmcc", "delta"], output_rows


def _build_hazard_comparison_table_payload(artifacts: AuxiliaryArtifacts, title: str) -> dict[str, Any] | None:
    comparison = _build_hazard_comparison_csv_rows(artifacts)
    if comparison is None:
        return None
    headers, rows = comparison
    return {"type": "table", "title": title, "headers": headers, "rows": rows}


def _build_exposure_network_table_payload(artifacts: AuxiliaryArtifacts, title: str) -> dict[str, Any] | None:
    exposition = _page7_block(artifacts, "exposition")
    if not isinstance(exposition, dict):
        return None
    lengths = exposition.get("lengths_km") if isinstance(exposition.get("lengths_km"), dict) else {}
    values_per_km = exposition.get("value_per_km_eur") if isinstance(exposition.get("value_per_km_eur"), dict) else {}
    totals = exposition.get("total_value_by_type_eur") if isinstance(exposition.get("total_value_by_type_eur"), dict) else {}
    rows: list[list[str]] = []
    total_networks = 0.0
    for key in NETWORK_EXPOSURE_ORDER:
        total = _safe_float(totals.get(key))
        total_networks += total
        rows.append(
            [
                NETWORK_EXPOSURE_LABELS.get(key, key),
                _format_number(lengths.get(key)),
                _format_number(values_per_km.get(key)),
                _format_eur(total),
            ]
        )
    if not rows:
        return None
    rows.append(["Total reseaux", "—", "—", _format_eur(total_networks)])
    return {
        "type": "table",
        "title": title,
        "headers": ["Reseau", "Longueur (km)", "Valeur / km (EUR)", "Valorisation totale (EUR)"],
        "rows": rows,
    }


def _build_exposure_ouvrage_table_payload(artifacts: AuxiliaryArtifacts, title: str) -> dict[str, Any] | None:
    exposition = _page7_block(artifacts, "exposition")
    if not isinstance(exposition, dict):
        return None
    counts = exposition.get("counts") if isinstance(exposition.get("counts"), dict) else {}
    totals = exposition.get("total_value_by_type_eur") if isinstance(exposition.get("total_value_by_type_eur"), dict) else {}
    valuation = exposition.get("valuation_metadata") if isinstance(exposition.get("valuation_metadata"), dict) else {}
    new_values = valuation.get("new_values") if isinstance(valuation.get("new_values"), dict) else {}
    rows = [
        [
            OUVRAGE_EXPOSURE_LABELS["eau_aep_ouvrages"],
            _format_number(counts.get("aep_ouvrages_total")),
            "Depend du type d'ouvrage",
            _format_eur(totals.get("eau_aep_ouvrages")),
        ],
        [
            OUVRAGE_EXPOSURE_LABELS["eau_eu_pr"],
            _format_number(counts.get("eu_pr_total")),
            _format_number(new_values.get("eu_pr_eur_per_unit")),
            _format_eur(totals.get("eau_eu_pr")),
        ],
        [
            OUVRAGE_EXPOSURE_LABELS["eau_eu_step"],
            _format_number(counts.get("eu_step_total")),
            _format_number(new_values.get("eu_step_eur_per_unit")),
            _format_eur(totals.get("eau_eu_step")),
        ],
    ]
    total_ouvrages = sum(_safe_float(totals.get(key)) for key in OUVRAGE_EXPOSURE_LABELS)
    rows.append(["Total ouvrages", "—", "—", _format_eur(total_ouvrages)])
    return {
        "type": "table",
        "title": title,
        "headers": ["Ouvrage", "Nombre", "Valeur unitaire (EUR)", "Valorisation totale (EUR)"],
        "rows": rows,
    }


def _build_social_impact_table_payload(artifacts: AuxiliaryArtifacts, title: str) -> dict[str, Any] | None:
    scientific_summary = _scientific_summary_payload(artifacts)
    summary = _dict_path_get(scientific_summary, "social_impact", "scenario_summary", "rp1000")
    storm = summary.get("storm") if isinstance(summary, dict) and isinstance(summary.get("storm"), dict) else {}
    cmcc = summary.get("storm_cmcc") if isinstance(summary, dict) and isinstance(summary.get("storm_cmcc"), dict) else {}
    if not storm and not cmcc:
        raise _strict_graph_source_error(
            artifacts,
            graph_name=title,
            key_path="social_impact.scenario_summary.rp1000",
            detail="missing strict scientific social impact rp1000 summary",
        )
    metric_rows = [
        (f"Population totale affectee ({_state_join_label(('S1', 'S2', 'S3'))})", "total_population_affected_any_network"),
        (f"Population sans electricite ({_state_label('S3')})", "total_without_elec"),
        (f"Population sans eau potable AEP ({_state_label('S3')})", "total_without_eau_aep"),
        (f"Population sans eau EU ({_state_label('S3')})", "total_without_eau_eu"),
        (f"Population electricite degradee ({_state_join_label(('S1', 'S2'))})", "total_with_degraded_elec"),
        (f"Population eau potable degradee ({_state_join_label(('S1', 'S2'))})", "total_with_degraded_eau_aep"),
        (f"Population eau EU degradee ({_state_join_label(('S1', 'S2'))})", "total_with_degraded_eau_eu"),
    ]
    rows: list[list[str]] = []
    for label, key in metric_rows:
        storm_value = _safe_float(storm.get(key))
        cmcc_value = _safe_float(cmcc.get(key))
        rows.append(
            [
                label,
                str(int(round(storm_value))),
                str(int(round(cmcc_value))),
                str(int(round(cmcc_value - storm_value))),
            ]
        )
    return {
        "type": "table",
        "title": title,
        "headers": ["Indicateur", "STORM", "STORM_CMCC", "Delta"],
        "rows": rows,
        "note": "Les metriques sociales publiees ici proviennent strictement du scenario scientifique RP1000.",
    }


def _build_population_coverage_table_payload(artifacts: AuxiliaryArtifacts, title: str) -> dict[str, Any] | None:
    scientific_summary = _scientific_summary_payload(artifacts)
    distributions = _dict_path_get(scientific_summary, "social_impact", "scenario_population_state_distribution", "rp1000")
    storm_distribution = distributions.get("storm") if isinstance(distributions, dict) and isinstance(distributions.get("storm"), dict) else {}
    if not storm_distribution:
        raise _strict_graph_source_error(
            artifacts,
            graph_name=title,
            key_path="social_impact.scenario_population_state_distribution.rp1000.storm",
            detail="missing strict scientific population-state distribution for rp1000/storm",
        )
    rows: list[list[str]] = []
    service_rows = [
        ("Electricite", "elec"),
        ("Eau potable AEP", "eau_aep"),
        ("Eau EU", "eau_eu"),
    ]
    for label, service_key in service_rows:
        metrics = storm_distribution.get(service_key) if isinstance(storm_distribution.get(service_key), dict) else {}
        if not metrics:
            continue
        total_population = sum(_safe_float(metrics.get(state)) for state in STATE_SEQUENCE)
        rows.append(
            [
                label,
                str(int(round(total_population))),
                str(int(round(total_population))),
                _format_percent(100.0 if total_population > 0.0 else 0.0),
            ]
        )
    if not rows:
        return None
    return {
        "type": "table",
        "title": title,
        "headers": ["Service", "Population totale", "Population couverte", "% population couverte"],
        "rows": rows,
        "note": "La table est reconstruite a partir de la distribution scientifique de population par etat de service au scenario RP1000/STORM.",
    }


def _build_population_output_specs(artifacts: AuxiliaryArtifacts) -> list[tuple[str, dict[str, Any] | None]]:
    if artifacts.territory != "guadeloupe":
        return []
    territory_name = territory_label(artifacts.territory)
    return [
        (
            "carte_population_guadeloupe.png",
            _build_population_overlay_map_payload(artifacts, f"{territory_name} - Carte de population"),
        ),
        (
            "superplot_hotspots_population_affectee.png",
            _build_population_hotspot_superplot_payload(artifacts, f"{territory_name} - Hotspots population affectee"),
        ),
        (
            "importance_zonages_hydrauliques_aep.png",
            _build_hydraulic_population_importance_payload(artifacts, f"{territory_name} - Importance des zonages hydrauliques AEP"),
        ),
        (
            "matrice_population_etats_reseaux_storm.png",
            _build_population_state_matrix_payload(artifacts, "storm", f"{territory_name} - Matrice population etats reseaux STORM"),
        ),
        (
            "matrice_population_etats_reseaux_storm_cmcc.png",
            _build_population_state_matrix_payload(artifacts, "storm_cmcc", f"{territory_name} - Matrice population etats reseaux STORM_CMCC"),
        ),
        (
            "synthese_zones_population_storm_barres.png",
            _build_population_decision_bar_payload(artifacts, f"{territory_name} - Zones population principales STORM"),
        ),
        (
            "carte_zones_population_storm_decision.png",
            _build_population_decision_zone_map_payload(artifacts, f"{territory_name} - Localisation des zones population STORM"),
        ),
    ]


def _build_hazard_cell_points(artifacts: AuxiliaryArtifacts, hazard: str, field_name: str) -> list[dict[str, float]]:
    block = _wind_map_block(artifacts, hazard)
    if not block:
        return []
    points: list[dict[str, float]] = []
    for cell in block.get("cells") or []:
        if not isinstance(cell, dict) or field_name not in cell:
            continue
        lat = cell.get("lat")
        lon = cell.get("lon")
        value = cell.get(field_name)
        if lat is None or lon is None or value is None:
            continue
        points.append({"lat": float(lat), "lon": float(lon), "value": float(value)})
    return points


def _build_landslide_points(artifacts: AuxiliaryArtifacts) -> list[dict[str, float]]:
    block = _landslide_map_block(artifacts, "storm")
    if not block:
        return []
    points: list[dict[str, float]] = []
    for cell in block.get("cells") or []:
        if not isinstance(cell, dict):
            continue
        lat = cell.get("lat")
        lon = cell.get("lon")
        value = cell.get("mean_landslide_score")
        if lat is None or lon is None or value is None:
            continue
        points.append({"lat": float(lat), "lon": float(lon), "value": float(value)})
    return points


def _scale_points(points: list[dict[str, float]], factor: float) -> list[dict[str, float]]:
    if math.isclose(factor, 1.0):
        return [dict(point) for point in points]
    out: list[dict[str, float]] = []
    for point in points:
        value = point.get("value")
        if value is None:
            continue
        out.append(
            {
                "lat": float(point["lat"]),
                "lon": float(point["lon"]),
                "value": float(value) * factor,
            }
        )
    return out


def _build_hazard_scatter_map_payloads(artifacts: AuxiliaryArtifacts, territory: str) -> dict[str, dict[str, Any]]:
    territory_name = territory_label(territory)
    wind_rp50_points = _scale_points(_build_hazard_cell_points(artifacts, "storm", "rp50_wind_mps"), 3.6)
    wind_rp100_points = _scale_points(_build_hazard_cell_points(artifacts, "storm", "rp100_wind_mps"), 3.6)
    landslide_points = _build_landslide_points(artifacts)
    landslide_note = (
        "Le payload archive n'expose pas de couche glissement distincte par temps de retour; "
        "la vue reutilise le score moyen archive."
    )
    return {
        "wind_rp50": {
            "type": "scatter_map",
            "title": f"{territory_name} - Vent RP50",
            "points": wind_rp50_points,
            "cmap_colors": WIND_MAP_COLORS,
            "colorbar_label": "Vent RP50 (km/h)",
        },
        "wind_rp100": {
            "type": "scatter_map",
            "title": f"{territory_name} - Vent RP100",
            "points": wind_rp100_points,
            "cmap_colors": WIND_MAP_COLORS,
            "colorbar_label": "Vent RP100 (km/h)",
        },
        "rain_rp50": {
            "type": "scatter_map",
            "title": f"{territory_name} - Pluie RP50",
            "points": _build_hazard_cell_points(artifacts, "storm", "rp50_rain_mm"),
            "cmap": "GnBu",
            "colorbar_label": "Pluie RP50 (mm)",
        },
        "rain_rp100": {
            "type": "scatter_map",
            "title": f"{territory_name} - Pluie RP100",
            "points": _build_hazard_cell_points(artifacts, "storm", "rp100_rain_mm"),
            "cmap": "GnBu",
            "colorbar_label": "Pluie RP100 (mm)",
        },
        "surge_rp50": {
            "type": "scatter_map",
            "title": f"{territory_name} - Submersion cotiere RP50",
            "points": _build_hazard_cell_points(artifacts, "storm", "rp50_surge_m"),
            "cmap_colors": SURGE_COLORS,
            "colorbar_label": "Submersion RP50 (m)",
        },
        "surge_rp100": {
            "type": "scatter_map",
            "title": f"{territory_name} - Submersion cotiere RP100",
            "points": _build_hazard_cell_points(artifacts, "storm", "rp100_surge_m"),
            "cmap_colors": SURGE_COLORS,
            "colorbar_label": "Submersion RP100 (m)",
        },
        "landslide_rp50": {
            "type": "scatter_map",
            "title": f"{territory_name} - Mouvements de terrain RP50",
            "points": landslide_points,
            "cmap_colors": LANDSLIDE_COLORS,
            "colorbar_label": "Score mouvement de terrain",
            "note": landslide_note,
        },
        "landslide_rp100": {
            "type": "scatter_map",
            "title": f"{territory_name} - Mouvements de terrain RP100",
            "points": landslide_points,
            "cmap_colors": LANDSLIDE_COLORS,
            "colorbar_label": "Score mouvement de terrain",
            "note": landslide_note,
        },
        "landslide_mean": {
            "type": "scatter_map",
            "title": f"{territory_name} - Mouvements de terrain",
            "points": landslide_points,
            "cmap_colors": LANDSLIDE_COLORS,
            "colorbar_label": "Score mouvement de terrain",
        },
    }


def _resolve_scatter_value_bounds(
    point_groups: list[list[dict[str, float]]],
    *,
    lower_pad_ratio: float = 0.0,
    upper_pad_ratio: float = 0.0,
    floor_zero: bool = False,
) -> tuple[float, float] | None:
    values = [float(point["value"]) for points in point_groups for point in points if isinstance(point, dict) and point.get("value") is not None]
    if not values:
        return None
    lower = min(values)
    upper = max(values)
    if math.isclose(lower, upper):
        pad = max(abs(lower) * 0.05, 1.0)
        lower -= pad
        upper += pad
    span = max(upper - lower, 1.0)
    lower -= span * max(lower_pad_ratio, 0.0)
    upper += span * max(upper_pad_ratio, 0.0)
    if floor_zero:
        lower = max(0.0, lower)
    return lower, upper


def _build_guadeloupe_hazard_supergraph_payload(artifacts: AuxiliaryArtifacts, territory: str) -> dict[str, Any] | None:
    if territory != "guadeloupe":
        return None
    map_payloads = _build_hazard_scatter_map_payloads(artifacts, territory)
    rows = [
        {"key": "rp50", "label": "RP50"},
        {"key": "rp100", "label": "RP100"},
    ]
    columns = [
        {"key": "wind", "label": "Vent", "colorbar_label": "Vent (km/h)", "upper_pad_ratio": 0.08, "force_zero_baseline": True, "round_step": 25.0},
        {"key": "rain", "label": "Pluie", "colorbar_label": "Pluie (mm)", "upper_pad_ratio": 0.08, "force_zero_baseline": True, "round_step": 50.0},
        {"key": "surge", "label": "Inondation cotiere", "colorbar_label": "Submersion (m)"},
        {"key": "landslide", "label": "Mouvements de terrain", "colorbar_label": "Score glissement"},
    ]
    cells: list[list[dict[str, Any]]] = []
    for row in rows:
        row_cells: list[dict[str, Any]] = []
        for column in columns:
            row_cells.append(dict(map_payloads[f"{column['key']}_{row['key']}"]))
        cells.append(row_cells)

    for column_index in range(len(columns)):
        column = columns[column_index]
        bounds = _resolve_scatter_value_bounds(
            [cells[row_index][column_index].get("points") or [] for row_index in range(len(rows))],
            lower_pad_ratio=float(column.get("lower_pad_ratio") or 0.0),
            upper_pad_ratio=float(column.get("upper_pad_ratio") or 0.0),
            floor_zero=bool(column.get("floor_zero")),
        )
        if bounds is None:
            continue
        if bool(column.get("force_zero_baseline")):
            step = max(_safe_float(column.get("round_step"), default=1.0), 1.0)
            upper = max(bounds[1], 1.0)
            bounds = (0.0, math.ceil(upper / step) * step)
        for row_index in range(len(rows)):
            cells[row_index][column_index]["vmin"] = bounds[0]
            cells[row_index][column_index]["vmax"] = bounds[1]

    return {
        "type": "scatter_map_grid",
        "title": f"{territory_label(territory)} - Supergraph des aleas RP50 et RP100",
        "rows": rows,
        "columns": columns,
        "cells": cells,
    }


def _build_global_basin_payload(artifacts_by_territory: dict[str, AuxiliaryArtifacts]) -> dict[str, Any] | None:
    palette = {
        "guadeloupe": "#0f766e",
        "martinique": "#c2410c",
        "saint-barthelemy": "#2563eb",
    }
    series: list[dict[str, Any]] = []
    for territory, artifacts in artifacts_by_territory.items():
        points = _build_hazard_cell_points(artifacts, "storm", "event_max_wind_mps")
        if not points:
            continue
        series.append(
            {
                "name": territory_label(territory),
                "points": [{"lat": point["lat"], "lon": point["lon"]} for point in points],
                "color": palette.get(territory, "#64748b"),
                "size": 55,
            }
        )
    if not series:
        return None
    return {
        "type": "multi_scatter_map",
        "title": "Bassin NA - visualisation alea zone complete",
        "series": series,
        "note": "Synthese globale des cellules archivees utilisees pour les cartes de vent RP100 (scenario STORM).",
    }


def _write_csv_table(output_path: Path, headers: list[str], rows: list[list[str]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def _write_table_payload_csv(output_path: Path, payload: dict[str, Any]) -> None:
    headers = [str(item) for item in payload.get("headers") or []]
    rows = [
        [str(cell) for cell in row]
        for row in payload.get("rows") or []
        if isinstance(row, list)
    ]
    _write_csv_table(output_path, headers, rows)


def _resolve_archived_artifact_path(bundle: TerritoryPayload, raw_path: Any) -> Path | None:
    if not raw_path:
        return None
    path = Path(str(raw_path))
    if path.is_absolute():
        return path
    return Path(bundle.payload_path).resolve().parent / path


def _build_targeted_trajectory_map_payload(
    territory: str,
    bundle: TerritoryPayload,
) -> dict[str, Any] | None:
    meta = bundle.payload.get("meta") if isinstance(bundle.payload.get("meta"), dict) else {}
    geojson_path = _resolve_archived_artifact_path(bundle, meta.get("targeted_cyclone_track_segments_geojson"))
    if geojson_path is None or not geojson_path.exists():
        return None
    return {
        "type": "geojson_map",
        "title": f"{territory_label(territory)} - Trajectoire du cyclone transposee",
        "geojson_path": str(geojson_path),
        "color_column": "saffir_simpson_category",
        "color_map": TARGETED_TRAJECTORY_CATEGORY_COLORS,
        "legend_labels": TARGETED_TRAJECTORY_CATEGORY_LABELS,
        "category_order": ["-1", "0", "1", "2", "3", "4", "5"],
        "legend_title": "Saffir-Simpson",
        "line_width": 3.2,
        "note": (
            "La trajectoire transposée est colorée par catégorie Saffir-Simpson, "
            "calculée à partir du vent maximum soutenu segment par segment."
        ),
    }


def _render_targeted_event_assets(
    record: RunRecord,
    payloads: dict[str, TerritoryPayload],
    output_dir: Path,
) -> tuple[list[str], list[str]]:
    tables_dir = output_dir / "tables"
    maps_dir = output_dir / "maps"
    if tables_dir.exists():
        shutil.rmtree(tables_dir)
    if maps_dir.exists():
        shutil.rmtree(maps_dir)
    tables_dir.mkdir(parents=True, exist_ok=True)
    maps_dir.mkdir(parents=True, exist_ok=True)

    generated_paths: list[str] = []
    warnings: list[str] = []
    _, plt = _load_matplotlib()
    for territory, bundle in sorted(payloads.items()):
        payload = bundle.payload
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        selected_cyclones = meta.get("selected_cyclones") if isinstance(meta.get("selected_cyclones"), list) else []
        trajectory_map_payload = _build_targeted_trajectory_map_payload(territory, bundle)
        trajectory_map_path = maps_dir / f"{territory}_trajectoire_cyclone_saffir_simpson.png"
        if trajectory_map_payload is None:
            warnings.append(_warning_message(territory, trajectory_map_path.name, "missing targeted trajectory geojson"))
        else:
            try:
                _render_auxiliary_output(plt, trajectory_map_path, trajectory_map_payload)
                generated_paths.append(str(trajectory_map_path))
            except Exception as exc:
                warnings.append(_warning_message(territory, trajectory_map_path.name, f"render failed: {type(exc).__name__}: {exc}"))
        if selected_cyclones:
            rows: list[list[str]] = []
            for item in selected_cyclones:
                if not isinstance(item, dict):
                    continue
                transposition = item.get("transposition") if isinstance(item.get("transposition"), dict) else {}
                rows.append(
                    [
                        str(item.get("preset_id") or ""),
                        str(item.get("storm_id") or ""),
                        str(item.get("name") or item.get("original_name") or ""),
                        str(item.get("season") or ""),
                        str(item.get("basin") or ""),
                        _format_number(transposition.get("lat_shift")),
                        _format_number(transposition.get("lon_shift")),
                    ]
                )
            if rows:
                output_path = tables_dir / f"{territory}_cyclones_selection.csv"
                _write_csv_table(
                    output_path,
                    ["preset_id", "storm_id", "name", "season", "basin", "lat_shift", "lon_shift"],
                    rows,
                )
                generated_paths.append(str(output_path))

        for hazard in _available_hazards_for_payload(payload):
            events = _extract_event_list(payload, hazard)
            if not events:
                continue
            rows = []
            for index, event in enumerate(events, start=1):
                rows.append(
                    [
                        str(index),
                        str(event.get("event_id") or ""),
                        str(event.get("event_name") or ""),
                        _format_number(event.get("loss_eur")),
                        _format_number(event.get("frequency_annual")),
                        _format_number(event.get("return_period_years_approx")),
                    ]
                )
            output_path = tables_dir / f"{territory}_{hazard}_top_events.csv"
            _write_csv_table(
                output_path,
                ["rank", "event_id", "event_name", "loss_eur", "frequency_annual", "return_period_years_approx"],
                rows,
            )
            generated_paths.append(str(output_path))

    if not generated_paths:
        warnings.append(f"No targeted event CSV tables were generated for run {record.run_id}")
    return generated_paths, warnings


def _render_damage_zone_assets_from_artifacts(
    plt: Any,
    artifacts_by_territory: dict[str, AuxiliaryArtifacts],
    output_dir: Path,
    *,
    clean: bool = False,
) -> tuple[list[str], list[str]]:
    damage_zones_dir = output_dir / DAMAGE_ZONE_OUTPUT_DIRNAME
    if clean and damage_zones_dir.exists():
        shutil.rmtree(damage_zones_dir)
    damage_zones_dir.mkdir(parents=True, exist_ok=True)
    generated_paths: list[str] = []
    warnings: list[str] = []
    for territory, artifacts in artifacts_by_territory.items():
        specs, build_warnings = _build_damage_zone_output_specs(artifacts, territory)
        warnings.extend(build_warnings)
        for file_name, payload in specs:
            output_path = damage_zones_dir / file_name
            try:
                _render_auxiliary_output(plt, output_path, payload)
                generated_paths.append(str(output_path))
            except Exception as exc:
                warnings.append(_warning_message(territory, output_path.name, f"render failed: {type(exc).__name__}: {exc}"))
    return sorted(generated_paths), warnings


def _render_damage_zone_assets(
    record: RunRecord,
    payloads: dict[str, TerritoryPayload],
    output_dir: Path,
    *,
    clean: bool = False,
) -> tuple[list[str], list[str]]:
    _, plt = _load_matplotlib()
    artifacts_by_territory = {territory: _load_auxiliary_artifacts(record, bundle) for territory, bundle in payloads.items()}
    return _render_damage_zone_assets_from_artifacts(plt, artifacts_by_territory, output_dir, clean=clean)


def _render_integrated_vincennes_assets(
    record: RunRecord,
    payloads: dict[str, TerritoryPayload],
    output_dir: Path,
) -> tuple[list[str], list[str]]:
    _, plt = _load_matplotlib()
    _clean_output_categories(output_dir)
    artifacts_by_territory = {territory: _load_auxiliary_artifacts(record, bundle) for territory, bundle in payloads.items()}
    generated_paths: list[str] = []
    warnings: list[str] = []

    charts_dir = output_dir / "charts"
    maps_dir = output_dir / "maps"
    tables_dir = output_dir / "tables"
    population_dir = output_dir / "Population"
    damage_zones_dir = output_dir / DAMAGE_ZONE_OUTPUT_DIRNAME
    charts_dir.mkdir(parents=True, exist_ok=True)
    maps_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)
    population_dir.mkdir(parents=True, exist_ok=True)
    damage_zones_dir.mkdir(parents=True, exist_ok=True)

    for territory, artifacts in artifacts_by_territory.items():
        hazard_map_payloads = _build_hazard_scatter_map_payloads(artifacts, territory)
        chart_specs = [
            (charts_dir / f"{territory}_vent_max_par_annee.png", _build_wind_hist_payload(artifacts, "year_max_hist", f"{territory_label(territory)} - Vent max par annee")),
            (charts_dir / f"{territory}_vent_max_par_evenement.png", _build_wind_hist_payload(artifacts, "track_max_hist", f"{territory_label(territory)} - Vent max par evenement")),
            (charts_dir / f"{territory}_vent_max_par_annee_1_point_sur_2.png", _build_wind_hist_payload(artifacts, "year_max_hist", f"{territory_label(territory)} - Vent max par annee", point_divisor=2)),
            (charts_dir / f"{territory}_vent_max_par_evenement_1_point_sur_2.png", _build_wind_hist_payload(artifacts, "track_max_hist", f"{territory_label(territory)} - Vent max par evenement", point_divisor=2)),
            (charts_dir / f"{territory}_degats_eau_par_scenario_labels.png", _build_damage_scenario_payload(artifacts, "water", f"{territory_label(territory)} - Degats eau par classe RP10")),
            (charts_dir / f"{territory}_degats_elec_par_scenario_labels.png", _build_damage_scenario_payload(artifacts, "electric", f"{territory_label(territory)} - Degats electricite par classe RP10")),
            (charts_dir / f"{territory}_degats_eau_totaux_par_temps_retour_labels.png", _build_total_damage_by_return_period_payload(artifacts, "water", f"{territory_label(territory)} - Degats eau dans les scenarios globaux de retour")),
            (charts_dir / f"{territory}_degats_elec_totaux_par_temps_retour_labels.png", _build_total_damage_by_return_period_payload(artifacts, "electric", f"{territory_label(territory)} - Degats electricite dans les scenarios globaux de retour")),
            (charts_dir / f"{territory}_degats_eau_elec_totaux_par_temps_retour_labels.png", _build_total_damage_water_electric_by_return_period_payload(artifacts, f"{territory_label(territory)} - Degats eau/electricite dans les scenarios globaux de retour")),
            (charts_dir / f"{territory}_matrice_etats_reseaux_storm.png", _build_network_state_matrix_payload(artifacts, "storm", f"{territory_label(territory)} - Matrice etats reseaux STORM")),
            (charts_dir / f"{territory}_matrice_etats_reseaux_storm_cmcc.png", _build_network_state_matrix_payload(artifacts, "storm_cmcc", f"{territory_label(territory)} - Matrice etats reseaux STORM_CMCC")),
            (charts_dir / f"{territory}_matrice_criticite_economique_reseaux_storm.png", _build_network_economic_damage_matrix_payload(artifacts, "storm", f"{territory_label(territory)} - Matrice criticite economique reseaux STORM")),
            (charts_dir / f"{territory}_matrice_criticite_economique_reseaux_storm_cmcc.png", _build_network_economic_damage_matrix_payload(artifacts, "storm_cmcc", f"{territory_label(territory)} - Matrice criticite economique reseaux STORM_CMCC")),
        ]
        for output_path, payload in chart_specs:
            if payload is None:
                warnings.append(_warning_message(territory, output_path.name, "missing archived inputs"))
                continue
            try:
                _render_auxiliary_output(plt, output_path, payload)
                generated_paths.append(str(output_path))
            except Exception as exc:
                warnings.append(_warning_message(territory, output_path.name, f"render failed: {type(exc).__name__}: {exc}"))

        service_rp_payload = _build_service_rp_curve_payload(
            record,
            artifacts,
            f"{territory_label(territory)} - Courbes RP par service eau/elec",
        )
        service_rp_chart_path = charts_dir / f"{territory}_courbes_rp_eau_elec_par_service.png"
        if service_rp_payload is None:
            warnings.append(_warning_message(territory, service_rp_chart_path.name, "missing service RP checkpoint inputs"))
        else:
            try:
                _render_auxiliary_output(plt, service_rp_chart_path, service_rp_payload)
                generated_paths.append(str(service_rp_chart_path))
                service_rp = _compute_service_rp_curves_from_checkpoints(record, artifacts)
                rows = list((service_rp or {}).get("rows") or [])
                _write_csv_table(
                    tables_dir / f"{territory}_courbes_rp_eau_elec_par_service.csv",
                    [
                        "territory",
                        "service",
                        "hazard",
                        "return_period_years",
                        "damage_eur",
                        "quality",
                        "mixed_shards",
                        "total_shards",
                    ],
                    [
                        [
                            str(row.get("territory") or ""),
                            str(row.get("service") or ""),
                            str(row.get("hazard") or ""),
                            str(row.get("return_period_years") or ""),
                            f"{float(row.get('damage_eur') or 0.0):.6f}",
                            str(row.get("quality") or ""),
                            str(row.get("mixed_shards") or 0),
                            str(row.get("total_shards") or 0),
                        ]
                        for row in rows
                    ],
                )
                generated_paths.append(str(tables_dir / f"{territory}_courbes_rp_eau_elec_par_service.csv"))
            except Exception as exc:
                warnings.append(_warning_message(territory, service_rp_chart_path.name, f"service RP render failed: {type(exc).__name__}: {exc}"))

        map_specs = [
            (
                maps_dir / f"{territory}_aep_canalisations.png",
                {
                    "type": "geojson_map",
                    "title": f"{territory_label(territory)} - AEP canalisations",
                    "geojson_path": artifacts.water_infra_path,
                    "filter_column": "infra_type",
                    "filter_values": ["aep_cana"],
                    "color": "#0f766e",
                } if artifacts.water_infra_path else None,
            ),
            (
                maps_dir / f"{territory}_haute_tension_souterrain.png",
                {
                    "type": "geojson_map",
                    "title": f"{territory_label(territory)} - Haute tension souterrain",
                    "geojson_path": artifacts.water_infra_path,
                    "filter_column": "infra_type",
                    "filter_values": ["elec_hta_souterrain"],
                    "color": ELECTRIC_NETWORK_MAP_COLOR,
                } if artifacts.water_infra_path else None,
            ),
            (
                maps_dir / f"{territory}_etat_reseaux_aep_retour_1000_ans.png",
                {
                    "type": "geojson_map",
                    "title": f"{territory_label(territory)} - Etat reseaux AEP retour 1000 ans",
                    "geojson_path": artifacts.network_states_path,
                    "source_geojson_path": artifacts.water_infra_path,
                    "filter_column": "layer_key",
                    "filter_values": ["eau_aep"],
                    "state_column": "state_rp1000_storm",
                } if artifacts.network_states_path else None,
            ),
            (
                maps_dir / f"{territory}_etat_reseaux_aep_retour_100_ans.png",
                {
                    "type": "geojson_map",
                    "title": f"{territory_label(territory)} - Etat reseaux AEP retour 100 ans",
                    "geojson_path": artifacts.network_states_path,
                    "source_geojson_path": artifacts.water_infra_path,
                    "filter_column": "layer_key",
                    "filter_values": ["eau_aep"],
                    "state_column": "state_rp100_storm",
                } if artifacts.network_states_path else None,
            ),
            (
                maps_dir / f"{territory}_etat_reseaux_elec_aerien_retour_1000_ans.png",
                {
                    "type": "geojson_map",
                    "title": f"{territory_label(territory)} - Etat reseaux ELEC aerien retour 1000 ans",
                    "geojson_path": artifacts.network_states_path,
                    "source_geojson_path": artifacts.water_infra_path,
                    "filter_column": "layer_key",
                    "filter_values": ["elec_grid_0p1deg", "elec_bt_aerien", "elec_hta_aerien"],
                    "source_filter_values": ["elec_bt_aerien", "elec_hta_aerien"],
                    "state_column": "state_rp1000_storm",
                } if artifacts.network_states_path else None,
            ),
            (
                maps_dir / f"{territory}_etat_reseaux_elec_aerien_retour_100_ans.png",
                {
                    "type": "geojson_map",
                    "title": f"{territory_label(territory)} - Etat reseaux ELEC aerien retour 100 ans",
                    "geojson_path": artifacts.network_states_path,
                    "source_geojson_path": artifacts.water_infra_path,
                    "filter_column": "layer_key",
                    "filter_values": ["elec_grid_0p1deg", "elec_bt_aerien", "elec_hta_aerien"],
                    "source_filter_values": ["elec_bt_aerien", "elec_hta_aerien"],
                    "state_column": "state_rp100_storm",
                } if artifacts.network_states_path else None,
            ),
            (
                maps_dir / f"{territory}_etat_reseaux_elec_souterrain_retour_1000_ans.png",
                {
                    "type": "geojson_map",
                    "title": f"{territory_label(territory)} - Etat reseaux ELEC souterrain retour 1000 ans",
                    "geojson_path": artifacts.network_states_path,
                    "source_geojson_path": artifacts.water_infra_path,
                    "filter_column": "layer_key",
                    "filter_values": ["elec_grid_0p1deg", "elec_bt_souterrain", "elec_hta_souterrain"],
                    "source_filter_values": ["elec_bt_souterrain", "elec_hta_souterrain"],
                    "state_column": "state_rp1000_storm",
                } if artifacts.network_states_path else None,
            ),
            (
                maps_dir / f"{territory}_etat_reseaux_elec_souterrain_retour_100_ans.png",
                {
                    "type": "geojson_map",
                    "title": f"{territory_label(territory)} - Etat reseaux ELEC souterrain retour 100 ans",
                    "geojson_path": artifacts.network_states_path,
                    "source_geojson_path": artifacts.water_infra_path,
                    "filter_column": "layer_key",
                    "filter_values": ["elec_grid_0p1deg", "elec_bt_souterrain", "elec_hta_souterrain"],
                    "source_filter_values": ["elec_bt_souterrain", "elec_hta_souterrain"],
                    "state_column": "state_rp100_storm",
                } if artifacts.network_states_path else None,
            ),
            (
                maps_dir / f"{territory}_etat_reseaux_eu_retour_1000_ans.png",
                {
                    "type": "geojson_map",
                    "title": f"{territory_label(territory)} - Etat reseaux EU retour 1000 ans",
                    "geojson_path": artifacts.network_states_path,
                    "source_geojson_path": artifacts.water_infra_path,
                    "filter_column": "layer_key",
                    "filter_values": ["eau_eu"],
                    "state_column": "state_rp1000_storm",
                } if artifacts.network_states_path else None,
            ),
            (
                maps_dir / f"{territory}_etat_reseaux_eu_retour_100_ans.png",
                {
                    "type": "geojson_map",
                    "title": f"{territory_label(territory)} - Etat reseaux EU retour 100 ans",
                    "geojson_path": artifacts.network_states_path,
                    "source_geojson_path": artifacts.water_infra_path,
                    "filter_column": "layer_key",
                    "filter_values": ["eau_eu"],
                    "state_column": "state_rp100_storm",
                } if artifacts.network_states_path else None,
            ),
            (
                maps_dir / f"{territory}_storm_vent_rp50.png",
                hazard_map_payloads["wind_rp50"],
            ),
            (
                maps_dir / f"{territory}_storm_vent_rp100.png",
                hazard_map_payloads["wind_rp100"],
            ),
            (
                maps_dir / f"{territory}_pluie_rp50.png",
                hazard_map_payloads["rain_rp50"],
            ),
            (
                maps_dir / f"{territory}_pluie_rp100.png",
                hazard_map_payloads["rain_rp100"],
            ),
            (
                maps_dir / f"{territory}_inondation_cotiere_rp50.png",
                hazard_map_payloads["surge_rp50"],
            ),
            (
                maps_dir / f"{territory}_inondation_cotiere_rp100.png",
                hazard_map_payloads["surge_rp100"],
            ),
            (
                maps_dir / f"{territory}_mouvements_de_terrain.png",
                hazard_map_payloads["landslide_mean"],
            ),
            (
                maps_dir / f"{territory}_mouvements_de_terrain_rp50.png",
                hazard_map_payloads["landslide_rp50"],
            ),
            (
                maps_dir / f"{territory}_mouvements_de_terrain_rp100.png",
                hazard_map_payloads["landslide_rp100"],
            ),
        ]
        supergraph_payload = _build_guadeloupe_hazard_supergraph_payload(artifacts, territory)
        if supergraph_payload is not None:
            map_specs.append(
                (
                    maps_dir / f"{territory}_supergraph_vent_pluie_inondation_cotiere_mouvements_de_terrain_rp50_rp100.png",
                    supergraph_payload,
                )
            )
        for output_path, payload in map_specs:
            if payload is None:
                warnings.append(_warning_message(territory, output_path.name, "missing archived inputs"))
                continue
            points = payload.get("points")
            if isinstance(points, list) and not points:
                warnings.append(_warning_message(territory, output_path.name, "no map points available"))
                continue
            try:
                _render_auxiliary_output(plt, output_path, payload)
                generated_paths.append(str(output_path))
            except Exception as exc:
                warnings.append(_warning_message(territory, output_path.name, f"render failed: {type(exc).__name__}: {exc}"))

        comparison_rows = _build_hazard_comparison_csv_rows(artifacts)
        comparison_path = tables_dir / f"{territory}_comparaison_aleas.csv"
        if comparison_rows is None:
            warnings.append(_warning_message(territory, comparison_path.name, "missing archived inputs"))
        else:
            headers, rows = comparison_rows
            _write_csv_table(comparison_path, headers, rows)
            generated_paths.append(str(comparison_path))
        if territory == "guadeloupe":
            validation_csv = REPO_ROOT / "outputs" / "Graphs" / "_validation-vincennes-light" / "tables" / "guadeloupe_comparaison_aleas.csv"
            if validation_csv.exists():
                copied_validation_path = tables_dir / "guadeloupe_comparaison_aleas_validation.csv"
                shutil.copyfile(validation_csv, copied_validation_path)
                generated_paths.append(str(copied_validation_path))
            else:
                warnings.append(_warning_message(territory, "guadeloupe_comparaison_aleas_validation.csv", "validation source CSV is missing"))

        table_specs = [
            (tables_dir / f"{territory}_tableau_impacts_retour_1000_ans.csv", _build_impact_table_payload(artifacts, "rp1000", f"{territory_label(territory)} - Tableau impacts retour 1000 ans")),
            (tables_dir / f"{territory}_tableau_impacts_retour_100_ans.csv", _build_impact_table_payload(artifacts, "rp100", f"{territory_label(territory)} - Tableau impacts retour 100 ans")),
            (tables_dir / f"{territory}_tableau_exposition_reseaux.csv", _build_exposure_network_table_payload(artifacts, f"{territory_label(territory)} - Valorisation monetaire des reseaux")),
            (tables_dir / f"{territory}_tableau_exposition_ouvrages.csv", _build_exposure_ouvrage_table_payload(artifacts, f"{territory_label(territory)} - Valorisation monetaire des ouvrages")),
            (tables_dir / f"{territory}_tableau_comparaison_aleas.csv", _build_hazard_comparison_table_payload(artifacts, f"{territory_label(territory)} - Comparaison aleas")),
            (tables_dir / f"{territory}_tableau_population_affectee.csv", _build_social_impact_table_payload(artifacts, f"{territory_label(territory)} - Population affectee")),
            (tables_dir / f"{territory}_tableau_couverture_population.csv", _build_population_coverage_table_payload(artifacts, f"{territory_label(territory)} - Couverture population")),
        ]
        for output_path, payload in table_specs:
            if payload is None:
                warnings.append(_warning_message(territory, output_path.name, "missing archived inputs"))
                continue
            try:
                _write_table_payload_csv(output_path, payload)
                generated_paths.append(str(output_path))
            except Exception as exc:
                warnings.append(_warning_message(territory, output_path.name, f"csv export failed: {type(exc).__name__}: {exc}"))

        for file_name, payload in _build_population_output_specs(artifacts):
            output_path = population_dir / file_name
            if payload is None:
                warnings.append(_warning_message(territory, output_path.name, "missing population inputs"))
                continue
            try:
                _render_auxiliary_output(plt, output_path, payload)
                generated_paths.append(str(output_path))
            except Exception as exc:
                warnings.append(_warning_message(territory, output_path.name, f"render failed: {type(exc).__name__}: {exc}"))

    damage_zone_paths, damage_zone_warnings = _render_damage_zone_assets_from_artifacts(
        plt,
        artifacts_by_territory,
        output_dir,
        clean=False,
    )
    generated_paths.extend(damage_zone_paths)
    warnings.extend(damage_zone_warnings)

    return sorted(generated_paths), warnings


def render_png_graphs(graphs: list[GraphSpec], png_dir: Path) -> list[str]:
    _, plt = _load_matplotlib()
    png_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for graph in graphs:
        payload = graph.png_payload or {}
        output_path = png_dir / f"{_slugify(graph.graph_id)}.png"
        plot_type = str(payload.get("type") or "")
        if plot_type == "table":
            _render_table_png(plt, payload.get("title") or graph.title, payload.get("headers") or [], payload.get("rows") or [], output_path)
        elif plot_type == "line":
            _render_line_png(plt, payload, output_path)
        elif plot_type == "bar":
            _render_bar_png(plt, payload, output_path)
        elif plot_type == "horizontal_bar":
            _render_horizontal_bar_png(plt, payload, output_path)
        elif plot_type == "grouped_bar":
            _render_grouped_bar_png(plt, payload, output_path)
        elif plot_type == "grouped_stacked_bar":
            _render_grouped_stacked_bar_png(plt, payload, output_path)
        elif plot_type == "grouped_stacked_bar_segment_labels":
            _render_grouped_stacked_bar_segment_labels_png(plt, payload, output_path)
        elif plot_type == "stacked_bar":
            _render_stacked_bar_png(plt, payload, output_path)
        elif plot_type == "stacked_bar_with_line":
            _render_stacked_bar_with_line_png(plt, payload, output_path)
        else:
            continue
        written.append(str(output_path))
    return written


def write_graph_manifest(
    record: RunRecord,
    payloads: dict[str, TerritoryPayload],
    graphs: list[GraphSpec],
    output_dir: Path,
    html_index: Path | None,
    png_paths: list[str],
    auxiliary_output_paths: list[str],
    warnings: list[str],
) -> Path:
    all_output_paths = [*png_paths, *auxiliary_output_paths]
    generated_outputs = _build_generated_output_records(output_dir, graphs, png_paths, auxiliary_output_paths)
    payload = {
        "run_id": record.run_id,
        "run_family": record.run_family,
        "status": record.status,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "output_dir": str(output_dir),
        "html_index": str(html_index) if html_index is not None else None,
        "png_count": len(png_paths),
        "auxiliary_output_count": len(auxiliary_output_paths),
        "output_counts_by_category": _count_outputs_by_category(output_dir, all_output_paths),
        "output_counts_by_technical_type": _count_generated_outputs(generated_outputs, "technical_type"),
        "output_counts_by_family": _count_generated_outputs(generated_outputs, "family"),
        "warnings": warnings,
        "territories": {name: asdict(bundle) | {"payload": None} for name, bundle in payloads.items()},
        "graphs": [
            {
                "graph_id": graph.graph_id,
                "graph_type": graph.graph_type,
                "title": graph.title,
                "section": graph.section,
                "territory": graph.territory,
                "hazard": graph.hazard,
                "kind": graph.kind,
                "description": graph.description,
                "warning": graph.warning,
            }
            for graph in graphs
        ],
        "png_paths": png_paths,
        "auxiliary_output_paths": auxiliary_output_paths,
        "generated_outputs": generated_outputs,
    }
    manifest_path = output_dir / "graphs-manifest.json"
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def _manifest_path_starts_with_category(output_dir: Path, raw_path: Any, category: str) -> bool:
    path = Path(str(raw_path))
    try:
        relative = path.relative_to(output_dir)
    except ValueError:
        relative = Path(str(raw_path))
    return bool(relative.parts) and relative.parts[0] == category


def merge_damage_zone_manifest(
    record: RunRecord,
    payloads: dict[str, TerritoryPayload],
    output_dir: Path,
    damage_zone_paths: list[str],
    warnings: list[str],
) -> Path:
    manifest_path = output_dir / "graphs-manifest.json"
    existing = _load_json(manifest_path) if manifest_path.exists() else {}
    damage_zone_prefix = f"{DAMAGE_ZONE_OUTPUT_DIRNAME}/"

    png_paths = [
        str(path)
        for path in (existing.get("png_paths") if isinstance(existing.get("png_paths"), list) else [])
    ]
    auxiliary_output_paths = [
        str(path)
        for path in (existing.get("auxiliary_output_paths") if isinstance(existing.get("auxiliary_output_paths"), list) else [])
        if not _manifest_path_starts_with_category(output_dir, path, DAMAGE_ZONE_OUTPUT_DIRNAME)
    ]
    auxiliary_output_paths.extend(str(path) for path in damage_zone_paths)

    generated_outputs = [
        item
        for item in (existing.get("generated_outputs") if isinstance(existing.get("generated_outputs"), list) else [])
        if isinstance(item, dict) and not str(item.get("path") or "").startswith(damage_zone_prefix)
    ]
    for raw_path in damage_zone_paths:
        relative, technical_type, family = _auxiliary_output_classification(output_dir, raw_path)
        hazard = "storm_cmcc" if "storm_cmcc" in str(relative).lower() else DAMAGE_ZONE_HAZARD
        generated_outputs.append(
            {
                "path": relative,
                "technical_type": technical_type,
                "family": family,
                "source": "integrated_auxiliary",
                "graph_type": None,
                "territory": None,
                "hazard": hazard,
            }
        )

    merged_warnings = [
        str(item)
        for item in (existing.get("warnings") if isinstance(existing.get("warnings"), list) else [])
    ]
    for warning in warnings:
        if warning not in merged_warnings:
            merged_warnings.append(warning)

    all_output_paths = [*png_paths, *auxiliary_output_paths]
    payload = {
        **existing,
        "run_id": existing.get("run_id") or record.run_id,
        "run_family": existing.get("run_family") or record.run_family,
        "status": existing.get("status") or record.status,
        "created_at": existing.get("created_at") or record.created_at,
        "updated_at": datetime.now(tz=UTC).isoformat(),
        "output_dir": str(output_dir),
        "png_count": len(png_paths),
        "auxiliary_output_count": len(auxiliary_output_paths),
        "output_counts_by_category": _count_outputs_by_category(output_dir, all_output_paths),
        "output_counts_by_technical_type": _count_generated_outputs(generated_outputs, "technical_type"),
        "output_counts_by_family": _count_generated_outputs(generated_outputs, "family"),
        "warnings": merged_warnings,
        "territories": {name: asdict(bundle) | {"payload": None} for name, bundle in payloads.items()},
        "png_paths": png_paths,
        "auxiliary_output_paths": auxiliary_output_paths,
        "generated_outputs": generated_outputs,
    }
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate HTML and PNG graph packs from SIB archived runs."
    )
    run_group = parser.add_mutually_exclusive_group()
    run_group.add_argument("--run-id", help="Run ID to load. Use 'latest' to force latest-manifest.json")
    run_group.add_argument("--latest-success", action="store_true", help="Resolve the most recent complete-analysis run with top-level status=success")
    parser.add_argument("--run-family", default="complete-analysis", help="Run family: complete-analysis or targeted-cyclone")
    parser.add_argument("--list-runs", action="store_true", help="List available archived runs for the selected family and exit")
    parser.add_argument("--territories", nargs="*", help="Optional territory filter: guadeloupe, martinique, saint-barthelemy, gua, mar, stb, blm")
    parser.add_argument("--hazards", nargs="*", help="Optional hazard filter: storm, storm_cmcc, cmcc")
    parser.add_argument("--graph-ids", nargs="*", help="Optional graph-type filter. Choices include: " + ", ".join(GRAPH_TYPE_ORDER))
    parser.add_argument("--formats", default="html", help="Comma-separated outputs: html,png")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT), help="Output root directory for generated graph packs")
    parser.add_argument(
        "--damages-zones-only",
        action="store_true",
        help="Render only the Damages_Zones maps and merge them into an existing graph manifest.",
    )
    parser.add_argument(
        "--state-label-style",
        choices=STATE_LABEL_STYLE_CHOICES,
        default="code",
        help="Network state labels in generated graphs: code gives S0/S1/S2/S3; descriptive keeps operational text.",
    )
    parser.add_argument(
        "--storm-cmcc-layout",
        choices=STORM_CMCC_LAYOUT_CHOICES,
        default="harmonized",
        help="Style storm/cmcc comparisons. harmonized gives STORM solid/darker and STORM_CMCC dashed or dotted/lighter.",
    )
    parser.add_argument(
        "--matrix-percent-label-scale",
        type=float,
        default=MATRIX_PERCENT_LABEL_SCALE_DEFAULT,
        help="Scale factor for percentage labels inside network-state bars and population pie sectors.",
    )
    parser.add_argument("--open-index", action="store_true", help="Open the generated HTML index in the default browser")
    parser.add_argument("--verbose", action="store_true", help="Print extra diagnostic information while generating graphs")
    return parser


def main(argv: list[str] | None = None) -> int:
    global RUN_OUTPUTS_DIR
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    set_state_label_style(args.state_label_style)
    set_storm_cmcc_layout(args.storm_cmcc_layout)
    set_matrix_percent_label_scale(args.matrix_percent_label_scale)
    run_family = _resolve_run_family(args.run_family)
    RUN_OUTPUTS_DIR = RUN_FAMILY_OUTPUT_DIRS[run_family]

    records = list_run_records()
    if args.list_runs:
        print_runs(records)
        return 0

    requested_territories = _split_cli_values(args.territories)
    requested_hazards = _split_cli_values(args.hazards)
    requested_graph_types = _split_cli_values(args.graph_ids)
    output_formats = [item.strip().lower() for item in str(args.formats or "html").split(",") if item.strip()]
    if not output_formats:
        output_formats = ["html"]
    invalid_formats = [item for item in output_formats if item not in {"html", "png"}]
    if invalid_formats:
        raise RuntimeError(f"Unsupported format(s): {', '.join(invalid_formats)}")

    selected_record = resolve_run_record(args.run_id, args.latest_success or not args.run_id, records)
    selected_territories = _resolve_selected_territories(selected_record, requested_territories)

    warnings: list[str] = []
    payloads: dict[str, TerritoryPayload] = {}
    for territory in selected_territories:
        bundle = load_territory_payload(selected_record, territory)
        payloads[territory] = bundle
        if bundle.warning:
            warnings.append(bundle.warning)
        if args.verbose:
            print(f"[info] territory={territory} source={bundle.source_kind} path={bundle.payload_path}")

    selected_hazards = _resolve_selected_hazards(requested_hazards)
    if not requested_hazards:
        selected_hazards = _available_hazards_for_payloads(payloads)
    selected_graph_types = (
        _resolve_selected_graph_types(requested_graph_types)
        if requested_graph_types
        else _default_graph_types_for_run_family(selected_record.run_family)
    )

    graphs: list[GraphSpec] = []
    if not args.damages_zones_only:
        graphs = [build_run_overview_graph(selected_record, payloads)]
        if selected_record.run_family == "targeted-cyclone":
            for territory in selected_territories:
                graphs.extend(build_targeted_graphs_for_territory(territory, payloads[territory], selected_hazards))
        else:
            for territory in selected_territories:
                graphs.extend(build_graphs_for_territory(selected_record, territory, payloads[territory], selected_hazards))
        graphs = filter_graphs(graphs, selected_graph_types)
    if not args.damages_zones_only and not graphs:
        raise RuntimeError("No graphs left after applying filters")

    output_root, output_root_warning = _resolve_output_root(args.output_dir)
    if output_root_warning:
        warnings.append(output_root_warning)
        print(f"[warn] {output_root_warning}", file=sys.stderr)
    run_output_dir = output_root / selected_record.run_id
    run_output_dir.mkdir(parents=True, exist_ok=True)

    if args.damages_zones_only:
        damage_zone_paths, damage_zone_warnings = _render_damage_zone_assets(
            selected_record,
            payloads,
            run_output_dir,
            clean=True,
        )
        for damage_zone_warning in damage_zone_warnings:
            warnings.append(damage_zone_warning)
            print(f"[warn] {damage_zone_warning}", file=sys.stderr)
        if not damage_zone_paths:
            raise RuntimeError("No Damages_Zones maps were generated")
        manifest_path = merge_damage_zone_manifest(selected_record, payloads, run_output_dir, damage_zone_paths, warnings)
        print(f"[ok] Damages_Zones maps written to {run_output_dir / DAMAGE_ZONE_OUTPUT_DIRNAME}")
        print(f"[ok] Graph manifest updated at {manifest_path}")
        print(f"[ok] Selected run: {selected_record.run_id}")
        print(f"[ok] Run family: {selected_record.run_family}")
        print(f"[ok] Damages_Zones output count: {len(damage_zone_paths)}")
        return 0

    html_index: Path | None = None
    if "html" in output_formats:
        html_index = _render_index_html(selected_record, payloads, graphs, run_output_dir, warnings)
        print(f"[ok] HTML graph pack written to {html_index}")

    png_paths: list[str] = []
    auxiliary_output_paths: list[str] = []
    if "png" in output_formats:
        png_dir = run_output_dir / "png"
        if png_dir.exists():
            shutil.rmtree(png_dir)
        png_paths = render_png_graphs(graphs, png_dir)
        if selected_record.run_family == "targeted-cyclone":
            auxiliary_output_paths, auxiliary_warnings = _render_targeted_event_assets(selected_record, payloads, run_output_dir)
        else:
            auxiliary_output_paths, auxiliary_warnings = _render_integrated_vincennes_assets(selected_record, payloads, run_output_dir)
        for auxiliary_warning in auxiliary_warnings:
            warnings.append(auxiliary_warning)
            print(f"[warn] {auxiliary_warning}", file=sys.stderr)
        print(f"[ok] PNG graphs written to {png_dir}")
        if auxiliary_output_paths:
            print(f"[ok] Integrated charts/maps/tables written to {run_output_dir}")

    manifest_path = write_graph_manifest(selected_record, payloads, graphs, run_output_dir, html_index, png_paths, auxiliary_output_paths, warnings)
    print(f"[ok] Graph manifest written to {manifest_path}")
    print(f"[ok] Selected run: {selected_record.run_id}")
    print(f"[ok] Run family: {selected_record.run_family}")
    print(f"[ok] Graph count: {len(graphs)}")

    if args.open_index and html_index is not None:
        webbrowser.open(html_index.as_uri())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
