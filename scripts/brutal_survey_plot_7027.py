"""Brutal performance + correctness test for Survey Plots on real 7027.db."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from xpostmaps.core.database import Database  # noqa: E402
from xpostmaps.core.postplot_4d_matching import build_postplot_4d_rows  # noqa: E402
from xpostmaps.core.postplot_4d_survey_plot_pdf import (  # noqa: E402
    Postplot4DSurveyPlotPdfOptions,
    export_survey_plot_pdf,
    iter_survey_plot_page_specs,
)
from xpostmaps.core.postplot_4d_survey_plots_worker import SurveyPlotsLoadWorker  # noqa: E402
from xpostmaps.ui.postplot_4d_survey_plots.survey_plots_view import (  # noqa: E402
    Postplot4DSurveyPlotsView,
)

DB_PATH = ROOT / "data" / "7027.db"
OUT_DIR = ROOT / "data" / "brutal_survey_plot_7027"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def main() -> int:
    if not DB_PATH.is_file():
        print(f"SKIP: {DB_PATH} not found")
        return 1

    app = QApplication.instance() or QApplication(sys.argv)
    db = Database(DB_PATH)
    project = db.list_projects()[0]
    settings, map_data = db.load_project(project, with_positions=False)
    matched = [
        row
        for row in build_postplot_4d_rows(map_data, settings, "preplot")
        if row.has_match
    ]
    print(f"7027 matched rows: {len(matched)}")

    worker = SurveyPlotsLoadWorker(DB_PATH, project, "preplot", matched)
    result_box: list = []
    errors: list[str] = []

    def on_ok(result) -> None:
        result_box.append(result)

    def on_fail(message: str) -> None:
        errors.append(message)

    worker.finished_ok.connect(on_ok, Qt.ConnectionType.DirectConnection)
    worker.finished_failed.connect(on_fail, Qt.ConnectionType.DirectConnection)

    t0 = time.perf_counter()
    worker.start()
    worker.wait()
    app.processEvents()
    load_s = time.perf_counter() - t0
    print(f"Worker load: {load_s:.2f}s")

    if errors:
        print("LOAD FAILED:", errors[0])
        return 1
    if not result_box:
        print("LOAD FAILED: no result")
        return 1

    result = result_box[0]
    print(
        f"Loaded {result.sequence_count} sequences, "
        f"{result.shotpoint_count:,} shotpoints, "
        f"kinds={result.available_kinds}"
    )

    view = Postplot4DSurveyPlotsView()
    view.resize(1200, 800)
    view.show()
    view.apply_load_result(result)
    app.processEvents()

    t0 = time.perf_counter()
    view.refresh_all()
    app.processEvents()
    render_s = time.perf_counter() - t0
    print(f"Render all tabs: {render_s:.2f}s")

    options = Postplot4DSurveyPlotPdfOptions(
        output_dir=OUT_DIR,
        filename="7027_survey_plots.pdf",
        dpi=150,
    )
    specs = iter_survey_plot_page_specs(view, options)
    print(f"PDF page specs: {len(specs)}")

    t0 = time.perf_counter()
    pdf_path = OUT_DIR / options.filename
    export_survey_plot_pdf(view, pdf_path, options)
    pdf_s = time.perf_counter() - t0
    print(f"PDF export: {pdf_s:.2f}s -> {pdf_path} ({pdf_path.stat().st_size // 1024} KB)")

    assert pdf_path.is_file() and pdf_path.stat().st_size > 10_000
    assert result.sequence_count > 100
    assert load_s < 45.0, f"load too slow: {load_s:.1f}s"
    print("PASS brutal 7027 survey plots")
    QTimer.singleShot(0, app.quit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
