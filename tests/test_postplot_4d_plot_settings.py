"""Tests for persisted 4D Stat plot style settings."""

from xpostmaps.core.models import LineStyle
from xpostmaps.core.postplot_4d_plot_data import SourceStyleRow, default_source_styles
from xpostmaps.core.postplot_4d_plot_settings import (
    PlotViewSettings,
    boundary_row_from_dict,
    boundary_row_to_dict,
    load_plot_view_settings,
    load_saved_kind_settings,
    resolve_boundaries_for_kind,
    resolve_source_styles_for_line,
    save_kind_settings,
    save_plot_view_settings,
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
    assert boundaries[0].limit_value == 6.0
    assert boundaries[0].absolute is True
    assert boundaries[1].limit_value == 9.0
    assert boundaries[1].absolute is True


def test_save_and_load_kind_settings(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(
        "xpostmaps.core.postplot_4d_plot_settings._SETTINGS_PATH",
        settings_path,
    )
    save_kind_settings(
        "radial",
        [SourceStyleRow(source_no="G01", color="#abcdef")],
        [
            boundary_row_from_dict(
                {
                    "limit_value": 12.0,
                    "reference_value": 2.0,
                    "absolute": True,
                    "color": "#00ff00",
                }
            )
        ],
    )
    loaded = load_saved_kind_settings("radial")
    assert loaded is not None
    sources, boundaries = loaded
    assert len(sources) == 1
    assert sources[0].color == "#abcdef"
    assert len(boundaries) == 1
    assert boundaries[0].limit_value == 12.0
    assert boundaries[0].reference_value == 2.0
    assert boundaries[0].absolute is True
    assert boundary_row_to_dict(boundaries[0])["color"] == "#00ff00"


def test_boundary_row_from_dict_migrates_legacy_abs_boundary() -> None:
    row = boundary_row_from_dict({"abs_boundary": 7.0, "color": "#123456"})
    assert row.limit_value == 7.0
    assert row.reference_value == 0.0
    assert row.absolute is True
    assert row.color == "#123456"


def test_plot_view_settings_defaults_when_missing(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(
        "xpostmaps.core.postplot_4d_plot_settings._SETTINGS_PATH",
        settings_path,
    )
    loaded = load_plot_view_settings()
    assert loaded.auto_y is True
    assert loaded.y_min == -10.0
    assert loaded.y_max == 10.0
    assert loaded.combine_sources is True


def test_save_and_load_plot_view_settings(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(
        "xpostmaps.core.postplot_4d_plot_settings._SETTINGS_PATH",
        settings_path,
    )
    save_plot_view_settings(
        PlotViewSettings(
            auto_y=False,
            y_min=-3.5,
            y_max=7.25,
            combine_sources=False,
        )
    )
    loaded = load_plot_view_settings()
    assert loaded.auto_y is False
    assert loaded.y_min == -3.5
    assert loaded.y_max == 7.25
    assert loaded.combine_sources is False


def test_plot_specific_kind_settings(tmp_path, monkeypatch) -> None:
    from xpostmaps.core.postplot_4d_matching import Postplot4DMatchRow
    from xpostmaps.core.postplot_4d_plot_settings import (
        plot_settings_key,
        resolve_boundaries_for_plot,
        resolve_source_styles_for_plot,
        save_plot_kind_settings,
    )

    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(
        "xpostmaps.core.postplot_4d_plot_settings._SETTINGS_PATH",
        settings_path,
    )
    match = Postplot4DMatchRow(
        baseline_name="PreplotA",
        baseline_kind="preplot",
        line_name="Line1",
        subline="SL01",
        sequence_no="101",
        first_sp=1,
        last_sp=100,
        line_direction="up",
    )
    key = plot_settings_key(match)
    save_plot_kind_settings(
        key,
        "crossline",
        [SourceStyleRow(source_no="G01", color="#aabbcc")],
        [],
    )
    styles = resolve_source_styles_for_plot(key, ["G01"], "crossline")
    assert styles[0].color == "#aabbcc"
    boundaries = resolve_boundaries_for_plot(key, "inline")
    assert len(boundaries) == 2


def test_default_source_styles_avoid_flag_colors_when_combined() -> None:
    styles = default_source_styles(["G01", "G02", "G03"])
    reserved = {"#ff0000", "#ff8c00", "#ef4444", "#f97316"}
    for row in styles:
        assert row.color.lower() not in {color.lower() for color in reserved}


def test_default_source_styles_avoid_flag_colors_for_multi_sequence_keys() -> None:
    keys = ["G01 \u00b7 Seq 070", "G01 \u00b7 Seq 071", "G02 \u00b7 Seq 070"]
    styles = default_source_styles(keys)
    reserved = {"#ff0000", "#ff8c00", "#ef4444", "#f97316"}
    for row in styles:
        assert row.color.lower() not in {color.lower() for color in reserved}


def test_resolve_source_styles_remaps_saved_flag_colors_when_combined(
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
            SourceStyleRow(source_no="G02", color="#ef4444"),
            SourceStyleRow(source_no="G03", color="#f97316"),
        ],
        [],
    )
    styles = resolve_source_styles_for_line(["G01", "G02", "G03"], "crossline")
    assert styles[0].color == "#111111"
    assert styles[1].color == "#3b82f6"
    assert styles[2].color == "#a855f7"
