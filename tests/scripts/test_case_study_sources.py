from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import case_study_sources, run_web_artifacts


def test_parse_territory_selection_supports_stb_and_all() -> None:
    assert case_study_sources.parse_territory_selection("stb") == ["saint-barthelemy"]
    assert case_study_sources.parse_territory_selection("all") == [
        "guadeloupe",
        "martinique",
        "saint-barthelemy",
    ]
    assert case_study_sources.parse_territory_selection("both") == [
        "guadeloupe",
        "martinique",
    ]


def test_page_suffix_and_frontend_paths_support_saint_barthelemy() -> None:
    assert case_study_sources.territory_page_suffix("saint-barthelemy") == "page7"
    assert run_web_artifacts.case_study_page_suffix("saint-barthelemy") == "page7"
    assert run_web_artifacts.territory_frontend_rebuild_relative_paths("saint-barthelemy") == (
        "data/saint-barthelemy-wind-maps.json",
        "data/saint-barthelemy-landslide-maps.json",
        "data/saint-barthelemy-multi-hazard-proxy.json",
        "data/saint-barthelemy-page7-analysis.json",
        "data/saint-barthelemy-water-infra.geojson",
        "data/saint-barthelemy-network-states.geojson",
    )
