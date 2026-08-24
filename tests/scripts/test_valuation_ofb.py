from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import valuation_ofb


def test_get_water_values_shares_eu_profile_between_guadeloupe_and_martinique() -> None:
    guadeloupe = valuation_ofb.get_water_values("guadeloupe")
    martinique = valuation_ofb.get_water_values("martinique")

    assert guadeloupe["eau_eu"] == martinique["eau_eu"] == 957_143.0
    assert guadeloupe["eau_eu_pr"] == martinique["eau_eu_pr"] == 397_636.0
    assert guadeloupe["eau_eu_step"] == martinique["eau_eu_step"] == 8_785_714.0


def test_get_water_values_keeps_aep_pending_values_by_territory() -> None:
    guadeloupe = valuation_ofb.get_water_values("guadeloupe")
    martinique = valuation_ofb.get_water_values("martinique")
    fallback = valuation_ofb.get_water_values("unknown")

    assert guadeloupe["eau_aep"] == 776_386.0
    assert martinique["eau_aep"] == 653_445.0
    assert fallback["eau_aep"] == guadeloupe["eau_aep"]


def test_build_valuation_metadata_marks_explicit_territory_inputs() -> None:
    metadata = valuation_ofb.build_valuation_metadata("guadeloupe")

    assert metadata["territory_input"] == "guadeloupe"
    assert metadata["territory_effective"] == "guadeloupe"
    assert metadata["reference_profile_territory"] == "guadeloupe"
    assert metadata["source"] == valuation_ofb.SOURCE_LABEL
    assert metadata["valuation_version"] == valuation_ofb.VALUATION_VERSION
    assert metadata["new_values"]["eu_cana_eur_per_km"] == 957_143.0
    assert metadata["class_coverage"]["eau_eu"]["status"] == "shared_default_profile"
    assert metadata["class_coverage"]["eau_aep"]["reference_territory"] == "guadeloupe"
    assert metadata["policy_outside_bbox"] == "explicit_territory_input"


def test_build_valuation_metadata_keeps_default_policy_for_unknown_territory() -> None:
    metadata = valuation_ofb.build_valuation_metadata("unknown")

    assert metadata["territory_input"] == "fallback_guadeloupe"
    assert metadata["territory_effective"] == "guadeloupe"
    assert metadata["new_values"]["aep_cana_eur_per_km"] == 776_386.0
    assert metadata["policy_outside_bbox"] == "default_to_guadeloupe"


def test_build_valuation_metadata_keeps_martinique_aep_exception() -> None:
    metadata = valuation_ofb.build_valuation_metadata("martinique")

    assert metadata["territory_effective"] == "martinique"
    assert metadata["new_values"]["aep_cana_eur_per_km"] == 653_445.0
    assert metadata["new_values"]["eu_cana_eur_per_km"] == 957_143.0
    assert metadata["nb_prix_compares"]["eu_pr"] == 11
    assert metadata["class_coverage"]["eau_aep"]["status"] == "temporary_exception_pending_aep_transcription"
    assert metadata["class_coverage"]["eau_aep"]["reference_territory"] == "martinique"


def test_saint_barthelemy_uses_guadeloupe_profile_with_50pct_uplift() -> None:
    guadeloupe = valuation_ofb.get_water_values("guadeloupe")
    saint_barthelemy = valuation_ofb.get_water_values("saint-barthelemy")
    elec_stb = valuation_ofb.get_elec_values_for_territory("saint-barthelemy")
    network_values_stb = valuation_ofb.get_network_values_per_km("saint-barthelemy")
    metadata = valuation_ofb.build_valuation_metadata("stb")

    assert saint_barthelemy["eau_aep"] == guadeloupe["eau_aep"] * 1.5
    assert saint_barthelemy["eau_eu"] == guadeloupe["eau_eu"] * 1.5
    assert elec_stb["elec_bt_aerien"] == valuation_ofb.ELECTRIC_VALUES["elec_bt_aerien"] * 1.5
    assert network_values_stb["elec_hta_souterrain"] == valuation_ofb.ELECTRIC_VALUES["elec_hta_souterrain"] * 1.5
    assert valuation_ofb.get_aep_ouvrage_value_for_territory("blm", "CAP") == valuation_ofb.AEP_OUVRAGE_VALUES["CAP"] * 1.5
    assert metadata["territory_effective"] == "saint-barthelemy"
    assert metadata["territory_cost_multiplier"] == 1.5
