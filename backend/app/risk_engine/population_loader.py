"""
Population data loading and aggregation module.

Loads WorldPop raster data and aggregates population by territory (0.2° grid cells).
Supports Guadeloupe, Martinique, and Saint-Barthélemy territories.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Optional, Tuple
import warnings

try:
    import rasterio
    from rasterio.windows import from_bounds
except ImportError:
    rasterio = None  # type: ignore[assignment]

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)

# Territory configuration: ISO code -> (population_raster_path, bounds)
TERRITORY_CONFIG = {
    "GUA": {
        "name": "Guadeloupe",
        "iso_code": "GLP",
        "raster_filename": "glp_pop_2020_CN_100m_R2025A_v1.tif",
        "bounds": (-61.82, 15.87, -60.93, 16.45),  # (minlon, minlat, maxlon, maxlat)
    },
    "MTQ": {
        "name": "Martinique",
        "iso_code": "MTQ",
        "raster_filename": "mtq_pop_2020_CN_100m_R2025A_v1.tif",
        "bounds": (-61.24, 14.39, -60.81, 14.88),
    },
    "BLM": {
        "name": "Saint-Barthélemy",
        "iso_code": "BLM",
        "raster_filename": "blm_pop_2020_CN_100m_R2025A_v1.tif",
        "bounds": (-62.95, 17.86, -62.78, 17.98),
    },
}

TERRITORY_GRID_DEG = 0.2  # Grid cell size in degrees


def _aligned_grid_centers(min_coord: float, max_coord: float, step: float = TERRITORY_GRID_DEG) -> list[float]:
    start = math.floor(min_coord / step) * step
    stop = math.ceil(max_coord / step) * step
    centers: list[float] = []
    current = start
    while current <= stop + 1e-9:
        centers.append(round(current, 2))
        current += step
    return centers


def _territory_for_coords(lat: float, lon: float) -> Optional[str]:
    """
    Determine which territory a coordinate belongs to.

    Args:
        lat: Latitude
        lon: Longitude

    Returns:
        Territory ID ("GUA", "MTQ", "BLM") or None if not in supported territory
    """
    for territory_id, config in TERRITORY_CONFIG.items():
        minlon, minlat, maxlon, maxlat = config["bounds"]
        if minlon <= lon <= maxlon and minlat <= lat <= maxlat:
            return territory_id
    return None


def load_population_raster(
    raster_path: str | Path,
) -> Tuple[Optional[np.ndarray], Optional[dict]]:
    """
    Load a WorldPop raster file.

    Args:
        raster_path: Path to the GeoTIFF file

    Returns:
        Tuple of (raster_array, metadata_dict) or (None, None) if load fails
    """
    if rasterio is None or np is None:
        logger.warning("rasterio or numpy not available; population data unavailable")
        return None, None

    raster_path = Path(raster_path)
    if not raster_path.exists():
        logger.warning(f"Population raster not found: {raster_path}")
        return None, None

    try:
        with rasterio.open(raster_path) as src:
            data = src.read(1)  # Read first (and only) band
            metadata = {
                "crs": src.crs.to_string() if src.crs else "EPSG:4326",
                "transform": src.transform,
                "bounds": src.bounds,
                "width": src.width,
                "height": src.height,
                "nodata": src.nodata,
                "dtype": str(data.dtype),
            }
            return data, metadata
    except Exception as e:
        logger.warning(f"Failed to load population raster {raster_path}: {e}")
        return None, None


def _sample_population_in_cell(
    raster_data: np.ndarray,
    metadata: dict,
    cell_lat: float,
    cell_lon: float,
    cell_size_deg: float = TERRITORY_GRID_DEG,
) -> float:
    """
    Sample and sum population in a grid cell from raster.

    Uses rasterio's window-based sampling to extract the region covering
    the cell bounds and sum the population values.

    Args:
        raster_data: Numpy array of raster data (already loaded)
        metadata: Raster metadata (transform, bounds, etc.)
        cell_lat: Center latitude of cell
        cell_lon: Center longitude of cell
        cell_size_deg: Cell size in degrees (default 0.2°)

    Returns:
        Sum of population in the cell
    """
    if raster_data is None or metadata is None:
        return 0.0

    try:
        # Cell bounds
        half_cell = cell_size_deg / 2.0
        cell_minlat = cell_lat - half_cell
        cell_maxlat = cell_lat + half_cell
        cell_minlon = cell_lon - half_cell
        cell_maxlon = cell_lon + half_cell

        # Use rasterio transform to convert bounds to window
        transform = metadata.get("transform")
        if transform is None:
            return 0.0

        # Rasterio's from_bounds requires (left, bottom, right, top)
        window = from_bounds(
            cell_minlon, cell_minlat, cell_maxlon, cell_maxlat, transform
        )

        # Extract window from raster
        # Handle edge cases where window extends beyond raster bounds
        row_start = max(0, int(window.row_off))
        row_stop = min(raster_data.shape[0], int(window.row_off + window.height))
        col_start = max(0, int(window.col_off))
        col_stop = min(raster_data.shape[1], int(window.col_off + window.width))

        if row_start >= row_stop or col_start >= col_stop:
            return 0.0

        window_data = raster_data[row_start:row_stop, col_start:col_stop]

        # Handle nodata values
        nodata = metadata.get("nodata")
        if nodata is not None:
            window_data = np.where(window_data == nodata, 0, window_data)

        # Sum population, convert to float for safety
        population = float(np.sum(window_data))
        return max(0.0, population)

    except Exception as e:
        logger.debug(f"Error sampling population in cell ({cell_lat}, {cell_lon}): {e}")
        return 0.0


def aggregate_population_by_territory(
    raster_data: Optional[np.ndarray],
    metadata: Optional[dict],
    territories: Optional[dict[str, dict]] = None,
    bounds: Optional[Tuple[float, float, float, float]] = None,
    cell_size_deg: float = TERRITORY_GRID_DEG,
) -> dict[str, float]:
    """
    Aggregate population from raster into 0.2° grid cells.

    Scans the raster bounds (or specified bounds) and sums population
    for each 0.2° grid cell that overlaps the raster.

    Args:
        raster_data: Raster numpy array
        metadata: Raster metadata
        territories: Optional dict mapping territory_id -> config
        bounds: Optional (minlon, minlat, maxlon, maxlat) to scan;
                uses raster bounds if not specified

    Returns:
        Dict mapping cell_id (e.g., "cell-+16.20_-061.40") to population count
    """
    if raster_data is None or metadata is None:
        return {}

    if territories is None:
        territories = TERRITORY_CONFIG

    try:
        # Determine scan bounds
        if bounds:
            minlon, minlat, maxlon, maxlat = bounds
        else:
            raster_bounds = metadata.get("bounds")
            if raster_bounds is None:
                return {}
            minlon, minlat, maxlon, maxlat = raster_bounds

        result = {}

        lat_centers = _aligned_grid_centers(minlat, maxlat, step=cell_size_deg)
        lon_centers = _aligned_grid_centers(minlon, maxlon, step=cell_size_deg)

        for lat in lat_centers:
            for lon in lon_centers:
                # Sample population in this cell
                population = _sample_population_in_cell(
                    raster_data, metadata, lat, lon, cell_size_deg
                )

                if population > 0:
                    # Format cell ID: "cell-{lat:+05.2f}_{lon:+06.2f}"
                    cell_id = f"cell-{lat:+05.2f}_{lon:+06.2f}"
                    result[cell_id] = population

        logger.info(
            f"Aggregated population for {len(result)} cells "
            f"(bounds: {minlon:.2f}, {minlat:.2f}, {maxlon:.2f}, {maxlat:.2f})"
        )
        return result

    except Exception as e:
        logger.error(f"Failed to aggregate population by territory: {e}")
        return {}


def load_population_data(
    population_data_dir: str | Path,
    territories: Optional[list[str]] = None,
    cell_size_deg: float = TERRITORY_GRID_DEG,
) -> dict[str, dict[str, float]]:
    """
    Load and aggregate population data for specified territories.

    High-level function to load WorldPop rasters for a set of territories
    and aggregate by grid cell.

    Args:
        population_data_dir: Directory containing WorldPop TIF files
        territories: List of territory codes ("GUA", "MTQ", "BLM"); if None, loads all available

    Returns:
        Dict mapping territory_id -> {cell_id -> population_count}
        Example: {"GUA": {"cell-+16.20_-061.40": 5000, ...}}
    """
    if territories is None:
        territories = list(TERRITORY_CONFIG.keys())

    population_data_dir = Path(population_data_dir)
    result = {}

    for territory_id in territories:
        if territory_id not in TERRITORY_CONFIG:
            logger.warning(f"Unknown territory: {territory_id}")
            continue

        config = TERRITORY_CONFIG[territory_id]
        raster_path = population_data_dir / config["raster_filename"]

        logger.info(f"Loading population data for {config['name']} ({territory_id})")

        raster_data, metadata = load_population_raster(raster_path)
        if raster_data is None:
            logger.warning(f"Skipping {territory_id}: raster not available")
            result[territory_id] = {}
            continue

        # Aggregate by grid
        aggregated = aggregate_population_by_territory(
            raster_data,
            metadata,
            bounds=config["bounds"],
            cell_size_deg=cell_size_deg,
        )
        result[territory_id] = aggregated
        logger.info(f"Loaded {len(aggregated)} cells for {territory_id}")

    return result


def get_population_for_cell(
    cell_id: str,
    population_by_territory: dict[str, dict[str, float]],
) -> float:
    """
    Get population for a specific cell from aggregated data.

    Args:
        cell_id: Cell ID (e.g., "cell-+16.20_-061.40")
        population_by_territory: Result from load_population_data()

    Returns:
        Population count, or 0.0 if cell not found
    """
    for territory_data in population_by_territory.values():
        if cell_id in territory_data:
            return float(territory_data[cell_id])
    return 0.0


def get_territory_id_from_cell_id(cell_id: str) -> Optional[str]:
    """
    Determine territory ID from cell ID based on coordinates.

    Parses cell ID to extract coordinates and determines which territory
    the cell belongs to.

    Args:
        cell_id: Cell ID (e.g., "cell-+16.20_-061.40")

    Returns:
        Territory ID ("GUA", "MTQ", "BLM") or None
    """
    try:
        # Parse cell ID: "cell-{lat:+05.2f}_{lon:+06.2f}"
        parts = cell_id.replace("cell-", "").split("_")
        if len(parts) != 2:
            return None
        lat = float(parts[0])
        lon = float(parts[1])
        return _territory_for_coords(lat, lon)
    except Exception:
        return None
