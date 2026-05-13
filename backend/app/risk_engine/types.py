from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


POPULATION_STATE_KEYS = ("S0", "S1", "S2", "S3", "uncovered")


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
    matching_qa: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, list[dict[str, str]]] = field(default_factory=dict)


@dataclass
class SocialImpactMetrics:
    """Social impact metrics for a territory/hazard combination."""
    population_with_degraded_elec: float = 0.0
    population_with_degraded_water_aep: float = 0.0
    population_with_degraded_water_eu: float = 0.0
    population_without_elec: float = 0.0
    population_without_water_aep: float = 0.0
    population_without_water_eu: float = 0.0
    total_population_affected: float = 0.0

    def to_dict(self) -> dict[str, float]:
        """Convert metrics to dictionary for JSON serialization."""
        return {
            "population_with_degraded_elec": round(self.population_with_degraded_elec, 0),
            "population_with_degraded_water_aep": round(self.population_with_degraded_water_aep, 0),
            "population_with_degraded_water_eu": round(self.population_with_degraded_water_eu, 0),
            "population_without_elec": round(self.population_without_elec, 0),
            "population_without_water_aep": round(self.population_without_water_aep, 0),
            "population_without_water_eu": round(self.population_without_water_eu, 0),
            "total_population_affected": round(self.total_population_affected, 0),
        }


@dataclass
class PopulationStateDistribution:
    """Population counts assigned to one canonical service state bucket."""

    S0: float = 0.0
    S1: float = 0.0
    S2: float = 0.0
    S3: float = 0.0
    uncovered: float = 0.0
    covered_population: float = 0.0
    island_population_total: float = 0.0

    def assign_population(self, *, state: str, population: float, covered: bool) -> None:
        pop = max(0.0, float(population))
        self.island_population_total += pop
        if pop <= 0.0:
            return

        if not covered:
            self.uncovered += pop
            return

        normalized_state = str(state or "S0").upper()
        if normalized_state not in {"S0", "S1", "S2", "S3"}:
            normalized_state = "S0"
        setattr(self, normalized_state, float(getattr(self, normalized_state)) + pop)
        self.covered_population += pop

    def merge(self, other: "PopulationStateDistribution") -> None:
        for key in POPULATION_STATE_KEYS:
            setattr(self, key, float(getattr(self, key)) + float(getattr(other, key)))
        self.covered_population += float(other.covered_population)
        self.island_population_total += float(other.island_population_total)

    def to_dict(self) -> dict[str, Any]:
        island_total = max(float(self.island_population_total), 0.0)
        covered_total = max(float(self.covered_population), 0.0)
        share_of_island_population = {
            key: round(float(getattr(self, key)) / island_total, 6) if island_total > 0.0 else 0.0
            for key in POPULATION_STATE_KEYS
        }
        share_of_covered_population = {
            key: round(float(getattr(self, key)) / covered_total, 6) if covered_total > 0.0 else 0.0
            for key in ("S0", "S1", "S2", "S3")
        }
        coverage_rate = round(covered_total / island_total, 6) if island_total > 0.0 else 0.0
        return {
            "S0": round(self.S0, 0),
            "S1": round(self.S1, 0),
            "S2": round(self.S2, 0),
            "S3": round(self.S3, 0),
            "uncovered": round(self.uncovered, 0),
            "covered_population": round(self.covered_population, 0),
            "island_population_total": round(self.island_population_total, 0),
            "coverage_rate": coverage_rate,
            "share_of_island_population": share_of_island_population,
            "share_of_covered_population": share_of_covered_population,
        }
