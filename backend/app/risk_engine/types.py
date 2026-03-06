from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class NormalizedFeature:
    feature_id: str
    label: str
    value_eur: float
    geometry_type: str
    exposure_category: str = "habitation"
    lon: float | None = None
    lat: float | None = None
    geometry_geojson: dict[str, Any] | None = None
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalizedExposure:
    source_name: str
    source_format: str
    input_mode: str
    features: list[NormalizedFeature]
    warnings: list[str] = field(default_factory=list)

    @property
    def asset_count_original(self) -> int:
        return len(self.features)

    @property
    def total_exposure_eur(self) -> float:
        return float(sum(max(0.0, f.value_eur) for f in self.features))


@dataclass
class DisaggregationSummary:
    spacing_m: float
    metric_crs: str
    asset_count_points: int
    by_geometry_type: dict[str, int]
    warnings: list[str] = field(default_factory=list)


@dataclass
class ImpactComputationResult:
    engine: str
    territory_results: list[dict[str, Any]]
    portfolio_results: dict[str, Any]
    graphs: dict[str, Any]
    notes: list[str]
    asset_results: list[dict[str, Any]] = field(default_factory=list)
    modeling: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, list[dict[str, str]]] = field(default_factory=dict)
