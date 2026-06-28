"""Tests for persisted 4D Stat plot style settings."""

from xpostmaps.core.models import LineStyle
from xpostmaps.core.postplot_4d_plot_data import SourceStyleRow
from xpostmaps.core.postplot_4d_plot_settings import (
    boundary_row_from_dict,
    boundary_row_to_dict,
    load_saved_kind_settings,
    resolve_boundaries_for_kind,
    resolve_source_styles_for_line,
    save_kind_settings,
    source_style_row_from_dict,
    source_style_row_to_dict,
)


def test_source_style_round_trip() -> None:
    row = SourceStyleRow(
        source_no="G01",
        line_style=LineStyle.DASH,
        color="#ff0000",
        opacity=0.5,
        line_width_mm=0.5,
    )
    restored = source_style_row_from_dict(source_style_row_to_dict(row))
    assert restored.source_no == "G01"
    assert restored.line_style == LineStyle.DASH
    assert restored.color == "#ff0000"
    assert restored.opacity == 0.5
    assert restored.line_width_mm == 0.5


def test_resolve_source_styles_uses_saved_by_label(
    tmp_path, monkeypatch
) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(
        "xpostmaps.core.postplot_4d_plot_settings._SETTINGS_PATH",
        settings_path,
    )
    save_kind_settings(
        "crossline",
        [
            SourceStyleRow(source_no="G01", color="#111111"),
            SourceStyleRow(source_no="G02", color="#222222"),
        ],
        [],
    )
    styles = resolve_source_styles_for_line(["G01", "G03"], "crossline")
    assert styles[0].color == "#111111"
    assert styles[0].source_no == "G01"
    assert styles[1].source_no == "G03"
    assert styles[1].color != "#111111"


def test_resolve_boundaries_falls_back_to_defaults(
    tmp_path, monkeypatch
) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(
        "xpostmaps.core.postplot_4d_plot_settings._SETTINGS_PATH",
        settings_path,
    )
    boundaries = resolve_boundaries_for_kind("inline")
    assert len(boundaries) == 2
    assert boundaries[0].abs_boundary == 6.0
    assert boundaries[1].abs_boundary == 9.0


def test_save_and_load_kind_settings(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(
        "xpostmaps.core.postplot_4d_plot_settings._SETTINGS_PATH",
        settings_path,
    )
    save_kind_settings(
        "radial",
        [SourceStyleRow(source_no="G01", color="#abcdef")],
        [boundary_row_from_dict({"abs_boundary": 12.0, "color": "#00ff00"})],
    )
    loaded = load_saved_kind_settings("radial")
    assert loaded is not None
    sources, boundaries = loaded
    assert len(sources) == 1
    assert sources[0].color == "#abcdef"
    assert len(boundaries) == 1
    assert boundaries[0].abs_boundary == 12.0
    assert boundary_row_to_dict(boundaries[0])["color"] == "#00ff00"
