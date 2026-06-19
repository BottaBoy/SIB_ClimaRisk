#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.risk_engine.hazard_comparison_engine import (  # noqa: E402
    DEFAULT_HAZARD_COMPARISON_CATALOGS_PATH,
    DEFAULT_HAZARD_COMPARISON_RUNS_ROOT,
    DEFAULT_HAZARD_COMPARISON_SCENARIOS_PATH,
    HazardComparisonExecutionError,
    build_hazard_comparison_execution_plan,
    materialize_hazard_comparison_exports,
    materialize_hazard_comparison_hazards,
    materialize_hazard_comparison_metrics,
    materialize_hazard_comparison_report,
)
from backend.app.risk_engine.hazard_comparison_registry import DEFAULT_HAZARD_COMPARISON_REGISTRY_PATH  # noqa: E402


UTC = timezone.utc


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class HazardComparisonRunLogger:
    def __init__(self, *, run_id: str, events_path: Path):
        self.run_id = str(run_id)
        self.events_path = Path(events_path)
        self.events_path.parent.mkdir(parents=True, exist_ok=True)

    def log_event(self, event: str, **kwargs: Any) -> dict[str, Any]:
        payload = {
            "timestamp": _utc_now(),
            "run_id": self.run_id,
            "event": str(event),
        }
        payload.update(kwargs)
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return payload


class HazardComparisonRunManifest:
    def __init__(
        self,
        *,
        root_dir: Path,
        run_id: str,
        data: dict[str, Any],
        persist: bool = True,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.run_id = str(run_id)
        self.run_dir = self.root_dir / self.run_id
        self.manifest_path = self.run_dir / "manifest.json"
        self.latest_path = self.root_dir / "latest-manifest.json"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.data: dict[str, Any] = dict(data)
        self.data["run_id"] = self.run_id
        self.data["manifest_path"] = str(self.manifest_path)
        self.data["events_path"] = str(self.run_dir / "events.jsonl")
        if persist:
            self.write()

    @classmethod
    def load(cls, *, root_dir: Path, run_id: str) -> "HazardComparisonRunManifest":
        manifest_path = Path(root_dir) / str(run_id) / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Hazard comparison manifest not found: {manifest_path}")
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Invalid hazard comparison manifest payload: {manifest_path}")
        return cls(root_dir=root_dir, run_id=run_id, data=payload, persist=False)

    def _atomic_write(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)

    def write(self) -> None:
        self.data["run_id"] = self.run_id
        self.data["manifest_path"] = str(self.manifest_path)
        self.data["events_path"] = str(self.run_dir / "events.jsonl")
        self.data.setdefault("updated_at", _utc_now())
        self._atomic_write(self.manifest_path, self.data)
        self._atomic_write(self.latest_path, self.data)

    def _territory_entry(self, territory_id: str) -> dict[str, Any]:
        territories = self.data.setdefault("territories", {})
        if not isinstance(territories, dict):
            territories = {}
            self.data["territories"] = territories
        entry = territories.setdefault(
            str(territory_id),
            {
                "label": str(territory_id),
                "status": "pending",
                "updated_at": _utc_now(),
                "phases": {},
                "scenarios": {},
            },
        )
        if not isinstance(entry, dict):
            entry = {
                "label": str(territory_id),
                "status": "pending",
                "updated_at": _utc_now(),
                "phases": {},
                "scenarios": {},
            }
            territories[str(territory_id)] = entry
        entry.setdefault("phases", {})
        entry.setdefault("scenarios", {})
        return entry

    def _scenario_entry(self, territory_id: str, scenario_id: str) -> dict[str, Any]:
        territory_entry = self._territory_entry(territory_id)
        scenarios = territory_entry.setdefault("scenarios", {})
        if not isinstance(scenarios, dict):
            scenarios = {}
            territory_entry["scenarios"] = scenarios
        entry = scenarios.setdefault(
            str(scenario_id),
            {
                "label": str(scenario_id),
                "status": "pending",
                "updated_at": _utc_now(),
                "components": {},
            },
        )
        if not isinstance(entry, dict):
            entry = {
                "label": str(scenario_id),
                "status": "pending",
                "updated_at": _utc_now(),
                "components": {},
            }
            scenarios[str(scenario_id)] = entry
        entry.setdefault("components", {})
        return entry

    def _component_entry(self, territory_id: str, scenario_id: str, component_id: str) -> dict[str, Any]:
        scenario_entry = self._scenario_entry(territory_id, scenario_id)
        components = scenario_entry.setdefault("components", {})
        if not isinstance(components, dict):
            components = {}
            scenario_entry["components"] = components
        entry = components.setdefault(
            str(component_id),
            {
                "status": "pending",
                "updated_at": _utc_now(),
            },
        )
        if not isinstance(entry, dict):
            entry = {
                "status": "pending",
                "updated_at": _utc_now(),
            }
            components[str(component_id)] = entry
        return entry

    def apply_progress(self, payload: dict[str, Any]) -> None:
        event = str(payload.get("event") or "")
        territory_id = str(payload.get("territory") or "")
        scenario_id = str(payload.get("scenario") or "")
        component_id = str(payload.get("component") or "")

        if event in {"run_initialized", "run_resumed"}:
            self.data["status"] = "running"
            self.data["mode"] = str(payload.get("phase") or self.data.get("mode") or "phase2_preflight")
        elif event == "territory_started" and territory_id:
            territory_entry = self._territory_entry(territory_id)
            territory_entry["status"] = "running"
            territory_entry["updated_at"] = payload.get("timestamp") or _utc_now()
            territory_entry.setdefault("phases", {})["phase3_hazard_build"] = {
                "status": "running",
                "started_at": payload.get("timestamp") or _utc_now(),
                "grid_point_count": payload.get("grid_point_count"),
                "surge_grid_point_count": payload.get("surge_grid_point_count"),
                "dynamic_max_tracks": payload.get("dynamic_max_tracks"),
            }
        elif event == "scenario_started" and territory_id and scenario_id:
            scenario_entry = self._scenario_entry(territory_id, scenario_id)
            scenario_entry["status"] = "running"
            scenario_entry["updated_at"] = payload.get("timestamp") or _utc_now()
            scenario_entry.setdefault("components", {})
        elif event == "component_started" and territory_id and scenario_id and component_id:
            component_entry = self._component_entry(territory_id, scenario_id, component_id)
            component_entry["status"] = "running"
            component_entry["updated_at"] = payload.get("timestamp") or _utc_now()
            component_entry["started_at"] = payload.get("timestamp") or _utc_now()
            if payload.get("output_path") is not None:
                component_entry["output_path"] = str(payload.get("output_path"))
        elif event == "component_completed" and territory_id and scenario_id and component_id:
            component_entry = self._component_entry(territory_id, scenario_id, component_id)
            component_entry["status"] = "complete"
            component_entry["updated_at"] = payload.get("timestamp") or _utc_now()
            component_entry["completed_at"] = payload.get("timestamp") or _utc_now()
            if payload.get("output_path") is not None:
                component_entry["output_path"] = str(payload.get("output_path"))
            if payload.get("event_count") is not None:
                component_entry["event_count"] = int(payload.get("event_count") or 0)
            if payload.get("resumed") is True:
                component_entry["resumed"] = True
        elif event == "scenario_completed" and territory_id and scenario_id:
            scenario_entry = self._scenario_entry(territory_id, scenario_id)
            scenario_entry["status"] = "complete"
            scenario_entry["updated_at"] = payload.get("timestamp") or _utc_now()
            scenario_entry["completed_at"] = payload.get("timestamp") or _utc_now()
            if payload.get("track_count_used") is not None:
                scenario_entry["track_count_used"] = int(payload.get("track_count_used") or 0)
        elif event == "territory_completed" and territory_id:
            territory_entry = self._territory_entry(territory_id)
            territory_entry["status"] = "complete"
            territory_entry["updated_at"] = payload.get("timestamp") or _utc_now()
            territory_entry["completed_at"] = payload.get("timestamp") or _utc_now()
        elif event == "run_completed":
            self.data["status"] = str(payload.get("status") or "complete")
            self.data["finished_at"] = payload.get("timestamp") or _utc_now()
        elif event == "run_failed":
            self.data["status"] = "failed"
            self.data["error"] = {
                "type": str(payload.get("error_type") or ""),
                "message": str(payload.get("error_message") or ""),
            }
        self.data["latest_event"] = dict(payload)
        self.data["updated_at"] = payload.get("timestamp") or _utc_now()


def run_hazard_comparative_analysis(
    *,
    run_id: str | None = None,
    resume_run_id: str | None = None,
    output_root: Path | None = None,
    registry_path: Path | None = None,
    catalogs_path: Path | None = None,
    scenarios_path: Path | None = None,
    territory_ids: tuple[str, ...] | None = None,
    scenario_ids: tuple[str, ...] | None = None,
    plan_only: bool = False,
    dynamic_max_tracks: int | None = None,
) -> dict[str, Any]:
    if run_id is not None and resume_run_id is not None and str(run_id).strip() != str(resume_run_id).strip():
        raise ValueError("run_id and resume_run_id must match when both are provided")
    resolved_run_id = str(resume_run_id or run_id or _new_run_id())
    resolved_output_root = Path(output_root or DEFAULT_HAZARD_COMPARISON_RUNS_ROOT)
    run_dir = resolved_output_root / resolved_run_id
    manifest_path = run_dir / "manifest.json"
    latest_manifest_path = resolved_output_root / "latest-manifest.json"
    events_path = run_dir / "events.jsonl"
    logger = HazardComparisonRunLogger(run_id=resolved_run_id, events_path=events_path)
    manifest_obj: HazardComparisonRunManifest
    resume_mode = bool(resume_run_id is not None)

    if resume_mode:
        manifest_obj = HazardComparisonRunManifest.load(root_dir=resolved_output_root, run_id=resolved_run_id)
        if str(manifest_obj.data.get("status") or "").lower() == "success":
            return manifest_obj.data
        manifest_obj.data["status"] = "running"
        manifest_obj.data["resumed_at"] = _utc_now()
        manifest_obj.data["updated_at"] = _utc_now()
        manifest_obj.write()
    else:
        manifest_obj = HazardComparisonRunManifest(
            root_dir=resolved_output_root,
            run_id=resolved_run_id,
            data={
                "run_id": resolved_run_id,
                "status": "running",
                "created_at": _utc_now(),
                "updated_at": _utc_now(),
                "mode": "phase2_preflight",
                "plan_only": bool(plan_only),
                "manifest_path": str(manifest_path),
                "events_path": str(events_path),
                "parameters": {
                    "registry_path": str(Path(registry_path or DEFAULT_HAZARD_COMPARISON_REGISTRY_PATH)),
                    "catalogs_path": str(Path(catalogs_path or DEFAULT_HAZARD_COMPARISON_CATALOGS_PATH)),
                    "scenarios_path": str(Path(scenarios_path or DEFAULT_HAZARD_COMPARISON_SCENARIOS_PATH)),
                    "territories": list(territory_ids or ()),
                    "scenarios": list(scenario_ids or ()),
                    "dynamic_max_tracks": int(dynamic_max_tracks) if dynamic_max_tracks is not None else None,
                },
                "territories": {},
                "latest_event": None,
            },
        )

    manifest = manifest_obj.data

    def _persist() -> None:
        manifest["updated_at"] = _utc_now()
        manifest_obj.write()

    def _log_and_persist(event_name: str, **kwargs: Any) -> dict[str, Any]:
        event = logger.log_event(event_name, **kwargs)
        manifest["latest_event"] = event
        manifest_obj.apply_progress(event)
        _persist()
        return event

    try:
        if resume_mode:
            _log_and_persist(
                "run_resumed",
                phase=str(manifest.get("mode") or "phase3_hazard_build"),
                plan_only=bool(plan_only),
                territory_count_requested=int(len(territory_ids or ())),
                scenario_count_requested=int(len(scenario_ids or ())),
            )
            plan = manifest
        else:
            _log_and_persist(
                "run_initialized",
                phase="phase2_preflight",
                plan_only=bool(plan_only),
                territory_count_requested=int(len(territory_ids or ())),
                scenario_count_requested=int(len(scenario_ids or ())),
            )

            plan = build_hazard_comparison_execution_plan(
                run_id=resolved_run_id,
                output_root=resolved_output_root,
                registry_path=registry_path,
                catalogs_path=catalogs_path,
                scenarios_path=scenarios_path,
                territory_ids=territory_ids,
                scenario_ids=scenario_ids,
                check_filesystem=True,
            )

            for territory_id, territory_payload in plan.get("territories", {}).items():
                scenario_payloads = territory_payload.get("scenarios") if isinstance(territory_payload.get("scenarios"), dict) else {}
                _log_and_persist(
                    "territory_planned",
                    phase="phase2_preflight",
                    territory=territory_id,
                    status=str(territory_payload.get("status") or "ready"),
                    scenario_ids=list(scenario_payloads.keys()),
                    component_count=sum(
                        len(scenario_payload.get("components") or {})
                        for scenario_payload in scenario_payloads.values()
                        if isinstance(scenario_payload, dict)
                    ),
                )
                for scenario_id, scenario_payload in scenario_payloads.items():
                    _log_and_persist(
                        "scenario_planned",
                        phase="phase2_preflight",
                        territory=territory_id,
                        scenario=scenario_id,
                        provider=str(scenario_payload.get("track_catalog_provider") or ""),
                        catalog_track_count=int((scenario_payload.get("catalog") or {}).get("track_count") or 0),
                    )

            manifest.update(plan)
            _persist()

            if plan_only:
                manifest["status"] = "planned"
                _log_and_persist(
                    "run_completed",
                    phase="phase2_preflight",
                    status=manifest["status"],
                    territory_count=int(len(plan.get("territories") or {})),
                    scenario_count=int(len(plan.get("selected_scenarios") or [])),
                )
                return manifest

        effective_dynamic_max_tracks = dynamic_max_tracks
        if resume_mode:
            stored_dynamic_max_tracks = (manifest.get("parameters") or {}).get("dynamic_max_tracks")
            if stored_dynamic_max_tracks is not None:
                effective_dynamic_max_tracks = int(stored_dynamic_max_tracks)

        manifest["mode"] = "phase3_hazard_build"
        _log_and_persist(
            "phase3_started",
            phase="phase3_hazard_build",
            dynamic_max_tracks=int(effective_dynamic_max_tracks) if effective_dynamic_max_tracks is not None else None,
            territory_count=int(len(plan.get("territories") or {})),
            scenario_count=int(len(plan.get("selected_scenarios") or [])),
        )

        def _progress_callback(payload: dict[str, Any]) -> None:
            event_name = str(payload.get("event") or "phase3_progress")
            event_kwargs = {key: value for key, value in payload.items() if key != "event"}
            _log_and_persist(event_name, **event_kwargs)

        executed = materialize_hazard_comparison_hazards(
            plan,
            dynamic_max_tracks=effective_dynamic_max_tracks,
            resume_enabled=resume_mode,
            progress_callback=_progress_callback,
        )
        manifest.update(executed)

        manifest["mode"] = "phase4_metric_extraction"
        _log_and_persist(
            "phase4_started",
            phase="phase4_metric_extraction",
            territory_count=int(len(manifest.get("territories") or {})),
            scenario_count=int(len(manifest.get("selected_scenarios") or [])),
        )

        executed = materialize_hazard_comparison_metrics(
            manifest,
            progress_callback=_progress_callback,
        )
        manifest.update(executed)

        manifest["mode"] = "phase5_export_artifacts"
        _log_and_persist(
            "phase5_started",
            phase="phase5_export_artifacts",
            territory_count=int(len(manifest.get("territories") or {})),
            scenario_count=int(len(manifest.get("selected_scenarios") or [])),
        )

        executed = materialize_hazard_comparison_exports(
            manifest,
            progress_callback=_progress_callback,
        )
        manifest.update(executed)

        manifest["mode"] = "phase6_html_report"
        _log_and_persist(
            "phase6_started",
            phase="phase6_html_report",
            territory_count=int(len(manifest.get("territories") or {})),
            scenario_count=int(len(manifest.get("selected_scenarios") or [])),
        )

        executed = materialize_hazard_comparison_report(
            manifest,
            progress_callback=_progress_callback,
        )
        manifest.update(executed)
        manifest["status"] = str(executed.get("status") or "complete")
        _log_and_persist(
            "run_completed",
            phase="phase6_html_report",
            status=manifest["status"],
            territory_count=int(len(manifest.get("territories") or {})),
            scenario_count=int(len(manifest.get("selected_scenarios") or [])),
        )
        return manifest
    except HazardComparisonExecutionError as exc:
        manifest.update(exc.payload)
        manifest["status"] = "failed"
        _log_and_persist(
            "run_failed",
            phase=str(manifest.get("mode") or exc.payload.get("mode") or "phase2_preflight"),
            status="failed",
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        raise
    except Exception as exc:
        _log_and_persist(
            "run_failed",
            phase=str(manifest.get("mode") or "phase2_preflight"),
            status="failed",
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        manifest["status"] = "failed"
        manifest["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        _persist()
        raise


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lot 2-6 runner for the hazard-only comparison chain (strict preflight, native hazard build, metrics, exports, HTML report, manifest, and event log)."
    )
    parser.add_argument("--run-id", default=None, help="Optional explicit run id.")
    parser.add_argument("--resume-run-id", default=None, help="Resume an existing hazard comparison run id.")
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_HAZARD_COMPARISON_RUNS_ROOT),
        help="Output root for run-scoped manifests and logs.",
    )
    parser.add_argument(
        "--registry-path",
        default=str(DEFAULT_HAZARD_COMPARISON_REGISTRY_PATH),
        help="Territory registry JSON path.",
    )
    parser.add_argument(
        "--catalogs-path",
        default=str(DEFAULT_HAZARD_COMPARISON_CATALOGS_PATH),
        help="Comparison catalogs JSON path.",
    )
    parser.add_argument(
        "--scenarios-path",
        default=str(DEFAULT_HAZARD_COMPARISON_SCENARIOS_PATH),
        help="Scenario definition JSON path.",
    )
    parser.add_argument(
        "--territories",
        nargs="*",
        default=None,
        help="Optional subset of territory ids or aliases.",
    )
    parser.add_argument(
        "--scenarios",
        nargs="*",
        default=None,
        help="Optional subset of scenario ids.",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Mark the run as a planning-only preflight checkpoint for phase 3.",
    )
    parser.add_argument(
        "--dynamic-max-tracks",
        type=int,
        default=None,
        help="Optional override for the dynamic track cap used by the native lot 3 hazard build.",
    )
    args = parser.parse_args()

    manifest = run_hazard_comparative_analysis(
        run_id=args.run_id,
        resume_run_id=args.resume_run_id,
        output_root=Path(args.output_root),
        registry_path=Path(args.registry_path),
        catalogs_path=Path(args.catalogs_path),
        scenarios_path=Path(args.scenarios_path),
        territory_ids=tuple(str(value) for value in args.territories) if args.territories else None,
        scenario_ids=tuple(str(value) for value in args.scenarios) if args.scenarios else None,
        plan_only=bool(args.plan_only),
        dynamic_max_tracks=int(args.dynamic_max_tracks) if args.dynamic_max_tracks is not None else None,
    )
    print(
        json.dumps(
            {
                "run_id": manifest["run_id"],
                "status": manifest["status"],
                "manifest_path": manifest["manifest_path"],
                "events_path": manifest["events_path"],
                "territory_count": len(manifest.get("territories") or {}),
                "scenario_count": len(manifest.get("selected_scenarios") or []),
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
