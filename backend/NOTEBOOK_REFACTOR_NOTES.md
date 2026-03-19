# Notebook Refactor Notes (`SIB_ClimatRisques10.ipynb`)

This backend scaffold is designed to replace the monolithic notebook execution path with modular code.

## Cleanups applied in the production-oriented code path

1. **Impact function cell cleanup (Notebook cell 4)**
   - Kept only the Eberenz-style tropical cyclone vulnerability curve in `app/risk_engine/impact_functions.py`.
   - Removed the notebook-only dummy/random impact function (`haz_type = "XXX"`, random `mdd/paa`) from the production path.

2. **Duplicate impact/disaggregation cells (Notebook cells 5 and 6)**
   - Consolidated into one architecture path:
     - `exposure_ingest.py`
     - `exposure_disaggregation.py`
     - `impact_runner.py`
     - `analysis_export.py`
   - Backend uses a single run pipeline (`app/risk_engine/pipeline.py`).

3. **Duplicate side-by-side plotting cells (Notebook cells 11 and 12)**
   - Replaced by one schema-driven frontend chart renderer (ECharts) and a unified `graphs` result section.

4. **CRS / spacing bug risk (cells 0, 5, 6)**
   - Notebook used `spacing = 100` (meters) while `crs_file` could be `EPSG:4326` (degrees).
   - Backend disaggregation module explicitly records metric CRS usage (`EPSG:3857` default in MVP) and is structured to sample in metric CRS before exporting back to WGS84.

5. **Hazard frequency scaling idempotency (cell 1)**
   - Backend `hazard_loader.py` normalizes frequency on a copy and marks normalized objects to avoid double-scaling in reused objects.

6. **Save/load cell consistency (cells 16 and 17)**
   - Result export is standardized through the unified result schema and artifacts list.
   - Variable naming mismatch (`imp_pnt` vs `imp_pnt_storm`, `EAI` vs `EAI_storm`/`EAI_CMCC`) is removed from the backend path.

## Runtime status on this server

The full CLIMADA + geopandas stack is not installed yet, so the backend currently uses a deterministic fallback engine while keeping the API and result schema stable.

## Impact humains

- Population rasters currently available in `/home/ubuntu/uploads/Population`:
  - `mtq_pop_2020_CN_100m_R2025A_v1.tif` (Martinique)
  - `glp_pop_2020_CN_100m_R2025A_v1.tif` (Guadeloupe)
  - `pyf_pop_2020_CN_100m_R2025A_v1.tif` (Polynesie francaise)
- Technical characteristics (from file metadata + provided doc):
  - GeoTIFF, CRS `EPSG:4326` (WGS84), ~100 m grid (3 arc-seconds).
  - Pixel unit = `number of people per pixel` (NoData = `-99999`).
- Source:
  - WorldPop Global Demographic Data Project, constrained population counts 2015-2030, release `R2025A v1`.
  - DOI: `10.5258/SOTON/WP00839`.
