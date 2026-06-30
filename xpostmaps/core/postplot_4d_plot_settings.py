"""Persist 4D Stat plot source/boundary styles across lines and sessions."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from xpostmaps.core.models import LineStyle
from xpostmaps.core.postplot_4d_matching import Postplot4DMatchRow
from xpostmaps.core.postplot_4d_plot_data import (
    BoundaryRow,
    PlotKind,
    SourceStyleRow,
    default_source_styles,
    is_flag_reserved_source_color,
    should_exclude_flag_colors_from_sources,
)
from xpostmaps.core.postplot_4d_survey_spec import (
    Severity,
    SurveySpecRow,
    metric_kind_from_str,
    severity_from_str,
    stat_type_from_str,
)

_SETTINGS_PATH = Path(__file__).resolve().parents[2] / "data" / "settings.json"
_SETTINGS_KEY = "postplot_4d_plot_kinds"
_PLOT_BY_LINE_KEY = "postplot_4d_plot_by_line"
_VIEW_SETTINGS_KEY = "postplot_4d_plot_view"
_SURVEY_SPECS_KEY = "postplot_4d_survey_specs"
_EXCLUDED_SHOTPOINTS_KEY = "postplot_4d_excluded_shotpoints"


@dataclass(frozen=True)
class PlotViewSettings:
    auto_y: bool = True
    y_min: float = -10.0
    y_max: float = 10.0
    combine_sources: bool = True

DEFAULT_BOUNDARY_ROWS = [
    BoundaryRow(limit_value=6.0, absolute=True),
    BoundaryRow(limit_value=9.0, absolute=True),
]

_ALL_KINDS: tuple[PlotKind, ...] = (
    "crossline",
    "inline",
    "radial",
    "feather",
    "feather_diff",
)


def _read_settings() -> dict:
    if not _SETTINGS_PATH.is_file():
        return {}
    try:
        return json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_settings(data: dict) -> None:
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def plot_settings_key(match_row: Postplot4DMatchRow) -> str:
    """Stable key for plot-specific Source Style / Boundary / Y-axis settings."""
    subline = (match_row.subline or "").strip()
    baseline = (match_row.baseline_name or "").strip()
    line = (match_row.line_name or "").strip()
    return f"{match_row.baseline_kind}|{baseline}|{line}|{subline}"


def _plot_blob(plot_key: str) -> dict:
    root = _read_settings().get(_PLOT_BY_LINE_KEY)
    if not isinstance(root, dict):
        return {}
    blob = root.get(plot_key)
    return blob if isinstance(blob, dict) else {}


def _write_plot_blob(plot_key: str, blob: dict) -> None:
    data = _read_settings()
    root = data.get(_PLOT_BY_LINE_KEY)
    if not isinstance(root, dict):
        root = {}
    root[plot_key] = blob
    data[_PLOT_BY_LINE_KEY] = root
    _write_settings(data)


def _line_style_to_str(style: LineStyle) -> str:
    return style.value if hasattr(style, "value") else str(style)


def _line_style_from_str(text: str) -> LineStyle:
    normalized = (text or "").strip().lower()
    for style in LineStyle:
        if style.value.lower() == normalized or style.name.lower() == normalized:
            return style
    return LineStyle.SOLID


def source_style_row_to_dict(row: SourceStyleRow) -> dict:
    return {
        "source_no": row.source_no,
        "line_style": _line_style_to_str(row.line_style),
        "color": row.color,
        "opacity": row.opacity,
        "line_width_mm": row.line_width_mm,
        "dot_radius_mm": row.dot_radius_mm,
        "dash_length_mm": row.dash_length_mm,
    }


def source_style_row_from_dict(data: dict) -> SourceStyleRow:
    return SourceStyleRow(
        source_no=str(data.get("source_no", "")),
        line_style=_line_style_from_str(str(data.get("line_style", "solid"))),
        color=str(data.get("color", "#22c55e")),
        opacity=float(data.get("opacity", 1.0)),
        line_width_mm=float(data.get("line_width_mm", 0.35)),
        dot_radius_mm=float(data.get("dot_radius_mm", 0.8)),
        dash_length_mm=float(data.get("dash_length_mm", 3.0)),
    )


def boundary_row_to_dict(row: BoundaryRow) -> dict:
    return {
        "limit_value": row.limit_value,
        "reference_value": row.reference_value,
        "absolute": row.absolute,
        "line_style": _line_style_to_str(row.line_style),
        "color": row.color,
        "opacity": row.opacity,
        "line_width_mm": row.line_width_mm,
        "dot_radius_mm": row.dot_radius_mm,
        "dash_length_mm": row.dash_length_mm,
    }


def boundary_row_from_dict(data: dict) -> BoundaryRow:
    if "limit_value" in data or "reference_value" in data or "absolute" in data:
        limit_value = float(data.get("limit_value", 0.0))
        reference_value = float(data.get("reference_value", 0.0))
        absolute = bool(data.get("absolute", False))
    else:
        # Legacy projects stored a single ``abs_boundary`` that always drew a
        # symmetric pair around zero — preserve that as an absolute limit.
        limit_value = float(data.get("abs_boundary", 0.0))
        reference_value = 0.0
        absolute = True
    return BoundaryRow(
        limit_value=limit_value,
        reference_value=reference_value,
        absolute=absolute,
        line_style=_line_style_from_str(str(data.get("line_style", "dash"))),
        color=str(data.get("color", "#3b82f6")),
        opacity=float(data.get("opacity", 1.0)),
        line_width_mm=float(data.get("line_width_mm", 0.35)),
        dot_radius_mm=float(data.get("dot_radius_mm", 0.8)),
        dash_length_mm=float(data.get("dash_length_mm", 3.0)),
    )


def _kind_blob_to_rows(blob: dict) -> tuple[list[SourceStyleRow], list[BoundaryRow]]:
    source_rows = [
        source_style_row_from_dict(item)
        for item in blob.get("sources", [])
        if isinstance(item, dict)
    ]
    boundary_rows = [
        boundary_row_from_dict(item)
        for item in blob.get("boundaries", [])
        if isinstance(item, dict)
    ]
    return source_rows, boundary_rows


def load_saved_kind_settings(
    kind: PlotKind,
) -> tuple[list[SourceStyleRow], list[BoundaryRow]] | None:
    root = _read_settings().get(_SETTINGS_KEY, {})
    if not isinstance(root, dict):
        return None
    blob = root.get(kind)
    if not isinstance(blob, dict):
        return None
    source_rows, boundary_rows = _kind_blob_to_rows(blob)
    if not source_rows and not boundary_rows:
        return None
    return source_rows, boundary_rows


def save_kind_settings(
    kind: PlotKind,
    source_styles: list[SourceStyleRow],
    boundaries: list[BoundaryRow],
) -> None:
    """Persist global (legacy) kind settings — used as fallback when no plot key."""
    data = _read_settings()
    root = data.get(_SETTINGS_KEY)
    if not isinstance(root, dict):
        root = {}
    root[kind] = {
        "sources": [source_style_row_to_dict(row) for row in source_styles],
        "boundaries": [boundary_row_to_dict(row) for row in boundaries],
    }
    data[_SETTINGS_KEY] = root
    _write_settings(data)


def load_saved_plot_kind_settings(
    plot_key: str,
    kind: PlotKind,
) -> tuple[list[SourceStyleRow], list[BoundaryRow]] | None:
    """Load kind settings saved for one 4D Stat plot line."""
    kinds = _plot_blob(plot_key).get("kinds")
    if not isinstance(kinds, dict):
        return None
    blob = kinds.get(kind)
    if not isinstance(blob, dict):
        return None
    source_rows, boundary_rows = _kind_blob_to_rows(blob)
    if not source_rows and not boundary_rows:
        return None
    return source_rows, boundary_rows


def save_plot_kind_settings(
    plot_key: str,
    kind: PlotKind,
    source_styles: list[SourceStyleRow],
    boundaries: list[BoundaryRow],
) -> None:
    """Persist kind settings for one 4D Stat plot line."""
    blob = dict(_plot_blob(plot_key))
    kinds = blob.get("kinds")
    if not isinstance(kinds, dict):
        kinds = {}
    kinds[kind] = {
        "sources": [source_style_row_to_dict(row) for row in source_styles],
        "boundaries": [boundary_row_to_dict(row) for row in boundaries],
    }
    blob["kinds"] = kinds
    _write_plot_blob(plot_key, blob)


def _resolve_source_style_row(
    source_no: str,
    template: SourceStyleRow | None,
    default_row: SourceStyleRow,
    *,
    exclude_flag_colors: bool,
) -> SourceStyleRow:
    if template is None:
        return default_row
    color = template.color
    if exclude_flag_colors and is_flag_reserved_source_color(color):
        color = default_row.color
    return replace(template, source_no=source_no, color=color)


def resolve_source_styles_for_line(
    source_nos: list[str],
    kind: PlotKind,
) -> list[SourceStyleRow]:
    """Apply saved global styles by source label (G01, G02, …)."""
    exclude = should_exclude_flag_colors_from_sources(source_nos)
    defaults = default_source_styles(source_nos)
    default_by_no = {row.source_no: row for row in defaults}
    saved = load_saved_kind_settings(kind)
    if saved is None:
        return defaults
    saved_sources, _ = saved
    saved_by_no = {row.source_no: row for row in saved_sources}
    resolved: list[SourceStyleRow] = []
    for source_no in source_nos:
        resolved.append(
            _resolve_source_style_row(
                source_no,
                saved_by_no.get(source_no),
                default_by_no[source_no],
                exclude_flag_colors=exclude,
            )
        )
    return resolved


def resolve_source_styles_for_plot(
    plot_key: str,
    source_nos: list[str],
    kind: PlotKind,
) -> list[SourceStyleRow]:
    """Plot-specific source styles, falling back to global saved styles."""
    exclude = should_exclude_flag_colors_from_sources(source_nos)
    defaults = default_source_styles(source_nos)
    default_by_no = {row.source_no: row for row in defaults}
    saved = load_saved_plot_kind_settings(plot_key, kind)
    if saved is None:
        return resolve_source_styles_for_line(source_nos, kind)
    saved_sources, _ = saved
    saved_by_no = {row.source_no: row for row in saved_sources}
    resolved: list[SourceStyleRow] = []
    for source_no in source_nos:
        resolved.append(
            _resolve_source_style_row(
                source_no,
                saved_by_no.get(source_no),
                default_by_no[source_no],
                exclude_flag_colors=exclude,
            )
        )
    return resolved


def resolve_boundaries_for_kind(kind: PlotKind) -> list[BoundaryRow]:
    saved = load_saved_kind_settings(kind)
    if saved is None:
        return [BoundaryRow(**asdict(row)) for row in DEFAULT_BOUNDARY_ROWS]
    _, boundaries = saved
    if not boundaries:
        return [BoundaryRow(**asdict(row)) for row in DEFAULT_BOUNDARY_ROWS]
    return [replace(row) for row in boundaries]


def resolve_boundaries_for_plot(plot_key: str, kind: PlotKind) -> list[BoundaryRow]:
    """Plot-specific boundary limits, falling back to global saved limits."""
    saved = load_saved_plot_kind_settings(plot_key, kind)
    if saved is None:
        return resolve_boundaries_for_kind(kind)
    _, boundaries = saved
    if not boundaries:
        return resolve_boundaries_for_kind(kind)
    return [replace(row) for row in boundaries]


def apply_saved_settings_to_kinds(
    source_nos: list[str],
    kinds: tuple[PlotKind, ...] = _ALL_KINDS,
) -> dict[PlotKind, tuple[list[SourceStyleRow], list[BoundaryRow]]]:
    return {
        kind: (
            resolve_source_styles_for_line(source_nos, kind),
            resolve_boundaries_for_kind(kind),
        )
        for kind in kinds
    }


def load_plot_view_settings() -> PlotViewSettings:
    """Load shared global 4D Stat plot view options (legacy fallback)."""
    root = _read_settings().get(_VIEW_SETTINGS_KEY)
    if not isinstance(root, dict):
        return PlotViewSettings()
    return PlotViewSettings(
        auto_y=bool(root.get("auto_y", True)),
        y_min=float(root.get("y_min", -10.0)),
        y_max=float(root.get("y_max", 10.0)),
        combine_sources=bool(root.get("combine_sources", True)),
    )


def load_plot_view_settings_for_plot(plot_key: str) -> PlotViewSettings:
    """Load Y-axis / combine settings for one 4D Stat plot line."""
    view = _plot_blob(plot_key).get("view")
    if isinstance(view, dict):
        return PlotViewSettings(
            auto_y=bool(view.get("auto_y", True)),
            y_min=float(view.get("y_min", -10.0)),
            y_max=float(view.get("y_max", 10.0)),
            combine_sources=bool(view.get("combine_sources", True)),
        )
    return load_plot_view_settings()


def save_plot_view_settings(settings: PlotViewSettings) -> None:
    """Persist shared global plot view options (legacy)."""
    data = _read_settings()
    data[_VIEW_SETTINGS_KEY] = {
        "auto_y": settings.auto_y,
        "y_min": settings.y_min,
        "y_max": settings.y_max,
        "combine_sources": settings.combine_sources,
    }
    _write_settings(data)


def save_plot_view_settings_for_plot(plot_key: str, settings: PlotViewSettings) -> None:
    """Persist Y-axis / combine settings for one 4D Stat plot line."""
    blob = dict(_plot_blob(plot_key))
    blob["view"] = {
        "auto_y": settings.auto_y,
        "y_min": settings.y_min,
        "y_max": settings.y_max,
        "combine_sources": settings.combine_sources,
    }
    _write_plot_blob(plot_key, blob)


def survey_spec_row_to_dict(row: SurveySpecRow) -> dict:
    statistic = row.statistic.value if hasattr(row.statistic, "value") else str(row.statistic)
    severity = row.severity.value if hasattr(row.severity, "value") else str(row.severity)
    return {
        "metric": row.metric,
        "statistic": statistic,
        "reference_value": row.reference_value,
        "stat_value": row.stat_value,
        "absolute": row.absolute,
        "severity": severity,
    }


def survey_spec_row_from_dict(data: dict) -> SurveySpecRow:
    return SurveySpecRow(
        metric=metric_kind_from_str(str(data.get("metric", "crossline"))),
        statistic=stat_type_from_str(str(data.get("statistic", "max_value"))),
        reference_value=float(data.get("reference_value", 0.0)),
        stat_value=float(data.get("stat_value", 0.0)),
        absolute=bool(data.get("absolute", True)),
        severity=severity_from_str(str(data.get("severity", Severity.ERROR.value))),
    )


def load_survey_specs() -> list[SurveySpecRow]:
    """Load the saved survey spec rows (empty list when none saved)."""
    root = _read_settings().get(_SURVEY_SPECS_KEY)
    if not isinstance(root, list):
        return []
    return [
        survey_spec_row_from_dict(item)
        for item in root
        if isinstance(item, dict)
    ]


def save_survey_specs(rows: list[SurveySpecRow]) -> None:
    """Persist the survey spec rows shared across all lines/sequences."""
    data = _read_settings()
    data[_SURVEY_SPECS_KEY] = [survey_spec_row_to_dict(row) for row in rows]
    _write_settings(data)


def load_excluded_shotpoints(plot_key: str | None = None) -> dict[str, str]:
    """Load saved excluded-shotpoint text keyed by sequence number.

    When *plot_key* is supplied, exclusions are read from that line's plot
    settings first; a legacy global map is used only as a fallback.
    """
    if plot_key:
        blob = _plot_blob(plot_key)
        scoped = blob.get("excluded_by_sequence")
        if isinstance(scoped, dict) and scoped:
            return {
                str(key): str(value)
                for key, value in scoped.items()
                if str(key).strip()
            }
    root = _read_settings().get(_EXCLUDED_SHOTPOINTS_KEY)
    if not isinstance(root, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in root.items()
        if str(key).strip()
    }


def save_excluded_shotpoints(
    mapping: dict[str, str],
    plot_key: str | None = None,
) -> None:
    """Persist excluded-shotpoint text keyed by sequence number.

    When *plot_key* is supplied, exclusions are stored on that line's plot
    settings blob (preferred). The legacy global map is no longer updated.
    """
    cleaned = {
        str(key): str(value)
        for key, value in mapping.items()
        if str(key).strip()
    }
    if plot_key:
        blob = _plot_blob(plot_key)
        blob["excluded_by_sequence"] = cleaned
        _write_plot_blob(plot_key, blob)
        return
    data = _read_settings()
    data[_EXCLUDED_SHOTPOINTS_KEY] = cleaned
    _write_settings(data)
