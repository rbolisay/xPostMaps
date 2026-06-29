"""Data helpers for 4D Stat time-series plots."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from xpostmaps.core.models import LineStyle
from xpostmaps.core.postplot_4d_diff import Postplot4DDiffRow, feather_diff_deg
from xpostmaps.core.postplot_4d_matching import Postplot4DMatchRow

PlotKind = Literal["crossline", "inline", "radial", "feather", "feather_diff"]

PLOT_KIND_LABELS: dict[PlotKind, str] = {
    "crossline": "Crossline",
    "inline": "Inline",
    "radial": "Radial",
    "feather": "Feather",
    "feather_diff": "Feather Diff",
}

PLOT_KIND_PDF_LABELS: dict[PlotKind, str] = {
    "crossline": "Cross-line",
    "inline": "In-line",
    "radial": "Radial",
    "feather": "Feather",
    "feather_diff": "Feather Diff",
}

PLOT_KIND_UNITS: dict[PlotKind, str] = {
    "crossline": "meter",
    "inline": "meter",
    "radial": "meter",
    "feather": "degree",
    "feather_diff": "degree",
}

DEFAULT_SOURCE_COLORS: tuple[str, ...] = (
    "#22c55e",
    "#3b82f6",
    "#f97316",
    "#a855f7",
    "#ef4444",
    "#14b8a6",
    "#eab308",
    "#ec4899",
)

DEFAULT_BOUNDARY_COLOR = "#3b82f6"


@dataclass
class SourceStyleRow:
    source_no: str
    line_style: LineStyle = LineStyle.SOLID
    color: str = "#22c55e"
    opacity: float = 1.0
    line_width_mm: float = 0.35
    dot_radius_mm: float = 0.8
    dash_length_mm: float = 3.0


@dataclass
class BoundaryRow:
    """A pass/fail boundary limit drawn on the plot.

    ``limit_value`` is measured relative to ``reference_value`` (the baseline,
    default 0). With ``absolute`` off the limit draws a single line at
    ``reference + limit``. With ``absolute`` on the limit is mirrored on either
    side of the reference, drawing two lines at ``reference ± |limit|``.
    """

    limit_value: float = 3.0
    reference_value: float = 0.0
    absolute: bool = False
    line_style: LineStyle = LineStyle.DASH
    color: str = DEFAULT_BOUNDARY_COLOR
    opacity: float = 1.0
    line_width_mm: float = 0.35
    dot_radius_mm: float = 0.8
    dash_length_mm: float = 3.0


def boundary_line_values(row: BoundaryRow) -> list[float]:
    """Return the Y position(s) at which a boundary limit is drawn.

    - Absolute off: one line at ``reference + limit``.
    - Absolute on: two lines at ``reference ± |limit|`` (one each side).
    """
    reference = float(row.reference_value)
    limit = float(row.limit_value)
    if row.absolute:
        magnitude = abs(limit)
        candidates = [reference + magnitude, reference - magnitude]
    else:
        candidates = [reference + limit]
    values: list[float] = []
    for value in candidates:
        if value not in values:
            values.append(value)
    return values


@dataclass
class SeriesStats:
    attribute: str
    minimum: float
    maximum: float
    mean: float
    std_dev: float
    rms: float


@dataclass
class PlotSeries:
    source_no: str
    shotpoints: list[int] = field(default_factory=list)
    values: list[float] = field(default_factory=list)


def normalize_source_label(firing_source_id: str, *, fallback_index: int = 0) -> str:
    """Return G-prefixed source label (G01, G02, …) for table and legend."""
    text = (firing_source_id or "").strip()
    match = re.search(r"\d+", text)
    if match:
        try:
            index = int(match.group(0))
            if index > 0:
                return f"G{index:02d}"
        except ValueError:
            pass
    if fallback_index > 0:
        return f"G{fallback_index:02d}"
    return "G01"


def unique_sources_from_diff_rows(rows: list[Postplot4DDiffRow]) -> list[str]:
    seen: dict[str, None] = {}
    fallback = 0
    for diff_row in rows:
        fallback += 1
        label = normalize_source_label(diff_row.firing_source_id, fallback_index=fallback)
        if label not in seen:
            seen[label] = None
    return list(seen.keys())


def _line_direction_label(match_row: Postplot4DMatchRow) -> str:
    direction = (match_row.line_direction or "").strip().lower()
    if "down" in direction:
        return "Down-line"
    if "up" in direction:
        return "Up-line"
    if match_row.first_sp and match_row.last_sp:
        if match_row.first_sp <= match_row.last_sp:
            return "Up-line"
        return "Down-line"
    return "Up-line"


def shotpoint_order(
    diff_rows: list[Postplot4DDiffRow],
    match_row: Postplot4DMatchRow,
) -> list[int]:
    """Order shotpoints left-to-right from FSP toward LSP."""
    shotpoints = sorted({row.shotpoint for row in diff_rows if row.shotpoint > 0})
    if not shotpoints:
        return []
    fsp = match_row.first_sp
    lsp = match_row.last_sp
    if fsp and lsp:
        if fsp <= lsp:
            return sorted(shotpoints)
        return sorted(shotpoints, reverse=True)
    if len(shotpoints) >= 2 and shotpoints[0] > shotpoints[-1]:
        return sorted(shotpoints, reverse=True)
    return sorted(shotpoints)


def _value_for_kind(diff_row: Postplot4DDiffRow, kind: PlotKind) -> float | None:
    if kind == "crossline":
        return diff_row.crossline_m
    if kind == "inline":
        return diff_row.inline_m
    if kind == "radial":
        return diff_row.radial_m
    if kind == "feather":
        return diff_row.line_feather_deg
    if kind == "feather_diff":
        return feather_diff_deg(
            line_feather_deg=diff_row.line_feather_deg,
            navplan_feather_deg=diff_row.navplan_feather_deg,
        )
    return None


def build_plot_series(
    diff_rows: list[Postplot4DDiffRow],
    match_row: Postplot4DMatchRow,
    kind: PlotKind,
    source_no: str,
) -> PlotSeries:
    order = shotpoint_order(diff_rows, match_row)
    by_shot: dict[int, float] = {}
    fallback = 0
    for diff_row in diff_rows:
        fallback += 1
        label = normalize_source_label(diff_row.firing_source_id, fallback_index=fallback)
        if label != source_no:
            continue
        value = _value_for_kind(diff_row, kind)
        if value is None:
            continue
        by_shot[diff_row.shotpoint] = float(value)
    shotpoints: list[int] = []
    values: list[float] = []
    for shotpoint in order:
        if shotpoint in by_shot:
            shotpoints.append(shotpoint)
            values.append(by_shot[shotpoint])
    return PlotSeries(source_no=source_no, shotpoints=shotpoints, values=values)


def compute_series_stats(source_no: str, values: list[float]) -> SeriesStats | None:
    if not values:
        return None
    arr = np.asarray(values, dtype=np.float64)
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=0))
    rms = float(math.sqrt(float(np.mean(arr * arr))))
    return SeriesStats(
        attribute=source_no,
        minimum=float(np.min(arr)),
        maximum=float(np.max(arr)),
        mean=mean,
        std_dev=std,
        rms=rms,
    )


def default_source_styles(sources: list[str]) -> list[SourceStyleRow]:
    rows: list[SourceStyleRow] = []
    for index, source_no in enumerate(sources):
        color = DEFAULT_SOURCE_COLORS[index % len(DEFAULT_SOURCE_COLORS)]
        rows.append(SourceStyleRow(source_no=source_no, color=color))
    return rows


def feather_tab_available(
    diff_rows: list[Postplot4DDiffRow],
    *,
    streamers_detected: bool,
) -> bool:
    if streamers_detected:
        return True
    return any(row.line_feather_deg is not None for row in diff_rows)


def feather_diff_tab_available(
    match_row: Postplot4DMatchRow | None,
    *,
    streamers_detected: bool,
) -> bool:
    """Feather Diff requires navplan baseline and detected streamers."""
    return (
        match_row is not None
        and match_row.baseline_kind == "navplan"
        and streamers_detected
    )


def line_title(match_row: Postplot4DMatchRow) -> str:
    if match_row.subline:
        return f"{match_row.line_name}.{match_row.subline}"
    return match_row.line_name or match_row.baseline_name


def time_series_title(
    match_row: Postplot4DMatchRow,
    *,
    vessel_id: str,
    source_no: str,
    kind: PlotKind,
) -> str:
    baseline = match_row.baseline_name or match_row.line_name
    direction = _line_direction_label(match_row)
    stat_label = PLOT_KIND_PDF_LABELS[kind]
    vessel = vessel_id.strip() or "Monitor"
    seq = match_row.sequence_no.strip()
    line = line_title(match_row)
    parts = [vessel]
    if baseline:
        parts.append(baseline)
    if seq:
        parts.append(seq)
    parts.append(line)
    parts.append(source_no)
    parts.append(f"Position {stat_label} vs. Baseline ({direction})")
    return " ".join(part for part in parts if part)


def pdf_page_key(
    kind: PlotKind,
    source_no: str | None,
    *,
    combine: bool,
) -> str:
    if combine or not source_no:
        return kind
    return f"{kind}:{source_no}"


def default_pdf_time_series_description(
    match_row: Postplot4DMatchRow,
    *,
    source_nos: list[str],
    kind: PlotKind,
) -> str:
    direction = _line_direction_label(match_row)
    stat_label = PLOT_KIND_PDF_LABELS[kind]
    sources = ", ".join(source_nos)
    return f"{sources} Position {stat_label} vs. Baseline ({direction})"


def primary_vessel_id(diff_rows: list[Postplot4DDiffRow]) -> str:
    for diff_row in diff_rows:
        if diff_row.vessel_id.strip():
            return diff_row.vessel_id.strip()
    return ""
