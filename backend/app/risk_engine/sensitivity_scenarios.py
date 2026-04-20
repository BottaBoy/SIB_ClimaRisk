from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import Settings


SUPPORTED_SCENARIO_PACK_VERSION = 1


@dataclass(frozen=True)
class SensitivityScenario:
    scenario_id: str
    label: str
    parameter_key: str | None
    execution_tier: str
    supported: bool
    overrides: dict[str, Any]
    notes: list[str]
    source_pack_path: Path


def load_scenario_pack(pack_path: str | Path) -> dict[str, Any]:
    path = Path(pack_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Scenario pack must be a JSON object: {path}")
    version = int(payload.get("version") or 0)
    if version != SUPPORTED_SCENARIO_PACK_VERSION:
        raise ValueError(
            f"Unsupported scenario pack version {version} in {path}; expected {SUPPORTED_SCENARIO_PACK_VERSION}"
        )
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError(f"Scenario pack does not contain any scenarios: {path}")
    payload["_path"] = str(path)
    return payload


def _scenario_from_payload_item(item: dict[str, Any], *, source_pack_path: Path) -> SensitivityScenario:
    scenario_id = str(item.get("scenario_id") or "").strip()
    if not scenario_id:
        raise ValueError(f"Scenario entry is missing a scenario_id in {source_pack_path}")
    return SensitivityScenario(
        scenario_id=scenario_id,
        label=str(item.get("label") or scenario_id),
        parameter_key=str(item.get("parameter_key") or "").strip() or None,
        execution_tier=str(item.get("execution_tier") or "full_rerun"),
        supported=bool(item.get("supported", True)),
        overrides=dict(item.get("overrides") or {}),
        notes=[str(value) for value in list(item.get("notes") or [])],
        source_pack_path=source_pack_path,
    )


def list_scenarios_from_pack(
    pack_path: str | Path,
    *,
    scenario_ids: list[str] | tuple[str, ...] | None = None,
) -> list[SensitivityScenario]:
    payload = load_scenario_pack(pack_path)
    source_pack_path = Path(str(payload.get("_path") or pack_path))
    selected_ids = None
    if scenario_ids:
        selected_ids = {str(value).strip() for value in scenario_ids if str(value).strip()}
    scenarios: list[SensitivityScenario] = []
    for item in payload.get("scenarios") or []:
        if not isinstance(item, dict):
            continue
        scenario = _scenario_from_payload_item(item, source_pack_path=source_pack_path)
        if selected_ids is not None and scenario.scenario_id not in selected_ids:
            continue
        scenarios.append(scenario)

    if selected_ids is not None:
        found_ids = {scenario.scenario_id for scenario in scenarios}
        missing_ids = sorted(selected_ids - found_ids)
        if missing_ids:
            raise ValueError(
                f"Scenarios not found in {source_pack_path}: {', '.join(missing_ids)}"
            )
    return scenarios


def resolve_scenario_from_pack(pack_path: str | Path, scenario_id: str) -> SensitivityScenario:
    payload = load_scenario_pack(pack_path)
    requested_id = str(scenario_id or "").strip()
    if not requested_id:
        raise ValueError("scenario_id must not be empty")

    for item in payload.get("scenarios") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("scenario_id") or "").strip() != requested_id:
            continue
        return _scenario_from_payload_item(
            item,
            source_pack_path=Path(str(payload.get("_path") or pack_path)),
        )

    raise ValueError(f"Scenario '{requested_id}' was not found in {pack_path}")


def apply_settings_overrides(settings: Settings, scenario: SensitivityScenario | None) -> Settings:
    if scenario is None:
        return settings
    if not scenario.supported:
        raise ValueError(
            f"Scenario '{scenario.scenario_id}' is marked as unsupported for automated execution. "
            "Define the requested manual profile first or choose another scenario."
        )

    settings_overrides = dict((scenario.overrides or {}).get("settings") or {})
    if not settings_overrides:
        return settings

    settings_dict = dataclasses.asdict(settings)
    unknown_keys = sorted(set(settings_overrides) - set(settings_dict))
    if unknown_keys:
        raise ValueError(
            f"Scenario '{scenario.scenario_id}' contains unknown Settings override keys: {', '.join(unknown_keys)}"
        )

    settings_dict.update(settings_overrides)
    return Settings(**settings_dict)


def scenario_manifest_fields(scenario: SensitivityScenario | None) -> dict[str, Any]:
    if scenario is None:
        return {}
    return {
        "scenario_id": scenario.scenario_id,
        "scenario_label": scenario.label,
        "scenario_parameter_key": scenario.parameter_key,
        "scenario_execution_tier": scenario.execution_tier,
        "scenario_pack_path": str(scenario.source_pack_path),
    }