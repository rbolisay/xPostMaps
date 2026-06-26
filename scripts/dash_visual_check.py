"""Headless visual check for postplot line styles on real 4030_4D data.

Renders the real survey lines to PNGs (overview + zoomed) so we can visually
confirm whether DASH actually shows gaps and matches SOLID/DOTTED behaviour.

Usage:
    python scripts/dash_visual_check.py --style dash
    python scripts/dash_visual_check.py --style all
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication

from xpostmaps.core.database import Database
from xpostmaps.core.models import DisplayMode, LineStyle
from xpostmaps.ui.map_gl_overlay import gl_lines_available
from xpostmaps.ui.map_widget import PostplotMapWidget

DB_PATH = Path("data/4030_4D.db")
OUT_DIR = Path("output/dash_check")
_SUFFIX = ""


def _wait_until(app: QApplication, predicate, *, timeout_s: float = 120.0, poll_s: float = 0.005) -> bool:
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(poll_s)
    return False


def _settle(app: QApplication, widget: PostplotMapWidget) -> None:
    widget._apply_view_clip()
    widget._on_gl_view_settled()
    app.processEvents()
    _wait_until(app, lambda: not widget._interacting, timeout_s=15.0)
    # Let any debounced settle timers + GL repaint flush.
    for _ in range(8):
        app.processEvents()
        time.sleep(0.02)


def _save(app: QApplication, widget: PostplotMapWidget, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    app.processEvents()
    image = widget.capture_wysiwyg_image(1000, use_screen_grab=False)
    ok = image.save(str(path))
    print(f"  saved {path}  ({image.width()}x{image.height()})  ok={ok}")


def run(app: QApplication, style: LineStyle, dash_mm: float | None = None) -> None:
    print(f"\n=== STYLE: {style.value.upper()} ===")
    db = Database(DB_PATH)
    project = db.list_projects()[0]
    settings, map_data = db.load_project(project, with_positions=False)

    widget = PostplotMapWidget()
    widget.resize(1600, 1000)
    widget.show()
    app.processEvents()

    for entry in settings.legend_config.postplot_lines:
        entry.line_style = style
        entry.hidden = False
        entry.sequence_filter_active = True
        if dash_mm is not None:
            entry.dash_length_mm = dash_mm
        if not entry.sequence_ids:
            entry.sequence_ids = ["*"]
        print(f"  postplot row '{entry.name}': style={entry.line_style.value} dash_len_mm={entry.dash_length_mm}")

    widget.set_legend(settings.legend_config)
    widget.set_display_mode(DisplayMode.LINES)
    widget.render(map_data, force=True)
    app.processEvents()

    gl_ready = _wait_until(app, widget._gl_layers_ready, timeout_s=120.0)
    print(f"  gl_available={gl_lines_available()}  gl_ready={gl_ready}")
    print(f"  gl_line_layers={len(widget._gl_line_layers)}  gl_scatter_layers={len(widget._gl_scatter_layers)}")
    _settle(app, widget)

    _save(app, widget, OUT_DIR / f"{style.value}{_SUFFIX}_1_overview.png")

    # Zoom to ~12% of survey extent around the centre to inspect individual lines.
    vb = widget._plot.getViewBox()
    (x0, x1), (y0, y1) = vb.viewRange()
    cx = (x0 + x1) / 2.0
    cy = (y0 + y1) / 2.0
    hw = (x1 - x0) * 0.06
    hh = (y1 - y0) * 0.06
    vb.setRange(xRange=(cx - hw, cx + hw), yRange=(cy - hh, cy + hh), padding=0, update=True)
    app.processEvents()
    _settle(app, widget)
    _save(app, widget, OUT_DIR / f"{style.value}{_SUFFIX}_2_zoom.png")

    widget.close()
    db.close()
    app.processEvents()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--style", choices=("all", "solid", "dotted", "dash"), default="dash")
    parser.add_argument("--dash-mm", type=float, default=None, help="Override dash length (mm)")
    parser.add_argument("--suffix", default="", help="Filename suffix for outputs")
    args = parser.parse_args()
    styles = (
        [LineStyle.SOLID, LineStyle.DOTTED, LineStyle.DASH]
        if args.style == "all"
        else [LineStyle[args.style.upper()]]
    )
    global _SUFFIX
    _SUFFIX = args.suffix
    app = QApplication.instance() or QApplication(sys.argv)
    for style in styles:
        run(app, style, dash_mm=args.dash_mm)
    print("\nDone.")


if __name__ == "__main__":
    main()
