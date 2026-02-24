#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_settings
from app.job_store import JobStore
from app.risk_engine.pipeline import run_job_pipeline


def main() -> int:
    parser = argparse.ArgumentParser(description='Run a local backoffice sample using the risk-engine pipeline (fallback if CLIMADA stack absent).')
    parser.add_argument('--file', required=True, help='Path to exposure file (csv/xlsx/geojson/gpkg)')
    parser.add_argument('--value-field', default=None, help='Value field (required for most formats)')
    parser.add_argument('--id-field', default=None)
    parser.add_argument('--asset-type-field', default=None)
    parser.add_argument('--crs', default=None)
    parser.add_argument('--spacing-m', type=float, default=100.0)
    parser.add_argument('--output', default='sample_run_result.json')
    args = parser.parse_args()

    settings = load_settings()
    store = JobStore(settings.job_root, ttl_hours=settings.job_ttl_hours)
    params = {
        'input_mode': 'file',
        'value_field': args.value_field,
        'id_field': args.id_field,
        'asset_type_field': args.asset_type_field,
        'crs': args.crs,
        'sampling_spacing_m': args.spacing_m,
        'run_label': 'cli_backoffice_sample'
    }
    job = store.create_job(params=params)
    src = Path(args.file)
    if not src.exists():
        raise SystemExit(f'File not found: {src}')
    dst = store.upload_path(job.job_id, src.name)
    dst.write_bytes(src.read_bytes())
    params = store.get_params(job.job_id)
    params.update({'upload_original_name': src.name, 'upload_saved_name': dst.name, 'upload_size_bytes': dst.stat().st_size})
    store.set_params(job.job_id, params)

    result = run_job_pipeline(job.job_id, params, settings, store)
    store.save_result(job.job_id, result)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Job: {job.job_id}')
    print(f'Result written to: {args.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
