from backend.app.risk_engine import population_loader


def test_population_loader_registers_blm_raster() -> None:
    cfg = population_loader.TERRITORY_CONFIG["BLM"]

    assert cfg["name"] == "Saint-Barthélemy"
    assert cfg["iso_code"] == "BLM"
    assert cfg["raster_filename"] == "blm_pop_2020_CN_100m_R2025A_v1.tif"
