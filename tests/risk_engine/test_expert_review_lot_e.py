from pathlib import Path
import sys

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from types import SimpleNamespace

from backend.app.risk_engine.climada_engine import _compute_component_impact, _compute_loss_percentile, _rebuild_component_result


def test_compute_loss_percentile_uses_weighted_var99_not_raw_max():
    losses = np.array([0.0, 10.0, 20.0, 100.0], dtype=float)
    frequency = np.array([0.8, 0.1, 0.095, 0.005], dtype=float)

    percentile_99 = _compute_loss_percentile(np, losses, frequency, 0.99)

    assert percentile_99 == 20.0
    assert percentile_99 < float(losses.max())


def test_rebuild_component_result_exposes_percentile_99_and_keeps_raw_max_for_qa():
    result = _rebuild_component_result(
        np,
        eai_by_point=np.array([40.0, 60.0], dtype=float),
        at_event_loss=np.array([0.0, 10.0, 20.0, 100.0], dtype=float),
        event_frequency=np.array([0.8, 0.1, 0.095, 0.005], dtype=float),
        event_id=np.array([1, 2, 3, 4]),
        event_name=np.array(["e1", "e2", "e3", "e4"]),
        top_n_events=2,
    )

    assert result.max_event_loss_eur == 20.0
    assert result.raw_max_event_loss_eur == 100.0
    assert result.max_loss_by_point.tolist() == [8.0, 12.0]
    assert [event["event_id"] for event in result.top_events] == [4, 3]


def test_compute_component_impact_uses_imp_mat_column_max_for_asset_worst_case():
    impact = SimpleNamespace(
        eai_exp=np.array([10.0, 30.0], dtype=float),
        at_event=np.array([8.0, 30.0], dtype=float),
        frequency=np.array([0.9, 0.1], dtype=float),
        event_id=np.array([11, 22]),
        event_name=np.array(["evt-1", "evt-2"]),
        aai_agg=40.0,
        imp_mat=np.array(
            [
                [8.0, 1.0],
                [2.0, 29.0],
            ],
            dtype=float,
        ),
    )

    class FakeExposure:
        def assign_centroids(self, *args, **kwargs):
            return None

    class FakeImpactCalc:
        last_kwargs = None

        def __init__(self, exposures, impfset, hazard_obj):
            self.exposures = exposures

        def impact(self, **kwargs):
            FakeImpactCalc.last_kwargs = kwargs
            return impact

    result = _compute_component_impact(
        np,
        FakeImpactCalc,
        exposures=FakeExposure(),
        impfset=object(),
        hazard_obj=object(),
        top_n_events=2,
    )

    assert FakeImpactCalc.last_kwargs == {"save_mat": True, "assign_centroids": False}
    assert result.max_loss_by_point.tolist() == [8.0, 29.0]
    assert result.max_event_loss_eur == 30.0