from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable

from .errors import DependencyMissingError, InputValidationError
from .types import NormalizedExposure, NormalizedFeature


TERRITORY_GRID_DEG = 0.2
DEFAULT_METRIC_CRS = "EPSG:3857"
DEFAULT_MAX_POINTS_PER_FEATURE = 300


@dataclass
class ClimadaExposureBundle:
    exposures: Any
    point_records: list[dict[str, Any]]
    metric_crs: str
    warnings: list[str]


def _infer_infra_class(feature: Any) -> str:
    category = str(getattr(feature, "exposure_category", "habitation") or "habitation").strip().lower()
    props = getattr(feature, "properties", {}) or {}
    asset_type = str(props.get("asset_type") or "").strip().lower()
    gtype = str(getattr(feature, "geometry_type", "")).lower()

    if category == "ouvrage_electrique":
        if "souterrain" in asset_type or "underground" in asset_type:
            return "elec_souterrain"
        return "elec_aerien"

    if category == "ouvrage_eau":
        if (
            "step" in asset_type
            or "station" in asset_type
            or "stpmp" in asset_type
            or asset_type.startswith("pr")
            or "ouvrage" in asset_type
            or "point" in gtype
        ):
            return "eau_ouvrage"
        return "eau_reseau"

    return "habitation"


def _territory_for_coords(lat: float | None, lon: float | None) -> tuple[str, str]:
    if lat is None or lon is None:
        return "uploaded-aggregate", "Uploaded Exposure (aggregate)"
    lat_bin = round(float(lat) / TERRITORY_GRID_DEG) * TERRITORY_GRID_DEG
    lon_bin = round(float(lon) / TERRITORY_GRID_DEG) * TERRITORY_GRID_DEG
    return f"cell-{lat_bin:+05.2f}_{lon_bin:+06.2f}", f"Zone ({lat_bin:.2f}, {lon_bin:.2f})"


def _require_geo_dependencies() -> dict[str, Any]:
    try:
        import geopandas as gpd  # type: ignore
        from pyproj import Transformer  # type: ignore
        from shapely.geometry import LineString, MultiLineString, MultiPoint, MultiPolygon, Point, Polygon, shape  # type: ignore
        from shapely.ops import transform as shapely_transform  # type: ignore
    except Exception as exc:  # pragma: no cover - runtime dependency
        raise DependencyMissingError("geopandas/shapely/pyproj are required for CLIMADA exposure conversion") from exc

    return {
        "gpd": gpd,
        "Transformer": Transformer,
        "LineString": LineString,
        "MultiLineString": MultiLineString,
        "MultiPoint": MultiPoint,
        "MultiPolygon": MultiPolygon,
        "Point": Point,
        "Polygon": Polygon,
        "shape": shape,
        "shapely_transform": shapely_transform,
    }


def _sample_line_points(geom_metric: Any, spacing_m: float, max_points: int) -> list[Any]:
    length = float(getattr(geom_metric, "length", 0.0) or 0.0)
    if length <= 0:
        return [geom_metric.interpolate(0.0, normalized=True)]
    n_points = int(math.ceil(length / max(1.0, spacing_m))) + 1
    n_points = max(2, min(max_points, n_points))
    out: list[Any] = []
    for i in range(n_points):
        dist = length * (i / float(n_points - 1))
        out.append(geom_metric.interpolate(dist))
    return out


def _sample_multiline_points(geom_metric: Any, spacing_m: float, max_points: int) -> list[Any]:
    lines = [line for line in getattr(geom_metric, "geoms", []) if float(getattr(line, "length", 0.0) or 0.0) > 0.0]
    if not lines:
        return []
    total_len = sum(float(line.length) for line in lines)
    if total_len <= 0:
        return [lines[0].interpolate(0.0, normalized=True)]

    target = max(2, min(max_points, int(math.ceil(total_len / max(1.0, spacing_m))) + len(lines)))
    allocations: list[int] = []
    remaining = target
    for idx, line in enumerate(lines):
        if idx == len(lines) - 1:
            alloc = max(1, remaining)
        else:
            share = float(line.length) / total_len
            alloc = max(1, int(round(target * share)))
            alloc = min(alloc, max(1, remaining - (len(lines) - idx - 1)))
        allocations.append(alloc)
        remaining -= alloc

    out: list[Any] = []
    for line, n in zip(lines, allocations):
        out.extend(_sample_line_points(line, spacing_m, max(2, n)))
    return out[:max_points]


def _sample_polygon_points(geom_metric: Any, spacing_m: float, max_points: int, point_factory: Any) -> list[Any]:
    area = float(getattr(geom_metric, "area", 0.0) or 0.0)
    if area <= 0:
        return [geom_metric.representative_point()]

    target = max(1, min(max_points, int(math.ceil(area / (max(1.0, spacing_m) ** 2)))))
    cell = max(1.0, math.sqrt(area / max(1, target)))
    minx, miny, maxx, maxy = geom_metric.bounds
    points: list[Any] = []

    x = minx + 0.5 * cell
    while x <= maxx and len(points) < max_points:
        y = miny + 0.5 * cell
        while y <= maxy and len(points) < max_points:
            pt = point_factory(x, y)
            if geom_metric.contains(pt) or geom_metric.touches(pt):
                points.append(pt)
            y += cell
        x += cell

    if not points:
        return [geom_metric.representative_point()]
    return points


def _sample_multipolygon_points(geom_metric: Any, spacing_m: float, max_points: int, point_factory: Any) -> list[Any]:
    polys = [poly for poly in getattr(geom_metric, "geoms", []) if float(getattr(poly, "area", 0.0) or 0.0) > 0.0]
    if not polys:
        return []
    total_area = sum(float(poly.area) for poly in polys)
    if total_area <= 0:
        return [polys[0].representative_point()]

    out: list[Any] = []
    remaining = max_points
    for idx, poly in enumerate(polys):
        if idx == len(polys) - 1:
            alloc = max(1, remaining)
        else:
            share = float(poly.area) / total_area
            alloc = max(1, int(round(max_points * share)))
            alloc = min(alloc, max(1, remaining - (len(polys) - idx - 1)))
        remaining -= alloc
        out.extend(_sample_polygon_points(poly, spacing_m, alloc, point_factory))
    return out[:max_points]


def _feature_geometry(feature: NormalizedFeature, deps: dict[str, Any]) -> Any | None:
    if feature.geometry_geojson and isinstance(feature.geometry_geojson, dict):
        try:
            return deps["shape"](feature.geometry_geojson)
        except Exception:
            return None
    if feature.lon is not None and feature.lat is not None:
        return deps["Point"](float(feature.lon), float(feature.lat))
    return None


def _sample_feature_points(
    feature: NormalizedFeature,
    *,
    spacing_m: float,
    max_points: int,
    to_metric: Any,
    to_wgs84: Any,
    deps: dict[str, Any],
) -> list[tuple[float, float]]:
    shapely_transform = deps["shapely_transform"]
    Point = deps["Point"]
    LineString = deps["LineString"]
    MultiLineString = deps["MultiLineString"]
    Polygon = deps["Polygon"]
    MultiPolygon = deps["MultiPolygon"]
    MultiPoint = deps["MultiPoint"]

    geom_wgs84 = _feature_geometry(feature, deps)
    if geom_wgs84 is None or getattr(geom_wgs84, "is_empty", False):
        return []

    geom_metric = shapely_transform(to_metric.transform, geom_wgs84)
    sampled_metric: list[Any] = []

    if isinstance(geom_metric, Point):
        sampled_metric = [geom_metric]
    elif isinstance(geom_metric, MultiPoint):
        sampled_metric = list(getattr(geom_metric, "geoms", []))[:max_points] or [geom_metric.representative_point()]
    elif isinstance(geom_metric, LineString):
        sampled_metric = _sample_line_points(geom_metric, spacing_m, max_points)
    elif isinstance(geom_metric, MultiLineString):
        sampled_metric = _sample_multiline_points(geom_metric, spacing_m, max_points)
    elif isinstance(geom_metric, Polygon):
        sampled_metric = _sample_polygon_points(geom_metric, spacing_m, max_points, Point)
    elif isinstance(geom_metric, MultiPolygon):
        sampled_metric = _sample_multipolygon_points(geom_metric, spacing_m, max_points, Point)
    else:
        sampled_metric = [geom_metric.representative_point()]

    out: list[tuple[float, float]] = []
    for pt_metric in sampled_metric:
        pt_wgs = shapely_transform(to_wgs84.transform, pt_metric)
        lon = float(getattr(pt_wgs, "x", 0.0))
        lat = float(getattr(pt_wgs, "y", 0.0))
        if not math.isfinite(lon) or not math.isfinite(lat):
            continue
        out.append((lon, lat))
    return out


def build_climada_exposure(
    exposure: NormalizedExposure,
    *,
    spacing_m: float,
    metric_crs: str = DEFAULT_METRIC_CRS,
    max_points_per_feature: int = DEFAULT_MAX_POINTS_PER_FEATURE,
    impact_func_id: int = 2,
    impact_func_id_resolver: Callable[[str | None], int] | None = None,
) -> ClimadaExposureBundle:
    deps = _require_geo_dependencies()
    gpd = deps["gpd"]
    Transformer = deps["Transformer"]
    Point = deps["Point"]

    try:
        from climada.entity import Exposures  # type: ignore
    except Exception as exc:  # pragma: no cover - runtime dependency
        raise DependencyMissingError("CLIMADA Exposures class is required") from exc

    to_metric = Transformer.from_crs("EPSG:4326", metric_crs, always_xy=True)
    to_wgs84 = Transformer.from_crs(metric_crs, "EPSG:4326", always_xy=True)

    rows: list[dict[str, Any]] = []
    geometries: list[Any] = []
    point_records: list[dict[str, Any]] = []
    warnings: list[str] = []

    for feat in exposure.features:
        sampled = _sample_feature_points(
            feat,
            spacing_m=spacing_m,
            max_points=max(1, int(max_points_per_feature)),
            to_metric=to_metric,
            to_wgs84=to_wgs84,
            deps=deps,
        )
        if not sampled:
            warnings.append(f"Feature {feat.feature_id} could not be sampled and was skipped.")
            continue

        split_value = max(0.0, float(feat.value_eur)) / float(len(sampled))
        infra_class = _infer_infra_class(feat)
        asset_type = str((feat.properties or {}).get("asset_type") or "")
        point_impact_func_id = int(impact_func_id)
        if impact_func_id_resolver is not None:
            try:
                point_impact_func_id = int(impact_func_id_resolver(asset_type))
            except Exception:
                point_impact_func_id = int(impact_func_id)
        for idx, (lon, lat) in enumerate(sampled, start=1):
            territory_id, territory_label = _territory_for_coords(lat, lon)
            point_id = f"{feat.feature_id}::p{idx}"
            row = {
                "value": float(split_value),
                "impf_TC": int(point_impact_func_id),
                "point_id": point_id,
                "feature_id": str(feat.feature_id),
                "label": str(feat.label),
                "infra_class": infra_class,
                "asset_type": asset_type,
                "exposure_category": str(feat.exposure_category or "habitation"),
                "territory_id": territory_id,
                "territory_label": territory_label,
                "lon": float(lon),
                "lat": float(lat),
            }
            rows.append(row)
            geometries.append(Point(float(lon), float(lat)))
            point_records.append(
                {
                    "point_id": point_id,
                    "feature_id": str(feat.feature_id),
                    "label": str(feat.label),
                    "geometry_type": str(feat.geometry_type or "Unknown"),
                    "value_eur": float(split_value),
                    "infra_class": infra_class,
                    "asset_type": asset_type,
                    "impf_tc": int(point_impact_func_id),
                    "exposure_category": str(feat.exposure_category or "habitation"),
                    "territory_id": territory_id,
                    "territory_label": territory_label,
                    "lon": float(lon),
                    "lat": float(lat),
                }
            )

    if not rows:
        raise InputValidationError("No valid exposure points were generated for CLIMADA computation.")

    gdf = gpd.GeoDataFrame(rows, geometry=geometries, crs="EPSG:4326")
    exposures = Exposures(gdf)
    exposures.check()

    return ClimadaExposureBundle(
        exposures=exposures,
        point_records=point_records,
        metric_crs=metric_crs,
        warnings=warnings,
    )


def subset_climada_exposure_bundle(
    exposure_bundle: ClimadaExposureBundle,
    *,
    point_indices: list[int],
) -> ClimadaExposureBundle:
    """Return an exact subset of a CLIMADA exposure bundle for point-level sharding."""
    if not point_indices:
        raise InputValidationError("CLIMADA exposure shard requires at least one point index.")

    exposures = getattr(exposure_bundle, "exposures", None)
    gdf = getattr(exposures, "gdf", None)
    if exposures is None or gdf is None:
        raise DependencyMissingError("CLIMADA exposure object is required for sharded impact computation.")

    point_records = list(exposure_bundle.point_records or [])
    valid_indices = [int(idx) for idx in point_indices if 0 <= int(idx) < len(point_records)]
    if not valid_indices:
        raise InputValidationError("No valid CLIMADA point indices were provided for the shard.")

    subset_gdf = gdf.iloc[valid_indices].copy()
    subset_point_records = [point_records[idx] for idx in valid_indices]

    exposures_cls = type(exposures)
    subset_exposures = exposures_cls(subset_gdf)
    subset_exposures.check()

    return ClimadaExposureBundle(
        exposures=subset_exposures,
        point_records=subset_point_records,
        metric_crs=str(exposure_bundle.metric_crs),
        warnings=list(exposure_bundle.warnings or []),
    )
