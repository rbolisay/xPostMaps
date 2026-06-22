"""Brutal pan/zoom benchmark on real 7027.db — God Mode resident GL + overview raster."""

from __future__ import annotations

import gc
import sys
import time
from pathlib import Path

from PySide6.QtCore import QTimer
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


def run_7027_brutal_test(db_path: Path | None = None) -> dict[str, float]:
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

    for entry in settings.legend_config.postplot_lines:
        entry.line_style = LineStyle.SOLID
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
        lambda: not any(layer.has_pending_uploads for layer in widget._gl_line_layers),
        timeout_s=120.0,
    )
    gl_upload_ms = _ms(t0)

    vb = widget._plot.getViewBox()
    (x0, x1), (y0, y1) = vb.viewRange()
    span_x = x1 - x0
    span_y = y1 - y0

    widget._finish_pan_interaction()
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

    gl_runs = 0
    gl_visible = 0
    if widget._gl_overlay.available:
        gl_runs = len(widget._gl_overlay._items)
        gl_visible = sum(
            1 for item in widget._gl_overlay._items.values() if item.visible()
        )

    results: dict[str, float] = {
        "project_segments": float(len(map_data.segments)),
        "total_vertices": float(total_verts),
        "gl_available": float(gl_lines_available()),
        "gl_line_layers": float(len(widget._gl_line_layers)),
        "gl_line_runs": float(gl_runs),
        "gl_visible_runs": float(gl_visible),
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
    return results


def main() -> None:
    print("=" * 64)
    print("BRUTAL 7027.db — God Mode resident GL benchmark")
    print("Target: pan/zoom < 16 ms, GL upload completes, no spatial tiles")
    print("=" * 64)

    try:
        r = run_7027_brutal_test()
        for key in sorted(r.keys()):
            val = r[key]
            if key.endswith("_ms"):
                print(f"  {key:28s} {val:9.1f} ms")
            elif key in ("gl_available", "gl_upload_ok", "settle_ok"):
                print(f"  {key:28s} {'yes' if val else 'no'}")
            else:
                print(f"  {key:28s} {val:,.0f}")
    except Exception as exc:
        print(f"FAILED: {exc}")
        raise

    print("\n" + "=" * 64)
    ok = (
        r.get("detail_pan_p95_ms", 999) < 16.0
        and r.get("zoom_frame_max_ms", 999) < 16.0
        and r.get("gl_upload_ok", 0) == 1.0
    )
    print(f"God Mode pass: {'YES' if ok else 'NEEDS WORK'}")
    print("=" * 64)


if __name__ == "__main__":
    main()
