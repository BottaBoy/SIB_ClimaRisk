from __future__ import annotations

import json
from pathlib import Path
import sys
import types

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

shapely_module = types.ModuleType("shapely")
shapely_geometry_module = types.ModuleType("shapely.geometry")
shapely_geometry_module.box = lambda *args, **kwargs: None
shapely_module.geometry = shapely_geometry_module
sys.modules.setdefault("shapely", shapely_module)
sys.modules.setdefault("shapely.geometry", shapely_geometry_module)

from scripts import build_guadeloupe_page1_data


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _full_proxy_payload(*, fallback_active: bool = False) -> dict:
    scenarios = {
        scenario: {
            "component_ratios": {
                "annual": {"wind": 1.0, "rain": 0.0, "surge": 0.0, "landslide": 0.0},
                "rp50": {"wind": 0.4, "rain": 0.3, "surge": 0.3, "landslide": 0.0},
                "rp100": {"wind": 0.2, "rain": 0.3, "surge": 0.5, "landslide": 0.0},
                "event_max": {"wind": 0.1, "rain": 0.2, "surge": 0.7, "landslide": 0.0},
                "top10": {"wind": 0.8, "rain": 0.1, "surge": 0.1, "landslide": 0.0},
                "top5": {"wind": 0.7, "rain": 0.1, "surge": 0.2, "landslide": 0.0},
            }[scenario],
            "global_multiplier": 1.0,
            "breakdown_shares": {},
        }
        for scenario in build_guadeloupe_page1_data.MAP_SCENARIOS
    }
    return {
        "meta": {
            "publication_trace": {
                "artifact_kind": "multi_hazard_proxy",
                "source_mode": "lightweight_sampled_climada_proxy",
                "fallback_active": fallback_active,
            }
        },
        "hazards": {
            "storm": {"scenarios": dict(scenarios)},
            "storm_cmcc": {"scenarios": dict(scenarios)},
        },
    }


def test_load_multi_hazard_proxy_strict_rejects_missing_scenario(tmp_path: Path) -> None:
    payload = _full_proxy_payload()
    del payload["hazards"]["storm"]["scenarios"]["rp50"]
    path = tmp_path / "proxy.json"
    _write_json(path, payload)

    with pytest.raises(RuntimeError, match="storm.rp50"):
        build_guadeloupe_page1_data._load_multi_hazard_proxy(path, strict=True)


def test_load_multi_hazard_proxy_strict_rejects_fallback_trace(tmp_path: Path) -> None:
    path = tmp_path / "proxy.json"
    _write_json(path, _full_proxy_payload(fallback_active=True))

    with pytest.raises(RuntimeError, match="Fallback multi-hazard proxy is forbidden"):
        build_guadeloupe_page1_data._load_multi_hazard_proxy(path, strict=True)


def test_load_multi_hazard_proxy_strict_preserves_scenario_specific_ratios(tmp_path: Path) -> None:
    path = tmp_path / "proxy.json"
    _write_json(path, _full_proxy_payload())

    proxy = build_guadeloupe_page1_data._load_multi_hazard_proxy(path, strict=True)

    assert proxy["storm"]["component_ratios"]["annual"] == {
        "wind": 1.0,
        "rain": 0.0,
        "surge": 0.0,
        "landslide": 0.0,
    }
    assert proxy["storm"]["component_ratios"]["rp50"] == {
        "wind": 0.4,
        "rain": 0.3,
        "surge": 0.3,
        "landslide": 0.0,
    }
    assert proxy["storm"]["component_ratios"]["rp100"] == {
        "wind": 0.2,
        "rain": 0.3,
        "surge": 0.5,
        "landslide": 0.0,
    }