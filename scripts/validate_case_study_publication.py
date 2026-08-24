#!/usr/bin/env python3
from __future__ import annotations

import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "web"
SCIENTIFIC_SCENARIOS = ["rp10", "rp50", "rp100", "rp1000"]
FORBIDDEN_PUBLIC_SCENARIOS = {"annual", "p99", "event_max"}
POPULATION_PALETTE = ["#ffffff", "#fff7bc", "#fee391", "#fec44f", "#fb923c", "#ef4444", "#b91c1c"]
FORBIDDEN_VISIBLE_PATTERNS = (
    re.compile(r"\bP99\b", re.IGNORECASE),
    re.compile(r"percentile\s+99", re.IGNORECASE),
    re.compile(r"Evenement\s+le\s+plus\s+fort", re.IGNORECASE),
    re.compile(r"Événement\s+le\s+plus\s+fort", re.IGNORECASE),
)


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._hidden_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"} and self._hidden_depth > 0:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._hidden_depth == 0 and data.strip():
            self.parts.append(data)

    @property
    def visible_text(self) -> str:
        return " ".join(self.parts)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path} must contain a JSON object")
    return payload


def _validate_scientific_payload(territory: str, complete_path: Path, summary_path: Path) -> list[str]:
    issues: list[str] = []
    if not complete_path.is_file():
        return [f"[{territory}] missing complete-analysis: {complete_path}"]
    if not summary_path.is_file():
        return [f"[{territory}] missing scientific-web-summary: {summary_path}"]

    complete = _load_json(complete_path)
    summary = _load_json(summary_path)
    graph_inputs = complete.get("scientific_graph_inputs") if isinstance(complete.get("scientific_graph_inputs"), dict) else {}
    summary_inputs = summary.get("scientific_graph_inputs") if isinstance(summary.get("scientific_graph_inputs"), dict) else {}
    if graph_inputs.get("scenarios") != SCIENTIFIC_SCENARIOS:
        issues.append(f"[{territory}] complete-analysis scenarios are not {SCIENTIFIC_SCENARIOS}: {graph_inputs.get('scenarios')}")
    if summary_inputs.get("scenarios") != SCIENTIFIC_SCENARIOS:
        issues.append(f"[{territory}] scientific-web-summary scenarios are not {SCIENTIFIC_SCENARIOS}: {summary_inputs.get('scenarios')}")
    if graph_inputs.get("source_of_truth") != "complete_analysis":
        issues.append(f"[{territory}] scientific_graph_inputs.source_of_truth must be complete_analysis")
    for section in ("state_damage_tables", "damage_breakdown_by_scenario"):
        keys = set((graph_inputs.get(section) or {}).keys())
        forbidden = sorted(keys & FORBIDDEN_PUBLIC_SCENARIOS)
        if forbidden:
            issues.append(f"[{territory}] forbidden scenarios in {section}: {', '.join(forbidden)}")
    return issues


def _validate_graph_pack_sources(territory: str, graph_pack: Path, web_dir: Path) -> list[str]:
    issues: list[str] = []
    complete_path = graph_pack / "scientific_archive" / f"{territory}-complete-analysis.json"
    summary_path = graph_pack / "scientific_archive" / f"{territory}-scientific-web-summary.json"
    archive_available = complete_path.is_file() and summary_path.is_file()
    if archive_available:
        issues.extend(_validate_scientific_payload(territory, complete_path, summary_path))
    else:
        complete_path = web_dir / "data" / f"{territory}-complete-analysis.json"
        summary_path = web_dir / "data" / f"{territory}-scientific-web-summary.json"
        issues.extend(_validate_scientific_payload(territory, complete_path, summary_path))
    if not complete_path.is_file():
        return issues

    complete = _load_json(complete_path)
    meta = complete.get("meta") if isinstance(complete.get("meta"), dict) else {}
    modeling = meta.get("modeling") if isinstance(meta.get("modeling"), dict) else {}
    if modeling.get("hazard_source") != "dynamic_parquet":
        issues.append(f"[{territory}] expected modeling.hazard_source=dynamic_parquet, got {modeling.get('hazard_source')!r}")
    if modeling.get("hazard_dynamic_max_tracks_requested") not in (0, "0"):
        issues.append(
            f"[{territory}] expected full-track hazard_dynamic_max_tracks_requested=0, "
            f"got {modeling.get('hazard_dynamic_max_tracks_requested')!r}"
        )
    basin_ids = modeling.get("hazard_basin_ids")
    if basin_ids != [1]:
        issues.append(f"[{territory}] expected hazard_basin_ids=[1] for NA, got {basin_ids!r}")
    for relative in (
        "tables/guadeloupe_comparaison_aleas.csv",
        "tables/guadeloupe_comparaison_aleas_validation.csv",
    ):
        if territory == "guadeloupe" and not (graph_pack / relative).is_file():
            issues.append(f"[{territory}] missing graph-pack hazard comparison source: {graph_pack / relative}")
    required_graph_assets = ("graphs-manifest.json", "charts", "maps", "Population", "tables")
    missing_assets = [name for name in required_graph_assets if not (graph_pack / name).exists()]
    if missing_assets:
        issues.append(f"[{territory}] graph-pack missing assets: {', '.join(missing_assets)}")
    return issues


def _validate_population_palette(web_dir: Path) -> list[str]:
    path = web_dir / "hazard-maps" / "population-overlays.json"
    if not path.is_file():
        return [f"missing population overlay metadata: {path}"]
    payload = _load_json(path)
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    palette = meta.get("palette_hex")
    if palette != POPULATION_PALETTE:
        return [f"population overlay palette mismatch: {palette!r}"]
    return []


def _validate_visible_labels(web_dir: Path) -> list[str]:
    issues: list[str] = []
    html_path = web_dir / "index.html"
    parser = VisibleTextParser()
    parser.feed(html_path.read_text(encoding="utf-8"))
    visible_text = parser.visible_text
    for pattern in FORBIDDEN_VISIBLE_PATTERNS:
        if pattern.search(visible_text):
            issues.append(f"forbidden visible label in index.html: {pattern.pattern}")

    app_text = (web_dir / "assets" / "app.js").read_text(encoding="utf-8")
    for forbidden in ("Percentile 99", "Pertes percentile 99", "Evenement le plus fort"):
        if forbidden in app_text:
            issues.append(f"forbidden generated label in app.js: {forbidden}")
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate public case-study publication assets.")
    parser.add_argument("--web-dir", default=str(WEB_DIR))
    parser.add_argument(
        "--graph-pack",
        action="append",
        default=[],
        metavar="TERRITORY=PATH",
        help="External graph pack source to validate, e.g. guadeloupe=/home/ubuntu/uploads/from_popa/20260711_071243.",
    )
    parser.add_argument("--territories", nargs="+", default=["guadeloupe", "saint-barthelemy"])
    args = parser.parse_args(argv)

    web_dir = Path(args.web_dir)
    issues: list[str] = []
    issues.extend(_validate_population_palette(web_dir))
    issues.extend(_validate_visible_labels(web_dir))

    for territory in args.territories:
        normalized = str(territory).strip().lower()
        issues.extend(
            _validate_scientific_payload(
                normalized,
                web_dir / "data" / f"{normalized}-complete-analysis.json",
                web_dir / "data" / f"{normalized}-scientific-web-summary.json",
            )
        )

    for raw_spec in args.graph_pack:
        if "=" not in raw_spec:
            raise SystemExit("--graph-pack must use TERRITORY=PATH")
        territory, raw_path = raw_spec.split("=", 1)
        issues.extend(_validate_graph_pack_sources(territory.strip().lower(), Path(raw_path).expanduser().resolve(), web_dir))

    if issues:
        for issue in issues:
            print(f"[error] {issue}", file=sys.stderr)
        return 1
    print("[ok] case-study publication assets validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
