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
    run_label: str | None,
    exposure: NormalizedExposure,
    disagg: DisaggregationSummary,
    comp: ImpactComputationResult,
) -> dict[str, Any]:
    now = datetime.now(UTC).replace(microsecond=0)
    notes = list(comp.notes)
    notes.extend(disagg.warnings)
    notes.extend(exposure.warnings)
    category_counts = Counter((f.exposure_category or "habitation") for f in exposure.features)
    input_features_geojson, was_truncated = _build_input_features_geojson(exposure, max_features=5000)
    if was_truncated:
        notes.append("Input geometry preview was truncated to 5000 features for map rendering.")
    clean_run_label = str(run_label or "").strip()

    payload: dict[str, Any] = {
        "meta": {
            "title": clean_run_label or "SIB Cyclone Risk Thesis Demo",
            "run_label": clean_run_label or None,
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
        "asset_results": comp.asset_results,
        "portfolio_results": comp.portfolio_results,
        "graphs": comp.graphs,
        "artifacts": {
            "plots_png": [],
            "downloads": [],
        },
        "notes": _dedupe_non_empty(notes),
    }
    if input_features_geojson is not None:
        payload["input_features_geojson"] = input_features_geojson
    if comp.modeling:
        payload["meta"]["modeling"] = comp.modeling
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


def build_event_summary_csv(event_summary: dict[str, Any] | None) -> bytes | None:
    if not event_summary or not isinstance(event_summary, dict):
        return None

    rows: list[dict[str, Any]] = []
    for hazard_key, events in event_summary.items():
        if not isinstance(events, list):
            continue
        for rank, event in enumerate(events, start=1):
            if not isinstance(event, dict):
                continue
            rows.append(
                {
                    "hazard": hazard_key,
                    "rank": rank,
                    "event_id": event.get("event_id"),
                    "event_name": event.get("event_name"),
                    "loss_eur": event.get("loss_eur"),
                    "frequency_annual": event.get("frequency_annual"),
                    "return_period_years_approx": event.get("return_period_years_approx"),
                }
            )

    if not rows:
        return None

    output = io.StringIO()
    fieldnames = ["hazard", "rank", "event_id", "event_name", "loss_eur", "frequency_annual", "return_period_years_approx"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue().encode("utf-8")


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


def _build_input_features_geojson(
    exposure: NormalizedExposure,
    *,
    max_features: int = 5000,
) -> tuple[dict[str, Any] | None, bool]:
    features: list[dict[str, Any]] = []
    truncated = False
    limit = max(1, int(max_features))
    for idx, feat in enumerate(exposure.features):
        if len(features) >= limit:
            truncated = True
            break
        geom = feat.geometry_geojson
        if not isinstance(geom, dict):
            if feat.lon is None or feat.lat is None:
                continue
            geom = {"type": "Point", "coordinates": [float(feat.lon), float(feat.lat)]}
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "asset_id": str(feat.feature_id),
                    "label": str(feat.label),
                    "value_eur": float(feat.value_eur),
                    "asset_type": str((feat.properties or {}).get("asset_type") or ""),
                    "exposure_category": str(feat.exposure_category or "habitation"),
                    "geometry_type": str(feat.geometry_type or ""),
                    "row_index": idx + 1,
                },
                "geometry": geom,
            }
        )
    if not features:
        return None, truncated
    return {"type": "FeatureCollection", "features": features}, truncated
