"""
Social impact metrics calculation module.

Calculates human impact metrics for each territory/hazard combination based on
population and infrastructure network states (S0, S1, S2, S3).
"""

from __future__ import annotations

import logging
from typing import Any

from .types import SocialImpactMetrics

logger = logging.getLogger(__name__)


def calculate_social_impact_metrics(
    hazard: str,
    territory_id: str,
    population_total: float,
    infra_states: dict[str, str],
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

    # Parse infrastructure states (default to S0 if not specified)
    elec_state = str(infra_states.get("elec", "S0")).upper()
    water_aep_state = str(infra_states.get("water_aep", "S0")).upper()
    water_eu_state = str(infra_states.get("water_eu", "S0")).upper()

    # Validate states
    valid_states = {"S0", "S1", "S2", "S3"}
    if elec_state not in valid_states:
        elec_state = "S0"
    if water_aep_state not in valid_states:
        water_aep_state = "S0"
    if water_eu_state not in valid_states:
        water_eu_state = "S0"

    # Population with degraded electricity (S1 or S2)
    if elec_state in {"S1", "S2"}:
        metrics.population_with_degraded_elec = pop

    # Population with degraded water AEP (S1 or S2)
    if water_aep_state in {"S1", "S2"}:
        metrics.population_with_degraded_water_aep = pop

    # Population with degraded water EU (S1 or S2)
    if water_eu_state in {"S1", "S2"}:
        metrics.population_with_degraded_water_eu = pop

    # Population without electricity (S3)
    if elec_state == "S3":
        metrics.population_without_elec = pop

    # Population without water AEP (S3)
    if water_aep_state == "S3":
        metrics.population_without_water_aep = pop

    # Population without water EU (S3)
    if water_eu_state == "S3":
        metrics.population_without_water_eu = pop

    # Total population affected: anyone in a cell where at least one network is not S0
    if elec_state != "S0" or water_aep_state != "S0" or water_eu_state != "S0":
        metrics.total_population_affected = pop

    return metrics


def aggregate_social_metrics_by_territory(
    population_by_territory: dict[str, float],
    detailed_states: dict[str, dict[str, dict[str, str]]],
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
            metrics = calculate_social_impact_metrics(
                hazard=hazard,
                territory_id=territory_id,
                population_total=population,
                infra_states=infra_states,
            )
            result[hazard][territory_id] = metrics

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
