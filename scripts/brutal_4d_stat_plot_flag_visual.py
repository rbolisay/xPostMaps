"""Brutal visual QA: survey-spec flag colours, speed, and PDF export."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import pyqtgraph as pg  # noqa: E402

from xpostmaps.core.postplot_4d_diff import Postplot4DDiffRow  # noqa: E402
from xpostmaps.core.postplot_4d_matching import Postplot4DMatchRow  # noqa: E402
from xpostmaps.core.postplot_4d_plot_pdf import (  # noqa: E402
    Postplot4DStatPlotPdfOptions,
    export_4d_stat_plot_pdf,
)
from xpostmaps.core.postplot_4d_survey_spec import (  # noqa: E402
    Severity,
    StatType,
    SurveySpecRow,
)
from xpostmaps.ui.postplot_4d_stat_plot.plot_view import Postplot4DStatPlotView  # noqa: E402
from xpostmaps.ui.postplot_4d_stat_plot.plot_widget import (  # noqa: E402
    _FLAG_ERROR_COLOR,
    _FLAG_WARNING_COLOR,
)

OUT_DIR = ROOT / "data" / "brutal_4d_stat_plot_flags"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _make_rows() -> tuple[Postplot4DMatchRow, list[Postplot4DDiffRow]]:
    match = Postplot4DMatchRow(
        baseline_name="1065P1A",
        baseline_kind="navplan",
        line_name="1065P1A",
        subline="070",
        sequence_no="070",
        first_sp=14200,
        last_sp=14300,
        line_direction="Up-line",
        sequence_id="70.1065P1A-070.a070.p190|070|1065P1A",
    )
    rows: list[Postplot4DDiffRow] = []
    for sp in range(14200, 14301):
        radial = 5.0
        if sp == 14280:
            radial = 14.73
        elif sp == 14281:
            radial = 13.5
        rows.append(
            Postplot4DDiffRow(
                shotpoint=sp,
                baseline_x=0.0,
                baseline_y=0.0,
                baseline_latitude="",
                baseline_longitude="",
                source_x=0.0,
                source_y=0.0,
                source_latitude="",
                source_longitude="",
                crossline_m=radial * 0.4,
                inline_m=1.0,
                radial_m=radial,
                firing_source_id="001",
            )
        )
    return match, rows


def _pixel_at_data(plot, shotpoint: float, value: float) -> tuple[int, int]:
    vb = plot.getViewBox()
    scene_pt = vb.mapViewToScene(pg.Point(shotpoint, value))
    widget_pt = plot.mapFromScene(scene_pt)
    return int(round(widget_pt.x())), int(round(widget_pt.y()))


def _sample_near(plot, shotpoint: float, value: float, image: QImage) -> QColor:
    x, y = _pixel_at_data(plot, shotpoint, value)
    x = max(0, min(image.width() - 1, x))
    y = max(0, min(image.height() - 1, y))
    best = image.pixelColor(x, y)
    for dx in range(-4, 5):
        for dy in range(-4, 5):
            sx = max(0, min(image.width() - 1, x + dx))
            sy = max(0, min(image.height() - 1, y + dy))
            color = image.pixelColor(sx, sy)
            if color.red() > best.red():
                best = color
    return best


def _near(color: QColor, hex_color: str) -> bool:
    target = QColor(hex_color)
    return (
        abs(color.red() - target.red()) <= 90
        and abs(color.green() - target.green()) <= 90
        and abs(color.blue() - target.blue()) <= 90
    )


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    match, diff_rows = _make_rows()
    view = Postplot4DStatPlotView()
    view.resize(1200, 900)
    view.set_data(match, diff_rows, streamers_detected=False)
    view._survey_panel.set_rows(
        [
            SurveySpecRow(
                statistic=StatType.MAX_VALUE,
                metric="radial",
                stat_value=12.0,
                absolute=True,
                severity=Severity.WARNING,
            ),
            SurveySpecRow(
                statistic=StatType.MAX_CONSECUTIVE_FAILED,
                metric="radial",
                reference_value=10.0,
                stat_value=3.0,
                severity=Severity.ERROR,
            ),
        ]
    )
    view._evaluate_survey()
    view._tabs.setCurrentWidget(view._tab_pages["radial"])
    view._refresh_all_tabs()
    view.show()

    failures: list[str] = []

    def _verify() -> None:
        import pyqtgraph as pg_mod

        if pg_mod.getConfigOption("useOpenGL"):
            failures.append("4D Stat plot must use CPU raster (useOpenGL=False)")

        canvas = view.canvas_for_kind("radial")
        if canvas is None or canvas._combined_plot is None:
            failures.append("radial canvas missing")
            _report(failures)
            app.quit()
            return

        plot = canvas._combined_plot
        flag_count = len(plot._flag_items)
        print(f"flag overlay scatter groups={flag_count}")
        if flag_count == 0:
            failures.append("no flag overlay markers on radial plot")

        image = canvas.capture_image(width=1000, height=480)
        screen_path = OUT_DIR / "radial_with_flags.png"
        image.save(str(screen_path))
        print(f"screen capture: {screen_path}")

        warn_px = _sample_near(plot, 14280.0, 14.73, image)
        print(f"  SP 14280 sample RGB=({warn_px.red()}, {warn_px.green()}, {warn_px.blue()})")
        if not _near(warn_px, _FLAG_WARNING_COLOR) and not _near(warn_px, _FLAG_ERROR_COLOR):
            failures.append(
                f"SP 14280 not flagged orange/red, got ({warn_px.red()}, {warn_px.green()}, {warn_px.blue()})"
            )

        pdf_path = OUT_DIR / "radial_with_flags.pdf"
        export_4d_stat_plot_pdf(
            view,
            pdf_path,
            Postplot4DStatPlotPdfOptions(
                output_dir=OUT_DIR,
                filename=pdf_path.name,
                include_crossline=False,
                include_inline=False,
                include_radial=True,
                include_feather=False,
                include_feather_diff=False,
            ),
        )
        if not pdf_path.is_file() or pdf_path.stat().st_size < 5000:
            failures.append("PDF export failed or too small")
        else:
            print(f"pdf export: {pdf_path} ({pdf_path.stat().st_size} bytes)")

        pdf_image = canvas.capture_image(width=1000, height=480, for_pdf=True, dpi=120)
        pdf_png = OUT_DIR / "radial_with_flags_pdf_render.png"
        pdf_image.save(str(pdf_png))
        print(f"pdf render capture: {pdf_png}")

        iterations = 25
        start = time.perf_counter()
        for _ in range(iterations):
            view._render_tab("radial")
            app.processEvents()
        ms = (time.perf_counter() - start) / iterations * 1000.0
        print(f"render speed: {ms:.1f} ms / radial tab refresh")
        if ms > 120.0:
            failures.append(f"render too slow: {ms:.1f} ms")

        _report(failures)
        app.quit()

    def _report(failures: list[str]) -> None:
        if failures:
            print("BRUTAL 4D STAT FLAG VISUAL: FAIL")
            for item in failures:
                print(f"  - {item}")
            sys.exit(1)
        print("BRUTAL 4D STAT FLAG VISUAL: PASS")

    QTimer.singleShot(500, _verify)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
