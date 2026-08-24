from types import SimpleNamespace

import numpy as np

from backend.app.risk_engine.climada_engine import ClimadaRunResult, HazardImpactResult, RETURN_PERIODS
from backend.app.risk_engine.impact_runner import _build_climada_graphs


def _hazard_result(scale: float) -> HazardImpactResult:
    pml = {int(rp): float(scale * rp) for rp in RETURN_PERIODS}
    return HazardImpactResult(
        eai_direct_by_point=np.array([1.0, 2.0], dtype=float),
        max_loss_by_point=np.array([3.0, 4.0], dtype=float),
        at_event_loss=np.array([5.0, 15.0], dtype=float),
        event_frequency=np.array([0.1, 0.01], dtype=float),
        event_id=np.array([101, 202]),
        event_name=np.array(["evt-1", "evt-2"]),
        aai_agg_eur=3.0 * scale,
        max_event_loss_eur=15.0 * scale,
        pml_eur=pml,
        tvar_95_eur=12.0 * scale,
        top_events=[{"event_id": 202, "event_name": "evt-2", "loss_eur": 15.0 * scale}],
    )


def test_build_climada_graphs_uses_return_period_basis_and_pml_1000_comparison():
    climada = ClimadaRunResult(
        hazards={
            "storm": _hazard_result(1.0),
            "storm_cmcc": _hazard_result(2.0),
        }
    )
    portfolio_results = {
        "storm": {"eai_eur": 10.0, "pml_1000_eur": 1000.0, "percentile_99_loss_eur": 99.0},
        "storm_cmcc": {"eai_eur": 20.0, "pml_1000_eur": 2000.0, "percentile_99_loss_eur": 199.0},
    }

    graphs = _build_climada_graphs(
        climada,
        scaler_by_hazard={"storm": 1.0, "storm_cmcc": 1.0},
        portfolio_results=portfolio_results,
    )

    assert graphs["storm"]["annual_fec"]["return_period_years"] == [int(rp) for rp in RETURN_PERIODS]
    assert graphs["storm_cmcc"]["annual_fec"]["return_period_years"] == [int(rp) for rp in RETURN_PERIODS]
    assert graphs["comparison"]["side_by_side"]["metrics"] == ["annual_eai", "pml_1000"]
    assert graphs["comparison"]["side_by_side"]["values"]["pml_1000"] == [1000.0, 2000.0]