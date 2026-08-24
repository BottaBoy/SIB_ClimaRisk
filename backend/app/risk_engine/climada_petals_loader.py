from __future__ import annotations

from functools import lru_cache
import importlib.util
import sys
import sysconfig
from pathlib import Path
from types import ModuleType
from typing import Any

from .errors import DependencyMissingError


_ALLOWED_HAZARD_MODULES = frozenset({"landslide", "tc_rainfield", "tc_surge_bathtub"})


def _resolve_hazard_module_path(module_name: str) -> Path:
    normalized = str(module_name).strip()
    if normalized not in _ALLOWED_HAZARD_MODULES:
        raise DependencyMissingError(f"Unsupported CLIMADA Petals hazard module: {module_name}")

    purelib = Path(sysconfig.get_paths()["purelib"])
    module_path = purelib / "climada_petals" / "hazard" / f"{normalized}.py"
    if not module_path.exists():
        raise DependencyMissingError(f"CLIMADA Petals hazard module not found: {module_path}")
    return module_path


@lru_cache(maxsize=None)
def load_climada_petals_hazard_module(module_name: str) -> ModuleType:
    normalized = str(module_name).strip()
    module_path = _resolve_hazard_module_path(normalized)
    synthetic_name = f"_sib_climada_petals_hazard_{normalized}"

    existing = sys.modules.get(synthetic_name)
    if existing is not None:
        return existing

    spec = importlib.util.spec_from_file_location(synthetic_name, module_path)
    if spec is None or spec.loader is None:
        raise DependencyMissingError(f"Unable to create import spec for CLIMADA Petals module: {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[synthetic_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(synthetic_name, None)
        raise
    return module


def load_climada_petals_hazard_symbols(module_name: str, *symbol_names: str) -> dict[str, Any]:
    module = load_climada_petals_hazard_module(module_name)
    resolved: dict[str, Any] = {}
    for symbol_name in symbol_names:
        try:
            resolved[str(symbol_name)] = getattr(module, str(symbol_name))
        except AttributeError as exc:
            raise DependencyMissingError(
                f"CLIMADA Petals module '{module_name}' does not expose symbol '{symbol_name}'"
            ) from exc
    return resolved