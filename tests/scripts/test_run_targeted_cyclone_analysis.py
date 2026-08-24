from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.config import Settings
from backend.app.risk_engine.types import DisaggregationSummary, NormalizedExposure, NormalizedFeature
from scripts import run_targeted_cyclone_analysis


class _FakeArray:
    def __init__(self, values):
        self.values = values


class _FakeTrack(dict):
    def __init__(self):
        super().__init__(
            {
                "lon": _FakeArray([-62.8, -62.7]),
                "lat": _FakeArray([17.9, 18.0]),
                "max_sustained_wind": _FakeArray([75.0, 80.0]),
            }
        )


class _FakeCyclone:
    def __init__(self):
        self.translated_track = _FakeTrack()
        self.resolved = SimpleNamespace(storm_id="2017242N16333")

    def to_metadata(self):
        return {
            "preset_id": "irma-2017",
            "storm_id": "2017242N16333",
            "name": "IRMA",
            "season": 2017,
            "basin": "NA",
            "transposition": {"lat_shift": 6.9, "lon_shift": -11.8},
        }


def test_targeted_runner_archives_payload_and_manifest(monkeypatch, tmp_path) -> None:
    outputs_dir = tmp_path / "targeted-runs"
    journal_md = tmp_path / "Journalisation_Run_CompleteAnalysis.md"
    journal_jsonl = tmp_path / "Journalisation_Run_CompleteAnalysis.jsonl"

    graph_export_calls = []

    monkeypatch.setattr(run_targeted_cyclone_analysis, "TARGETED_RUN_OUTPUTS_DIR", outputs_dir)
    monkeypatch.setattr(run_targeted_cyclone_analysis, "JOURNAL_MD", journal_md)
    monkeypatch.setattr(run_targeted_cyclone_analysis, "JOURNAL_JSONL", journal_jsonl)
    monkeypatch.setattr(
        run_targeted_cyclone_analysis,
        "_load_presets",
        lambda: {
            "irma-2017": {
                "source": "ibtracs",
                "storm_id": "2017242N16333",
                "name": "IRMA",
                "season": 2017,
                "basin": "NA",
            }
        },
    )
    monkeypatch.setattr(
        run_targeted_cyclone_analysis,
        "build_complete_exposure",
        lambda territory: (
            NormalizedExposure(
                source_name=f"{territory}_reference",
                source_format="geojson",
                input_mode="reference_dataset",
                features=[
                    NormalizedFeature(
                        feature_id="feat-1",
                        label="asset",
                        value_eur=1000.0,
                        geometry_type="Point",
                        lon=-62.8,
                        lat=17.9,
                    )
                ],
            ),
            1,
        ),
    )
    monkeypatch.setattr(
        run_targeted_cyclone_analysis,
        "_build_complete_analysis_settings",
        lambda **_kwargs: Settings(multi_hazard_enabled=False),
    )
    monkeypatch.setattr(
        run_targeted_cyclone_analysis,
        "summarize_disaggregation",
        lambda *args, **kwargs: DisaggregationSummary(
            spacing_m=100.0,
            metric_crs="EPSG:3857",
            asset_count_points=1,
            by_geometry_type={"Point": 1},
        ),
    )
    monkeypatch.setattr(
        run_targeted_cyclone_analysis,
        "prepare_climada_exposure_bundle",
        lambda *args, **kwargs: SimpleNamespace(
            point_records=[{"lat": 17.9, "lon": -62.8, "asset_type": "elec_bt_aerien"}],
            exposures=SimpleNamespace(),
        ),
    )
    monkeypatch.setattr(
        run_targeted_cyclone_analysis,
        "build_transposed_targeted_cyclones",
        lambda *args, **kwargs: [_FakeCyclone()],
    )
    monkeypatch.setattr(
        run_targeted_cyclone_analysis,
        "build_targeted_cyclone_hazard_bundle",
        lambda *args, **kwargs: SimpleNamespace(storm=object(), source="explicit_ibtracs_targeted"),
    )
    monkeypatch.setattr(
        run_targeted_cyclone_analysis,
        "compute_impacts",
        lambda *args, **kwargs: SimpleNamespace(
            portfolio_results={"storm": {"eai_eur": 123.0}},
            modeling={"requested_hazard_keys": ["storm"]},
            notes=[],
            artifacts={},
        ),
    )
    monkeypatch.setattr(
        run_targeted_cyclone_analysis,
        "build_result_payload",
        lambda **kwargs: {
            "meta": {},
            "notes": [],
            "portfolio_results": {"storm": {"eai_eur": 123.0}},
        },
    )
    monkeypatch.setattr(
        run_targeted_cyclone_analysis,
        "_export_targeted_run_outputs",
        lambda **kwargs: graph_export_calls.append(dict(kwargs)),
    )

    exit_code = run_targeted_cyclone_analysis.main(
        ["--cyclones", "irma-2017", "--territory", "stb", "--memory-budget-gb", "2.0"]
    )

    assert exit_code == 0
    manifests = list(outputs_dir.glob("targeted_cyclone_*/manifest.json"))
    assert len(manifests) == 1
    manifest_payload = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest_payload["run_family"] == "targeted-cyclone"
    assert manifest_payload["status"] == "success"

    archived_payloads = list(outputs_dir.glob("targeted_cyclone_*/territories/saint-barthelemy/web/data/saint-barthelemy-complete-analysis.json"))
    assert len(archived_payloads) == 1
    payload = json.loads(archived_payloads[0].read_text(encoding="utf-8"))
    assert payload["meta"]["run_family"] == "targeted-cyclone"
    assert payload["meta"]["report_semantics"] == "event"
    assert payload["meta"]["selected_cyclone_ids"] == ["irma-2017"]
    assert payload["meta"]["targeted_cyclone_track_segments_geojson"].endswith(
        "saint-barthelemy-targeted-cyclone-segments.geojson"
    )

    archived_geojson = archived_payloads[0].with_name("saint-barthelemy-targeted-cyclones.geojson")
    assert archived_geojson.exists()
    archived_segments_geojson = archived_payloads[0].with_name("saint-barthelemy-targeted-cyclone-segments.geojson")
    assert archived_segments_geojson.exists()
    assert len(graph_export_calls) == 1
    assert graph_export_calls[0]["graph_formats"] == "html,png"
