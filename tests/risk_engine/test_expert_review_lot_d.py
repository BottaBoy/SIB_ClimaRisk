from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.risk_engine import impact_functions_multi_hazard as multi_hazard


def test_rain_proxy_model_uses_distinct_runoff_coefficients_per_infra_class(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        multi_hazard,
        "_load_flood_depth_curves",
        lambda _path: {
            "F17.5": {
                "depth_m": [0.1, 0.2],
                "mdd": [0.1, 0.2],
                "modeled_infrastructure_type": "Default",
                "modeled_infrastructure_characteristics": "Default",
            },
            "F6.2": {
                "depth_m": [0.1, 0.2],
                "mdd": [0.1, 0.2],
                "modeled_infrastructure_type": "Electricite",
                "modeled_infrastructure_characteristics": "Reseau",
            },
        },
    )
    monkeypatch.setattr(
        multi_hazard,
        "_build_climada_impact_func",
        lambda **kwargs: SimpleNamespace(
            id=int(kwargs["impf_id"]),
            name=str(kwargs["name"]),
            intensity=list(kwargs["intensity"]),
            mdd=list(kwargs["mdd"]),
            intensity_unit=str(kwargs["intensity_unit"]),
        ),
    )

    model = multi_hazard.build_multi_hazard_impact_model(
        surge_haz_type="TCSurgeBathtub",
        rain_haz_type="TR",
        flood_curve_file=Path("/tmp/fake-curves.xlsx"),
        asset_type_to_curve_code={
            "elec_bt_aerien": "F6.2",
            "elec_bt_souterrain": "F6.2",
        },
        rain_proxy_base_runoff_coeff=0.25,
    )

    rain_id_aerien = multi_hazard.resolve_rain_impf_id("elec_bt_aerien", model)
    rain_id_souterrain = multi_hazard.resolve_rain_impf_id("elec_bt_souterrain", model)

    assert rain_id_aerien != rain_id_souterrain
    assert model.mapping_info["effective_runoff_coeff_by_infra_class"]["elec_aerien"] == pytest.approx(0.10)
    assert model.mapping_info["effective_runoff_coeff_by_infra_class"]["elec_souterrain"] == pytest.approx(0.30)

    rain_funcs_by_id = {int(func.id): func for func in model.rain_funcs}
    assert rain_funcs_by_id[rain_id_aerien].intensity == pytest.approx([1000.0, 2000.0])
    assert rain_funcs_by_id[rain_id_souterrain].intensity == pytest.approx([333.3333333333, 666.6666666667])


def test_rain_proxy_global_sensitivity_scales_all_infra_coefficients(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        multi_hazard,
        "_load_flood_depth_curves",
        lambda _path: {
            "F17.5": {
                "depth_m": [0.1],
                "mdd": [0.1],
                "modeled_infrastructure_type": "Default",
                "modeled_infrastructure_characteristics": "Default",
            }
        },
    )
    monkeypatch.setattr(
        multi_hazard,
        "_build_climada_impact_func",
        lambda **kwargs: SimpleNamespace(
            id=int(kwargs["impf_id"]),
            name=str(kwargs["name"]),
            intensity=list(kwargs["intensity"]),
            mdd=list(kwargs["mdd"]),
            intensity_unit=str(kwargs["intensity_unit"]),
        ),
    )

    model = multi_hazard.build_multi_hazard_impact_model(
        surge_haz_type="TCSurgeBathtub",
        rain_haz_type="TR",
        flood_curve_file=Path("/tmp/fake-curves.xlsx"),
        rain_proxy_base_runoff_coeff=0.5,
    )

    effective_coeffs = model.mapping_info["effective_runoff_coeff_by_infra_class"]
    assert effective_coeffs["elec_aerien"] == pytest.approx(0.20)
    assert effective_coeffs["eau_reseau"] == pytest.approx(0.50)
    assert effective_coeffs["habitation"] == pytest.approx(0.40)