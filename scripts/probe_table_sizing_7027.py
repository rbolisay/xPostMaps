"""Probe Source Style / Boundary Limits table sizing in the real 4D Stat Plot."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QTableWidget, QWidget  # noqa: E402

from xpostmaps.core.database import Database  # noqa: E402
from xpostmaps.ui.dialogs.postplot_4d_dialog import Postplot4DDialog  # noqa: E402
from xpostmaps.ui.postplot_4d_stat_plot import Postplot4DStatPlotView  # noqa: E402

DB_PATH = ROOT / "data" / "7027.db"
OUT_DIR = ROOT / "data" / "nav_resize_7027"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def dump_table(tag: str, table: QTableWidget) -> None:
    cols = table.columnCount()
    headers = []
    for c in range(cols):
        item = table.horizontalHeaderItem(c)
        headers.append(item.text() if item else "<none>")
    widths = [table.columnWidth(c) for c in range(cols)]
    total = sum(widths)
    print(f"  [{tag}] cols={cols} headers={headers}")
    print(
        f"    col_widths={widths} sum={total} "
        f"table.width={table.width()} sizeHint.w={table.sizeHint().width()} "
        f"viewport.w={table.viewport().width()} "
        f"hscroll_visible={table.horizontalScrollBar().isVisible()}"
    )


def main() -> int:
    db = Database(DB_PATH)
    project_name = db.list_projects()[0]
    settings, map_data = db.load_project(project_name, with_positions=False)
    settings.postplot_4d_baseline = "preplot"

    app = QApplication.instance() or QApplication(sys.argv)
    parent = QWidget()
    parent.resize(1400, 900)
    parent.show()

    dialog = Postplot4DDialog.open(
        parent, settings, map_data, project_name=project_name, database=db
    )
    dialog.resize(1376, 800)
    plot_view = dialog.findChild(Postplot4DStatPlotView)

    def step1() -> None:
        plot_view.load_subline_requested.emit("3012")
        QTimer.singleShot(500, step2)

    def step2() -> None:
        print("SINGLE SEQUENCE (3012):")
        ctrl = plot_view.tab_controls_for_kind("crossline")
        dump_table("source", ctrl._source_table._table)
        dump_table("boundary", ctrl._boundary_table._table)
        print(f"  source_table.widget.width={ctrl._source_table.width()}")
        print(f"  boundary_table.widget.width={ctrl._boundary_table.width()}")
        print(f"  PlotTabControls.width={ctrl.width()}")
        img = dialog.grab()
        img.save(str(OUT_DIR / "single_tables.png"))

        plot_view.load_preplot_requested.emit("54420")
        QTimer.singleShot(600, step3)

    def step3() -> None:
        print("\nCOMBINED PREPLOT 54420:")
        ctrl = plot_view.tab_controls_for_kind("crossline")
        dump_table("source", ctrl._source_table._table)
        dump_table("boundary", ctrl._boundary_table._table)
        img = dialog.grab()
        img.save(str(OUT_DIR / "combined_tables.png"))
        app.quit()

    QTimer.singleShot(500, step1)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
