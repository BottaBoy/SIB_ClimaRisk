from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable


@dataclass(frozen=True)
class LayoutPlacementResult:
    success: bool
    text_artists: tuple[Any, ...]
    overlap_count: int = 0
    out_of_bounds_count: int = 0


def text_line_count(label_text: str | None) -> int:
    text = str(label_text or "").strip()
    if not text:
        return 1
    return text.count("\n") + 1


def points_to_pixels(fig: Any, points: float) -> float:
    return float(points) * float(fig.dpi) / 72.0


def data_delta_from_points(
    ax: Any,
    *,
    x_points: float = 0.0,
    y_points: float = 0.0,
    anchor: tuple[float, float] | None = None,
) -> tuple[float, float]:
    if anchor is None:
        x_limits = ax.get_xlim()
        y_limits = ax.get_ylim()
        anchor = (
            float(x_limits[0] + x_limits[1]) / 2.0,
            float(y_limits[0] + y_limits[1]) / 2.0,
        )
    fig = ax.figure
    origin_display = ax.transData.transform(anchor)
    shifted_display = (
        float(origin_display[0]) + points_to_pixels(fig, x_points),
        float(origin_display[1]) + points_to_pixels(fig, y_points),
    )
    shifted_data = ax.transData.inverted().transform(shifted_display)
    return float(shifted_data[0] - anchor[0]), float(shifted_data[1] - anchor[1])


def bboxes_overlap(first: Any, second: Any, *, padding_px: float = 0.0) -> bool:
    if first is None or second is None:
        return False
    return not (
        float(first.x1) + padding_px <= float(second.x0)
        or float(second.x1) + padding_px <= float(first.x0)
        or float(first.y1) + padding_px <= float(second.y0)
        or float(second.y1) + padding_px <= float(first.y0)
    )


def bbox_within(inner: Any, outer: Any, *, padding_px: float = 0.0) -> bool:
    if inner is None or outer is None:
        return False
    return (
        float(inner.x0) >= float(outer.x0) + padding_px
        and float(inner.y0) >= float(outer.y0) + padding_px
        and float(inner.x1) <= float(outer.x1) - padding_px
        and float(inner.y1) <= float(outer.y1) - padding_px
    )


def count_bbox_overlaps(bboxes: Iterable[Any], *, padding_px: float = 0.0) -> int:
    bbox_list = [bbox for bbox in bboxes if bbox is not None]
    overlap_count = 0
    for left_index in range(len(bbox_list)):
        for right_index in range(left_index + 1, len(bbox_list)):
            if bboxes_overlap(bbox_list[left_index], bbox_list[right_index], padding_px=padding_px):
                overlap_count += 1
    return overlap_count


def grouped_bar_figure_size(
    *,
    category_count: int,
    series_count: int,
    label_fontsize: int,
    max_label_lines: int,
    base_width: float = 11.0,
    base_height: float = 6.2,
) -> tuple[float, float]:
    width = max(
        base_width,
        4.5 + (float(category_count) * 1.35) + (float(series_count) * 0.85) + ((float(label_fontsize) - 8.0) * 0.18),
    )
    height = max(
        base_height,
        4.6 + (float(max_label_lines) * 0.95) + ((float(label_fontsize) - 8.0) * 0.12),
    )
    return width, height


def line_chart_figure_size(
    *,
    point_count: int,
    series_count: int,
    label_fontsize: int,
    max_label_lines: int,
    base_width: float = 11.0,
    base_height: float = 6.0,
    autoscale_mode: str = "both",
) -> tuple[float, float]:
    width = max(
        base_width,
        6.6 + (float(point_count) * 0.68) + (float(series_count) * 0.55) + (float(max_label_lines) * 0.5),
    )
    height = base_height
    if autoscale_mode == "both":
        height = max(
            base_height,
            4.8 + (float(max_label_lines) * 1.0) + ((float(label_fontsize) - 8.0) * 0.2),
        )
    return width, height


def horizontal_bar_figure_size(
    *,
    item_count: int,
    series_count: int,
    label_fontsize: int,
    base_width: float = 18.0,
    base_height: float = 6.0,
) -> tuple[float, float]:
    width = max(base_width, 10.0 + (float(series_count) * 1.2) + ((float(label_fontsize) - 8.0) * 0.4))
    height = max(base_height, (float(item_count) * 0.48) + 3.3 + ((float(label_fontsize) - 8.0) * 0.08))
    return width, height


def label_text_color_for_face(facecolor: Any) -> str:
    if not isinstance(facecolor, (list, tuple)) or len(facecolor) < 3:
        return "#0f172a"
    red = float(facecolor[0])
    green = float(facecolor[1])
    blue = float(facecolor[2])
    luminance = (0.299 * red) + (0.587 * green) + (0.114 * blue)
    return "#0f172a" if luminance >= 0.6 else "#ffffff"


def collect_text_bboxes(fig: Any, text_artists: Iterable[Any]) -> list[Any]:
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    return [text.get_window_extent(renderer=renderer) for text in text_artists]


def place_grouped_bar_labels(
    ax: Any,
    bar_groups: list[list[Any]],
    label_groups: list[list[str]],
    *,
    label_fontsize: int,
    lane_gap_pts: float = 6.0,
    outside_pad_pts: float = 5.0,
    max_lanes: int = 8,
    allow_inside: bool = True,
) -> LayoutPlacementResult:
    fig = ax.figure
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    axes_bbox = ax.get_window_extent(renderer=renderer)
    placed_bboxes: list[Any] = []
    text_artists: list[Any] = []

    for series_index, bars in enumerate(bar_groups):
        labels = label_groups[series_index] if series_index < len(label_groups) else []
        for bar_index, bar in enumerate(bars):
            label_text = str(labels[bar_index] if bar_index < len(labels) else "").strip()
            if not label_text:
                continue

            x_center = float(bar.get_x() + (bar.get_width() / 2.0))
            y_base = float(bar.get_y())
            height = float(bar.get_height())
            is_positive = height >= 0.0
            bar_top = y_base + height if is_positive else y_base

            if allow_inside and abs(height) > 0.0:
                inside_text = ax.text(
                    x_center,
                    y_base + (height / 2.0),
                    label_text,
                    ha="center",
                    va="center",
                    fontsize=label_fontsize,
                    color=label_text_color_for_face(bar.get_facecolor()),
                    clip_on=True,
                )
                inside_bbox = inside_text.get_window_extent(renderer=renderer)
                bar_bbox = bar.get_window_extent(renderer=renderer)
                if bbox_within(inside_bbox, bar_bbox, padding_px=3.0) and not any(
                    bboxes_overlap(inside_bbox, existing, padding_px=2.0) for existing in placed_bboxes
                ):
                    placed_bboxes.append(inside_bbox)
                    text_artists.append(inside_text)
                    continue
                inside_text.remove()

            placed = False
            for lane_index in range(max_lanes):
                lane_offset_pts = outside_pad_pts + (lane_index * ((label_fontsize * text_line_count(label_text) * 0.92) + lane_gap_pts))
                _, y_delta = data_delta_from_points(
                    ax,
                    y_points=lane_offset_pts if is_positive else -lane_offset_pts,
                    anchor=(x_center, bar_top),
                )
                candidate_text = ax.text(
                    x_center,
                    bar_top + y_delta,
                    label_text,
                    ha="center",
                    va="bottom" if is_positive else "top",
                    fontsize=label_fontsize,
                    color="#0f172a",
                    clip_on=True,
                    bbox={"boxstyle": "round,pad=0.18", "facecolor": "white", "edgecolor": "none", "alpha": 0.86},
                )
                candidate_bbox = candidate_text.get_window_extent(renderer=renderer)
                if bbox_within(candidate_bbox, axes_bbox, padding_px=2.0) and not any(
                    bboxes_overlap(candidate_bbox, existing, padding_px=2.0) for existing in placed_bboxes
                ):
                    placed_bboxes.append(candidate_bbox)
                    text_artists.append(candidate_text)
                    placed = True
                    break
                candidate_text.remove()
            if not placed:
                for text_artist in text_artists:
                    text_artist.remove()
                return LayoutPlacementResult(success=False, text_artists=tuple())

    final_bboxes = [text.get_window_extent(renderer=renderer) for text in text_artists]
    out_of_bounds_count = sum(0 if bbox_within(bbox, axes_bbox, padding_px=2.0) else 1 for bbox in final_bboxes)
    return LayoutPlacementResult(
        success=out_of_bounds_count == 0 and count_bbox_overlaps(final_bboxes, padding_px=2.0) == 0,
        text_artists=tuple(text_artists),
        overlap_count=count_bbox_overlaps(final_bboxes, padding_px=2.0),
        out_of_bounds_count=out_of_bounds_count,
    )


def _line_candidate_specs(
    *,
    font_size: int,
    preferred_positions: list[str] | None = None,
    allow_leader_lines: bool = True,
) -> list[tuple[float, float, str, str, bool]]:
    close_gap = max(12.0, float(font_size) * 0.9)
    far_gap = close_gap * 1.85
    very_far_gap = close_gap * 2.6
    position_map = {
        "top": (0.0, close_gap, "center", "bottom", False),
        "bottom": (0.0, -close_gap, "center", "top", False),
        "right": (close_gap, 0.0, "left", "center", False),
        "left": (-close_gap, 0.0, "right", "center", False),
        "top-right": (close_gap, close_gap, "left", "bottom", False),
        "top-left": (-close_gap, close_gap, "right", "bottom", False),
        "bottom-right": (close_gap, -close_gap, "left", "top", False),
        "bottom-left": (-close_gap, -close_gap, "right", "top", False),
        "far-top-right": (far_gap, far_gap, "left", "bottom", allow_leader_lines),
        "far-top-left": (-far_gap, far_gap, "right", "bottom", allow_leader_lines),
        "far-bottom-right": (far_gap, -far_gap, "left", "top", allow_leader_lines),
        "far-bottom-left": (-far_gap, -far_gap, "right", "top", allow_leader_lines),
        "far-right": (far_gap, 0.0, "left", "center", allow_leader_lines),
        "far-left": (-far_gap, 0.0, "right", "center", allow_leader_lines),
        "very-far-top-right": (very_far_gap, very_far_gap, "left", "bottom", allow_leader_lines),
        "very-far-top-left": (-very_far_gap, very_far_gap, "right", "bottom", allow_leader_lines),
        "very-far-bottom-right": (very_far_gap, -very_far_gap, "left", "top", allow_leader_lines),
        "very-far-bottom-left": (-very_far_gap, -very_far_gap, "right", "top", allow_leader_lines),
        "very-far-right": (very_far_gap, 0.0, "left", "center", allow_leader_lines),
        "very-far-left": (-very_far_gap, 0.0, "right", "center", allow_leader_lines),
    }
    order = preferred_positions or [
        "top",
        "bottom",
        "top-right",
        "top-left",
        "right",
        "left",
        "bottom-right",
        "bottom-left",
        "far-top-right",
        "far-top-left",
        "far-right",
        "far-left",
        "far-bottom-right",
        "far-bottom-left",
        "very-far-top-right",
        "very-far-top-left",
        "very-far-right",
        "very-far-left",
        "very-far-bottom-right",
        "very-far-bottom-left",
    ]
    return [position_map[name] for name in order if name in position_map]


def place_line_annotations(
    ax: Any,
    annotation_items: list[dict[str, Any]],
    *,
    label_fontsize: int,
    allow_leader_lines: bool = True,
) -> LayoutPlacementResult:
    fig = ax.figure
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    axes_bbox = ax.get_window_extent(renderer=renderer)
    placed_bboxes: list[Any] = []
    text_artists: list[Any] = []
    sorted_items = sorted(
        annotation_items,
        key=lambda item: (
            0 if item.get("priority") else 1,
            -abs(float(item.get("y") or 0.0)),
            float(item.get("x") or 0.0),
        ),
    )

    for item in sorted_items:
        label_text = str(item.get("text") or "").strip()
        if not label_text:
            continue
        x_value = float(item.get("x") or 0.0)
        y_value = float(item.get("y") or 0.0)
        color = str(item.get("color") or "#111827")
        preferred_positions = item.get("preferred_positions")
        candidates = _line_candidate_specs(
            font_size=label_fontsize,
            preferred_positions=list(preferred_positions) if isinstance(preferred_positions, list) else None,
            allow_leader_lines=allow_leader_lines,
        )
        placed = False
        for x_offset, y_offset, horizontal_align, vertical_align, with_leader in candidates:
            annotation = ax.annotate(
                label_text,
                (x_value, y_value),
                xytext=(x_offset, y_offset),
                textcoords="offset points",
                ha=horizontal_align,
                va=vertical_align,
                fontsize=label_fontsize,
                color=color,
                bbox={"boxstyle": "round,pad=0.18", "facecolor": "white", "edgecolor": "none", "alpha": 0.86},
                arrowprops=(
                    {"arrowstyle": "-", "color": color, "linewidth": 0.7, "alpha": 0.7}
                    if with_leader
                    else None
                ),
                annotation_clip=True,
            )
            bbox = annotation.get_window_extent(renderer=renderer)
            if bbox_within(bbox, axes_bbox, padding_px=2.0) and not any(
                bboxes_overlap(bbox, existing, padding_px=2.0) for existing in placed_bboxes
            ):
                placed_bboxes.append(bbox)
                text_artists.append(annotation)
                placed = True
                break
            annotation.remove()
        if not placed:
            for text_artist in text_artists:
                text_artist.remove()
            return LayoutPlacementResult(success=False, text_artists=tuple())

    final_bboxes = [text.get_window_extent(renderer=renderer) for text in text_artists]
    out_of_bounds_count = sum(0 if bbox_within(bbox, axes_bbox, padding_px=2.0) else 1 for bbox in final_bboxes)
    return LayoutPlacementResult(
        success=out_of_bounds_count == 0 and count_bbox_overlaps(final_bboxes, padding_px=2.0) == 0,
        text_artists=tuple(text_artists),
        overlap_count=count_bbox_overlaps(final_bboxes, padding_px=2.0),
        out_of_bounds_count=out_of_bounds_count,
    )


def place_horizontal_bar_labels(
    ax: Any,
    label_items: list[dict[str, Any]],
    *,
    label_fontsize: int,
    lane_gap_pts: float = 8.0,
    value_pad_pts: float = 7.0,
    max_lanes: int = 10,
) -> LayoutPlacementResult:
    fig = ax.figure
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    axes_bbox = ax.get_window_extent(renderer=renderer)
    placed_bboxes: list[Any] = []
    text_artists: list[Any] = []
    sorted_items = sorted(
        label_items,
        key=lambda item: (-abs(float(item.get("value") or 0.0)), float(item.get("y") or 0.0)),
    )

    for item in sorted_items:
        label_text = str(item.get("text") or "").strip()
        if not label_text:
            continue
        value = float(item.get("value") or 0.0)
        x_value = float(item.get("x") if item.get("x") is not None else value)
        y_value = float(item.get("y") or 0.0)
        sign = 1.0 if value >= 0.0 else -1.0
        horizontal_align = "left" if sign > 0 else "right"
        placed = False
        for lane_index in range(max_lanes):
            lane_offset_pts = value_pad_pts + (lane_index * ((label_fontsize * 0.85) + lane_gap_pts))
            x_delta, _ = data_delta_from_points(
                ax,
                x_points=lane_offset_pts * sign,
                anchor=(x_value, y_value),
            )
            text_artist = ax.text(
                x_value + x_delta,
                y_value,
                label_text,
                ha=horizontal_align,
                va="center",
                fontsize=label_fontsize,
                color="#0f172a",
                clip_on=True,
                bbox={"boxstyle": "round,pad=0.16", "facecolor": "white", "edgecolor": "none", "alpha": 0.86},
            )
            bbox = text_artist.get_window_extent(renderer=renderer)
            if bbox_within(bbox, axes_bbox, padding_px=2.0) and not any(
                bboxes_overlap(bbox, existing, padding_px=2.0) for existing in placed_bboxes
            ):
                placed_bboxes.append(bbox)
                text_artists.append(text_artist)
                placed = True
                break
            text_artist.remove()
        if not placed:
            for text_artist in text_artists:
                text_artist.remove()
            return LayoutPlacementResult(success=False, text_artists=tuple())

    final_bboxes = [text.get_window_extent(renderer=renderer) for text in text_artists]
    out_of_bounds_count = sum(0 if bbox_within(bbox, axes_bbox, padding_px=2.0) else 1 for bbox in final_bboxes)
    return LayoutPlacementResult(
        success=out_of_bounds_count == 0 and count_bbox_overlaps(final_bboxes, padding_px=2.0) == 0,
        text_artists=tuple(text_artists),
        overlap_count=count_bbox_overlaps(final_bboxes, padding_px=2.0),
        out_of_bounds_count=out_of_bounds_count,
    )
