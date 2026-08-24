from __future__ import annotations

from collections import Counter
import math
from typing import Any

from .exposure_to_climada import DEFAULT_MAX_POINTS_PER_FEATURE, count_sampled_feature_points
from .types import DisaggregationSummary, NormalizedExposure

try:
    from shapely.geometry import shape as shapely_shape  # type: ignore
    from shapely.ops import transform as shapely_transform  # type: ignore
except Exception:  # pragma: no cover
    shapely_shape = None
    shapely_transform = None

try:
    from pyproj import Transformer  # type: ignore
except Exception:  # pragma: no cover
    Transformer = None  # type: ignore


DEFAULT_METRIC_CRS = "EPSG:3857"


def _projected_measurements(geometry_geojson: dict[str, Any], metric_crs: str) -> tuple[float, float] | None:
    if shapely_shape is None or shapely_transform is None or Transformer is None:
        return None
    try:
        geom = shapely_shape(geometry_geojson)
        transformer = Transformer.from_crs("EPSG:4326", metric_crs, always_xy=True)
        geom_metric = shapely_transform(transformer.transform, geom)
        return float(getattr(geom_metric, "length", 0.0) or 0.0), float(getattr(geom_metric, "area", 0.0) or 0.0)
    except Exception:
        return None


def _estimate_points_for_feature(feature: Any, spacing_m: float, metric_crs: str) -> int:
    gtype = (feature.geometry_type or "Unknown").lower()
    if gtype.endswith("point"):
        return 1

    length_area = None
    if feature.geometry_geojson:
        length_area = _projected_measurements(feature.geometry_geojson, metric_crs)

    if gtype.endswith("linestring") or "line" in gtype:
        if length_area:
            length_m, _ = length_area
            return max(1, int(math.ceil(max(0.0, length_m) / max(1.0, spacing_m))))
        return 3

    if gtype.endswith("polygon") or "polygon" in gtype:
        if length_area:
            _, area_m2 = length_area
            if area_m2 <= 0:
                return 1
            return max(1, int(min(10_000, math.ceil(area_m2 / max(1.0, spacing_m) ** 2))))
        return 4

    return 1


def summarize_disaggregation(
    exposure: NormalizedExposure,
    *,
    spacing_m: float,
    metric_crs: str = DEFAULT_METRIC_CRS,
    max_points_per_feature: int = DEFAULT_MAX_POINTS_PER_FEATURE,
) -> DisaggregationSummary:
    by_geom = Counter()
    total_points = 0
    warnings = list(exposure.warnings)
    exact_count_warning_added = False

    if metric_crs != DEFAULT_METRIC_CRS:
        warnings.append(f"Using custom metric CRS {metric_crs} for spacing-based sampling.")

    for feat in exposure.features:
        by_geom[feat.geometry_type] += 1
        try:
            total_points += count_sampled_feature_points(
                feat,
                spacing_m=spacing_m,
                metric_crs=metric_crs,
                max_points=max(1, int(max_points_per_feature)),
            )
        except Exception:
            total_points += _estimate_points_for_feature(feat, spacing_m, metric_crs)
            if not exact_count_warning_added:
                warnings.append(
                    "Fell back to approximate disaggregation counting for one or more features; "
                    "exact CLIMADA-aligned counting dependencies were unavailable."
                )
                exact_count_warning_added = True

    warnings.append(
        "Production CLIMADA path should sample geometries in a metric CRS before reprojecting points back to EPSG:4326."
    )

    return DisaggregationSummary(
        spacing_m=float(spacing_m),
        metric_crs=metric_crs,
        asset_count_points=int(total_points),
        by_geometry_type=dict(by_geom),
        warnings=warnings,
    )
