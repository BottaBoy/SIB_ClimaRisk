#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any


DEFAULT_INFRA_ELEC_DIR = {
    "guadeloupe": Path("/home/ubuntu/uploads/Infra_Elec_Guadeloupe"),
    "martinique": Path("/home/ubuntu/uploads/Infra_Elec_Martinique"),
}

DEFAULT_INFRA_EAU_DIR = {
    "guadeloupe": Path("/home/ubuntu/uploads/Infra_Eau_Guadeloupe"),
    "martinique": Path("/home/ubuntu/uploads/Infra_Eau_Martinique"),
}

CASE_STUDY_BBOX = {
    "guadeloupe": {
        "lat_min": 15.5,
        "lat_max": 16.95625,
        "lon_min": -62.48125,
        "lon_max": -60.66875,
    },
    "martinique": {
        "lat_min": 14.3,
        "lat_max": 15.1,
        "lon_min": -61.4,
        "lon_max": -60.7,
    },
}

_ELEC_LINE_DEFS = {
    "guadeloupe": [
        {
            "class_key": "elec_bt_aerien",
            "asset_type": "elec_bt_aerien",
            "prefix": "elec-bt-aerien",
            "infra_type": "elec_bt_aerien",
            "source_group": "ELEC",
            "patterns": ["lignes-basse-tension-bt-aerien-gua.geojson"],
        },
        {
            "class_key": "elec_bt_souterrain",
            "asset_type": "elec_bt_souterrain",
            "prefix": "elec-bt-souterrain",
            "infra_type": "elec_bt_souterrain",
            "source_group": "ELEC",
            "patterns": ["lignes-basse-tension-bt-souterrain-gua.geojson"],
        },
        {
            "class_key": "elec_hta_aerien",
            "asset_type": "elec_hta_aerien",
            "prefix": "elec-hta-aerien",
            "infra_type": "elec_hta_aerien",
            "source_group": "ELEC",
            "patterns": ["lignes-haute-tension-hta-aerien-gua.geojson"],
        },
        {
            "class_key": "elec_hta_souterrain",
            "asset_type": "elec_hta_souterrain",
            "prefix": "elec-hta-souterrain",
            "infra_type": "elec_hta_souterrain",
            "source_group": "ELEC",
            "patterns": ["lignes-haute-tension-hta-souterrain-gua.geojson"],
        },
    ],
    "martinique": [
        {
            "class_key": "elec_bt_aerien",
            "asset_type": "elec_bt_aerien",
            "prefix": "elec-bt-aerien",
            "infra_type": "elec_bt_aerien",
            "source_group": "ELEC",
            "patterns": ["lignes-basse-tension-bt-aerien-martinique.geojson"],
        },
        {
            "class_key": "elec_bt_souterrain",
            "asset_type": "elec_bt_souterrain",
            "prefix": "elec-bt-souterrain",
            "infra_type": "elec_bt_souterrain",
            "source_group": "ELEC",
            "patterns": ["e_troncon_cable_bt_me_position_me_position-martinique.geojson"],
        },
        {
            "class_key": "elec_hta_aerien",
            "asset_type": "elec_hta_aerien",
            "prefix": "elec-hta-aerien",
            "infra_type": "elec_hta_aerien",
            "source_group": "ELEC",
            "patterns": ["lignes-haute-tension-hta-aerien-martinique.geojson"],
        },
        {
            "class_key": "elec_hta_souterrain",
            "asset_type": "elec_hta_souterrain",
            "prefix": "elec-hta-souterrain",
            "infra_type": "elec_hta_souterrain",
            "source_group": "ELEC",
            "patterns": ["lignes-haute-tension-hta-souterrain-martinique.geojson"],
        },
    ],
}

_WATER_LINE_DEFS = {
    "guadeloupe": [
        {
            "class_key": "eau_aep",
            "asset_type": "eau_aep_cana",
            "prefix": "aep-cana",
            "infra_type": "aep_cana",
            "source_group": "AEP",
            "patterns": ["AEP/cana_aep.gpkg"],
            "value_key": "eau_aep",
        },
        {
            "class_key": "eau_eu",
            "asset_type": "eau_eu_cana",
            "prefix": "eu-cana",
            "infra_type": "eu_cana",
            "source_group": "EU",
            "patterns": ["EU/cana_eu.gpkg"],
            "value_key": "eau_eu",
        },
    ],
    "martinique": [
        {
            "class_key": "eau_aep",
            "asset_type": "eau_aep_cana",
            "prefix": "aep-cana",
            "infra_type": "aep_cana",
            "source_group": "AEP",
            "patterns": ["AEP/Réseaux/*.shp"],
            "value_key": "eau_aep",
        },
        {
            "class_key": "eau_eu",
            "asset_type": "eau_eu_cana",
            "prefix": "eu-cana",
            "infra_type": "eu_cana",
            "source_group": "EU",
            "patterns": ["Assainissement/Reseaux/*.shp"],
            "value_key": "eau_eu",
        },
    ],
}

_WATER_POINT_FIXED_DEFS = {
    "guadeloupe": [
        {
            "asset_type": "eau_eu_pr",
            "prefix": "eu-pr",
            "infra_type": "eu_pr",
            "source_group": "EU",
            "patterns": ["EU/pr.gpkg"],
            "value_key": "eau_eu_pr",
        },
        {
            "asset_type": "eau_eu_step",
            "prefix": "eu-step",
            "infra_type": "eu_step",
            "source_group": "EU",
            "patterns": ["EU/step.gpkg"],
            "value_key": "eau_eu_step",
        },
    ],
    "martinique": [
        {
            "asset_type": "eau_eu_pr",
            "prefix": "eu-pr",
            "infra_type": "eu_pr",
            "source_group": "EU",
            "patterns": ["Assainissement/Poste de refoulement/Postes de refoulement_2024.shp"],
            "value_key": "eau_eu_pr",
        },
        {
            "asset_type": "eau_eu_step",
            "prefix": "eu-step",
            "infra_type": "eu_step",
            "source_group": "EU",
            "patterns": ["Assainissement/STEP/*.shp"],
            "value_key": "eau_eu_step",
        },
    ],
}

_AEP_OUVRAGE_DEFS = {
    "guadeloupe": [
        {
            "mode": "field",
            "prefix": "aep-ouvrage",
            "infra_type": "aep_ouvrage",
            "source_group": "AEP",
            "patterns": ["AEP/ouvrage_aep.gpkg"],
            "field_name": "ovrg_type",
        }
    ],
    "martinique": [
        {
            "mode": "fixed_type",
            "prefix": "aep-ouvrage-trait",
            "infra_type": "aep_ouvrage",
            "source_group": "AEP",
            "patterns": ["AEP/Usines/UPEP_2017.shp"],
            "ovrg_type": "TRAIT",
        },
        {
            "mode": "fixed_type",
            "prefix": "aep-ouvrage-cap",
            "infra_type": "aep_ouvrage",
            "source_group": "AEP",
            "patterns": ["AEP/Forages/AEP_CAPTAGES_FORAGES_2024.shp"],
            "ovrg_type": "CAP",
        },
    ],
}


def normalize_territory(territory: str | None) -> str:
    value = str(territory or "guadeloupe").strip().lower()
    if value in {"martinique", "mq"}:
        return "martinique"
    return "guadeloupe"


def territory_label(territory: str | None) -> str:
    key = normalize_territory(territory)
    return "Martinique" if key == "martinique" else "Guadeloupe"


def _resolve_patterns(root: Path, patterns: list[str], *, source_name: str) -> list[Path]:
    paths: list[Path] = []
    for pattern in patterns:
        matches = sorted(root.glob(pattern))
        if matches:
            paths.extend(matches)
            continue
        candidate = root / pattern
        if candidate.exists():
            paths.append(candidate)
    deduped: list[Path] = []
    seen = set()
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(path)
    if not deduped:
        raise FileNotFoundError(f"No files found for {source_name} under {root} with patterns={patterns}")
    return deduped


def get_case_study(
    territory: str | None,
    *,
    infra_elec_dir: Path | None = None,
    infra_eau_dir: Path | None = None,
) -> dict[str, Any]:
    key = normalize_territory(territory)
    elec_root = Path(infra_elec_dir) if infra_elec_dir is not None else DEFAULT_INFRA_ELEC_DIR[key]
    eau_root = Path(infra_eau_dir) if infra_eau_dir is not None else DEFAULT_INFRA_EAU_DIR[key]

    elec_sources: list[dict[str, Any]] = []
    for src in _ELEC_LINE_DEFS[key]:
        item = dict(src)
        item["paths"] = _resolve_patterns(elec_root, list(src["patterns"]), source_name=f"{key}:{src['asset_type']}")
        elec_sources.append(item)

    water_line_sources: list[dict[str, Any]] = []
    for src in _WATER_LINE_DEFS[key]:
        item = dict(src)
        item["paths"] = _resolve_patterns(eau_root, list(src["patterns"]), source_name=f"{key}:{src['asset_type']}")
        water_line_sources.append(item)

    water_point_fixed_sources: list[dict[str, Any]] = []
    for src in _WATER_POINT_FIXED_DEFS[key]:
        item = dict(src)
        item["paths"] = _resolve_patterns(eau_root, list(src["patterns"]), source_name=f"{key}:{src['asset_type']}")
        water_point_fixed_sources.append(item)

    aep_ouvrage_sources: list[dict[str, Any]] = []
    for src in _AEP_OUVRAGE_DEFS[key]:
        item = dict(src)
        item["paths"] = _resolve_patterns(eau_root, list(src["patterns"]), source_name=f"{key}:aep_ouvrage")
        aep_ouvrage_sources.append(item)

    water_map_layers: list[dict[str, Any]] = []
    for src in water_line_sources + water_point_fixed_sources + aep_ouvrage_sources + elec_sources:
        water_map_layers.append(
            {
                "infra_type": str(src["infra_type"]),
                "source_group": str(src["source_group"]),
                "paths": list(src["paths"]),
            }
        )

    network_geometry_sources = [
        {
            "class_key": str(src["class_key"]),
            "prefix": str(src["prefix"]),
            "paths": list(src["paths"]),
        }
        for src in (water_line_sources + elec_sources)
    ]

    return {
        "territory": key,
        "territory_label": territory_label(key),
        "infra_elec_dir": elec_root,
        "infra_eau_dir": eau_root,
        "wind_bbox": dict(CASE_STUDY_BBOX[key]),
        "elec_line_sources": elec_sources,
        "water_line_sources": water_line_sources,
        "water_point_fixed_sources": water_point_fixed_sources,
        "aep_ouvrage_sources": aep_ouvrage_sources,
        "water_map_layers": water_map_layers,
        "network_geometry_sources": network_geometry_sources,
        "wind_comparison_heading": territory_label(key),
        "analysis_json_name": f"{key}-{'page2' if key == 'martinique' else 'page1'}-analysis.json",
    }
