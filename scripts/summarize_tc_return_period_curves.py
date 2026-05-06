#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean, median


DEFAULT_INPUTS = {
    "guadeloupe": Path("/home/ubuntu/sib-work/web/data/guadeloupe-wind-maps.json"),
    "martinique": Path("/home/ubuntu/sib-work/web/data/martinique-wind-maps.json"),
}
HAZARD_KEYS = ("storm", "storm_cmcc")
METRICS = (
    ("mean_wind_mps", "mean_wind_mps"),
    ("rp50_wind_mps", "rp50_wind_mps"),
    ("rp100_wind_mps", "rp100_wind_mps"),
    ("event_max_wind_mps", "event_max_wind_mps"),
)


def _collect_numeric(rows: list[dict], key: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = row.get(key)
        if value is None:
            continue
        try:
            values.append(float(value))
        except Exception:
            continue
    return values


def _summarize_payload(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    territory = str((payload.get("meta") or {}).get("territory") or path.stem)
    out = {
        "territory": territory,
        "source": str(path),
        "hazards": {},
        "delta_cmcc_minus_storm": {},
    }
    for hazard_key in HAZARD_KEYS:
        hazard_payload = payload.get(hazard_key)
        if not isinstance(hazard_payload, dict):
            continue
        cells = hazard_payload.get("cells") or []
        if not isinstance(cells, list) or not cells:
            continue
        summary = {"cell_count": len(cells)}
        for output_key, cell_key in METRICS:
            values = _collect_numeric(cells, cell_key)
            if not values:
                continue
            summary[output_key] = {
                "mean": round(mean(values), 4),
                "median": round(median(values), 4),
                "min": round(min(values), 4),
                "max": round(max(values), 4),
            }
        out["hazards"][hazard_key] = summary

    storm = out["hazards"].get("storm") or {}
    cmcc = out["hazards"].get("storm_cmcc") or {}
    for output_key, _cell_key in METRICS:
        storm_metric = ((storm.get(output_key) or {}).get("mean"))
        cmcc_metric = ((cmcc.get(output_key) or {}).get("mean"))
        if storm_metric is None or cmcc_metric is None:
            continue
        delta = float(cmcc_metric) - float(storm_metric)
        pct = (delta / max(abs(float(storm_metric)), 1e-9)) * 100.0
        out["delta_cmcc_minus_storm"][output_key] = {
            "absolute": round(delta, 4),
            "percent": round(pct, 4),
        }
    return out


def _render_markdown(summaries: list[dict]) -> str:
    lines = [
        "# Territory Wind Return-Period Summary",
        "",
        "This file summarizes the current territory-level wind return-period indicators extracted from the published `*-wind-maps.json` artefacts.",
        "",
    ]
    for summary in summaries:
        lines.extend(
            [
                f"## {summary['territory'].title()}",
                "",
                f"Source: `{summary['source']}`",
                "",
                "| Hazard | Cells | Mean wind mean | RP50 mean | RP100 mean | Event-max mean |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for hazard_key in HAZARD_KEYS:
            hazard = summary["hazards"].get(hazard_key)
            if not hazard:
                continue
            lines.append(
                "| {hazard} | {cells} | {mean_wind:.4f} | {rp50:.4f} | {rp100:.4f} | {event_max:.4f} |".format(
                    hazard=hazard_key,
                    cells=int(hazard.get("cell_count", 0)),
                    mean_wind=float((hazard.get("mean_wind_mps") or {}).get("mean", 0.0)),
                    rp50=float((hazard.get("rp50_wind_mps") or {}).get("mean", 0.0)),
                    rp100=float((hazard.get("rp100_wind_mps") or {}).get("mean", 0.0)),
                    event_max=float((hazard.get("event_max_wind_mps") or {}).get("mean", 0.0)),
                )
            )
        delta = summary.get("delta_cmcc_minus_storm") or {}
        if delta:
            lines.extend([
                "",
                "CMCC minus STORM deltas (mean values):",
                "",
                "| Metric | Absolute | Percent |",
                "|---|---:|---:|",
            ])
            for metric_key in ("mean_wind_mps", "rp50_wind_mps", "rp100_wind_mps", "event_max_wind_mps"):
                metric = delta.get(metric_key)
                if not metric:
                    continue
                lines.append(
                    f"| {metric_key} | {float(metric['absolute']):.4f} | {float(metric['percent']):.4f}% |"
                )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize territory wind return-period curves from published wind-map artefacts.")
    parser.add_argument("--markdown-out", type=Path, help="Optional markdown output path.")
    parser.add_argument("--json-out", type=Path, help="Optional JSON output path.")
    args = parser.parse_args()

    summaries = [_summarize_payload(path) for path in DEFAULT_INPUTS.values()]
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(summaries, indent=2), encoding="utf-8")
    markdown = _render_markdown(summaries)
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(markdown + "\n", encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())