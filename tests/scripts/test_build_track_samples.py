from scripts.build_track_samples import CURVE_RP, RP_TARGETS, SAMPLE_SIZES, build_nested_samples_for_seed


def _fake_records(count: int = 2000) -> list[dict[str, object]]:
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
        else:
            stratum = "rank_1001_2000"
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


def test_build_nested_samples_keep_return_period_skeleton() -> None:
    samples = build_nested_samples_for_seed(_fake_records(), seed=4321, sample_sizes=SAMPLE_SIZES)
    skeleton = {f"storm|0|track-{idx}" for idx in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 100, 200, 1000]}

    assert skeleton.issubset(samples[50])


def test_damage_curve_uses_operational_return_periods_only() -> None:
    assert CURVE_RP == RP_TARGETS == (10, 50, 100, 1000)
