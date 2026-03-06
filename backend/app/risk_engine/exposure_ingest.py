from __future__ import annotations

from pathlib import Path
from typing import Any
import csv
import json
import math

from .errors import DependencyMissingError, InputValidationError
from .types import NormalizedExposure, NormalizedFeature

try:
    import shapely.wkt as shapely_wkt  # type: ignore
    from shapely.geometry import shape as shapely_shape  # type: ignore
    from shapely.geometry import mapping as shapely_mapping  # type: ignore
except Exception:  # pragma: no cover
    shapely_wkt = None
    shapely_shape = None
    shapely_mapping = None


SUPPORTED_UPLOAD_SUFFIXES = {".csv", ".xlsx", ".geojson", ".json", ".gpkg"}
EXPOSURE_CATEGORY_ALIASES = {
    "habitation": "habitation",
    "residential": "habitation",
    "house": "habitation",
    "housing": "habitation",
    "water": "ouvrage_eau",
    "water_network": "ouvrage_eau",
    "water_infra": "ouvrage_eau",
    "ouvrage_eau": "ouvrage_eau",
    "ouvrageeau": "ouvrage_eau",
    "electric": "ouvrage_electrique",
    "electricity": "ouvrage_electrique",
    "power": "ouvrage_electrique",
    "ouvrage_electrique": "ouvrage_electrique",
    "ouvrageelectrique": "ouvrage_electrique",
}
ASSET_TYPE_ALIASES = {
    "habitation": "habitation",
    "house": "habitation",
    "housing": "habitation",
    "eau_aep": "eau_aep_cana",
    "eau_aep_cana": "eau_aep_cana",
    "eau_eu": "eau_eu_cana",
    "eau_eu_cana": "eau_eu_cana",
    "elec_bt_aerien": "elec_bt_aerien",
    "elec_bt_souterrain": "elec_bt_souterrain",
    "elec_hta_aerien": "elec_hta_aerien",
    "elec_hta_souterrain": "elec_hta_souterrain",
    "eau_eu_pr": "eau_eu_pr",
    "eau_eu_step": "eau_eu_step",
    "aep_ouvrage_trait": "eau_aep_ouvrage_trait",
    "eau_aep_ouvrage_trait": "eau_aep_ouvrage_trait",
    "aep_ouvrage_stpmp": "eau_aep_ouvrage_stpmp",
    "eau_aep_ouvrage_stpmp": "eau_aep_ouvrage_stpmp",
    "aep_ouvrage_cap": "eau_aep_ouvrage_cap",
    "eau_aep_ouvrage_cap": "eau_aep_ouvrage_cap",
    "aep_ouvrage_cuv": "eau_aep_ouvrage_cuv",
    "eau_aep_ouvrage_cuv": "eau_aep_ouvrage_cuv",
    "aep_ouvrage_autres": "eau_aep_ouvrage_na",
    "eau_aep_ouvrage_na": "eau_aep_ouvrage_na",
}
VALID_ASSET_TYPES = sorted(set(ASSET_TYPE_ALIASES.values()))
VALID_EXPOSURE_CATEGORIES = sorted(set(EXPOSURE_CATEGORY_ALIASES.values()))


def _to_float(value: Any, field_name: str) -> float:
    try:
        result = float(value)
    except Exception as exc:
        raise InputValidationError(f"Invalid numeric value for {field_name}: {value!r}") from exc
    if not math.isfinite(result):
        raise InputValidationError(f"Non-finite numeric value for {field_name}")
    return result


def _normalize_token(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def _normalize_exposure_category(value: Any, default_category: str = "habitation", *, strict: bool = False) -> str:
    default_raw = _normalize_token(default_category) or "habitation"
    default_norm = EXPOSURE_CATEGORY_ALIASES.get(default_raw, "habitation")
    raw = _normalize_token(value)
    if not raw:
        return default_norm
    normalized = EXPOSURE_CATEGORY_ALIASES.get(raw)
    if normalized:
        return normalized
    if strict:
        raise InputValidationError(
            f"Unknown exposure_category {value!r}. Allowed values: {', '.join(VALID_EXPOSURE_CATEGORIES)}"
        )
    return default_norm


def _normalize_asset_type(value: Any, *, strict: bool = False) -> str:
    raw = _normalize_token(value)
    if not raw:
        if strict:
            raise InputValidationError("Missing asset_type")
        return ""
    normalized = ASSET_TYPE_ALIASES.get(raw)
    if normalized:
        return normalized
    if strict:
        raise InputValidationError(
            f"Unknown asset_type {value!r}. Allowed values: {', '.join(VALID_ASSET_TYPES)}"
        )
    return raw


def _append_row_error(errors: list[dict[str, str]], *, feature_id: str, column: str, detail: str) -> None:
    errors.append(
        {
            "feature_id": str(feature_id or "unknown"),
            "column": str(column or "unknown"),
            "detail": str(detail or "Invalid value"),
        }
    )


def _raise_row_errors(errors: list[dict[str, str]]) -> None:
    if not errors:
        return
    max_items = 16
    chunks = [
        f"asset_id={err['feature_id']} [{err['column']}]: {err['detail']}"
        for err in errors[:max_items]
    ]
    suffix = ""
    if len(errors) > max_items:
        suffix = f" ... +{len(errors) - max_items} other error(s)"
    raise InputValidationError(
        f"Import validation failed ({len(errors)} row error(s)). "
        + "; ".join(chunks)
        + suffix
    )


def _coords_bbox_and_centroid(coords: Any) -> tuple[tuple[float, float, float, float] | None, tuple[float, float] | None]:
    points: list[tuple[float, float]] = []

    def walk(node: Any) -> None:
        if isinstance(node, (list, tuple)) and node:
            if len(node) >= 2 and all(isinstance(v, (int, float)) for v in node[:2]):
                points.append((float(node[0]), float(node[1])))
                return
            for child in node:
                walk(child)

    walk(coords)
    if not points:
        return None, None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    bbox = (min(xs), min(ys), max(xs), max(ys))
    centroid = ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)
    return bbox, centroid


def _feature_from_geojson_feature(
    feature: dict[str, Any],
    idx: int,
    value_field: str,
    id_field: str | None,
    asset_type_field: str | None,
    exposure_category_field: str | None,
    default_exposure_category: str,
) -> NormalizedFeature:
    geom = feature.get("geometry")
    props = feature.get("properties") or {}
    if not isinstance(geom, dict) or not isinstance(props, dict):
        raise InputValidationError(f"Invalid GeoJSON feature at index {idx}")

    gtype = str(geom.get("type") or "Unknown")
    coords = geom.get("coordinates")
    _, centroid = _coords_bbox_and_centroid(coords)
    lon = centroid[0] if centroid else None
    lat = centroid[1] if centroid else None

    if value_field not in props:
        raise InputValidationError(f"Missing value field '{value_field}' in GeoJSON feature {idx}")

    feature_id = str(props.get(id_field) if id_field and id_field in props else props.get("id") or idx + 1)
    label = str(props.get("label") or props.get("name") or f"Feature {idx + 1}")
    value_eur = _to_float(props[value_field], value_field)

    extra: dict[str, Any] = {}
    if asset_type_field and asset_type_field in props:
        extra["asset_type"] = _normalize_asset_type(props[asset_type_field], strict=True)
    if exposure_category_field and exposure_category_field in props:
        category_raw = props[exposure_category_field]
    else:
        category_raw = props.get("exposure_category")
    exposure_category = _normalize_exposure_category(
        category_raw,
        default_exposure_category,
        strict=category_raw not in (None, ""),
    )

    return NormalizedFeature(
        feature_id=feature_id,
        label=label,
        value_eur=value_eur,
        geometry_type=gtype,
        exposure_category=exposure_category,
        lon=lon,
        lat=lat,
        geometry_geojson=geom,
        properties=extra,
    )


def ingest_drawn_geojson(
    drawn_geojson: str,
    *,
    default_value_eur: float = 1_000_000.0,
    default_exposure_category: str = "habitation",
) -> NormalizedExposure:
    try:
        payload = json.loads(drawn_geojson)
    except json.JSONDecodeError as exc:
        raise InputValidationError("drawn_geojson is not valid JSON") from exc

    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise InputValidationError("drawn_geojson must be a GeoJSON FeatureCollection")

    features_raw = payload.get("features")
    if not isinstance(features_raw, list) or not features_raw:
        raise InputValidationError("drawn_geojson contains no features")

    features: list[NormalizedFeature] = []
    warnings: list[str] = [
        "Drawn exposure uses default values when value_eur is not provided in GeoJSON properties."
    ]

    for idx, feat in enumerate(features_raw):
        if not isinstance(feat, dict) or feat.get("type") != "Feature":
            raise InputValidationError(f"Invalid drawn feature at index {idx}")
        geom = feat.get("geometry") or {}
        props = feat.get("properties") or {}
        if not isinstance(props, dict):
            props = {}
        gtype = str(geom.get("type") or "Unknown")
        _, centroid = _coords_bbox_and_centroid(geom.get("coordinates"))
        lon = centroid[0] if centroid else None
        lat = centroid[1] if centroid else None
        value_raw = props.get("value_eur", props.get("value"))
        value_eur = float(default_value_eur) if value_raw in (None, "") else _to_float(value_raw, "value_eur")
        label = str(props.get("label") or props.get("name") or f"Drawn {gtype} {idx + 1}")
        feature_id = str(props.get("asset_id") or idx + 1)
        extra_props: dict[str, Any] = {}
        if props.get("asset_type") is not None:
            extra_props["asset_type"] = props.get("asset_type")
        features.append(
            NormalizedFeature(
                feature_id=feature_id,
                label=label,
                value_eur=value_eur,
                geometry_type=gtype,
                exposure_category=_normalize_exposure_category(
                    props.get("exposure_category"),
                    default_exposure_category,
                ),
                lon=lon,
                lat=lat,
                geometry_geojson=geom if isinstance(geom, dict) else None,
                properties=extra_props,
            )
        )

    return NormalizedExposure(
        source_name="drawn_geojson",
        source_format="geojson",
        input_mode="drawn_geojson",
        features=features,
        warnings=warnings,
    )


def ingest_uploaded_exposure(
    file_path: Path,
    *,
    value_field: str | None,
    id_field: str | None = None,
    asset_type_field: str | None = None,
    exposure_category_field: str | None = None,
    default_exposure_category: str = "habitation",
    crs: str | None = None,
) -> NormalizedExposure:
    suffix = file_path.suffix.lower()
    if suffix not in SUPPORTED_UPLOAD_SUFFIXES:
        raise InputValidationError(f"Unsupported file type: {suffix}")

    if suffix == ".csv":
        return _ingest_csv(
            file_path,
            value_field=value_field,
            id_field=id_field,
            asset_type_field=asset_type_field,
            exposure_category_field=exposure_category_field,
            default_exposure_category=default_exposure_category,
        )
    if suffix in {".geojson", ".json"}:
        return _ingest_geojson(
            file_path,
            value_field=value_field,
            id_field=id_field,
            asset_type_field=asset_type_field,
            exposure_category_field=exposure_category_field,
            default_exposure_category=default_exposure_category,
        )
    if suffix == ".xlsx":
        return _ingest_xlsx(
            file_path,
            value_field=value_field,
            id_field=id_field,
            asset_type_field=asset_type_field,
            exposure_category_field=exposure_category_field,
            default_exposure_category=default_exposure_category,
        )
    if suffix == ".gpkg":
        return _ingest_gpkg(
            file_path,
            value_field=value_field,
            id_field=id_field,
            asset_type_field=asset_type_field,
            exposure_category_field=exposure_category_field,
            default_exposure_category=default_exposure_category,
            crs=crs,
        )

    raise InputValidationError(f"Unsupported file type: {suffix}")


def _ingest_csv(
    file_path: Path,
    *,
    value_field: str | None,
    id_field: str | None,
    asset_type_field: str | None,
    exposure_category_field: str | None,
    default_exposure_category: str,
) -> NormalizedExposure:
    with file_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        headers = reader.fieldnames or []

    if not rows:
        raise InputValidationError("CSV file is empty")

    features: list[NormalizedFeature] = []
    warnings: list[str] = []
    # Build case-insensitive header lookup.
    normalized_headers = {str(h).lower(): str(h) for h in headers if h is not None}
    lat_key = normalized_headers.get("lat") or normalized_headers.get("latitude")
    lon_key = normalized_headers.get("lon") or normalized_headers.get("longitude")
    wkt_key = normalized_headers.get("geometry_wkt") or normalized_headers.get("wkt") or normalized_headers.get("geometry")
    if value_field and value_field not in headers:
        value_field = normalized_headers.get(str(value_field).lower()) or value_field
    if id_field and id_field not in headers:
        id_field = normalized_headers.get(str(id_field).lower()) or id_field
    if asset_type_field and asset_type_field not in headers:
        asset_type_field = normalized_headers.get(str(asset_type_field).lower()) or asset_type_field
    if exposure_category_field and exposure_category_field not in headers:
        exposure_category_field = normalized_headers.get(str(exposure_category_field).lower()) or exposure_category_field

    if not value_field:
        value_field = normalized_headers.get("value_eur") or normalized_headers.get("value")
    if not value_field:
        raise InputValidationError("CSV requires a value field (e.g. value_eur)")
    if not asset_type_field:
        asset_type_field = normalized_headers.get("asset_type")
    if not asset_type_field:
        raise InputValidationError("CSV requires an asset_type column.")
    if not exposure_category_field:
        exposure_category_field = normalized_headers.get("exposure_category") or normalized_headers.get("category")

    row_errors: list[dict[str, str]] = []
    for idx, row in enumerate(rows):
        row = {str(k): v for k, v in row.items()}
        feature_id = str(row.get(id_field) if id_field and id_field in row else row.get("asset_id") or idx + 1)
        label = str(row.get("label") or row.get("name") or f"Row {idx + 1}")
        try:
            value_eur = _to_float(row.get(value_field), value_field)
        except InputValidationError as exc:
            _append_row_error(row_errors, feature_id=feature_id, column=value_field, detail=str(exc))
            continue

        geometry_type = "Unknown"
        lon = None
        lat = None
        geometry_geojson = None

        try:
            if lat_key and lon_key and row.get(lat_key) not in (None, "") and row.get(lon_key) not in (None, ""):
                lat = _to_float(row.get(lat_key), lat_key)
                lon = _to_float(row.get(lon_key), lon_key)
                geometry_type = "Point"
                geometry_geojson = {"type": "Point", "coordinates": [lon, lat]}
            elif wkt_key and row.get(wkt_key):
                if shapely_wkt is None:
                    raise DependencyMissingError("Shapely is required to parse CSV WKT geometry columns")
                geom = shapely_wkt.loads(str(row[wkt_key]))
                geometry_type = geom.geom_type
                lon = getattr(geom.centroid, "x", None)
                lat = getattr(geom.centroid, "y", None)
                geometry_geojson = shapely_mapping(geom) if shapely_mapping is not None else None
            else:
                raise InputValidationError(
                    "CSV row is missing geometry: provide lat/lon columns or geometry_wkt/WKT/Geometry"
                )
        except InputValidationError as exc:
            _append_row_error(row_errors, feature_id=feature_id, column="geometry", detail=str(exc))
            continue

        props: dict[str, Any] = {}
        try:
            props["asset_type"] = _normalize_asset_type(row.get(asset_type_field), strict=True)
        except InputValidationError as exc:
            _append_row_error(row_errors, feature_id=feature_id, column=asset_type_field, detail=str(exc))
            continue
        category_raw = row.get(exposure_category_field) if exposure_category_field else None
        try:
            exposure_category = _normalize_exposure_category(
                category_raw,
                default_exposure_category,
                strict=category_raw not in (None, ""),
            )
        except InputValidationError as exc:
            _append_row_error(
                row_errors,
                feature_id=feature_id,
                column=(exposure_category_field or "exposure_category"),
                detail=str(exc),
            )
            continue

        features.append(
            NormalizedFeature(
                feature_id=feature_id,
                label=label,
                value_eur=value_eur,
                geometry_type=geometry_type,
                exposure_category=exposure_category,
                lon=lon,
                lat=lat,
                geometry_geojson=geometry_geojson,
                properties=props,
            )
        )

    _raise_row_errors(row_errors)

    if wkt_key:
        warnings.append("CSV WKT parsing uses Shapely when available; install geospatial dependencies for full fidelity.")

    return NormalizedExposure(
        source_name=file_path.name,
        source_format="csv",
        input_mode="file",
        features=features,
        warnings=warnings,
    )


def _ingest_geojson(
    file_path: Path,
    *,
    value_field: str | None,
    id_field: str | None,
    asset_type_field: str | None,
    exposure_category_field: str | None,
    default_exposure_category: str,
) -> NormalizedExposure:
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise InputValidationError("GeoJSON must be a FeatureCollection")
    features_raw = payload.get("features")
    if not isinstance(features_raw, list) or not features_raw:
        raise InputValidationError("GeoJSON contains no features")
    if not value_field:
        raise InputValidationError("GeoJSON upload requires value_field")

    features = [
        _feature_from_geojson_feature(
            feat,
            i,
            value_field=value_field,
            id_field=id_field,
            asset_type_field=asset_type_field,
            exposure_category_field=exposure_category_field,
            default_exposure_category=default_exposure_category,
        )
        for i, feat in enumerate(features_raw)
    ]

    return NormalizedExposure(
        source_name=file_path.name,
        source_format="geojson",
        input_mode="file",
        features=features,
        warnings=[],
    )


def _ingest_xlsx(
    file_path: Path,
    *,
    value_field: str | None,
    id_field: str | None,
    asset_type_field: str | None,
    exposure_category_field: str | None,
    default_exposure_category: str,
) -> NormalizedExposure:
    try:
        import pandas as pd  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise DependencyMissingError("pandas/openpyxl are required for XLSX uploads") from exc

    df = pd.read_excel(file_path)
    tmp_csv = file_path.with_suffix(".xlsx.csv.tmp")
    try:
        df.to_csv(tmp_csv, index=False)
        return _ingest_csv(
            tmp_csv,
            value_field=value_field,
            id_field=id_field,
            asset_type_field=asset_type_field,
            exposure_category_field=exposure_category_field,
            default_exposure_category=default_exposure_category,
        )
    finally:
        if tmp_csv.exists():
            tmp_csv.unlink(missing_ok=True)


def _ingest_gpkg(
    file_path: Path,
    *,
    value_field: str | None,
    id_field: str | None,
    asset_type_field: str | None,
    exposure_category_field: str | None,
    default_exposure_category: str,
    crs: str | None,
) -> NormalizedExposure:
    try:
        import geopandas as gpd  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise DependencyMissingError("geopandas is required for GPKG uploads") from exc

    gdf = gpd.read_file(file_path)
    if gdf.empty:
        raise InputValidationError("GPKG contains no features")
    if not value_field or value_field not in gdf.columns:
        raise InputValidationError("GPKG upload requires a valid value_field")
    if not exposure_category_field and "exposure_category" in gdf.columns:
        exposure_category_field = "exposure_category"

    warnings: list[str] = []
    if gdf.crs is None and crs:
        gdf = gdf.set_crs(crs)
        warnings.append(f"CRS missing in GPKG; using user override {crs}.")
    elif gdf.crs is None:
        warnings.append("CRS missing in GPKG; assuming EPSG:4326 for centroid export.")
        gdf = gdf.set_crs("EPSG:4326", allow_override=True)

    gdf_wgs84 = gdf.to_crs("EPSG:4326") if gdf.crs else gdf
    features: list[NormalizedFeature] = []
    for pos, (idx, row) in enumerate(gdf_wgs84.iterrows()):
        geom = row.geometry
        raw_asset_type = row.get(asset_type_field) if asset_type_field and asset_type_field in row else None
        features.append(
            NormalizedFeature(
                feature_id=str(row.get(id_field) if id_field and id_field in row else idx),
                label=str(row.get("label") or row.get("name") or f"Feature {idx}"),
                value_eur=_to_float(row.get(value_field), value_field),
                geometry_type=getattr(geom, "geom_type", "Unknown"),
                exposure_category=_normalize_exposure_category(
                    (row.get(exposure_category_field) if exposure_category_field and exposure_category_field in row else None),
                    default_exposure_category,
                    strict=(exposure_category_field is not None and row.get(exposure_category_field) not in (None, "")),
                ),
                lon=float(geom.centroid.x) if geom is not None else None,
                lat=float(geom.centroid.y) if geom is not None else None,
                geometry_geojson=(json.loads(gdf_wgs84.iloc[[pos]].to_json())["features"][0]["geometry"] if geom is not None else None),
                properties={"asset_type": _normalize_asset_type(raw_asset_type, strict=True)} if raw_asset_type not in (None, "") else {},
            )
        )

    return NormalizedExposure(
        source_name=file_path.name,
        source_format="gpkg",
        input_mode="file",
        features=features,
        warnings=warnings,
    )
