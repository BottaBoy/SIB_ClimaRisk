"""
Tests for social impact metrics calculation module.
"""

import pytest

from backend.app.risk_engine.social_impact import (
    calculate_social_impact_metrics,
    aggregate_social_metrics_by_territory,
    aggregate_social_summary,
)
from backend.app.risk_engine.types import SocialImpactMetrics


class TestCalculateSocialImpactMetrics:
    """Test calculate_social_impact_metrics function."""

    def test_all_s0_no_impact(self):
        """All networks operational (S0) => no population affected."""
        metrics = calculate_social_impact_metrics(
            hazard="storm",
            territory_id="cell-+16.20_-061.40",
            population_total=1000.0,
            infra_states={"elec": "S0", "water_aep": "S0", "water_eu": "S0"},
        )
        assert metrics.population_with_degraded_elec == 0.0
        assert metrics.population_with_degraded_water_aep == 0.0
        assert metrics.population_with_degraded_water_eu == 0.0
        assert metrics.population_without_elec == 0.0
        assert metrics.population_without_water_aep == 0.0
        assert metrics.population_without_water_eu == 0.0
        assert metrics.total_population_affected == 0.0

    def test_electricity_degraded_s1(self):
        """Electricity degraded (S1) => population affected."""
        metrics = calculate_social_impact_metrics(
            hazard="storm",
            territory_id="cell-+16.20_-061.40",
            population_total=1000.0,
            infra_states={"elec": "S1", "water_aep": "S0", "water_eu": "S0"},
        )
        assert metrics.population_with_degraded_elec == 1000.0
        assert metrics.population_without_elec == 0.0
        assert metrics.total_population_affected == 1000.0

    def test_electricity_degraded_s2(self):
        """Electricity critical (S2) => population affected."""
        metrics = calculate_social_impact_metrics(
            hazard="storm",
            territory_id="cell-+16.20_-061.40",
            population_total=1000.0,
            infra_states={"elec": "S2", "water_aep": "S0", "water_eu": "S0"},
        )
        assert metrics.population_with_degraded_elec == 1000.0
        assert metrics.population_without_elec == 0.0
        assert metrics.total_population_affected == 1000.0

    def test_electricity_down_s3(self):
        """Electricity down (S3) => population without access."""
        metrics = calculate_social_impact_metrics(
            hazard="storm",
            territory_id="cell-+16.20_-061.40",
            population_total=1000.0,
            infra_states={"elec": "S3", "water_aep": "S0", "water_eu": "S0"},
        )
        assert metrics.population_with_degraded_elec == 0.0
        assert metrics.population_without_elec == 1000.0
        assert metrics.total_population_affected == 1000.0

    def test_water_aep_degraded_and_down(self):
        """Water AEP states S1, S2, S3 handled correctly."""
        # S1 degraded
        metrics_s1 = calculate_social_impact_metrics(
            hazard="storm",
            territory_id="cell-+16.20_-061.40",
            population_total=2000.0,
            infra_states={"elec": "S0", "water_aep": "S1", "water_eu": "S0"},
        )
        assert metrics_s1.population_with_degraded_water_aep == 2000.0
        assert metrics_s1.population_without_water_aep == 0.0

        # S3 down
        metrics_s3 = calculate_social_impact_metrics(
            hazard="storm",
            territory_id="cell-+16.20_-061.40",
            population_total=2000.0,
            infra_states={"elec": "S0", "water_aep": "S3", "water_eu": "S0"},
        )
        assert metrics_s3.population_with_degraded_water_aep == 0.0
        assert metrics_s3.population_without_water_aep == 2000.0

    def test_water_eu_degraded_and_down(self):
        """Water EU (wastewater) states handled correctly."""
        metrics = calculate_social_impact_metrics(
            hazard="storm",
            territory_id="cell-+16.20_-061.40",
            population_total=1500.0,
            infra_states={"elec": "S0", "water_aep": "S0", "water_eu": "S2"},
        )
        assert metrics.population_with_degraded_water_eu == 1500.0
        assert metrics.total_population_affected == 1500.0

    def test_multiple_networks_affected(self):
        """Multiple networks affected => population counted in multiple metrics."""
        metrics = calculate_social_impact_metrics(
            hazard="storm",
            territory_id="cell-+16.20_-061.40",
            population_total=5000.0,
            infra_states={"elec": "S1", "water_aep": "S2", "water_eu": "S3"},
        )
        assert metrics.population_with_degraded_elec == 5000.0
        assert metrics.population_with_degraded_water_aep == 5000.0
        assert metrics.population_without_water_eu == 5000.0
        assert metrics.total_population_affected == 5000.0

    def test_zero_population(self):
        """Zero population => all metrics are zero."""
        metrics = calculate_social_impact_metrics(
            hazard="storm",
            territory_id="cell-+16.20_-061.40",
            population_total=0.0,
            infra_states={"elec": "S3", "water_aep": "S3", "water_eu": "S3"},
        )
        assert metrics.population_with_degraded_elec == 0.0
        assert metrics.population_without_elec == 0.0
        assert metrics.total_population_affected == 0.0

    def test_invalid_state_defaults_to_s0(self):
        """Invalid state strings default to S0 (no impact)."""
        metrics = calculate_social_impact_metrics(
            hazard="storm",
            territory_id="cell-+16.20_-061.40",
            population_total=1000.0,
            infra_states={"elec": "INVALID", "water_aep": "S0", "water_eu": "S0"},
        )
        assert metrics.population_with_degraded_elec == 0.0
        assert metrics.total_population_affected == 0.0

    def test_missing_infra_defaults_to_s0(self):
        """Missing infrastructure state defaults to S0."""
        metrics = calculate_social_impact_metrics(
            hazard="storm",
            territory_id="cell-+16.20_-061.40",
            population_total=1000.0,
            infra_states={"elec": "S1"},  # missing water_aep, water_eu
        )
        assert metrics.population_with_degraded_elec == 1000.0
        assert metrics.population_with_degraded_water_aep == 0.0
        assert metrics.population_with_degraded_water_eu == 0.0

    def test_metrics_to_dict(self):
        """Test SocialImpactMetrics.to_dict() conversion."""
        metrics = calculate_social_impact_metrics(
            hazard="storm",
            territory_id="cell-+16.20_-061.40",
            population_total=1234.56,
            infra_states={"elec": "S2", "water_aep": "S0", "water_eu": "S0"},
        )
        metrics_dict = metrics.to_dict()
        
        assert isinstance(metrics_dict, dict)
        assert metrics_dict["population_with_degraded_elec"] == 1235.0  # rounded
        assert metrics_dict["total_population_affected"] == 1235.0


class TestAggregateSocialMetricsByTerritory:
    """Test aggregate_social_metrics_by_territory function."""

    def test_empty_inputs(self):
        """Empty inputs => empty output."""
        result = aggregate_social_metrics_by_territory(
            population_by_territory={},
            detailed_states={},
        )
        assert result == {}

    def test_single_territory_single_hazard(self):
        """Single territory/hazard combination."""
        result = aggregate_social_metrics_by_territory(
            population_by_territory={"cell-+16.20_-061.40": 5000.0},
            detailed_states={
                "storm": {
                    "cell-+16.20_-061.40": {"elec": "S1", "water_aep": "S0", "water_eu": "S0"}
                }
            },
        )
        
        assert "storm" in result
        assert "cell-+16.20_-061.40" in result["storm"]
        metrics = result["storm"]["cell-+16.20_-061.40"]
        assert isinstance(metrics, SocialImpactMetrics)
        assert metrics.population_with_degraded_elec == 5000.0
        assert metrics.total_population_affected == 5000.0

    def test_multiple_territories_multiple_hazards(self):
        """Multiple territories and hazards."""
        result = aggregate_social_metrics_by_territory(
            population_by_territory={
                "cell-+16.20_-061.40": 1000.0,
                "cell-+16.40_-061.20": 2000.0,
            },
            detailed_states={
                "storm": {
                    "cell-+16.20_-061.40": {"elec": "S1", "water_aep": "S0", "water_eu": "S0"},
                    "cell-+16.40_-061.20": {"elec": "S0", "water_aep": "S3", "water_eu": "S0"},
                },
                "storm_cmcc": {
                    "cell-+16.20_-061.40": {"elec": "S2", "water_aep": "S0", "water_eu": "S0"},
                    "cell-+16.40_-061.20": {"elec": "S0", "water_aep": "S0", "water_eu": "S0"},
                },
            },
        )
        
        # Check storm hazard
        assert result["storm"]["cell-+16.20_-061.40"].population_with_degraded_elec == 1000.0
        assert result["storm"]["cell-+16.40_-061.20"].population_without_water_aep == 2000.0
        
        # Check storm_cmcc hazard
        assert result["storm_cmcc"]["cell-+16.20_-061.40"].population_with_degraded_elec == 1000.0
        assert result["storm_cmcc"]["cell-+16.40_-061.20"].total_population_affected == 0.0

    def test_missing_population_defaults_to_zero(self):
        """Territory in states but not in population => population defaults to 0."""
        result = aggregate_social_metrics_by_territory(
            population_by_territory={},
            detailed_states={
                "storm": {
                    "cell-unknown": {"elec": "S3", "water_aep": "S0", "water_eu": "S0"}
                }
            },
        )
        
        metrics = result["storm"]["cell-unknown"]
        assert metrics.total_population_affected == 0.0


class TestAggregateSocialSummary:
    """Test aggregate_social_summary function."""

    def test_empty_metrics(self):
        """Empty metrics => all zeros."""
        result = aggregate_social_summary({})
        assert result == {}

    def test_single_hazard_single_territory(self):
        """Single hazard/territory."""
        metrics = SocialImpactMetrics(
            population_with_degraded_elec=100.0,
            population_with_degraded_water_aep=50.0,
            population_with_degraded_water_eu=0.0,
            population_without_elec=0.0,
            population_without_water_aep=0.0,
            population_without_water_eu=0.0,
            total_population_affected=100.0,
        )
        result = aggregate_social_summary(
            {"storm": {"cell-+16.20_-061.40": metrics}}
        )
        
        assert "storm" in result
        assert result["storm"]["total_population_affected_any_network"] == 100.0
        assert result["storm"]["total_with_degraded_elec"] == 100.0
        assert result["storm"]["total_with_degraded_water_aep"] == 50.0

    def test_multiple_territories_aggregation(self):
        """Multiple territories => sums aggregated."""
        metrics_1 = SocialImpactMetrics(
            population_with_degraded_elec=100.0,
            total_population_affected=100.0,
        )
        metrics_2 = SocialImpactMetrics(
            population_without_elec=200.0,
            total_population_affected=200.0,
        )
        result = aggregate_social_summary(
            {
                "storm": {
                    "cell-1": metrics_1,
                    "cell-2": metrics_2,
                }
            }
        )
        
        assert result["storm"]["total_population_affected_any_network"] == 300.0
        assert result["storm"]["total_with_degraded_elec"] == 100.0
        assert result["storm"]["total_without_elec"] == 200.0

    def test_multiple_hazards(self):
        """Multiple hazards => separate summaries."""
        metrics_storm = SocialImpactMetrics(total_population_affected=500.0)
        metrics_cmcc = SocialImpactMetrics(total_population_affected=600.0)
        
        result = aggregate_social_summary(
            {
                "storm": {"cell-1": metrics_storm},
                "storm_cmcc": {"cell-1": metrics_cmcc},
            }
        )
        
        assert result["storm"]["total_population_affected_any_network"] == 500.0
        assert result["storm_cmcc"]["total_population_affected_any_network"] == 600.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
