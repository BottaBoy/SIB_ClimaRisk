#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import html
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap
import webbrowser
from typing import Any

from case_study_sources import territory_label

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_OUTPUTS_DIR = REPO_ROOT / "outputs" / "complete-analysis-runs"
WEB_DATA_DIR = REPO_ROOT / "web" / "data"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "outputs" / "Graphs"
UTC = timezone.utc
BACKEND_ROOT = REPO_ROOT / "backend"

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

HAZARD_COLORS = {
    "storm": "#0f766e",
    "storm_cmcc": "#c2410c",
    "direct": "#1d4ed8",
    "indirect": "#be123c",
    "s1": "#f59e0b",
    "s2": "#ef4444",
    "s3": "#7f1d1d",
    "health": "#166534",
}

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
ANNUAL_FEC_COMBO_COLORS = {
    ("guadeloupe", "storm"): "#0f766e",
    ("guadeloupe", "storm_cmcc"): "#c2410c",
    ("martinique", "storm"): "#14b8a6",
    ("martinique", "storm_cmcc"): "#f97316",
    ("saint-barthelemy", "storm"): "#2563eb",
    ("saint-barthelemy", "storm_cmcc"): "#7c3aed",
}
LIFETIME_EXTRA_RETURN_PERIODS = (400, 600, 800)
EXTENDED_PML_PERIODS = tuple(sorted({*PML_PERIODS, *LIFETIME_EXTRA_RETURN_PERIODS}))

GRAPH_TYPE_ORDER = (
    "run_overview_summary",
    "hazard_metric_scorecard",
    "annual_fec_all_territories",
    "annual_fec_all_territories_pct",
    "annual_fec_by_territory_hazard",
    "lifetime_fec_by_territory_hazard",
    "hazard_component_share_annual_by_territory",
    "hazard_component_share_p99_by_territory",
    "pml_ladder_by_territory_hazard",
    "top_events_by_hazard",
    "wind_year_hist_by_hazard",
    "direct_vs_indirect_eai_by_hazard",
)

GRAPH_TYPE_LABELS = {
    "run_overview_summary": "Resume du run",
    "hazard_metric_scorecard": "Scorecard alea",
    "annual_fec_all_territories": "FEC annuelle comparee",
    "annual_fec_all_territories_pct": "FEC annuelle comparee en %",
    "annual_fec_by_territory_hazard": "FEC annuelle",
    "lifetime_fec_by_territory_hazard": "FEC duree de vie",
    "hazard_component_share_annual_by_territory": "Mix relatif EAI direct",
    "hazard_component_share_p99_by_territory": "Mix relatif P99 direct",
    "pml_ladder_by_territory_hazard": "Echelle PML",
    "top_events_by_hazard": "Top evenements",
    "wind_year_hist_by_hazard": "Histogramme vent max par annee",
    "direct_vs_indirect_eai_by_hazard": "Direct vs indirect",
}

SECTION_LABELS = {
    "overview": "Overview",
    "comparison": "Comparisons",
    "fec": "Frequency Exceedance",
    "loss": "Loss Metrics",
    "events": "Top Events",
    "wind": "Wind Distributions",
    "health": "Health And Dependency",
}


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


_NATIVE_PML_CACHE: dict[tuple[str, str, str], dict[int, float] | None] = {}
_WIND_MAP_CACHE: dict[tuple[str, str], tuple[dict[str, Any], str] | None] = {}
_REAL_WIND_TRACK_HIST_CACHE: dict[tuple[str, str, str], tuple[list[float], list[float], str] | None] = {}
_DYNAMIC_HAZARD_BUNDLE_CACHE: dict[tuple[str, str, int], Any] = {}
_BACKEND_RUNTIME: tuple[Any, Any] | None = None


def _render_integrated_vincennes_assets(record: RunRecord, output_dir: Path) -> tuple[list[str], str | None]:
    helper_script = REPO_ROOT / "outputs" / "Graphs" / "presentation-vincennes" / "export_assets.py"
    if not helper_script.exists():
        warning = (
            "Skipping integrated charts/maps/tables export because helper script is missing: "
            f"{helper_script}"
        )
        return [], warning
    for category in ("charts", "maps", "tables"):
        category_dir = output_dir / category
        if category_dir.exists():
            shutil.rmtree(category_dir)
    command = [
        sys.executable,
        str(helper_script),
        "--run-id",
        record.run_id,
        "--output-root",
        str(output_dir),
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        details = "\n".join(part for part in [stdout, stderr] if part)
        raise RuntimeError(
            "Integrated charts/maps/tables export failed for "
            f"run {record.run_id} using {helper_script}:\n{details or 'no error details available'}"
        )
    generated_paths: list[str] = []
    for category in ("charts", "maps", "tables"):
        category_dir = output_dir / category
        if not category_dir.exists():
            continue
        for path in sorted(candidate for candidate in category_dir.rglob("*") if candidate.is_file()):
            generated_paths.append(str(path))
    return generated_paths, None


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
    technical_type = {"charts": "chart", "maps": "map", "tables": "table"}.get(category, "file")
    if category == "maps":
        if any(token in file_name for token in ("storm_vent", "pluie", "inondation_cotiere", "mouvements_de_terrain", "bassin_")):
            family = "alea"
        elif any(token in file_name for token in ("aep_canalisations", "haute_tension_souterrain")):
            family = "exposition"
        else:
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
            )
        )
    records.sort(key=lambda item: _timestamp_sort_key(item.manifest), reverse=True)
    return records


def print_runs(records: list[RunRecord]) -> None:
    if not records:
        print("No runs found under outputs/complete-analysis-runs")
        return
    headers = (
        "run_id",
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
        )
    if latest_success or not run_id:
        successful = [record for record in records if record.status == "success"]
        if not successful:
            raise RuntimeError("No successful complete-analysis run found")
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
            source_kind="archived",
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
        ["Status", record.status],
        ["Created At", record.created_at or ""],
        ["Updated At", record.updated_at or ""],
        ["dynamic_max_tracks", str(record.dynamic_max_tracks or "")],
        ["memory_budget_gb", _format_number(record.memory_budget_gb or 0.0)],
        ["Territories", ", ".join(record.territories)],
    ]
    for territory, bundle in payloads.items():
        rows.append([f"Source {territory}", f"{bundle.source_kind}: {bundle.payload_path}"])
    return _make_table_graph(
        "run_overview_summary",
        f"Run Overview - {record.run_id}",
        "overview",
        "Resume operateur du run selectionne et des sources chargees.",
        ["Field", "Value"],
        rows,
    )


def build_hazard_metric_scorecard(territory: str, payload: dict[str, Any], selected_hazards: list[str]) -> GraphSpec:
    categories = ["Annual EAI", "Direct EAI", "Indirect EAI", "PML100", "PML1000", "TVaR95", "P99"]
    series: list[dict[str, Any]] = []
    for hazard in selected_hazards:
        metrics = _extract_hazard_metrics(payload, hazard)
        series.append(
            {
                "name": HAZARD_LABELS[hazard],
                "type": "bar",
                "data": [
                    _safe_float(metrics.get("eai_eur")),
                    _safe_float(metrics.get("eai_direct_eur")),
                    _safe_float(metrics.get("eai_indirect_eur")),
                    _safe_float(metrics.get("pml_100_eur")),
                    _safe_float(metrics.get("pml_1000_eur")),
                    _safe_float(metrics.get("tvar_95_eur")),
                    _safe_float(metrics.get("percentile_99_loss_eur")),
                ],
                "itemStyle": {"color": HAZARD_COLORS[hazard]},
            }
        )
    return GraphSpec(
        graph_id=_graph_id("hazard_metric_scorecard", territory),
        graph_type="hazard_metric_scorecard",
        title=f"Hazard Scorecard - {territory}",
        section="overview",
        territory=territory,
        hazard=None,
        kind="chart",
        description="Comparaison synthetique des principales metriques de pertes par alea.",
        echarts_option=_build_bar_option(f"Hazard Scorecard - {territory}", categories, series),
        png_payload={
            "type": "grouped_bar",
            "title": f"Hazard Scorecard - {territory}",
            "categories": categories,
            "series": [
                {
                    "name": str(item.get("name") or ""),
                    "values": list(item.get("data") or []),
                    "color": item.get("itemStyle", {}).get("color") if isinstance(item.get("itemStyle"), dict) else None,
                }
                for item in series
            ],
            "ylabel": "Loss (EUR)",
        },
    )


def build_storm_vs_cmcc_comparison(territory: str, payload: dict[str, Any], selected_hazards: list[str]) -> GraphSpec | None:
    if set(selected_hazards) != set(SUPPORTED_HAZARDS):
        return None
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
        f"STORM vs STORM_CMCC - {territory}",
        categories,
        [
            {"name": "STORM", "type": "bar", "data": storm_values, "itemStyle": {"color": HAZARD_COLORS["storm"]}},
            {"name": "STORM_CMCC", "type": "bar", "data": cmcc_values, "itemStyle": {"color": HAZARD_COLORS["storm_cmcc"]}},
        ],
    )
    return GraphSpec(
        graph_id=_graph_id("storm_vs_cmcc_eai_pml1000", territory),
        graph_type="storm_vs_cmcc_eai_pml1000",
        title=f"STORM vs STORM_CMCC - {territory}",
        section="comparison",
        territory=territory,
        hazard=None,
        kind="chart",
        description="Comparaison frontale des metriques annual_eai et pml_1000.",
        echarts_option=option,
        png_payload={
            "type": "grouped_bar",
            "title": f"STORM vs STORM_CMCC - {territory}",
            "categories": categories,
            "series": [
                {"name": "STORM", "values": storm_values, "color": HAZARD_COLORS["storm"]},
                {"name": "STORM_CMCC", "values": cmcc_values, "color": HAZARD_COLORS["storm_cmcc"]},
            ],
            "ylabel": "Loss (EUR)",
        },
    )


def build_tvar95_comparison(territory: str, payload: dict[str, Any], selected_hazards: list[str]) -> GraphSpec:
    categories = [HAZARD_LABELS[hazard] for hazard in selected_hazards]
    values = [_safe_float(_extract_hazard_metrics(payload, hazard).get("tvar_95_eur")) for hazard in selected_hazards]
    option = _build_bar_option(
        f"TVaR95 - {territory}",
        categories,
        [{"name": "TVaR95", "type": "bar", "data": values, "itemStyle": {"color": "#7c3aed"}}],
    )
    return GraphSpec(
        graph_id=_graph_id("tvar95_by_territory_hazard", territory),
        graph_type="tvar95_by_territory_hazard",
        title=f"TVaR95 - {territory}",
        section="loss",
        territory=territory,
        hazard=None,
        kind="chart",
        description="Comparaison du tail risk TVaR95 entre aleas selectionnes.",
        echarts_option=option,
        png_payload={
            "type": "bar",
            "title": f"TVaR95 - {territory}",
            "categories": categories,
            "values": values,
            "color": "#7c3aed",
            "ylabel": "TVaR95 (EUR)",
        },
    )


def build_annual_fec_graph(record: RunRecord, territory: str, payload: dict[str, Any], hazard: str) -> GraphSpec | None:
    rp, damage, native_added, warning = _resolve_annual_fec_curve(record, territory, payload, hazard)
    if not rp or not damage or len(rp) != len(damage):
        return None
    total_value_eur = _resolve_total_exposure_value(record, territory, payload)
    point_labels = _build_point_labels(rp, damage, total_value_eur)
    option = _build_line_option(
        f"Annual FEC - {territory} - {HAZARD_LABELS[hazard]}",
        "Return period (years)",
        "Damage (EUR)",
        [
            {
                "name": HAZARD_LABELS[hazard],
                "type": "line",
                "smooth": False,
                "showSymbol": True,
                "symbolSize": 8,
                "labelLayout": {"hideOverlap": True},
                "lineStyle": {"width": 3, "color": HAZARD_COLORS[hazard]},
                "itemStyle": {"color": HAZARD_COLORS[hazard]},
                "data": _build_labeled_line_points(rp, damage, point_labels),
            }
        ],
    )
    return GraphSpec(
        graph_id=_graph_id("annual_fec_by_territory_hazard", territory, hazard),
        graph_type="annual_fec_by_territory_hazard",
        title=f"Annual FEC - {territory} - {HAZARD_LABELS[hazard]}",
        section="fec",
        territory=territory,
        hazard=hazard,
        kind="chart",
        description=(
            "Courbe de depassement de frequence annuelle pour le scenario complet "
            "STORM/STORM_CMCC du territoire, avec toutes les composantes actives agregees. "
            "Chaque point annote le dommage en EUR et sa part du parc d'infrastructure mesuree comme damage / point_value_total_eur."
        ),
        echarts_option=option,
        png_payload={
            "type": "line",
            "title": f"Annual FEC - {territory} - {HAZARD_LABELS[hazard]}",
            "series": [
                {
                    "name": HAZARD_LABELS[hazard],
                    "x": rp,
                    "y": damage,
                    "color": HAZARD_COLORS[hazard],
                    "annotations": point_labels,
                }
            ],
            "xlabel": "Return period (years)",
            "ylabel": "Damage (EUR)",
            "note": (
                "Scenario total losses for the selected STORM/STORM_CMCC hazard, not wind-only losses. "
                "Labels show damage in EUR and the share of total infrastructure value."
            ),
        },
        warning=warning,
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
    territory_line_types = {
        "guadeloupe": "solid",
        "martinique": "dashed",
        "saint-barthelemy": "dotted",
    }
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
            line_type = territory_line_types.get(territory, "solid")
            series.append(
                {
                    "name": name,
                    "type": "line",
                    "smooth": False,
                    "showSymbol": True,
                    "lineStyle": {"width": 3, "color": color, "type": line_type},
                    "itemStyle": {"color": color},
                    "data": [[rp[idx], damage[idx]] for idx in range(len(rp))],
                }
            )
            png_series.append({"name": name, "x": rp, "y": damage, "color": color, "linestyle": line_type})
    if len(series) < 2:
        return None
    option = _build_line_option(
        f"Annual FEC - {title_suffix}",
        "Return period (years)",
        "Damage (EUR)",
        series,
    )
    return GraphSpec(
        graph_id=_graph_id("annual_fec_all_territories"),
        graph_type="annual_fec_all_territories",
        title=f"Annual FEC - {title_suffix}",
        section="fec",
        territory=None,
        hazard=None,
        kind="chart",
        description=f"Vue consolidee sur un seul graphe des courbes annuelles {title_suffix} x STORM/STORM_CMCC.",
        echarts_option=option,
        png_payload={
            "type": "line",
            "title": f"Annual FEC - {title_suffix}",
            "series": png_series,
            "xlabel": "Return period (years)",
            "ylabel": "Damage (EUR)",
            "note": "One curve per territory x scenario. Curves represent total scenario losses, not wind-only losses.",
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
    territory_line_types = {
        "guadeloupe": "solid",
        "martinique": "dashed",
        "saint-barthelemy": "dotted",
    }
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
            line_type = territory_line_types.get(territory, "solid")
            series.append(
                {
                    "name": name,
                    "type": "line",
                    "smooth": False,
                    "showSymbol": True,
                    "lineStyle": {"width": 3, "color": color, "type": line_type},
                    "itemStyle": {"color": color},
                    "data": [[rp[idx], damage_pct[idx]] for idx in range(len(rp))],
                }
            )
            png_series.append({"name": name, "x": rp, "y": damage_pct, "color": color, "linestyle": line_type})
    if len(series) < 2:
        return None
    option = _build_line_option(
        f"Annual FEC - {title_suffix} (%)",
        "Return period (years)",
        "Damage (% of territory infrastructure value)",
        series,
    )
    return GraphSpec(
        graph_id=_graph_id("annual_fec_all_territories_pct"),
        graph_type="annual_fec_all_territories_pct",
        title=f"Annual FEC - {title_suffix} (%)",
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
            "title": f"Annual FEC - {title_suffix} (%)",
            "series": png_series,
            "xlabel": "Return period (years)",
            "ylabel": "Damage (% of territory infrastructure value)",
            "note": (
                "Each curve is normalized by the total infrastructure value of its own territory. "
                "Curves represent total scenario losses, not wind-only losses."
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
        png_series.append({"name": name, "x": rp, "y": damage, "color": color})
    if not series:
        return None
    option = _build_line_option(
        f"Lifetime FEC - {territory} - {HAZARD_LABELS[hazard]}",
        "Return period (years)",
        "Damage (EUR)",
        series,
    )
    return GraphSpec(
        graph_id=_graph_id("lifetime_fec_by_territory_hazard", territory, hazard),
        graph_type="lifetime_fec_by_territory_hazard",
        title=f"Lifetime FEC - {territory} - {HAZARD_LABELS[hazard]}",
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
            "title": f"Lifetime FEC - {territory} - {HAZARD_LABELS[hazard]}",
            "series": png_series,
            "xlabel": "Return period (years)",
            "ylabel": "Damage (EUR)",
            "annotate_x_values": list(LIFETIME_EXTRA_RETURN_PERIODS),
            "note": (
                "Added 400/600/800-year points use annual PML values recomputed from archived event-loss checkpoints, "
                "then apply the same lifetime factor as the backend 30y/50y series."
            ),
        },
        warning=annual_warning,
    )


def build_pml_ladder_graph(territory: str, payload: dict[str, Any], hazard: str) -> GraphSpec:
    hazard_metrics = _extract_hazard_metrics(payload, hazard)
    categories = [f"PML{period}" for period in PML_PERIODS]
    values = [_safe_float(hazard_metrics.get(f"pml_{period}_eur")) for period in PML_PERIODS]
    option = _build_bar_option(
        f"PML Ladder - {territory} - {HAZARD_LABELS[hazard]}",
        categories,
        [{"name": HAZARD_LABELS[hazard], "type": "bar", "data": values, "itemStyle": {"color": HAZARD_COLORS[hazard]}}],
    )
    return GraphSpec(
        graph_id=_graph_id("pml_ladder_by_territory_hazard", territory, hazard),
        graph_type="pml_ladder_by_territory_hazard",
        title=f"PML Ladder - {territory} - {HAZARD_LABELS[hazard]}",
        section="loss",
        territory=territory,
        hazard=hazard,
        kind="chart",
        description="Lecture rapide de la queue de pertes sur les periodes de retour standard.",
        echarts_option=option,
        png_payload={
            "type": "bar",
            "title": f"PML Ladder - {territory} - {HAZARD_LABELS[hazard]}",
            "categories": categories,
            "values": values,
            "color": HAZARD_COLORS[hazard],
            "ylabel": "Loss (EUR)",
        },
    )


def build_top_events_graph(territory: str, payload: dict[str, Any], hazard: str) -> GraphSpec | None:
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
        f"Top Events - {territory} - {HAZARD_LABELS[hazard]}",
        categories,
        [{"name": "Loss", "type": "bar", "data": values, "itemStyle": {"color": HAZARD_COLORS[hazard]}}],
        horizontal=True,
    )
    return GraphSpec(
        graph_id=_graph_id("top_events_by_hazard", territory, hazard),
        graph_type="top_events_by_hazard",
        title=f"Top Events - {territory} - {HAZARD_LABELS[hazard]}",
        section="events",
        territory=territory,
        hazard=hazard,
        kind="chart",
        description="Top 10 evenements les plus dommageables sur le portefeuille du territoire.",
        echarts_option=option,
        png_payload={
            "type": "horizontal_bar",
            "title": f"Top Events - {territory} - {HAZARD_LABELS[hazard]}",
            "categories": categories,
            "values": values,
            "color": HAZARD_COLORS[hazard],
            "xlabel": "Loss (EUR)",
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
            title = f"{title_prefix} - {territory} - {HAZARD_LABELS[hazard]}"
            option = _build_bar_option(
                title,
                categories,
                [{"name": "%", "type": "bar", "data": values, "itemStyle": {"color": HAZARD_COLORS[hazard]}}],
            )
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
                    "color": HAZARD_COLORS[hazard],
                    "ylabel": "Percent of tracks",
                    "xlabel": "Max wind intensity per track across archived territory cells (m/s)",
                    "note": (
                        f"Reconstructed from hazard intensities over archived wind-map cells using the run's STORM/STORM_CMCC catalog selection. "
                        f"Source wind-map artifact: {wind_map_path}."
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
        x_label = "Event loss bin (EUR)"
        description = (
            "Malgre son identifiant historique, ce graphe montre une distribution des pertes evenementielles du portefeuille. "
            "L'axe X est en EUR, pas une vitesse de vent."
        )
        note = "Legacy graph id, but the backend payload bins event losses in EUR on the X axis."
    else:
        categories = [f"{value:.0f}" for value in bin_values]
        x_label = "Event loss intensity proxy (sqrt(EUR))"
        description = (
            "Malgre son identifiant historique, ce graphe montre un proxy de pertes par evenement construit cote backend sur sqrt(loss). "
            "L'axe X n'est ni une vitesse de vent ni un nombre de tracks."
        )
        note = "Backend builds this X axis from sqrt(event loss EUR), not from wind speed or track count."
    title = str(block.get("title") or f"{title_prefix} - {territory} - {HAZARD_LABELS[hazard]}")
    option = _build_bar_option(
        title,
        categories,
        [{"name": "%", "type": "bar", "data": values, "itemStyle": {"color": HAZARD_COLORS[hazard]}}],
    )
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
            "color": HAZARD_COLORS[hazard],
            "ylabel": "Percent",
            "xlabel": x_label,
            "note": note,
        },
        warning=warning,
    )


def build_direct_vs_indirect_graph(territory: str, payload: dict[str, Any], selected_hazards: list[str]) -> GraphSpec:
    categories = [HAZARD_LABELS[hazard] for hazard in selected_hazards]
    direct_values = [_safe_float(_extract_hazard_metrics(payload, hazard).get("eai_direct_eur")) for hazard in selected_hazards]
    indirect_values = [_safe_float(_extract_hazard_metrics(payload, hazard).get("eai_indirect_eur")) for hazard in selected_hazards]
    option = _build_bar_option(
        f"Direct vs Indirect EAI - {territory}",
        categories,
        [
            {"name": "Direct", "type": "bar", "stack": "loss", "data": direct_values, "itemStyle": {"color": HAZARD_COLORS["direct"]}},
            {"name": "Indirect", "type": "bar", "stack": "loss", "data": indirect_values, "itemStyle": {"color": HAZARD_COLORS["indirect"]}},
        ],
    )
    return GraphSpec(
        graph_id=_graph_id("direct_vs_indirect_eai_by_hazard", territory),
        graph_type="direct_vs_indirect_eai_by_hazard",
        title=f"Direct vs Indirect EAI - {territory}",
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
            "title": f"Direct vs Indirect EAI - {territory}",
            "categories": categories,
            "series": [
                {"name": "Direct", "values": direct_values, "color": HAZARD_COLORS["direct"]},
                {"name": "Indirect", "values": indirect_values, "color": HAZARD_COLORS["indirect"]},
            ],
            "ylabel": "Annual EAI (EUR)",
            "note": "Each STORM/STORM_CMCC bar is a full-scenario total across active hazard components; indirect is the electricity-to-water uplift.",
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
            "ylabel": "Share of direct loss mix (%)",
            "note": note,
        },
    )


def build_component_health_graph(territory: str, payload: dict[str, Any], hazard: str) -> GraphSpec | None:
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
        categories.append(component_name)
        s1_values.append(100.0 * _safe_float(component_metrics.get("L_S1")) / total)
        s2_values.append(100.0 * _safe_float(component_metrics.get("L_S2")) / total)
        s3_values.append(100.0 * _safe_float(component_metrics.get("L_S3")) / total)
        health_values.append(100.0 * _safe_float(component_metrics.get("health"), default=0.0))
    if not categories:
        return None
    option = _build_bar_option(
        f"Component Health - {territory} - {HAZARD_LABELS[hazard]}",
        categories,
        [
            {"name": "S1 %", "type": "bar", "stack": "state", "data": s1_values, "itemStyle": {"color": HAZARD_COLORS["s1"]}},
            {"name": "S2 %", "type": "bar", "stack": "state", "data": s2_values, "itemStyle": {"color": HAZARD_COLORS["s2"]}},
            {"name": "S3 %", "type": "bar", "stack": "state", "data": s3_values, "itemStyle": {"color": HAZARD_COLORS["s3"]}},
            {"name": "Health %", "type": "line", "yAxisIndex": 1, "data": health_values, "lineStyle": {"color": HAZARD_COLORS["health"], "width": 3}, "itemStyle": {"color": HAZARD_COLORS["health"]}},
        ],
        secondary_axis=True,
    )
    return GraphSpec(
        graph_id=_graph_id("component_health_by_territory", territory, hazard),
        graph_type="component_health_by_territory",
        title=f"Component Health - {territory} - {HAZARD_LABELS[hazard]}",
        section="health",
        territory=territory,
        hazard=hazard,
        kind="chart",
        description=(
            "Synthese des etats finaux S1/S2/S3 annualises pour le scenario complet, apres propagation elec->eau quand elle s'applique. "
            "Ce n'est pas un graphe de retour 100 ans / 1000 ans, mais une synthese ponderee par geometrie d'actif."
        ),
        echarts_option=option,
        png_payload={
            "type": "stacked_bar_with_line",
            "title": f"Component Health - {territory} - {HAZARD_LABELS[hazard]}",
            "categories": categories,
            "stacked_series": [
                {"name": "S1 %", "values": s1_values, "color": HAZARD_COLORS["s1"]},
                {"name": "S2 %", "values": s2_values, "color": HAZARD_COLORS["s2"]},
                {"name": "S3 %", "values": s3_values, "color": HAZARD_COLORS["s3"]},
            ],
            "line_series": {"name": "Health %", "values": health_values, "color": HAZARD_COLORS["health"]},
            "ylabel": "State share (%)",
            "line_ylabel": "Health (%)",
            "note": (
                "Annualized final-state synthesis for the selected scenario; not tied to a single return period. "
                "Weighting uses feature geometry (km for lines, count for points)."
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
        f"Interdependency Summary - {territory}",
        "health",
        "Resume des hypotheses et parametres de propagation electricite vers eau.",
        ["Field", "Value"],
        rows,
        territory=territory,
    )


def build_graphs_for_territory(
    record: RunRecord,
    territory: str,
    bundle: TerritoryPayload,
    selected_hazards: list[str],
) -> list[GraphSpec]:
    payload = bundle.payload
    graphs: list[GraphSpec] = []
    graphs.append(build_hazard_metric_scorecard(territory, payload, selected_hazards))
    graphs.append(build_direct_vs_indirect_graph(territory, payload, selected_hazards))
    annual_component_mix = build_hazard_component_share_graph(
        territory,
        payload,
        selected_hazards,
        metric_key="components_direct_eai_eur",
        graph_type="hazard_component_share_annual_by_territory",
        title=f"Relative Hazard Mix - Annual Direct EAI - {territory}",
        description=(
            "Part relative des composantes directes vent/pluie/submersion/mouvement de terrain dans l'EAI direct annuel. "
            "Les composantes absentes du payload sont affichees a zero."
        ),
        note="Shares use portfolio_results.*.components_direct_eai_eur. This is direct multi-hazard mix only; indirect uplift is excluded.",
    )
    if annual_component_mix is not None:
        graphs.append(annual_component_mix)
    p99_component_mix = build_hazard_component_share_graph(
        territory,
        payload,
        selected_hazards,
        metric_key="components_direct_percentile_99_loss_eur",
        graph_type="hazard_component_share_p99_by_territory",
        title=f"Relative Hazard Mix - Direct P99 Loss - {territory}",
        description=(
            "Part relative des composantes directes vent/pluie/submersion/mouvement de terrain dans la perte directe P99 du scenario. "
            "Les composantes absentes du payload sont affichees a zero."
        ),
        note="Shares use portfolio_results.*.components_direct_percentile_99_loss_eur. This is direct multi-hazard mix only.",
    )
    if p99_component_mix is not None:
        graphs.append(p99_component_mix)
    for hazard in selected_hazards:
        for graph in (
            build_annual_fec_graph(record, territory, payload, hazard),
            build_lifetime_fec_graph(record, territory, payload, hazard),
            build_pml_ladder_graph(territory, payload, hazard),
            build_top_events_graph(territory, payload, hazard),
            build_wind_hist_graph(record, territory, payload, hazard, "wind_year_hist", "wind_year_hist_by_hazard", "Wind Year Histogram"),
        ):
            if graph is not None:
                graphs.append(graph)
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
        warnings_html = f"<section class=\"warnings\"><h2>Warnings</h2><ul>{warning_items}</ul></section>"

    nav_parts = []
    for section_key, label in SECTION_LABELS.items():
        if sections.get(section_key):
            nav_parts.append(
                f'<section class="nav-group"><h3>{html.escape(label)}</h3><ul>{"".join(sections[section_key])}</ul></section>'
            )
    payload_rows = "".join(
        f"<li><strong>{html.escape(name)}</strong>: {html.escape(bundle.source_kind)} - {html.escape(bundle.payload_path)}</li>"
        for name, bundle in payloads.items()
    )
    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SIB Graphs - {html.escape(record.run_id)}</title>
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
    <h1>SIB Run Graphs</h1>
    <p>Run <strong>{html.escape(record.run_id)}</strong> - status={html.escape(record.status)} - territories={html.escape(', '.join(record.territories))}</p>
    <p>Sources chargees:</p>
    <ul>{payload_rows}</ul>
  </header>
  <div class="layout">
    <aside class="sidebar">
      <h2>Graph List</h2>
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
    fig, ax = plt.subplots(figsize=(11, 6))
    annotate_x_values = {int(value) for value in (payload.get("annotate_x_values") or [])}
    for series_idx, series in enumerate(payload.get("series") or []):
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
    ax.grid(True, alpha=0.25)
    if payload.get("series"):
        ax.legend()
    _save_figure(fig, output_path, payload.get("note"))
    plt.close(fig)


def _render_bar_png(plt: Any, payload: dict[str, Any], output_path: Path) -> None:
    categories = payload.get("categories") or []
    values = payload.get("values") or []
    fig, ax = plt.subplots(figsize=(11, 6))
    ax.bar(categories, values, color=payload.get("color") or "#0f766e")
    ax.set_title(payload.get("title") or "")
    if payload.get("xlabel"):
        ax.set_xlabel(payload.get("xlabel"))
    if payload.get("ylabel"):
        ax.set_ylabel(payload.get("ylabel"))
    ax.tick_params(axis="x", rotation=24)
    ax.grid(True, axis="y", alpha=0.2)
    _save_figure(fig, output_path, payload.get("note"))
    plt.close(fig)


def _render_horizontal_bar_png(plt: Any, payload: dict[str, Any], output_path: Path) -> None:
    categories = payload.get("categories") or []
    values = payload.get("values") or []
    fig, ax = plt.subplots(figsize=(12, max(5, len(categories) * 0.5)))
    ax.barh(categories, values, color=payload.get("color") or "#0f766e")
    ax.set_title(payload.get("title") or "")
    if payload.get("xlabel"):
        ax.set_xlabel(payload.get("xlabel"))
    ax.grid(True, axis="x", alpha=0.2)
    _save_figure(fig, output_path, payload.get("note"))
    plt.close(fig)


def _render_grouped_bar_png(plt: Any, payload: dict[str, Any], output_path: Path) -> None:
    categories = payload.get("categories") or []
    series = payload.get("series") or []
    fig, ax = plt.subplots(figsize=(11, 6))
    if not categories or not series:
        fig.savefig(output_path, dpi=180)
        plt.close(fig)
        return
    width = 0.8 / max(1, len(series))
    positions = list(range(len(categories)))
    for idx, item in enumerate(series):
        offset = (idx - (len(series) - 1) / 2.0) * width
        shifted = [pos + offset for pos in positions]
        ax.bar(shifted, item.get("values") or [], width=width, label=item.get("name"), color=item.get("color"))
    ax.set_xticks(positions)
    ax.set_xticklabels(categories, rotation=20)
    ax.set_title(payload.get("title") or "")
    if payload.get("ylabel"):
        ax.set_ylabel(payload.get("ylabel"))
    ax.legend()
    ax.grid(True, axis="y", alpha=0.2)
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


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate HTML and PNG graph packs from SIB complete-analysis runs."
    )
    run_group = parser.add_mutually_exclusive_group()
    run_group.add_argument("--run-id", help="Run ID to load. Use 'latest' to force latest-manifest.json")
    run_group.add_argument("--latest-success", action="store_true", help="Resolve the most recent complete-analysis run with top-level status=success")
    parser.add_argument("--list-runs", action="store_true", help="List available complete-analysis runs and exit")
    parser.add_argument("--territories", nargs="*", help="Optional territory filter: guadeloupe, martinique, saint-barthelemy, gua, mar, stb, blm")
    parser.add_argument("--hazards", nargs="*", help="Optional hazard filter: storm, storm_cmcc, cmcc")
    parser.add_argument("--graph-ids", nargs="*", help="Optional graph-type filter. Choices include: " + ", ".join(GRAPH_TYPE_ORDER))
    parser.add_argument("--formats", default="html", help="Comma-separated outputs: html,png")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT), help="Output root directory for generated graph packs")
    parser.add_argument("--open-index", action="store_true", help="Open the generated HTML index in the default browser")
    parser.add_argument("--verbose", action="store_true", help="Print extra diagnostic information while generating graphs")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

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
    selected_hazards = _resolve_selected_hazards(requested_hazards)
    selected_graph_types = _resolve_selected_graph_types(requested_graph_types)

    warnings: list[str] = []
    payloads: dict[str, TerritoryPayload] = {}
    for territory in selected_territories:
        bundle = load_territory_payload(selected_record, territory)
        payloads[territory] = bundle
        if bundle.warning:
            warnings.append(bundle.warning)
        if args.verbose:
            print(f"[info] territory={territory} source={bundle.source_kind} path={bundle.payload_path}")

    graphs: list[GraphSpec] = [build_run_overview_graph(selected_record, payloads)]
    annual_fec_all_graph = build_annual_fec_all_territories_graph(selected_record, payloads, selected_territories, selected_hazards)
    if annual_fec_all_graph is not None:
        graphs.append(annual_fec_all_graph)
    annual_fec_all_pct_graph = build_annual_fec_all_territories_pct_graph(selected_record, payloads, selected_territories, selected_hazards)
    if annual_fec_all_pct_graph is not None:
        graphs.append(annual_fec_all_pct_graph)
    for territory in selected_territories:
        graphs.extend(build_graphs_for_territory(selected_record, territory, payloads[territory], selected_hazards))
    graphs = filter_graphs(graphs, selected_graph_types)
    if not graphs:
        raise RuntimeError("No graphs left after applying filters")

    output_root, output_root_warning = _resolve_output_root(args.output_dir)
    if output_root_warning:
        warnings.append(output_root_warning)
        print(f"[warn] {output_root_warning}", file=sys.stderr)
    run_output_dir = output_root / selected_record.run_id
    run_output_dir.mkdir(parents=True, exist_ok=True)

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
        auxiliary_output_paths, auxiliary_warning = _render_integrated_vincennes_assets(selected_record, run_output_dir)
        if auxiliary_warning:
            warnings.append(auxiliary_warning)
            print(f"[warn] {auxiliary_warning}", file=sys.stderr)
        print(f"[ok] PNG graphs written to {png_dir}")
        if auxiliary_output_paths:
            print(f"[ok] Integrated charts/maps/tables written to {run_output_dir}")

    manifest_path = write_graph_manifest(selected_record, payloads, graphs, run_output_dir, html_index, png_paths, auxiliary_output_paths, warnings)
    print(f"[ok] Graph manifest written to {manifest_path}")
    print(f"[ok] Selected run: {selected_record.run_id}")
    print(f"[ok] Graph count: {len(graphs)}")

    if args.open_index and html_index is not None:
        webbrowser.open(html_index.as_uri())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
