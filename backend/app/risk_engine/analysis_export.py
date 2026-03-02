from __future__ import annotations

from datetime import datetime, timezone
import csv
import io
from typing import Any
from collections import Counter

from .types import DisaggregationSummary, ImpactComputationResult, NormalizedExposure

UTC = timezone.utc


def build_result_payload(
    *,
    job_id: str,
    source: str,
    exposure: NormalizedExposure,
    disagg: DisaggregationSummary,
    comp: ImpactComputationResult,
) -> dict[str, Any]:
    now = datetime.now(UTC).replace(microsecond=0)
    notes = list(comp.notes)
    notes.extend(disagg.warnings)
    notes.extend(exposure.warnings)
    category_counts = Counter((f.exposure_category or "habitation") for f in exposure.features)

    payload: dict[str, Any] = {
        "meta": {
            "title": "SIB Cyclone Risk Thesis Demo",
            "source": source,
            "job_id": job_id,
            "updated_at": now.isoformat(),
            "unit_currency": "EUR",
            "currency_display_unit": "MEUR",
            "sampling_spacing_m": float(disagg.spacing_m),
            "impact_function": "Eberenz_2021_TC",
            "hazards": ["STORM", "STORM_CMCC"],
            "engine": comp.engine,
        },
        "exposure_summary": {
            "asset_count_original": exposure.asset_count_original,
            "asset_count_points": disagg.asset_count_points,
            "total_exposure_eur": round(exposure.total_exposure_eur, 2),
            "source_name": exposure.source_name,
            "source_format": exposure.source_format,
            "geometry_type_counts": disagg.by_geometry_type,
            "exposure_category_counts": dict(category_counts),
            "metric_crs": disagg.metric_crs,
        },
        "territory_results": comp.territory_results,
        "portfolio_results": comp.portfolio_results,
        "graphs": comp.graphs,
        "artifacts": {
            "plots_png": [],
            "downloads": [],
        },
        "notes": _dedupe_non_empty(notes),
    }
    return payload


def build_territory_csv(territory_results: list[dict[str, Any]]) -> bytes:
    output = io.StringIO()
    if not territory_results:
        output.write("territory_id,territory_label\n")
    else:
        fieldnames = list(territory_results[0].keys())
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for row in territory_results:
            writer.writerow(row)
    return output.getvalue().encode("utf-8")


def build_graph_json_artifact(graphs: dict[str, Any]) -> bytes:
    import json

    return json.dumps(graphs, ensure_ascii=False, indent=2).encode("utf-8")


def _dedupe_non_empty(items: list[str]) -> list[str]:
    seen = set()
    out: list[str] = []
    for item in items:
        if not item:
            continue
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out
