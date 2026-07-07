from __future__ import annotations

import matplotlib
import pytest

from backend.app.risk_engine import png_label_layout


matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _assert_bboxes_do_not_overlap(fig, text_artists) -> None:
    bboxes = png_label_layout.collect_text_bboxes(fig, text_artists)
    axes_bbox = text_artists[0].axes.get_window_extent(renderer=fig.canvas.get_renderer()) if text_artists else None
    for bbox in bboxes:
        assert png_label_layout.bbox_within(bbox, axes_bbox, padding_px=2.0)
    assert png_label_layout.count_bbox_overlaps(bboxes, padding_px=2.0) == 0


def test_grouped_bar_figure_size_grows_with_density() -> None:
    small = png_label_layout.grouped_bar_figure_size(
        category_count=3,
        series_count=2,
        label_fontsize=12,
        max_label_lines=2,
    )
    large = png_label_layout.grouped_bar_figure_size(
        category_count=8,
        series_count=3,
        label_fontsize=14,
        max_label_lines=3,
    )

    assert large[0] > small[0]
    assert large[1] > small[1]


def test_place_grouped_bar_labels_avoids_overlap() -> None:
    fig, ax = plt.subplots(figsize=(13.5, 8.5))
    positions = [0, 1, 2]
    width = 0.35
    bars_a = ax.bar([position - 0.18 for position in positions], [120.0, 85.0, 60.0], width=width, color="#0f766e")
    bars_b = ax.bar([position + 0.18 for position in positions], [95.0, 70.0, 55.0], width=width, color="#c2410c")
    ax.set_ylim(0, 180)

    result = png_label_layout.place_grouped_bar_labels(
        ax,
        [list(bars_a), list(bars_b)],
        [
            ["120.00 EUR\n(10.00% valeur)", "85.00 EUR\n(8.00% valeur)", "60.00 EUR\n(6.00% valeur)"],
            ["95.00 EUR\n(9.50% valeur)", "70.00 EUR\n(7.00% valeur)", "55.00 EUR\n(5.50% valeur)"],
        ],
        label_fontsize=13,
        lane_gap_pts=6.0,
    )

    assert result.success is True
    _assert_bboxes_do_not_overlap(fig, result.text_artists)
    plt.close(fig)


def test_place_line_annotations_avoids_overlap() -> None:
    fig, ax = plt.subplots(figsize=(22.0, 10.0))
    x_values = [10, 20, 50, 100, 200, 400, 600, 800, 1000]
    y_values = [100, 150, 220, 320, 420, 540, 580, 620, 700]
    ax.plot(x_values, y_values, marker="o", color="#2563eb")
    ax.plot(x_values, [value * 0.85 for value in y_values], marker="o", color="#c2410c")
    ax.margins(x=0.12, y=0.22)

    items: list[dict[str, object]] = []
    for idx, (x_value, y_value) in enumerate(zip(x_values, y_values)):
        items.append(
            {
                "x": float(x_value),
                "y": float(y_value),
                "text": f"{x_value}y\n{y_value:.0f} EUR",
                "color": "#2563eb",
                "priority": idx >= 5,
            }
        )
        items.append(
            {
                "x": float(x_value),
                "y": float(y_value * 0.85),
                "text": f"{x_value}y\n{(y_value * 0.85):.0f} EUR",
                "color": "#c2410c",
                "priority": idx >= 5,
            }
        )

    result = png_label_layout.place_line_annotations(
        ax,
        items,
        label_fontsize=11,
        allow_leader_lines=True,
    )

    assert result.success is True
    _assert_bboxes_do_not_overlap(fig, result.text_artists)
    plt.close(fig)


def test_place_horizontal_bar_labels_avoids_overlap() -> None:
    fig, ax = plt.subplots(figsize=(14.0, 7.5))
    y_positions = [0.0, 0.2, 1.0, 1.2]
    values = [12.0, 11.2, -9.5, -8.8]
    ax.barh(y_positions, values, height=0.16, color="#38bdf8")
    ax.set_xlim(-18, 18)

    result = png_label_layout.place_horizontal_bar_labels(
        ax,
        [
            {"x": values[0], "y": y_positions[0], "value": values[0], "text": "+12.0%"},
            {"x": values[1], "y": y_positions[1], "value": values[1], "text": "+11.2%"},
            {"x": values[2], "y": y_positions[2], "value": values[2], "text": "-9.5%"},
            {"x": values[3], "y": y_positions[3], "value": values[3], "text": "-8.8%"},
        ],
        label_fontsize=11,
        lane_gap_pts=8.0,
    )

    assert result.success is True
    _assert_bboxes_do_not_overlap(fig, result.text_artists)
    plt.close(fig)
