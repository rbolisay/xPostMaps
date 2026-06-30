"""Visual QA for survey plot pan/zoom on heatmap and histogram."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from xpostmaps.core.database import Database
from xpostmaps.core.postplot_4d_matching import build_postplot_4d_rows
from xpostmaps.core.postplot_4d_survey_plots_worker import SurveyPlotsLoadWorker
from xpostmaps.ui.postplot_4d_survey_plots.aerial_heatmap_canvas import AerialHeatmapCanvas
from xpostmaps.ui.postplot_4d_survey_plots.histogram_canvas import HistogramCanvas
from xpostmaps.ui.postplot_4d_survey_plots.survey_plot_navigation import SurveyPlotViewBox

OUT = ROOT / "data" / "pdf_qa" / "navigation"
DB = ROOT / "data" / "4030_4D.db"


def _load_4030():
    db = Database(DB)
    settings, map_data = db.load_project("4030_4D", with_positions=False)
    matched = [
        row
        for row in build_postplot_4d_rows(map_data, settings, "navplan")
        if row.has_match
    ]
    result_box: list = []
    worker = SurveyPlotsLoadWorker(DB, "4030_4D", "navplan", matched)
    worker.finished_ok.connect(
        lambda result: result_box.append(result),
        Qt.ConnectionType.DirectConnection,
    )
    worker.start()
    worker.wait()
    return result_box[0]


def _ranges_close(a, b, tol: float = 1e-6) -> bool:
    return abs(a[0][0] - b[0][0]) < tol and abs(a[0][1] - b[0][1]) < tol and abs(a[1][0] - b[1][0]) < tol and abs(a[1][1] - b[1][1]) < tol


def _exercise_viewbox(canvas, viewbox: SurveyPlotViewBox, prefix: str, app) -> None:
    assert isinstance(viewbox, SurveyPlotViewBox)
    start = viewbox.viewRange()
    viewbox.translateBy(x=2.0, y=50.0)
    app.processEvents()
    canvas._plot.grab().save(str(OUT / f"{prefix}_panned.png"))
    viewbox.scaleBy((0.4, 0.4))
    app.processEvents()
    canvas._plot.grab().save(str(OUT / f"{prefix}_zoomed.png"))
    viewbox.zoom_to_extent()
    app.processEvents()
    canvas._plot.grab().save(str(OUT / f"{prefix}_reset.png"))
    reset = viewbox.viewRange()
    if not _ranges_close(start, reset):
        raise AssertionError(f"{prefix}: reset extent mismatch {start} vs {reset}")


def main() -> int:
    app = QApplication([])
    OUT.mkdir(parents=True, exist_ok=True)
    result = _load_4030()

    aerial = AerialHeatmapCanvas()
    aerial.resize(1400, 900)
    aerial.show()
    aerial.render(result.heatmap_cache["radial"])
    app.processEvents()
    _exercise_viewbox(aerial, aerial._viewbox, "heatmap", app)

    hist = HistogramCanvas()
    hist.resize(1400, 700)
    hist.show()
    hist.render(result.histogram_cache["radial"])
    app.processEvents()
    _exercise_viewbox(hist, hist._viewbox, "histogram", app)

    print(f"Navigation visual QA saved under {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
