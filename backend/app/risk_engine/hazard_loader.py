from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import copy

from .errors import DependencyMissingError


@dataclass
class HazardBundle:
    storm: Any
    storm_cmcc: Any
    storm_years: int
    normalized_on_copy: bool = True


def _normalize_frequency_safe(hazard_obj: Any, storm_years: int) -> Any:
    hazard_copy = copy.deepcopy(hazard_obj)
    freq = getattr(hazard_copy, "frequency", None)
    if freq is None:
        return hazard_copy

    # Idempotent normalization marker to avoid double-dividing in reused objects.
    if getattr(hazard_copy, "_sib_frequency_normalized", False):
        return hazard_copy

    try:
        hazard_copy.frequency = freq / float(storm_years)
        setattr(hazard_copy, "_sib_frequency_normalized", True)
    except Exception:
        # Leave hazard unchanged if structure is not compatible.
        pass
    return hazard_copy


def load_storm_hazards(storm_path: Path, cmcc_path: Path, storm_years: int) -> HazardBundle:
    try:
        from climada.hazard import Hazard  # type: ignore
    except Exception as exc:  # pragma: no cover - optional at scaffold stage
        raise DependencyMissingError("CLIMADA is required to load STORM hazards") from exc

    storm = Hazard.from_hdf5(str(storm_path))
    storm_cmcc = Hazard.from_hdf5(str(cmcc_path))

    return HazardBundle(
        storm=_normalize_frequency_safe(storm, storm_years),
        storm_cmcc=_normalize_frequency_safe(storm_cmcc, storm_years),
        storm_years=storm_years,
        normalized_on_copy=True,
    )
