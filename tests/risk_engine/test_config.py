from __future__ import annotations

from pathlib import Path

import pytest

from backend.app import config


@pytest.mark.parametrize(
    ("territory", "copernicus_name", "legacy_name"),
    [
        ("guadeloupe", "Guadeloupe_COP30.tif", "Guadeloupe.tif"),
        ("martinique", "Martinique_COP30.tif", "Martinique.tif"),
    ],
)
def test_resolve_surge_topo_path_prefers_copernicus_default_over_legacy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    territory: str,
    copernicus_name: str,
    legacy_name: str,
) -> None:
    copernicus_path = tmp_path / "Copernicus GLO-30 Digital Elevation Model" / copernicus_name
    legacy_path = tmp_path / legacy_name
    fallback_path = tmp_path / "fallback.asc"

    copernicus_path.parent.mkdir(parents=True, exist_ok=True)
    copernicus_path.write_text("copernicus", encoding="utf-8")
    legacy_path.write_text("legacy", encoding="utf-8")
    fallback_path.write_text("fallback", encoding="utf-8")

    monkeypatch.setattr(config, "_DEFAULT_SURGE_TOPO_BY_TERRITORY", {territory: copernicus_path})
    monkeypatch.setattr(config, "_LEGACY_SURGE_TOPO_BY_TERRITORY", {territory: legacy_path})

    resolved = config.resolve_surge_topo_path_for_territory(
        territory,
        settings=config.Settings(hazard_surge_topo_path=fallback_path),
        env={},
    )

    assert resolved == copernicus_path


def test_resolve_surge_topo_path_uses_territory_env_override_first(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    override_path = tmp_path / "override-guadeloupe.tif"
    copernicus_path = tmp_path / "Copernicus GLO-30 Digital Elevation Model" / "Guadeloupe_COP30.tif"
    legacy_path = tmp_path / "Guadeloupe.tif"
    fallback_path = tmp_path / "fallback.asc"

    override_path.write_text("override", encoding="utf-8")
    copernicus_path.parent.mkdir(parents=True, exist_ok=True)
    copernicus_path.write_text("copernicus", encoding="utf-8")
    legacy_path.write_text("legacy", encoding="utf-8")
    fallback_path.write_text("fallback", encoding="utf-8")

    monkeypatch.setattr(config, "_DEFAULT_SURGE_TOPO_BY_TERRITORY", {"guadeloupe": copernicus_path})
    monkeypatch.setattr(config, "_LEGACY_SURGE_TOPO_BY_TERRITORY", {"guadeloupe": legacy_path})

    resolved = config.resolve_surge_topo_path_for_territory(
        "guadeloupe",
        settings=config.Settings(hazard_surge_topo_path=fallback_path),
        env={"SIB_RISK_HAZARD_SURGE_TOPO_PATH_GUADELOUPE": str(override_path)},
    )

    assert resolved == override_path


def test_resolve_surge_topo_path_supports_saint_barthelemy_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    copernicus_path = tmp_path / "Copernicus GLO-30 Digital Elevation Model" / "SaintBarthelemy_COP30.tif"
    fallback_path = tmp_path / "fallback.asc"

    copernicus_path.parent.mkdir(parents=True, exist_ok=True)
    copernicus_path.write_text("copernicus", encoding="utf-8")
    fallback_path.write_text("fallback", encoding="utf-8")

    monkeypatch.setattr(config, "_DEFAULT_SURGE_TOPO_BY_TERRITORY", {"saint-barthelemy": copernicus_path})
    monkeypatch.setattr(config, "_LEGACY_SURGE_TOPO_BY_TERRITORY", {})

    resolved = config.resolve_surge_topo_path_for_territory(
        "stb",
        settings=config.Settings(hazard_surge_topo_path=fallback_path),
        env={},
    )

    assert resolved == copernicus_path
