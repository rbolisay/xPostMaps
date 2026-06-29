"""Tests for conditional postplot map rendering helpers."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from xpostmaps.core.models import LineStyle
from xpostmaps.ui.map_gl_resident_layer import ResidentGlLineLayer
from xpostmaps.ui.map_widget import PostplotMapWidget, _make_nav_pen


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _widget_with_lookup(
    points: list[tuple[float, float, str, float, float]],
) -> PostplotMapWidget:
    widget = PostplotMapWidget.__new__(PostplotMapWidget)
    widget._conditional_postplot_lookup = {}
    widget.set_conditional_postplot_points(points)
    return widget


def test_split_scatter_replaces_conditional_shotpoints(qapp) -> None:
    widget = _widget_with_lookup([(1.0, 2.0, "#ff0000", 1.0, 3.0)])
    xs = np.array([1.0, 5.0])
    ys = np.array([2.0, 6.0])

    default_xs, default_ys, conditional = widget._split_scatter_coords(xs, ys)

    assert default_xs.tolist() == [5.0]
    assert default_ys.tolist() == [6.0]
    assert len(conditional) == 1
    (_, _, radius) = next(iter(conditional))
    assert radius == 3.0


def test_split_polyline_recolors_conditional_run_with_parent_style(qapp) -> None:
    widget = _widget_with_lookup([(3.0, 30.0, "#00ff00", 1.0, 2.5)])
    xs = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    ys = np.array([10.0, 20.0, 30.0, 40.0, 50.0])

    default_parts, conditional = widget._split_polyline_by_color(xs, ys)

    # Default runs share boundary vertices so the line stays continuous.
    assert default_parts[0][0].tolist() == [1.0, 2.0, 3.0]
    assert default_parts[1][0].tolist() == [4.0, 5.0]

    # Conditional run is a connected polyline (not isolated dots) so it can be
    # drawn with the parent line style — only the color differs.
    assert len(conditional) == 1
    key = next(iter(conditional))
    assert key == ("#00ff00", 1.0)
    part_xs, part_ys = conditional[key][0]
    assert part_xs.tolist() == [3.0, 4.0]
    assert part_ys.tolist() == [30.0, 40.0]


def test_conditional_colors_are_vertex_colors_not_marker_overlay(qapp) -> None:
    widget = _widget_with_lookup([(3.0, 30.0, "#00ff00", 0.5, 2.5)])
    xs = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    ys = np.array([10.0, 20.0, 30.0, 40.0, 50.0])

    colors = widget._conditional_vertex_colors(xs, ys, (255, 0, 0, 255))

    assert colors is not None
    assert colors.shape == (5, 4)
    assert colors[0].tolist() == [1.0, 0.0, 0.0, 1.0]
    assert colors[2].tolist() == [0.0, 1.0, 0.0, pytest.approx(128 / 255)]


def test_colored_gl_line_keeps_one_item_and_colors_existing_segments(qapp) -> None:
    xs = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    ys = np.array([10.0, 20.0, 30.0], dtype=np.float64)
    colors = np.array(
        [
            [1.0, 0.0, 0.0, 1.0],
            [0.0, 1.0, 0.0, 1.0],
            [0.0, 0.0, 1.0, 1.0],
        ],
        dtype=np.float32,
    )

    gx, gy, gl_colors = ResidentGlLineLayer._segment_gl_geometry(xs, ys, colors)

    # Two existing line segments are emitted as one GL "lines" item input. The
    # first segment is red, the second is green; no marker overlay is involved.
    assert gx.tolist() == [1.0, 2.0, 2.0, 3.0]
    assert gy.tolist() == [10.0, 20.0, 20.0, 30.0]
    assert gl_colors.tolist() == [
        [1.0, 0.0, 0.0, 1.0],
        [1.0, 0.0, 0.0, 1.0],
        [0.0, 1.0, 0.0, 1.0],
        [0.0, 1.0, 0.0, 1.0],
    ]


class _FakeOverlay:
    """Captures GL line uploads so we can assert the chosen GL representation."""

    available = True

    def __init__(self) -> None:
        self.runs: list[dict] = []

    def add_line_run(self, layer_id, run_index, rx, ry, *, color, width, mode):
        self.runs.append(
            {
                "rx": np.asarray(rx),
                "ry": np.asarray(ry),
                "color": color,
                "mode": mode,
            }
        )

    def set_layer_visible(self, *_args, **_kwargs):
        pass


def test_colored_lines_upload_as_uniform_color_strips(qapp) -> None:
    xs = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float64)
    ys = np.array([10.0, 20.0, 30.0, 40.0, 50.0], dtype=np.float64)
    red = [1.0, 0.0, 0.0, 1.0]
    green = [0.0, 1.0, 0.0, 1.0]
    colors = np.array([red, red, green, green, green], dtype=np.float32)

    overlay = _FakeOverlay()
    layer = ResidentGlLineLayer(
        parts=[(xs, ys)],
        color_parts=[colors],
        pen=_make_nav_pen((0, 0, 255, 255), 1.0, LineStyle.SOLID, dpi=96.0),
        export_pen=_make_nav_pen((0, 0, 255, 255), 1.0, LineStyle.SOLID, dpi=96.0),
        line_style=LineStyle.SOLID,
        map_layer="postplot",
        plot_item=None,
        gl_overlay=overlay,
        line_items=[],
        plot_items=[],
    )

    layer.upload_pending_batch()

    # Two contiguous color runs -> two uniform-color line_strip uploads. No
    # per-vertex color array and no doubled "lines" geometry: identical GL cost
    # to a plain colored line.
    assert len(overlay.runs) == 2
    assert all(run["mode"] == "line_strip" for run in overlay.runs)
    assert all(isinstance(run["color"], tuple) for run in overlay.runs)
    assert overlay.runs[0]["color"] == pytest.approx(tuple(red))
    assert overlay.runs[1]["color"] == pytest.approx(tuple(green))
    # Boundary vertex is shared so the strips stay visually continuous.
    assert overlay.runs[0]["rx"].tolist() == [1.0, 2.0, 3.0]
    assert overlay.runs[1]["rx"].tolist() == [3.0, 4.0, 5.0]


def test_colored_resident_layers_follow_default_overview_motion(qapp) -> None:
    widget = PostplotMapWidget.__new__(PostplotMapWidget)
    layer_type = type(
        "Layer",
        (),
        {
            "set_gl_visible": lambda self, value: setattr(self, "visible", value),
            "clear_settled_detail": lambda self: None,
        },
    )
    colored = layer_type()
    plain = layer_type()
    colored.has_vertex_colors = True
    plain.has_vertex_colors = False
    widget._gl_line_layers = [colored, plain]
    widget._gl_scatter_layers = []
    widget._overview_cpu_items = []
    widget._gl_layers_ready = lambda: True
    widget._hide_reference_layers = lambda: None
    widget._view_clip_bbox = lambda: (0.0, 1.0, 0.0, 1.0)
    widget._is_overview_zoom = lambda _bbox: True

    PostplotMapWidget._enter_gl_motion_mode(widget)

    # Conditional colors are now treated exactly like default colors: both hide
    # full-detail GL during overview motion and rely on the overview preview.
    assert colored.visible is False
    assert plain.visible is False


def test_colored_dash_settle_groups_runs_for_real_dashed_segments(qapp) -> None:
    xs = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float64)
    ys = np.array([10.0, 20.0, 30.0, 40.0], dtype=np.float64)
    colors = np.array(
        [
            [1.0, 0.0, 0.0, 1.0],
            [1.0, 0.0, 0.0, 1.0],
            [0.0, 1.0, 0.0, 1.0],
            [0.0, 1.0, 0.0, 1.0],
        ],
        dtype=np.float32,
    )

    runs = ResidentGlLineLayer._colored_runs(xs, ys, colors)

    assert len(runs) == 2
    assert runs[0][0].tolist() == [1.0, 2.0, 3.0]
    assert runs[0][2] == (1.0, 0.0, 0.0, 1.0)
    assert runs[1][0].tolist() == [3.0, 4.0]
    assert runs[1][2] == (0.0, 1.0, 0.0, 1.0)


def test_nav_pen_dash_uses_custom_dash_pattern(qapp) -> None:
    pen = _make_nav_pen(
        (255, 0, 0, 255),
        1.2,
        LineStyle.DASH,
        dpi=96.0,
        dash_length_mm=4.0,
    )

    assert pen.style() == Qt.PenStyle.CustomDashLine
    assert pen.dashPattern()
    # Dash longer than the gap, and the dash length tracks the configured mm
    # (4 mm @ 96 dpi ~= 15 px) rather than collapsing to a fixed floor.
    dash_px = pen.dashPattern()[0] * pen.widthF()
    gap_px = pen.dashPattern()[1] * pen.widthF()
    assert dash_px > gap_px
    assert 13.0 <= dash_px <= 17.0
    assert gap_px >= 2.5


def test_finish_pan_interaction_restores_hidden_preplot(qapp) -> None:
    widget = PostplotMapWidget()
    curve = pg.PlotCurveItem()
    widget._plot_item.addItem(curve)
    widget._preplot_motion_items.append(curve)
    widget._interacting = True
    curve.setVisible(False)

    widget._finish_pan_interaction()

    assert not widget._interacting
    assert curve.isVisible()


def test_ensure_settled_for_capture_restores_hidden_preplot(qapp) -> None:
    widget = PostplotMapWidget()
    curve = pg.PlotCurveItem()
    widget._plot_item.addItem(curve)
    widget._preplot_motion_items.append(curve)
    widget._interacting = True
    curve.setVisible(False)

    widget.ensure_settled_for_capture(max_wait_ms=0)

    assert curve.isVisible()
    assert not widget._interacting
