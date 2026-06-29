"""Persist 4D Stat plot source/boundary styles across lines and sessions."""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path

from xpostmaps.core.models import LineStyle
from xpostmaps.core.postplot_4d_plot_data import (
    BoundaryRow,
    PlotKind,
    SourceStyleRow,
    default_source_styles,
)

_SETTINGS_PATH = Path(__file__).resolve().parents[2] / "data" / "settings.json"
_SETTINGS_KEY = "postplot_4d_plot_kinds"

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


def resolve_source_styles_for_line(
    source_nos: list[str],
    kind: PlotKind,
) -> list[SourceStyleRow]:
    """Apply saved styles by source label (G01, G02, …) for the current line."""
    defaults = default_source_styles(source_nos)
    default_by_no = {row.source_no: row for row in defaults}
    saved = load_saved_kind_settings(kind)
    if saved is None:
        return defaults
    saved_sources, _ = saved
    saved_by_no = {row.source_no: row for row in saved_sources}
    resolved: list[SourceStyleRow] = []
    for source_no in source_nos:
        template = saved_by_no.get(source_no)
        if template is None:
            resolved.append(default_by_no[source_no])
            continue
        resolved.append(replace(template, source_no=source_no))
    return resolved


def resolve_boundaries_for_kind(kind: PlotKind) -> list[BoundaryRow]:
    saved = load_saved_kind_settings(kind)
    if saved is None:
        return [BoundaryRow(**asdict(row)) for row in DEFAULT_BOUNDARY_ROWS]
    _, boundaries = saved
    if not boundaries:
        return [BoundaryRow(**asdict(row)) for row in DEFAULT_BOUNDARY_ROWS]
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
