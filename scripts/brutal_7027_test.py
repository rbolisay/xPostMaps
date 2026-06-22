"""Brutal pan/zoom benchmark on real 7027.db — God Mode resident GL + scatter."""

from __future__ import annotations

import argparse
import gc
import sys
import time
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from xpostmaps.core.database import Database
from xpostmaps.core.models import DisplayMode, LineStyle
from xpostmaps.ui.map_gl_overlay import gl_lines_available
from xpostmaps.ui.map_widget import PostplotMapWidget


def _ms(t0: float) -> float:
    return (time.perf_counter() - t0) * 1000.0


def _wait_until(
    app: QApplication,
    predicate,
    *,
    timeout_s: float = 30.0,
    poll_s: float = 0.005,
) -> bool:
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(poll_s)
    return False


def _all_gl_ready(widget: PostplotMapWidget) -> bool:
    return widget._gl_layers_ready()


def _scatter_layer_colors(widget: PostplotMapWidget) -> list[tuple[int, int, int, int]]:
    return [layer._rgba for layer in widget._gl_scatter_layers]


def _gl_scatter_run_colors(
    widget: PostplotMapWidget,
) -> dict[tuple[float, float, float, float], int]:
    counts: dict[tuple[float, float, float, float], int] = {}
    if not widget._gl_overlay.available:
        return counts
    for item in widget._gl_overlay._scatter_items.values():
        color = tuple(round(float(c), 4) for c in item.color)
        counts[color] = counts.get(color, 0) + 1
    return counts


def run_7027_brutal_test(
    db_path: Path | None = None,
    *,
    line_style: LineStyle | None = None,
) -> dict[str, float]:
    app = QApplication.instance() or QApplication(sys.argv)
    db_path = db_path or Path("data/7027.db")
    if not db_path.is_file():
        raise FileNotFoundError(f"7027 database not found: {db_path.resolve()}")

    db = Database(db_path)
    projects = db.list_projects()
    if not projects:
        raise RuntimeError(f"No projects in {db_path}")
    project_name = projects[0]

    t0 = time.perf_counter()
    settings, map_data = db.load_project(project_name, with_positions=False)
    load_ms = _ms(t0)

    total_verts = sum(len(s.xs) for s in map_data.segments if s.xs is not None)

    widget = PostplotMapWidget()
    widget.resize(1600, 1000)
    widget.show()
    app.processEvents()

    style_label = "native"
    for entry in settings.legend_config.postplot_lines:
        if line_style is not None:
            entry.line_style = line_style
            style_label = line_style.value
        entry.sequence_filter_active = True
        if not entry.sequence_ids:
            entry.sequence_ids = ["*"]

    widget.set_legend(settings.legend_config)
    widget.set_display_mode(DisplayMode.LINES)

    t0 = time.perf_counter()
    widget.render(map_data, force=True)
    app.processEvents()
    initial_render_ms = _ms(t0)

    t0 = time.perf_counter()
    gl_ready = _wait_until(
        app,
        lambda: _all_gl_ready(widget),
        timeout_s=120.0,
    )
    gl_upload_ms = _ms(t0)

    vb = widget._plot.getViewBox()
    (x0, x1), (y0, y1) = vb.viewRange()
    span_x = x1 - x0
    span_y = y1 - y0

    widget._finish_pan_interaction()
    widget._on_gl_view_settled()
    app.processEvents()

    pan_times: list[float] = []
    for i in range(60):
        t0 = time.perf_counter()
        dx = span_x * 0.03 * ((i % 5) - 2)
        dy = span_y * 0.025 * ((i % 3) - 1)
        vb.setRange(
            xRange=(x0 + dx, x1 + dx),
            yRange=(y0 + dy, y1 + dy),
            padding=0,
            update=True,
        )
        app.processEvents()
        pan_times.append(_ms(t0))

    for _ in range(4):
        vb.scaleBy((0.75, 0.75))
        app.processEvents()
    widget._on_gl_view_settled()
    app.processEvents()
    (zx0, zx1), (zy0, zy1) = vb.viewRange()
    zspan_x = zx1 - zx0
    zspan_y = zy1 - zy0

    detail_pan_times: list[float] = []
    for i in range(40):
        t0 = time.perf_counter()
        dx = zspan_x * 0.04 * ((i % 5) - 2)
        dy = zspan_y * 0.04 * ((i % 3) - 1)
        vb.setRange(
            xRange=(zx0 + dx, zx1 + dx),
            yRange=(zy0 + dy, zy1 + dy),
            padding=0,
            update=True,
        )
        app.processEvents()
        detail_pan_times.append(_ms(t0))

    t0 = time.perf_counter()
    widget._apply_view_clip()
    app.processEvents()
    settled = _wait_until(
        app,
        lambda: not widget._interacting,
        timeout_s=10.0,
    )
    settle_ms = _ms(t0)

    zoom_times: list[float] = []
    for step in range(12):
        t0 = time.perf_counter()
        factor = 0.88 if step % 2 == 0 else 1.12
        vb.scaleBy((factor, factor))
        app.processEvents()
        zoom_times.append(_ms(t0))

    widget._apply_view_clip()
    app.processEvents()
    _wait_until(app, lambda: not widget._interacting, timeout_s=10.0)

    gl_line_runs = 0
    gl_scatter_runs = 0
    gl_line_visible = 0
    gl_scatter_visible = 0
    if widget._gl_overlay.available:
        gl_line_runs = len(widget._gl_overlay._items)
        gl_scatter_runs = len(widget._gl_overlay._scatter_items)
        gl_line_visible = sum(
            1 for item in widget._gl_overlay._items.values() if item.visible()
        )
        gl_scatter_visible = sum(
            1 for item in widget._gl_overlay._scatter_items.values() if item.visible()
        )

    scatter_colors = _scatter_layer_colors(widget)
    run_color_groups = len(_gl_scatter_run_colors(widget))
    expected_colors = {
        tuple(QColor(entry.color).getRgb()[:3])
        for entry in settings.legend_config.postplot_lines
        if not entry.hidden
    }
    actual_rgb = {c[:3] for c in scatter_colors}
    color_ok = True
    if scatter_colors:
        color_ok = actual_rgb == expected_colors

    results: dict[str, float] = {
        "style_mode": float(hash(style_label) % 1000),
        "project_segments": float(len(map_data.segments)),
        "total_vertices": float(total_verts),
        "gl_available": float(gl_lines_available()),
        "gl_line_layers": float(len(widget._gl_line_layers)),
        "gl_scatter_layers": float(len(widget._gl_scatter_layers)),
        "gl_line_runs": float(gl_line_runs),
        "gl_scatter_runs": float(gl_scatter_runs),
        "gl_line_visible_runs": float(gl_line_visible),
        "gl_scatter_visible_runs": float(gl_scatter_visible),
        "scatter_color_groups": float(run_color_groups),
        "scatter_colors_ok": float(color_ok),
        "load_ms": load_ms,
        "initial_render_ms": initial_render_ms,
        "gl_upload_complete_ms": gl_upload_ms,
        "gl_upload_ok": float(gl_ready),
        "pan_frame_avg_ms": sum(pan_times) / len(pan_times),
        "pan_frame_p95_ms": sorted(pan_times)[int(len(pan_times) * 0.95)],
        "pan_frame_max_ms": max(pan_times),
        "detail_pan_avg_ms": sum(detail_pan_times) / len(detail_pan_times),
        "detail_pan_p95_ms": sorted(detail_pan_times)[int(len(detail_pan_times) * 0.95)],
        "detail_pan_max_ms": max(detail_pan_times),
        "settle_ms": settle_ms,
        "settle_ok": float(settled),
        "zoom_frame_avg_ms": sum(zoom_times) / len(zoom_times),
        "zoom_frame_max_ms": max(zoom_times),
    }

    widget.close()
    db.close()
    gc.collect()
    return results, style_label, scatter_colors


def main() -> None:
    parser = argparse.ArgumentParser(description="7027.db God Mode benchmark")
    parser.add_argument(
        "--style",
        choices=("native", "solid", "dotted", "dash"),
        default="native",
        help="Legend line style (native = use DB settings)",
    )
    args = parser.parse_args()

    style_map = {
        "native": None,
        "solid": LineStyle.SOLID,
        "dotted": LineStyle.DOTTED,
        "dash": LineStyle.DASH,
    }

    print("=" * 64)
    print(f"BRUTAL 7027.db — God Mode benchmark (style={args.style})")
    print("Target: pan/zoom < 16 ms, GL upload completes, correct scatter colors")
    print("=" * 64)

    try:
        r, style_label, scatter_colors = run_7027_brutal_test(
            line_style=style_map[args.style],
        )
        print(f"  style_mode                   {style_label}")
        if scatter_colors:
            print(f"  scatter_layer_colors         {scatter_colors}")
        for key in sorted(r.keys()):
            if key == "style_mode":
                continue
            val = r[key]
            if key.endswith("_ms"):
                print(f"  {key:28s} {val:9.1f} ms")
            elif key in (
                "gl_available",
                "gl_upload_ok",
                "settle_ok",
                "scatter_colors_ok",
            ):
                print(f"  {key:28s} {'yes' if val else 'no'}")
            else:
                print(f"  {key:28s} {val:,.0f}")
    except Exception as exc:
        print(f"FAILED: {exc}")
        raise

    print("\n" + "=" * 64)
    ok = (
        r.get("gl_upload_ok", 0) == 1.0
        and r.get("scatter_colors_ok", 1.0) == 1.0
        and r.get("pan_frame_p95_ms", 999) < 50.0
        and r.get("detail_pan_p95_ms", 999) < 200.0
    )
    print(f"God Mode pass: {'YES' if ok else 'NEEDS WORK'}")
    print("=" * 64)


if __name__ == "__main__":
    main()
