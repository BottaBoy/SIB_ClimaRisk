from __future__ import annotations

import signal
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from backend.app.risk_engine.types import DisaggregationSummary
from scripts import run_complete_analysis


class _DummyRunLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def log_event(self, event_name: str, **payload) -> None:
        self.events.append((event_name, dict(payload)))


class _DummyRunManifest:
    def __init__(self) -> None:
        self.data = {"status": "running"}
        self.status_calls: list[tuple[str, dict]] = []

    def set_status(self, status: str, **payload) -> None:
        self.status_calls.append((status, dict(payload)))
        self.data["status"] = status


def test_run_termination_guard_ignores_sighup_by_default(monkeypatch) -> None:
    signal_calls: list[tuple[int, object]] = []

    monkeypatch.setattr(run_complete_analysis.atexit, "register", lambda _callback: None)
    monkeypatch.setattr(run_complete_analysis.signal, "getsignal", lambda _signum: signal.SIG_DFL)
    monkeypatch.setattr(
        run_complete_analysis.signal,
        "signal",
        lambda signum, handler: signal_calls.append((signum, handler)),
    )

    dummy_logger = _DummyRunLogger()
    dummy_manifest = _DummyRunManifest()
    guard = run_complete_analysis.RunTerminationGuard(dummy_logger, dummy_manifest)

    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(run_complete_analysis.os, "kill", lambda pid, signum: killed.append((pid, signum)))

    guard._on_signal(signal.SIGHUP, None)

    assert killed == []
    assert dummy_logger.events == []
    assert dummy_manifest.status_calls == []
    assert [signum for signum, _handler in signal_calls] == [signal.SIGINT, signal.SIGTERM]


def test_run_termination_guard_still_aborts_on_sigint(monkeypatch) -> None:
    signal_calls: list[tuple[int, object]] = []

    monkeypatch.setattr(run_complete_analysis.atexit, "register", lambda _callback: None)
    monkeypatch.setattr(run_complete_analysis.signal, "getsignal", lambda _signum: signal.SIG_DFL)
    monkeypatch.setattr(
        run_complete_analysis.signal,
        "signal",
        lambda signum, handler: signal_calls.append((signum, handler)),
    )

    dummy_logger = _DummyRunLogger()
    dummy_manifest = _DummyRunManifest()
    guard = run_complete_analysis.RunTerminationGuard(dummy_logger, dummy_manifest)

    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(run_complete_analysis.os, "kill", lambda pid, signum: killed.append((pid, signum)))

    guard._on_signal(signal.SIGINT, None)

    assert killed == [(run_complete_analysis.os.getpid(), signal.SIGINT)]
    assert dummy_logger.events[0][0] == "aborted"
    assert dummy_logger.events[0][1]["reason"] == "signal_interrupt"
    assert dummy_manifest.status_calls[0][0] == "aborted"
    assert [signum for signum, _handler in signal_calls] == [signal.SIGINT, signal.SIGTERM, signal.SIGINT]


def test_reconcile_disaggregation_with_climada_bundle_uses_exact_point_count() -> None:
    disagg = DisaggregationSummary(
        spacing_m=100.0,
        metric_crs="EPSG:3857",
        asset_count_points=180148,
        by_geometry_type={"LineString": 12},
        warnings=["initial"],
    )

    reconciled = run_complete_analysis._reconcile_disaggregation_with_climada_bundle(
        territory_key="guadeloupe",
        disagg=disagg,
        point_count_exact=290545,
    )

    assert reconciled.asset_count_points == 290545
    assert reconciled.warnings[:-1] == ["initial"]
    assert "reconciled to the exact CLIMADA exposure bundle point count" in reconciled.warnings[-1]


def test_reconcile_disaggregation_with_climada_bundle_noops_when_counts_match() -> None:
    disagg = DisaggregationSummary(
        spacing_m=100.0,
        metric_crs="EPSG:3857",
        asset_count_points=290545,
        by_geometry_type={"LineString": 12},
        warnings=["initial"],
    )

    reconciled = run_complete_analysis._reconcile_disaggregation_with_climada_bundle(
        territory_key="guadeloupe",
        disagg=disagg,
        point_count_exact=290545,
    )

    assert reconciled is disagg
