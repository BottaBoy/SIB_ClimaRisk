"""
Social impact metrics calculation module.

Calculates human impact metrics for each territory/hazard combination based on
population and infrastructure network states (S0, S1, S2, S3).
"""

from __future__ import annotations

import logging
from typing import Any

from .types import PopulationStateDistribution, SocialImpactMetrics

logger = logging.getLogger(__name__)


SOCIAL_IMPACT_SUMMARY_KEY = "social_impact_summary"
SOCIAL_IMPACT_SUMMARY_LEGACY_ALIASES = ("social_impact_worst_case_summary",)
SOCIAL_IMPACT_SUMMARY_BASIS = "population_projected_service_state_from_aggregated_native_service_state_v1"
SOCIAL_IMPACT_POPULATION_STATE_DISTRIBUTION_KEY = "social_impact_population_state_distribution"
SERVICE_NAMES = ("elec", "water_aep", "water_eu")
VALID_STATES = {"S0", "S1", "S2", "S3"}


def _normalize_state(state: str | None) -> str:
    normalized = str(state or "S0").upper()
    if normalized not in VALID_STATES:
        return "S0"
    return normalized


def _normalize_coverage(infra_coverage: dict[str, bool] | None) -> dict[str, bool]:
    if infra_coverage is None:
        return {service: True for service in SERVICE_NAMES}
    return {service: bool(infra_coverage.get(service, False)) for service in SERVICE_NAMES}


def calculate_social_impact_metrics(
    hazard: str,
    territory_id: str,
    population_total: float,
    infra_states: dict[str, str],
    infra_coverage: dict[str, bool] | None = None,
) -> SocialImpactMetrics:
    """
    Calculate social impact metrics for a territory/hazard combination.

    Based on population and final state of each infrastructure type,
    determines how many people are affected by degraded or failed networks.

    Args:
        hazard: Hazard identifier ("storm", "storm_cmcc")
        territory_id: Territory identifier (cell ID like "cell-+16.20_-061.40")
        population_total: Total population in the territory
        infra_states: Dict mapping infrastructure type ("elec", "water_aep", "water_eu") to state ("S0"-"S3")
                     Example: {"elec": "S1", "water_aep": "S2", "water_eu": "S0"}

    Returns:
        SocialImpactMetrics instance with 7 calculated metrics
    """
    metrics = SocialImpactMetrics()

    if population_total <= 0:
        return metrics

    pop = float(population_total)

    coverage = _normalize_coverage(infra_coverage)
    elec_state = _normalize_state(infra_states.get("elec", "S0"))
    water_aep_state = _normalize_state(infra_states.get("water_aep", "S0"))
    water_eu_state = _normalize_state(infra_states.get("water_eu", "S0"))

    # Population with degraded electricity (S1 or S2)
    if coverage["elec"] and elec_state in {"S1", "S2"}:
        metrics.population_with_degraded_elec = pop

    # Population with degraded water AEP (S1 or S2)
    if coverage["water_aep"] and water_aep_state in {"S1", "S2"}:
        metrics.population_with_degraded_water_aep = pop

    # Population with degraded water EU (S1 or S2)
    if coverage["water_eu"] and water_eu_state in {"S1", "S2"}:
        metrics.population_with_degraded_water_eu = pop

    # Population without electricity (S3)
    if coverage["elec"] and elec_state == "S3":
        metrics.population_without_elec = pop

    # Population without water AEP (S3)
    if coverage["water_aep"] and water_aep_state == "S3":
        metrics.population_without_water_aep = pop

    # Population without water EU (S3)
    if coverage["water_eu"] and water_eu_state == "S3":
        metrics.population_without_water_eu = pop

    # Total population affected: anyone in a cell where at least one network is not S0
    if (
        (coverage["elec"] and elec_state != "S0")
        or (coverage["water_aep"] and water_aep_state != "S0")
        or (coverage["water_eu"] and water_eu_state != "S0")
    ):
        metrics.total_population_affected = pop

    return metrics


def calculate_population_state_distribution(
    hazard: str,
    territory_id: str,
    population_total: float,
    infra_states: dict[str, str],
    infra_coverage: dict[str, bool] | None = None,
) -> dict[str, PopulationStateDistribution]:
    """Assign each service's cell population to exactly one state bucket or `uncovered`."""
    distributions = {service: PopulationStateDistribution() for service in SERVICE_NAMES}
    pop = max(0.0, float(population_total))
    coverage = _normalize_coverage(infra_coverage)

    for service in SERVICE_NAMES:
        distributions[service].assign_population(
            state=_normalize_state(infra_states.get(service, "S0")),
            population=pop,
            covered=coverage[service],
        )

    return distributions


def aggregate_social_metrics_by_territory(
    population_by_territory: dict[str, float],
    detailed_states: dict[str, dict[str, dict[str, str]]],
    coverage_by_territory: dict[str, dict[str, dict[str, bool]]] | None = None,
) -> dict[str, dict[str, SocialImpactMetrics]]:
    """
    Aggregate social impact metrics for all territories and hazards.

    Processes population and infrastructure state data to produce metrics
    for each hazard/territory combination.

    Args:
        population_by_territory: Dict mapping territory_id (cell ID) to population count
        detailed_states: Dict[hazard][territory_id][infra_type] -> state
                        Example: {"storm": {"cell-+16.20_-061.40": {"elec": "S1", ...}}}

    Returns:
        Dict[hazard][territory_id] -> SocialImpactMetrics
    """
    result: dict[str, dict[str, SocialImpactMetrics]] = {}

    if not detailed_states:
        return result

    for hazard, states_by_territory in detailed_states.items():
        result[hazard] = {}

        for territory_id, infra_states in states_by_territory.items():
            population = population_by_territory.get(territory_id, 0.0)
            infra_coverage = None
            if coverage_by_territory is not None:
                infra_coverage = (coverage_by_territory.get(hazard) or {}).get(territory_id)
            metrics = calculate_social_impact_metrics(
                hazard=hazard,
                territory_id=territory_id,
                population_total=population,
                infra_states=infra_states,
                infra_coverage=infra_coverage,
            )
            result[hazard][territory_id] = metrics

    return result


def aggregate_population_state_distribution_by_territory(
    population_by_territory: dict[str, float],
    detailed_states: dict[str, dict[str, dict[str, str]]],
    coverage_by_territory: dict[str, dict[str, dict[str, bool]]] | None = None,
) -> dict[str, dict[str, dict[str, PopulationStateDistribution]]]:
    """Build per-territory service distributions on the canonical cell+service state contract."""
    result: dict[str, dict[str, dict[str, PopulationStateDistribution]]] = {}

    if not detailed_states:
        return result

    for hazard, states_by_territory in detailed_states.items():
        result[hazard] = {}
        for territory_id, infra_states in states_by_territory.items():
            infra_coverage = None
            if coverage_by_territory is not None:
                infra_coverage = (coverage_by_territory.get(hazard) or {}).get(territory_id)
            result[hazard][territory_id] = calculate_population_state_distribution(
                hazard=hazard,
                territory_id=territory_id,
                population_total=population_by_territory.get(territory_id, 0.0),
                infra_states=infra_states,
                infra_coverage=infra_coverage,
            )

    return result


def aggregate_population_state_distribution_summary(
    population_state_distributions: dict[str, dict[str, dict[str, PopulationStateDistribution]]],
) -> dict[str, dict[str, dict[str, Any]]]:
    """Aggregate canonical service distributions to island-level hazard summaries."""
    result: dict[str, dict[str, dict[str, Any]]] = {}

    for hazard, territory_distributions in population_state_distributions.items():
        service_totals = {service: PopulationStateDistribution() for service in SERVICE_NAMES}
        for distributions_by_service in territory_distributions.values():
            for service, distribution in distributions_by_service.items():
                service_totals[service].merge(distribution)
        result[hazard] = {
            service: distribution.to_dict() for service, distribution in service_totals.items()
        }

    return result


def aggregate_social_summary(
    social_metrics: dict[str, dict[str, SocialImpactMetrics]],
) -> dict[str, dict[str, float]]:
    """
    Aggregate social metrics to portfolio-level summary.

    Sums up human impacts across all territories for each hazard.

    Args:
        social_metrics: Result from aggregate_social_metrics_by_territory

    Returns:
        Dict[hazard] -> {metric_name -> total_count}
        Example: {"storm": {"total_population_affected_any_network": 123456, ...}}
    """
    result: dict[str, dict[str, float]] = {}

    for hazard, metrics_by_territory in social_metrics.items():
        summary = {
            "total_population_affected_any_network": 0.0,
            "total_with_degraded_elec": 0.0,
            "total_with_degraded_water_aep": 0.0,
            "total_with_degraded_water_eu": 0.0,
            "total_without_elec": 0.0,
            "total_without_water_aep": 0.0,
            "total_without_water_eu": 0.0,
        }

        for metrics in metrics_by_territory.values():
            summary["total_population_affected_any_network"] += metrics.total_population_affected
            summary["total_with_degraded_elec"] += metrics.population_with_degraded_elec
            summary["total_with_degraded_water_aep"] += metrics.population_with_degraded_water_aep
            summary["total_with_degraded_water_eu"] += metrics.population_with_degraded_water_eu
            summary["total_without_elec"] += metrics.population_without_elec
            summary["total_without_water_aep"] += metrics.population_without_water_aep
            summary["total_without_water_eu"] += metrics.population_without_water_eu

        result[hazard] = {k: round(v, 0) for k, v in summary.items()}

    return result


def build_social_impact_summary_payload(
    social_summary_by_hazard: dict[str, dict[str, float]],
    population_state_distribution_by_hazard: dict[str, dict[str, dict[str, Any]]] | None = None,
    state_aggregation_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Package social summaries with the canonical cell+service basis and legacy aliases."""
    summary = social_summary_by_hazard if isinstance(social_summary_by_hazard, dict) else {}
    population_distribution = (
        population_state_distribution_by_hazard
        if isinstance(population_state_distribution_by_hazard, dict)
        else {}
    )
    payload: dict[str, Any] = {
        SOCIAL_IMPACT_SUMMARY_KEY: summary,
        SOCIAL_IMPACT_POPULATION_STATE_DISTRIBUTION_KEY: population_distribution,
        "social_impact_summary_basis": SOCIAL_IMPACT_SUMMARY_BASIS,
        "social_impact_summary_key": SOCIAL_IMPACT_SUMMARY_KEY,
        "social_impact_summary_legacy_aliases": list(SOCIAL_IMPACT_SUMMARY_LEGACY_ALIASES),
        "state_aggregation_metadata": state_aggregation_metadata if isinstance(state_aggregation_metadata, dict) else {},
    }
    for alias in SOCIAL_IMPACT_SUMMARY_LEGACY_ALIASES:
        payload[alias] = summary
    return payload
