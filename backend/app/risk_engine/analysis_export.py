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
    valuation_audit = _build_valuation_audit(exposure)
    input_features_geojson, was_truncated = _build_input_features_geojson(exposure, max_features=5000)
    if was_truncated:
        notes.append("Input geometry preview was truncated to 5000 features for map rendering.")
    if int(valuation_audit.get("default_value_asset_count") or 0) > 0:
        notes.append(
            f"Default valuation assumption applied to {int(valuation_audit['default_value_asset_count'])} input feature(s)."
        )
    if int(valuation_audit.get("untracked_asset_count") or 0) > 0:
        notes.append(
            f"Valuation provenance metadata is missing for {int(valuation_audit['untracked_asset_count'])} input feature(s)."
        )
    clean_run_label = str(run_label or "").strip()
    impact_function_label = "Eberenz_2021_TC"
    hazard_components = ["wind"]
    if isinstance(comp.modeling, dict):
        impact_function_label = str(comp.modeling.get("impact_function_profile") or impact_function_label)
        comp_by_hazard = comp.modeling.get("multi_hazard_components_by_hazard")
        if isinstance(comp_by_hazard, dict):
            seen_components = []
            for names in comp_by_hazard.values():
                if not isinstance(names, list):
                    continue
                for name in names:
                    name_txt = str(name or "").strip().lower()
                    if name_txt and name_txt not in seen_components:
                        seen_components.append(name_txt)
            if seen_components:
                hazard_components = seen_components

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
            "impact_function": impact_function_label,
            "hazards": ["STORM", "STORM_CMCC"],
            "hazard_components": hazard_components,
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
            "default_value_asset_count": int(valuation_audit.get("default_value_asset_count") or 0),
            "explicit_value_asset_count": int(valuation_audit.get("explicit_value_asset_count") or 0),
            "untracked_valuation_asset_count": int(valuation_audit.get("untracked_asset_count") or 0),
        },
        "valuation_audit": valuation_audit,
        "territory_results": comp.territory_results,
        "asset_results": comp.asset_results,
        "portfolio_results": comp.portfolio_results,
        "matching_qa": comp.matching_qa,
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
        # Flatten social_metrics from nested dict to flat columns
        flattened_results = []
        for row in territory_results:
            flat_row = dict(row)
            
            # Handle social_metrics if present
            social_metrics = flat_row.pop("social_metrics", {})
            if isinstance(social_metrics, dict):
                for hazard, metrics_dict in social_metrics.items():
                    if isinstance(metrics_dict, dict):
                        for metric_name, metric_value in metrics_dict.items():
                            col_name = f"social_{hazard}_{metric_name}"
                            flat_row[col_name] = metric_value
            
            flattened_results.append(flat_row)
        
        # Get all fieldnames from all rows to ensure complete column set
        all_fieldnames = set()
        for row in flattened_results:
            all_fieldnames.update(row.keys())
        
        # Sort fieldnames: standard ones first, then social ones
        standard_fields = [
            "territory_id", "territory_label", "lat", "lon", 
            "exposure_eur", "population_total",
            "eai_storm_direct_eur", "eai_storm_indirect_eur", "eai_storm_eur",
            "eai_cmcc_direct_eur", "eai_cmcc_indirect_eur", "eai_cmcc_eur",
            "risk_index_storm", "risk_index_cmcc"
        ]
        social_fields = sorted([f for f in all_fieldnames if f.startswith("social_")])
        other_fields = sorted([f for f in all_fieldnames if f not in standard_fields and not f.startswith("social_")])
        
        fieldnames = [f for f in standard_fields if f in all_fieldnames] + other_fields + social_fields
        
        writer = csv.DictWriter(output, fieldnames=fieldnames, restval="")
        writer.writeheader()
        for row in flattened_results:
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
                    "uses_default_value": bool((feat.properties or {}).get("uses_default_value")),
                    "valuation_source": str((feat.properties or {}).get("valuation_source") or ""),
                    "valuation_version": str((feat.properties or {}).get("valuation_version") or ""),
                    "default_value_eur": (feat.properties or {}).get("default_value_eur"),
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


def _build_valuation_audit(
    exposure: NormalizedExposure,
    *,
    preview_limit: int = 20,
) -> dict[str, Any]:
    valuation_source_counts: Counter[str] = Counter()
    default_preview: list[dict[str, Any]] = []
    tracked_asset_count = 0
    default_value_asset_count = 0
    default_value_total_eur = 0.0

    for feat in exposure.features:
        props = feat.properties or {}
        uses_default_key_present = "uses_default_value" in props
        valuation_source = str(props.get("valuation_source") or "")
        if uses_default_key_present or valuation_source:
            tracked_asset_count += 1
        if valuation_source:
            valuation_source_counts[valuation_source] += 1
        if bool(props.get("uses_default_value")):
            default_value_asset_count += 1
            default_value_total_eur += float(feat.value_eur)
            if len(default_preview) < max(1, int(preview_limit)):
                default_preview.append(
                    {
                        "asset_id": str(feat.feature_id),
                        "label": str(feat.label),
                        "geometry_type": str(feat.geometry_type or ""),
                        "value_eur": round(float(feat.value_eur), 2),
                        "default_value_eur": props.get("default_value_eur"),
                        "valuation_source": valuation_source,
                    }
                )

    total_assets = exposure.asset_count_original
    explicit_value_asset_count = max(0, tracked_asset_count - default_value_asset_count)
    untracked_asset_count = max(0, total_assets - tracked_asset_count)

    return {
        "tracked_asset_count": int(tracked_asset_count),
        "untracked_asset_count": int(untracked_asset_count),
        "default_value_asset_count": int(default_value_asset_count),
        "explicit_value_asset_count": int(explicit_value_asset_count),
        "default_value_total_eur": round(default_value_total_eur, 2),
        "valuation_source_counts": dict(sorted(valuation_source_counts.items())),
        "default_value_asset_preview": default_preview,
        "default_value_asset_preview_truncated": bool(default_value_asset_count > len(default_preview)),
    }
