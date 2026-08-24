from __future__ import annotations

from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from scripts import build_case_study_multi_hazard_proxy


class _FakeProcess:
    def __init__(self, *, exitcode: int) -> None:
        self.exitcode = exitcode

    def start(self) -> None:
        return None

    def join(self) -> None:
        return None


class _FakeContext:
    def __init__(self, *, exitcode: int) -> None:
        self._exitcode = exitcode

    def Process(self, target, args):  # noqa: N802 - mirror multiprocessing API
        return _FakeProcess(exitcode=self._exitcode)


def test_run_proxy_climada_raises_clear_error_on_empty_failed_worker(monkeypatch, tmp_path: Path) -> None:
    empty_file = tmp_path / "proxy-storm.json"
    empty_file.write_text("", encoding="utf-8")

    class _FakeTempFile:
        name = str(empty_file)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        build_case_study_multi_hazard_proxy.multiprocessing,
        "get_context",
        lambda method: _FakeContext(exitcode=9),
    )
    monkeypatch.setattr(
        build_case_study_multi_hazard_proxy.tempfile,
        "NamedTemporaryFile",
        lambda **kwargs: _FakeTempFile(),
    )

    with pytest.raises(RuntimeError, match=r"child process exited with code 9"):
        build_case_study_multi_hazard_proxy._run_proxy_climada(object(), {})


def test_run_proxy_climada_rejects_empty_success_payload(monkeypatch, tmp_path: Path) -> None:
    empty_file = tmp_path / "proxy-storm.json"
    empty_file.write_text("", encoding="utf-8")

    class _FakeTempFile:
        name = str(empty_file)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        build_case_study_multi_hazard_proxy.multiprocessing,
        "get_context",
        lambda method: _FakeContext(exitcode=0),
    )
    monkeypatch.setattr(
        build_case_study_multi_hazard_proxy.tempfile,
        "NamedTemporaryFile",
        lambda **kwargs: _FakeTempFile(),
    )

    with pytest.raises(RuntimeError, match=r"produced no payload"):
        build_case_study_multi_hazard_proxy._run_proxy_climada(object(), {})
