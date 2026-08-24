from __future__ import annotations

import sys
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import build_basin_wind_leaflet_overlays as overlays


def test_mask_cmcc_low_band_covers_return_period_and_event_max_metrics() -> None:
    grid = np.asarray([[17.9, 18.0, 18.1]], dtype=np.float32)

    for metric in ("rp50", "rp100", "event_max"):
        masked = overlays._mask_cmcc_low_band(grid, "storm_cmcc", metric)
        assert np.isnan(masked[0, 0])
        assert np.isnan(masked[0, 1])
        assert masked[0, 2] == np.float32(18.1)


def test_mask_cmcc_low_band_leaves_mean_and_storm_values_unchanged() -> None:
    grid = np.asarray([[18.0]], dtype=np.float32)

    assert overlays._mask_cmcc_low_band(grid, "storm_cmcc", "mean")[0, 0] == np.float32(18.0)
    assert overlays._mask_cmcc_low_band(grid, "storm", "rp100")[0, 0] == np.float32(18.0)
