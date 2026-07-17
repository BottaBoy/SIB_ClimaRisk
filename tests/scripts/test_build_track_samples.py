from scripts.build_track_samples import (
    CURVE_RP,
    RP_TARGETS,
    SAMPLE_SIZES,
    SELECTION_MODE_INTENSITY_DISTANCE,
    SELECTION_MODE_INTENSITY_MAX,
    SELECTION_SCORE_KIND_INTENSITY_DISTANCE,
    SELECTION_SCORE_KIND_INTENSITY_MAX,
    V2_INTENSITY_SAMPLE_SIZES,
    _selection_score_for_mode,
    build_nested_samples_for_seed,
)


def _fake_records(count: int = 18000) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for idx in range(1, count + 1):
        if idx <= 10:
            stratum = "rank_001_010"
        elif idx <= 20:
            stratum = "rank_011_020"
        elif idx <= 50:
            stratum = "rank_021_050"
        elif idx <= 100:
            stratum = "rank_051_100"
        elif idx <= 200:
            stratum = "rank_101_200"
        elif idx <= 500:
            stratum = "rank_201_500"
        elif idx <= 1000:
            stratum = "rank_501_1000"
        elif idx <= 2000:
            stratum = "rank_1001_2000"
        elif idx <= 5000:
            stratum = "rank_2001_5000"
        elif idx <= 10000:
            stratum = "rank_5001_10000"
        else:
            stratum = "rank_gt_10000"
        rows.append(
            {
                "track_instance_id": f"storm|0|track-{idx}",
                "loss_eur": float(count - idx + 1),
                "rank": idx,
                "stratum": stratum,
                "category": idx % 6,
                "quadrant": ("NE", "NW", "SE", "SW")[idx % 4],
                "max_wind_mps": float(20 + (idx % 80)),
                "min_distance_km": float(idx % 300),
            }
        )
    return rows


def test_build_nested_samples_are_exact_and_progressive() -> None:
    samples = build_nested_samples_for_seed(_fake_records(), seed=1234, sample_sizes=SAMPLE_SIZES)

    assert [len(samples[size]) for size in SAMPLE_SIZES] == list(SAMPLE_SIZES)
    assert samples[50].issubset(samples[100])
    assert samples[100].issubset(samples[800])
    assert samples[800].issubset(samples[1500])
    assert samples[1500].issubset(samples[5000])
    assert samples[5000].issubset(samples[15000])


def test_build_nested_samples_keep_return_period_skeleton() -> None:
    samples = build_nested_samples_for_seed(_fake_records(), seed=4321, sample_sizes=SAMPLE_SIZES)
    skeleton = {f"storm|0|track-{idx}" for idx in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 100, 200, 1000]}

    assert skeleton.issubset(samples[50])


def test_damage_curve_uses_operational_return_periods_only() -> None:
    assert CURVE_RP == RP_TARGETS == (10, 50, 100, 1000)


def test_intensity_v2_nested_samples_are_exact_and_progressive_without_skeleton() -> None:
    samples = build_nested_samples_for_seed(
        _fake_records(),
        seed=5678,
        sample_sizes=V2_INTENSITY_SAMPLE_SIZES,
        neutral_strata=True,
        keep_skeleton=False,
        balance_mode="none",
    )

    assert [len(samples[size]) for size in V2_INTENSITY_SAMPLE_SIZES] == list(V2_INTENSITY_SAMPLE_SIZES)
    assert samples[50].issubset(samples[100])
    assert samples[100].issubset(samples[800])
    assert samples[800].issubset(samples[1500])
    assert samples[1500].issubset(samples[5000])


def test_intensity_v2_score_uses_wind_only() -> None:
    score_a, kind_a, loss_a = _selection_score_for_mode(
        SELECTION_MODE_INTENSITY_MAX,
        loss_eur=1_000_000.0,
        max_wind_mps=42.5,
        min_distance_km=5.0,
        category=5,
    )
    score_b, kind_b, loss_b = _selection_score_for_mode(
        SELECTION_MODE_INTENSITY_MAX,
        loss_eur=0.0,
        max_wind_mps=42.5,
        min_distance_km=900.0,
        category=0,
    )

    assert score_a == score_b == 42.5
    assert kind_a == kind_b == SELECTION_SCORE_KIND_INTENSITY_MAX
    assert loss_a == loss_b == 0.0


def test_intensity_distance_score_uses_wind_and_distance_only() -> None:
    score_close, kind_close, loss_close = _selection_score_for_mode(
        SELECTION_MODE_INTENSITY_DISTANCE,
        loss_eur=1_000_000.0,
        max_wind_mps=60.0,
        min_distance_km=0.0,
        category=5,
    )
    score_mid, kind_mid, loss_mid = _selection_score_for_mode(
        SELECTION_MODE_INTENSITY_DISTANCE,
        loss_eur=0.0,
        max_wind_mps=60.0,
        min_distance_km=150.0,
        category=0,
    )
    score_far, kind_far, loss_far = _selection_score_for_mode(
        SELECTION_MODE_INTENSITY_DISTANCE,
        loss_eur=0.0,
        max_wind_mps=60.0,
        min_distance_km=300.0,
        category=0,
    )

    assert score_close == 60.0
    assert score_mid == 30.0
    assert score_far == 12.0
    assert kind_close == kind_mid == kind_far == SELECTION_SCORE_KIND_INTENSITY_DISTANCE
    assert loss_close == loss_mid == loss_far == 0.0


def test_score_mass_quotas_prioritize_high_score_strata() -> None:
    records = [
        {"track_instance_id": f"high-{idx}", "stratum": "high", "selection_score": 10.0}
        for idx in range(100)
    ]
    records.extend(
        {"track_instance_id": f"low-{idx}", "stratum": "low", "selection_score": 0.1}
        for idx in range(100)
    )

    samples = build_nested_samples_for_seed(
        records,
        seed=2468,
        sample_sizes=(20,),
        neutral_strata=True,
        keep_skeleton=False,
        balance_mode="score_weighted",
        quota_mode="score_mass",
    )

    assert len(samples[20]) == 20
    assert all(track_id.startswith("high-") for track_id in samples[20])
