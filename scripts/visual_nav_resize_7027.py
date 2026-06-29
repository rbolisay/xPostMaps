"""Reproduce/verify the 4D Stat Plot navigation width flicker on real 7027 data.

Opens the real Postplot4DDialog against data/7027.db, instruments every resize()
call on the host dialog, then drives Load Preplot + Next Preplot + Next Sequence.
A healthy run shows the dialog width staying at the plot size across navigation
(no transient shrink to the diff-table width).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from xpostmaps.core.database import Database  # noqa: E402
from xpostmaps.ui.dialogs.postplot_4d_dialog import Postplot4DDialog  # noqa: E402
from xpostmaps.ui.postplot_4d_stat_plot import Postplot4DStatPlotView  # noqa: E402

DB_PATH = ROOT / "data" / "7027.db"
OUT_DIR = ROOT / "data" / "nav_resize_7027"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def main() -> int:
    if not DB_PATH.is_file():
        print(f"DB not found: {DB_PATH}")
        return 1

    db = Database(DB_PATH)
    project_name = db.list_projects()[0]
    settings, map_data = db.load_project(project_name, with_positions=False)
    settings.postplot_4d_baseline = "preplot"
    print("project:", project_name)

    app = QApplication.instance() or QApplication(sys.argv)
    parent = QWidget()
    parent.resize(1200, 800)
    parent.show()

    dialog = Postplot4DDialog.open(
        parent,
        settings,
        map_data,
        project_name=project_name,
        database=db,
    )

    resize_log: list[tuple[str, int]] = []
    original_resize = dialog.resize

    def logged_resize(*args):
        if len(args) == 1:
            size = args[0]
            w, h = size.width(), size.height()
        else:
            w, h = args[0], args[1]
        resize_log.append((_phase[0], int(w)))
        return original_resize(*args)

    dialog.resize = logged_resize  # type: ignore[method-assign]
    _phase = ["init"]

    plot_view = dialog.findChild(Postplot4DStatPlotView)
    if plot_view is None:
        print("plot_view not found")
        return 1

    steps = iter(
        [
            ("load_preplot", lambda: plot_view.load_preplot_requested.emit("54420")),
            ("next_sequence", lambda: plot_view.next_subline_requested.emit()),
            ("next_preplot", lambda: plot_view.next_preplot_requested.emit()),
            ("next_preplot_2", lambda: plot_view.next_preplot_requested.emit()),
        ]
    )

    def run_next() -> None:
        try:
            name, action = next(steps)
        except StopIteration:
            _finish()
            return
        _phase[0] = name
        before = dialog.width()
        action()
        app.processEvents()
        after = dialog.width()
        widths = [w for ph, w in resize_log if ph == name]
        print(f"[{name}] before={before} after={after} resize_calls_width={widths}")
        QTimer.singleShot(400, run_next)

    def _finish() -> None:
        # Capture the final dialog state for a visual sanity check.
        img = dialog.grab()
        out = OUT_DIR / "dialog_after_nav.png"
        img.save(str(out))
        print(f"saved {out}  final_width={dialog.width()}")

        # Summary: any width during a nav step smaller than the final plot width
        # by a noticeable margin indicates a flicker.
        final_w = dialog.width()
        flicker = [
            (ph, w)
            for ph, w in resize_log
            if ph != "init" and w < final_w - 40
        ]
        if flicker:
            print("FLICKER DETECTED (intermediate narrow resizes):", flicker)
        else:
            print("NO FLICKER: width stable across navigation.")
        app.quit()

    QTimer.singleShot(500, run_next)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
