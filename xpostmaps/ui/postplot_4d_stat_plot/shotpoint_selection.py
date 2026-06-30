"""Shotpoint selection helpers for 4D Stat time-series plots."""

from __future__ import annotations

from xpostmaps.core.postplot_4d_survey_spec import (
    format_shotpoint_ranges,
    merge_excluded_shotpoints_text,
)

PickPoint = tuple[float, float, str]
SelectionKey = tuple[int, str]


def sequence_no_from_plot_source_key(source_no: str, default_sequence_no: str) -> str:
    """Resolve sequence number from a combined plot series label."""
    marker = " \u00b7 Seq "
    if marker in source_no:
        return source_no.split(marker, 1)[1].strip()
    return default_sequence_no


def normalize_view_rect(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
) -> tuple[float, float, float, float]:
    """Return (x_lo, x_hi, y_lo, y_hi) regardless of drag direction."""
    return min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)


def pick_points_in_rect(
    pick_points: list[PickPoint],
    x0: float,
    y0: float,
    x1: float,
    y1: float,
) -> list[SelectionKey]:
    """Return (shotpoint, source_no) keys for points inside a view-space rectangle."""
    x_lo, x_hi, y_lo, y_hi = normalize_view_rect(x0, y0, x1, y1)
    selected: list[SelectionKey] = []
    seen: set[SelectionKey] = set()
    for shotpoint, value, source_no in pick_points:
        if x_lo <= shotpoint <= x_hi and y_lo <= value <= y_hi:
            key = (int(round(shotpoint)), source_no)
            if key not in seen:
                seen.add(key)
                selected.append(key)
    return selected


def format_selection_overlay(keys: list[SelectionKey]) -> str:
    """Compact overlay label for the current multi-selection."""
    if not keys:
        return ""
    shotpoints = sorted({sp for sp, _source in keys})
    ranges = format_shotpoint_ranges(shotpoints)
    count = len(shotpoints)
    noun = "shotpoint" if count == 1 else "shotpoints"
    return f"Selected: {count} {noun} ({ranges})"


def group_selected_by_sequence(
    keys: list[SelectionKey],
    default_sequence_no: str,
) -> dict[str, set[int]]:
    """Group selected keys by sequence number for excluded-shotpoint updates."""
    grouped: dict[str, set[int]] = {}
    for shotpoint, source_no in keys:
        sequence_no = sequence_no_from_plot_source_key(source_no, default_sequence_no)
        if not sequence_no:
            continue
        grouped.setdefault(sequence_no, set()).add(shotpoint)
    return grouped
