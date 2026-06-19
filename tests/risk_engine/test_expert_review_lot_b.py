from __future__ import annotations

from backend.app.risk_engine.analysis_export import build_result_payload
from backend.app.risk_engine.expert_review_baseline import infer_default_valuation_asset_count
from backend.app.risk_engine.types import DisaggregationSummary, ImpactComputationResult, NormalizedExposure, NormalizedFeature


def test_build_result_payload_includes_valuation_audit_and_feature_metadata():
    exposure = NormalizedExposure(
        source_name="drawn.geojson",
        source_format="geojson",
        input_mode="drawn_geojson",
        features=[
            NormalizedFeature(
                feature_id="asset-1",
                label="Asset 1",
                value_eur=1_000_000.0,
                geometry_type="Point",
                lon=-61.5,
                lat=16.2,
                properties={
                    "asset_type": "habitation",
                    "uses_default_value": True,
                    "valuation_source": "drawn_geojson:default_1000000_eur",
                    "default_value_eur": 1_000_000.0,
                },
            ),
            NormalizedFeature(
                feature_id="asset-2",
                label="Asset 2",
                value_eur=250_000.0,
                geometry_type="Point",
                lon=-61.4,
                lat=16.3,
                properties={
                    "asset_type": "habitation",
                    "uses_default_value": False,
                    "valuation_source": "input:value_eur",
                },
            ),
        ],
    )
    disagg = DisaggregationSummary(
        spacing_m=100.0,
        metric_crs="EPSG:5490",
        asset_count_points=2,
        by_geometry_type={"Point": 2},
    )
    comp = ImpactComputationResult(
        engine="test",
        territory_results=[],
        asset_results=[
            {
                "asset_id": "asset-1",
                "asset_label": "Asset 1",
                "geometry_type": "Point",
                "asset_type": "habitation",
                "uses_default_value": True,
                "valuation_source": "drawn_geojson:default_1000000_eur",
                "default_value_eur": 1_000_000.0,
                "exposure_eur": 1_000_000.0,
                "eai_storm_direct_eur": 0.0,
                "eai_storm_indirect_eur": 0.0,
                "eai_storm_eur": 0.0,
                "eai_cmcc_direct_eur": 0.0,
                "eai_cmcc_indirect_eur": 0.0,
                "eai_cmcc_eur": 0.0,
                "risk_index_storm": 0.0,
                "risk_index_cmcc": 0.0,
            }
        ],
        portfolio_results={},
        graphs={},
        notes=[],
        modeling={
            "state_aggregation_metadata": {
                "schema_version": "aggregated_service_state_v1",
                "aggregation_method": "aggregated_service_state",
                "electric_state_unit": "fixed_grid_0p1deg",
                "water_state_unit": "zone_component_key",
            }
        },
    )

    payload = build_result_payload(
        job_id="job-1",
        source="test",
        run_label="Lot B",
        exposure=exposure,
        disagg=disagg,
        comp=comp,
    )

    assert payload["exposure_summary"]["default_value_asset_count"] == 1
    assert payload["exposure_summary"]["explicit_value_asset_count"] == 1
    assert payload["valuation_audit"]["tracked_asset_count"] == 2
    assert payload["valuation_audit"]["default_value_asset_preview"][0]["asset_id"] == "asset-1"
    assert payload["input_features_geojson"]["features"][0]["properties"]["uses_default_value"] is True
    assert payload["input_features_geojson"]["features"][0]["properties"]["valuation_source"] == "drawn_geojson:default_1000000_eur"
    assert payload["meta"]["network_state_methodology"]["aggregation_method"] == "aggregated_service_state"
    assert payload["meta"]["network_state_methodology_breaks_comparability"] is True
    assert payload["meta"]["network_state_payload_contract"]["native_service_states_key"] == "native_service_states"


def test_infer_default_valuation_asset_count_reads_explicit_asset_flags():
    payload = {
        "asset_results": [
            {"asset_id": "asset-1", "uses_default_value": True},
            {"asset_id": "asset-2", "uses_default_value": False},
            {"asset_id": "asset-3", "uses_default_value": True},
        ]
    }

    assert infer_default_valuation_asset_count(payload) == 2
