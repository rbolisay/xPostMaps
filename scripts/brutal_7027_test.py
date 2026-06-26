"""Brutal pan/zoom benchmark on real 7027.db — God Mode all postplot line styles."""

from __future__ import annotations

import argparse
import gc
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from xpostmaps.core.database import Database
from xpostmaps.core.models import DisplayMode, LineStyle
from xpostmaps.ui.map_gl_overlay import gl_lines_available
from xpostmaps.ui.map_widget import PostplotMapWidget


def _ms(t0: float) -> float:
    return (time.perf_counter() - t0) * 1000.0


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    return sorted(values)[int(len(values) * 0.95)]


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


@dataclass
class DetailSnapshot:
    gl_line_layers: int
    gl_scatter_layers: int
    gl_line_runs: int
    gl_scatter_runs: int
    gl_line_visible: int
    gl_scatter_visible: int
    postplot_gl_line_layers: int
    postplot_gl_scatter_layers: int
    postplot_dash_settle_curves: int
    overview_visible: int
    reference_visible: int
    viewport_cull: bool
    interacting: bool

    @classmethod
    def capture(cls, widget: PostplotMapWidget) -> DetailSnapshot:
        overlay = widget._gl_overlay
        gl_line_runs = len(overlay._items) if overlay.available else 0
        gl_scatter_runs = len(overlay._scatter_items) if overlay.available else 0
        gl_line_visible = (
            sum(1 for item in overlay._items.values() if item.visible())
            if overlay.available
            else 0
        )
        gl_scatter_visible = (
            sum(1 for item in overlay._scatter_items.values() if item.visible())
            if overlay.available
            else 0
        )
        postplot_line = sum(
            1 for layer in widget._gl_line_layers if layer.map_layer == "postplot"
        )
        postplot_scatter = sum(
            1 for layer in widget._gl_scatter_layers if layer.map_layer == "postplot"
        )
        dash_settle = sum(
            len(layer._settle_cpu_items)
            for layer in widget._gl_line_layers
            if layer.map_layer == "postplot"
        )
        overview_visible = sum(1 for item in widget._overview_cpu_items if item.isVisible())
        reference_visible = sum(
            1 for item in widget._preplot_motion_items if item.isVisible()
        )
        return cls(
            gl_line_layers=len(widget._gl_line_layers),
            gl_scatter_layers=len(widget._gl_scatter_layers),
            gl_line_runs=gl_line_runs,
            gl_scatter_runs=gl_scatter_runs,
            gl_line_visible=gl_line_visible,
            gl_scatter_visible=gl_scatter_visible,
            postplot_gl_line_layers=postplot_line,
            postplot_gl_scatter_layers=postplot_scatter,
            postplot_dash_settle_curves=dash_settle,
            overview_visible=overview_visible,
            reference_visible=reference_visible,
            viewport_cull=overlay._viewport_cull if overlay.available else False,
            interacting=widget._interacting,
        )


def _detail_parity_ok(
    style: LineStyle,
    baseline: DetailSnapshot,
    settled: DetailSnapshot,
    *,
    zoomed_in: bool,
) -> tuple[bool, list[str]]:
    issues: list[str] = []

    if baseline.gl_line_layers != settled.gl_line_layers:
        issues.append("gl_line_layer_count_changed")
    if baseline.gl_scatter_layers != settled.gl_scatter_layers:
        issues.append("gl_scatter_layer_count_changed")
    if baseline.gl_line_runs != settled.gl_line_runs:
        issues.append("gl_line_run_count_changed")
    if baseline.gl_scatter_runs != settled.gl_scatter_runs:
        issues.append("gl_scatter_run_count_changed")
    if settled.interacting:
        issues.append("still_interacting_after_settle")
    if settled.overview_visible > 0 and widget_gl_ready(settled):
        issues.append("overview_visible_after_settle")

    if style == LineStyle.SOLID:
        if settled.postplot_gl_line_layers == 0:
            issues.append("no_postplot_gl_line_layers")
        if settled.gl_line_runs == 0:
            issues.append("no_gl_line_runs")
        if zoomed_in and settled.gl_line_visible == 0:
            issues.append("no_visible_gl_lines_when_zoomed")

    elif style == LineStyle.DOTTED:
        if settled.postplot_gl_scatter_layers == 0:
            issues.append("no_postplot_gl_scatter_layers")
        if settled.gl_scatter_runs == 0:
            issues.append("no_gl_scatter_runs")
        if settled.gl_scatter_visible == 0:
            issues.append("no_visible_gl_scatter_after_settle")

    elif style == LineStyle.DASH:
        # Dash is now baked into GPU geometry (gaps in the vertices), so it
        # behaves exactly like SOLID: resident GL runs, no CPU settle curves.
        if settled.postplot_gl_line_layers == 0:
            issues.append("no_postplot_gl_line_layers")
        if settled.gl_line_runs == 0:
            issues.append("no_gl_line_runs")
        if zoomed_in and settled.gl_line_visible == 0:
            issues.append("no_visible_gl_lines_when_zoomed")
        if settled.postplot_dash_settle_curves > 0:
            issues.append("unexpected_dash_cpu_curves")

    return not issues, issues


def widget_gl_ready(snapshot: DetailSnapshot) -> bool:
    return snapshot.gl_line_layers + snapshot.gl_scatter_layers > 0


def _scatter_colors_ok(
    widget: PostplotMapWidget,
    settings,
) -> bool:
    scatter_colors = [layer._rgba for layer in widget._gl_scatter_layers]
    if not scatter_colors:
        return True
    expected_colors = {
        tuple(QColor(entry.color).getRgb()[:3])
        for entry in settings.legend_config.postplot_lines
        if not entry.hidden
    }
    actual_rgb = {c[:3] for c in scatter_colors}
    return actual_rgb == expected_colors


def run_7027_brutal_test(
    app: QApplication,
    *,
    line_style: LineStyle,
    db_path: Path | None = None,
) -> tuple[dict[str, float], DetailSnapshot, DetailSnapshot, list[str]]:
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

    for entry in settings.legend_config.postplot_lines:
        entry.line_style = line_style
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
        widget._gl_layers_ready,
        timeout_s=120.0,
    )
    gl_upload_ms = _ms(t0)

    widget._finish_pan_interaction()
    widget._on_gl_view_settled()
    app.processEvents()
    baseline = DetailSnapshot.capture(widget)

    vb = widget._plot.getViewBox()
    (x0, x1), (y0, y1) = vb.viewRange()
    span_x = x1 - x0
    span_y = y1 - y0

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
    settled_ok = _wait_until(app, lambda: not widget._interacting, timeout_s=10.0)
    settle_ms = _ms(t0)
    settled = DetailSnapshot.capture(widget)
    zoomed_in = not widget._is_overview_zoom()

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
    final = DetailSnapshot.capture(widget)

    detail_ok, detail_issues = _detail_parity_ok(
        line_style,
        baseline,
        settled,
        zoomed_in=zoomed_in,
    )

    results: dict[str, float] = {
        "project_segments": float(len(map_data.segments)),
        "total_vertices": float(total_verts),
        "gl_available": float(gl_lines_available()),
        "gl_line_layers": float(baseline.gl_line_layers),
        "gl_scatter_layers": float(baseline.gl_scatter_layers),
        "gl_line_runs": float(baseline.gl_line_runs),
        "gl_scatter_runs": float(baseline.gl_scatter_runs),
        "gl_upload_complete_ms": gl_upload_ms,
        "gl_upload_ok": float(gl_ready),
        "load_ms": load_ms,
        "initial_render_ms": initial_render_ms,
        "pan_frame_avg_ms": sum(pan_times) / len(pan_times),
        "pan_frame_p95_ms": _p95(pan_times),
        "pan_frame_max_ms": max(pan_times),
        "detail_pan_avg_ms": sum(detail_pan_times) / len(detail_pan_times),
        "detail_pan_p95_ms": _p95(detail_pan_times),
        "detail_pan_max_ms": max(detail_pan_times),
        "zoom_frame_avg_ms": sum(zoom_times) / len(zoom_times),
        "zoom_frame_p95_ms": _p95(zoom_times),
        "zoom_frame_max_ms": max(zoom_times),
        "settle_ms": settle_ms,
        "settle_ok": float(settled_ok),
        "detail_parity_ok": float(detail_ok),
        "scatter_colors_ok": float(_scatter_colors_ok(widget, settings)),
        "baseline_gl_line_visible": float(baseline.gl_line_visible),
        "settled_gl_line_visible": float(settled.gl_line_visible),
        "baseline_gl_scatter_visible": float(baseline.gl_scatter_visible),
        "settled_gl_scatter_visible": float(settled.gl_scatter_visible),
        "settled_dash_settle_curves": float(settled.postplot_dash_settle_curves),
    }

    widget.close()
    db.close()
    gc.collect()
    return results, baseline, final, detail_issues


def _god_mode_speed_ok(r: dict[str, float]) -> bool:
    return (
        r.get("gl_upload_ok", 0) == 1.0
        and r.get("pan_frame_p95_ms", 999) < 50.0
        and r.get("detail_pan_p95_ms", 999) < 200.0
        and r.get("zoom_frame_p95_ms", 999) < 60.0
    )


def _print_style_report(
    style: LineStyle,
    r: dict[str, float],
    baseline: DetailSnapshot,
    settled: DetailSnapshot,
    detail_issues: list[str],
) -> bool:
    print(f"\n{'-' * 64}")
    print(f"STYLE: {style.value.upper()}")
    print(f"{'-' * 64}")
    print(f"  GL line layers / runs     {int(r['gl_line_layers']):>6} / {int(r['gl_line_runs'])}")
    print(f"  GL scatter layers / runs  {int(r['gl_scatter_layers']):>6} / {int(r['gl_scatter_runs'])}")
    print(f"  GL upload                 {r['gl_upload_complete_ms']:>8.1f} ms  ({'ok' if r['gl_upload_ok'] else 'FAIL'})")
    print(f"  Full-extent pan p95       {r['pan_frame_p95_ms']:>8.1f} ms")
    print(f"  Zoomed detail pan p95     {r['detail_pan_p95_ms']:>8.1f} ms")
    print(f"  Zoom frame p95            {r['zoom_frame_p95_ms']:>8.1f} ms")
    print(f"  Detail parity             {'PASS' if r['detail_parity_ok'] else 'FAIL'}")
    if detail_issues:
        print(f"  Detail issues             {', '.join(detail_issues)}")
    print(
        f"  Visible GL (base->settled) lines {baseline.gl_line_visible}->{settled.gl_line_visible}"
        f"  scatter {baseline.gl_scatter_visible}->{settled.gl_scatter_visible}"
    )
    if style == LineStyle.DASH:
        print(f"  Dash CPU curves (settled)  {int(settled.postplot_dash_settle_curves)}")
    speed_ok = _god_mode_speed_ok(r)
    detail_ok = r.get("detail_parity_ok", 0) == 1.0 and r.get("scatter_colors_ok", 1) == 1.0
    print(f"  God Mode speed            {'PASS' if speed_ok else 'FAIL'}")
    print(f"  God Mode overall          {'PASS' if speed_ok and detail_ok else 'NEEDS WORK'}")
    return speed_ok and detail_ok


def main() -> None:
    parser = argparse.ArgumentParser(description="7027.db God Mode benchmark")
    parser.add_argument(
        "--style",
        choices=("all", "solid", "dotted", "dash"),
        default="all",
        help="Postplot line style to test (default: all)",
    )
    parser.add_argument(
        "--db",
        default="data/7027.db",
        help="Path to the project database (default: data/7027.db)",
    )
    args = parser.parse_args()
    db_path = Path(args.db)

    styles = (
        [LineStyle.SOLID, LineStyle.DOTTED, LineStyle.DASH]
        if args.style == "all"
        else [LineStyle[args.style.upper()]]
    )

    app = QApplication.instance() or QApplication(sys.argv)

    print("=" * 64)
    print("BRUTAL 7027.db — God Mode all postplot line styles")
    print("Targets: pan p95 < 50 ms, detail pan p95 < 200 ms, full detail after settle")
    print("=" * 64)

    all_pass = True
    for style in styles:
        try:
            r, baseline, settled, issues = run_7027_brutal_test(
                app, line_style=style, db_path=db_path
            )
            ok = _print_style_report(style, r, baseline, settled, issues)
            all_pass = all_pass and ok
        except Exception as exc:
            all_pass = False
            print(f"\nSTYLE {style.value.upper()} FAILED: {exc}")
            raise

    print(f"\n{'=' * 64}")
    print(f"ALL STYLES PASS: {'YES' if all_pass else 'NEEDS WORK'}")
    print("=" * 64)

    if not all_pass:
        sys.exit(1)


if __name__ == "__main__":
    main()
