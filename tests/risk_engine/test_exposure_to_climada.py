from __future__ import annotations

from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.risk_engine.errors import InputValidationError
from backend.app.risk_engine.exposure_to_climada import build_climada_exposure
from backend.app.risk_engine.types import NormalizedExposure, NormalizedFeature


def test_build_climada_exposure_preserves_custom_feature_properties_in_point_records() -> None:
    exposure = NormalizedExposure(
        source_name="test",
        source_format="unit",
        input_mode="unit",
        features=[
            NormalizedFeature(
                feature_id="water-1",
                label="Water 1",
                value_eur=100.0,
                geometry_type="Point",
                exposure_category="ouvrage_eau",
                lon=-61.0,
                lat=16.0,
                properties={
                    "asset_type": "eau_aep_cana",
                    "zone_component_key": "AEP_001",
                    "service_feature_id": "AEP_001",
                    "zone_uid": "AEP_001",
                    "custom_meta": "keep-me",
                },
            )
        ],
    )

    bundle = build_climada_exposure(
        exposure,
        spacing_m=100.0,
        max_points_per_feature=1,
    )

    point_record = bundle.point_records[0]
    assert point_record["feature_id"] == "water-1"
    assert point_record["asset_type"] == "eau_aep_cana"
    assert point_record["zone_component_key"] == "AEP_001"
    assert point_record["service_feature_id"] == "AEP_001"
    assert point_record["zone_uid"] == "AEP_001"
    assert point_record["custom_meta"] == "keep-me"


def test_build_climada_exposure_rejects_non_point_feature_without_geometry_geojson() -> None:
    exposure = NormalizedExposure(
        source_name="test",
        source_format="unit",
        input_mode="unit",
        features=[
            NormalizedFeature(
                feature_id="line-1",
                label="Line 1",
                value_eur=100.0,
                geometry_type="LineString",
                exposure_category="ouvrage_electrique",
                lon=-61.0,
                lat=16.0,
                geometry_geojson=None,
                properties={"asset_type": "elec_distribution"},
            )
        ],
    )

    with pytest.raises(InputValidationError, match="missing geometry_geojson"):
        build_climada_exposure(
            exposure,
            spacing_m=100.0,
            max_points_per_feature=10,
        )


def test_build_climada_exposure_sampling_changes_with_spacing_and_cap() -> None:
    exposure = NormalizedExposure(
        source_name="test",
        source_format="unit",
        input_mode="unit",
        features=[
            NormalizedFeature(
                feature_id="line-1",
                label="Line 1",
                value_eur=100.0,
                geometry_type="LineString",
                exposure_category="ouvrage_electrique",
                lon=-61.0,
                lat=16.0,
                geometry_geojson={
                    "type": "LineString",
                    "coordinates": [
                        [-61.0, 16.0],
                        [-61.0, 16.02],
                    ],
                },
                properties={"asset_type": "elec_distribution"},
            )
        ],
    )

    dense = build_climada_exposure(exposure, spacing_m=50.0, max_points_per_feature=1000)
    sparse = build_climada_exposure(exposure, spacing_m=500.0, max_points_per_feature=1000)
    capped = build_climada_exposure(exposure, spacing_m=50.0, max_points_per_feature=2)

    assert len(dense.point_records) > len(sparse.point_records) >= 2
    assert len(capped.point_records) == 2
