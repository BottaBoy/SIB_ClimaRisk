from __future__ import annotations

from pathlib import Path
import sys

from pyproj import Transformer

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.risk_engine.exposure_disaggregation import summarize_disaggregation
from backend.app.risk_engine.exposure_to_climada import _require_geo_dependencies, _sample_feature_points
from backend.app.risk_engine.types import NormalizedExposure, NormalizedFeature


def test_summarize_disaggregation_matches_sampling_point_count() -> None:
    exposure = NormalizedExposure(
        source_name="test",
        source_format="geojson",
        input_mode="upload",
        features=[
            NormalizedFeature(
                feature_id="line-1",
                label="Line 1",
                value_eur=1000.0,
                geometry_type="LineString",
                exposure_category="ouvrage_eau",
                geometry_geojson={
                    "type": "LineString",
                    "coordinates": [
                        [-62.85, 17.90],
                        [-62.849, 17.901],
                        [-62.848, 17.902],
                    ],
                },
            ),
            NormalizedFeature(
                feature_id="multi-1",
                label="Multi 1",
                value_eur=2000.0,
                geometry_type="MultiLineString",
                exposure_category="ouvrage_electrique",
                geometry_geojson={
                    "type": "MultiLineString",
                    "coordinates": [
                        [[-62.851, 17.901], [-62.8503, 17.9016], [-62.8498, 17.902]],
                        [[-62.8495, 17.9022], [-62.8489, 17.9027]],
                    ],
                },
            ),
            NormalizedFeature(
                feature_id="poly-1",
                label="Poly 1",
                value_eur=3000.0,
                geometry_type="Polygon",
                exposure_category="ouvrage_eau",
                geometry_geojson={
                    "type": "Polygon",
                    "coordinates": [[
                        [-62.8520, 17.8995],
                        [-62.8510, 17.8995],
                        [-62.8510, 17.9005],
                        [-62.8520, 17.9005],
                        [-62.8520, 17.8995],
                    ]],
                },
            ),
        ],
    )

    spacing_m = 100.0
    metric_crs = "EPSG:3857"
    max_points = 300

    disagg = summarize_disaggregation(
        exposure,
        spacing_m=spacing_m,
        metric_crs=metric_crs,
        max_points_per_feature=max_points,
    )

    deps = _require_geo_dependencies()
    transformer_to_metric = Transformer.from_crs("EPSG:4326", metric_crs, always_xy=True)
    transformer_to_wgs84 = Transformer.from_crs(metric_crs, "EPSG:4326", always_xy=True)
    actual_total = sum(
        len(
            _sample_feature_points(
                feature,
                spacing_m=spacing_m,
                max_points=max_points,
                to_metric=transformer_to_metric,
                to_wgs84=transformer_to_wgs84,
                deps=deps,
            )
        )
        for feature in exposure.features
    )

    assert disagg.asset_count_points == actual_total
