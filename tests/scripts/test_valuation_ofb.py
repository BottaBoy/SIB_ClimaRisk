from scripts import valuation_ofb


def test_build_valuation_metadata_marks_explicit_territory_inputs() -> None:
    metadata = valuation_ofb.build_valuation_metadata("guadeloupe")

    assert metadata["territory_input"] == "guadeloupe"
    assert metadata["territory_effective"] == "guadeloupe"
    assert metadata["policy_outside_bbox"] == "explicit_territory_input"


def test_build_valuation_metadata_keeps_default_policy_for_unknown_territory() -> None:
    metadata = valuation_ofb.build_valuation_metadata("unknown")

    assert metadata["territory_input"] == "fallback_guadeloupe"
    assert metadata["territory_effective"] == "guadeloupe"
    assert metadata["policy_outside_bbox"] == "default_to_guadeloupe"