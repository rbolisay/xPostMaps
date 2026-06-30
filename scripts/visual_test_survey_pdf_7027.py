"""Visual QA for survey plot PDF export + preview on real 7027 data."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from xpostmaps.core.database import Database
from xpostmaps.core.postplot_4d_matching import build_postplot_4d_rows
from xpostmaps.core.postplot_4d_survey_plot_pdf import (
    Postplot4DSurveyPlotPdfOptions,
    compose_survey_plot_pages,
    export_survey_plot_pdf,
    iter_survey_plot_page_specs,
    render_survey_plot_preview_pages,
    resolve_survey_plot_output_path,
)
from xpostmaps.core.survey_plot_pdf_guardrails import validate_aerial_page_image
from xpostmaps.core.postplot_4d_survey_plots_worker import SurveyPlotsLoadWorker
from xpostmaps.ui.postplot_4d_survey_plots.survey_plots_view import Postplot4DSurveyPlotsView

DB = ROOT / "data" / "7027.db"
OUT_DIR = ROOT / "data" / "pdf_qa" / "survey_pdf_7027"
PDF_OUT = ROOT / "data" / "preplot_survey_plots.pdf"


def _is_white(color: QColor, *, threshold: int = 248) -> bool:
    return (
        color.red() >= threshold
        and color.green() >= threshold
        and color.blue() >= threshold
    )


def _sample_colored(image: QImage, x0: int, x1: int, y0: int, y1: int, step: int = 6) -> int:
    colored = 0
    for y in range(y0, y1, step):
        for x in range(x0, x1, step):
            if not _is_white(image.pixelColor(x, y)):
                colored += 1
    return colored


def _sample_color_match(
    image: QImage,
    x0: int,
    x1: int,
    y0: int,
    y1: int,
    *,
    target: tuple[int, int, int],
    tolerance: int = 80,
    step: int = 8,
) -> int:
    tr, tg, tb = target
    matched = 0
    for y in range(y0, y1, step):
        for x in range(x0, x1, step):
            color = image.pixelColor(x, y)
            if (
                abs(color.red() - tr) <= tolerance
                and abs(color.green() - tg) <= tolerance
                and abs(color.blue() - tb) <= tolerance
            ):
                matched += 1
    return matched


def _load_result():
    db = Database(DB)
    settings, map_data = db.load_project("7027", with_positions=False)
    matched = [
        row
        for row in build_postplot_4d_rows(map_data, settings, "preplot")
        if row.has_match
    ]
    result_box: list = []
    worker = SurveyPlotsLoadWorker(DB, "7027", "preplot", matched)
    worker.finished_ok.connect(
        lambda result: result_box.append(result),
        Qt.ConnectionType.DirectConnection,
    )
    worker.start()
    worker.wait()
    return result_box[0]


def _plot_region(image: QImage) -> tuple[int, int, int, int]:
    width = image.width()
    height = image.height()
    header_h = max(1, int(height * 0.14))
    return 40, width - 20, header_h + 20, height - 20


def _assert_page(page, index: int) -> list[str]:
    errors: list[str] = []
    image = page.image
    if image.isNull():
        return [f"page {index + 1}: null image"]

    x0, x1, y0, y1 = _plot_region(image)
    plot_colored = _sample_colored(image, x0, x1, y0, y1)
    if plot_colored < 20:
        errors.append(f"page {index + 1} ({page.spec.page_key}): plot area too blank")

    kind = page.spec.page_kind.value
    if kind == "aerial":
        errors.extend(
            validate_aerial_page_image(image, page_key=page.spec.page_key)
        )

    if kind == "histogram":
        center_x = (x0 + x1) // 2
        center_y = (y0 + y1) // 2
        center_colored = _sample_colored(
            image,
            center_x - 80,
            center_x + 80,
            center_y - 60,
            center_y + 60,
        )
        if center_colored < 15:
            errors.append(
                f"page {index + 1} ({page.spec.page_key}): histogram too small or off-center"
            )

    if kind == "pie":
        pass_green = _sample_color_match(image, x0, x1, y0, y1, target=(34, 197, 94))
        fail_red = _sample_color_match(image, x0, x1, y0, y1, target=(239, 68, 68))
        alt_green = _sample_color_match(image, x0, x1, y0, y1, target=(34, 197, 94), tolerance=100)
        alt_red = _sample_color_match(image, x0, x1, y0, y1, target=(185, 28, 28), tolerance=100)
        if max(pass_green, alt_green) < 3 and max(fail_red, alt_red) < 3:
            errors.append(
                f"page {index + 1} ({page.spec.page_key}): pie slices not visible "
                f"(green={pass_green}, red={fail_red})"
            )

    overlap_colored = _sample_colored(image, x0, x1 - 180, y0 - 28, y0 + 8)
    if overlap_colored > 30:
        errors.append(f"page {index + 1} ({page.spec.page_key}): plot overlaps header")

    return errors


def main() -> int:
    if not DB.is_file():
        print(f"Missing database: {DB}")
        return 1

    app = QApplication([])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PDF_OUT.parent.mkdir(parents=True, exist_ok=True)

    result = _load_result()
    view = Postplot4DSurveyPlotsView()
    view.resize(1400, 900)
    view.show()
    view.apply_load_result(result)
    view.refresh_all()
    app.processEvents()

    options = Postplot4DSurveyPlotPdfOptions(
        output_dir=PDF_OUT.parent,
        filename=PDF_OUT.name,
        dpi=150,
        landscape=True,
        report_title="Survey 4D Report",
        include_survey_specs_pie=True,
    )
    specs = iter_survey_plot_page_specs(view, options)
    pie_count = sum(1 for spec in specs if spec.page_kind.value == "pie")
    print(f"Expected pages: {len(specs)} (pies={pie_count}, charts={len(result.pie_charts)})")

    preview_pages = render_survey_plot_preview_pages(view, options)
    export_pages = compose_survey_plot_pages(view, options, dpi=150)

    if len(preview_pages) != len(specs):
        print(f"FAIL: preview pages {len(preview_pages)} != specs {len(specs)}")
        return 1
    if len(export_pages) != len(specs):
        print(f"FAIL: export pages {len(export_pages)} != specs {len(specs)}")
        return 1
    if pie_count != len(result.pie_charts):
        print(f"FAIL: pie specs {pie_count} != charts {len(result.pie_charts)}")
        return 1

    failures: list[str] = []
    for label, pages in (("preview", preview_pages), ("export", export_pages)):
        for index, page in enumerate(pages):
            png = OUT_DIR / f"{label}_page_{index + 1:02d}_{page.spec.page_key.replace(':', '_')}.png"
            page.image.save(str(png))
            failures.extend(_assert_page(page, index))
            print(f"[{label}] saved {png.name} ({page.spec.page_key})")

    export_survey_plot_pdf(view, PDF_OUT, options)
    pdf_kb = PDF_OUT.stat().st_size // 1024
    print(f"PDF: {PDF_OUT} ({pdf_kb} KB, {len(export_pages)} pages)")

    if failures:
        print("FAILURES:")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("Survey PDF 7027 preview + export visual QA passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
