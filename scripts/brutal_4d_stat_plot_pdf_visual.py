"""Visual QA for 4D Stat Plot PDF page composition at multiple DPI/orientations."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from xpostmaps.core.postplot_4d_diff import Postplot4DDiffRow  # noqa: E402
from xpostmaps.core.postplot_4d_matching import Postplot4DMatchRow  # noqa: E402
from xpostmaps.core.postplot_4d_plot_data import BoundaryRow  # noqa: E402
from xpostmaps.core.postplot_4d_plot_pdf import (  # noqa: E402
    Postplot4DStatPlotPdfOptions,
    compose_4d_stat_plot_pages,
    export_4d_stat_plot_pdf,
)
from xpostmaps.ui.postplot_4d_stat_plot.plot_view import Postplot4DStatPlotView  # noqa: E402

OUT_DIR = ROOT / "data" / "brutal_4d_stat_plot_pdf"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _make_rows() -> tuple[Postplot4DMatchRow, list[Postplot4DDiffRow]]:
    match = Postplot4DMatchRow(
        baseline_name="1065P1A",
        baseline_kind="navplan",
        line_name="1065P1A",
        subline="070",
        sequence_no="070",
        first_sp=1000,
        last_sp=1040,
        line_direction="Up-line",
        sequence_id="70.1065P1A-070.a070.p190|070|1065P1A",
    )
    rows: list[Postplot4DDiffRow] = []
    for sp in range(1000, 1041):
        for source_id, offset in (("001", -1.0), ("002", 1.5)):
            cross = float(np.sin((sp - 1000) / 4.0) * 8.0 + offset * 2.0)
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
                    crossline_m=cross,
                    inline_m=cross * 0.3,
                    radial_m=abs(cross),
                    firing_source_id=source_id,
                )
            )
    return match, rows


def _plot_content_bounds(image: QImage) -> tuple[int, int, int, int]:
    """Bounding box (top, bottom, left, right) of non-white pixels below the header."""
    w = image.width()
    h = image.height()
    header = int(h * 0.16)
    top, bottom, left, right = h, header, w, 0
    found = False
    step = max(1, min(w, h) // 500)
    for y in range(header, h, step):
        for x in range(0, w, step):
            color = image.pixelColor(x, y)
            if color.red() < 250 or color.green() < 250 or color.blue() < 250:
                found = True
                top = min(top, y)
                bottom = max(bottom, y)
                left = min(left, x)
                right = max(right, x)
    if not found:
        return header, h, 0, w
    return top, bottom, left, right


def _plot_fill_ratio(image: QImage) -> float:
    """Fraction of non-white pixels inside the rendered plot rectangle."""
    w = image.width()
    h = image.height()
    if w <= 0 or h <= 0:
        return 0.0
    top, bottom, left, right = _plot_content_bounds(image)
    if bottom <= top or right <= left:
        return 0.0
    non_white = 0
    sampled = 0
    for y in range(top, bottom, 3):
        for x in range(left, right, 3):
            sampled += 1
            color = image.pixelColor(x, y)
            if color.red() < 250 or color.green() < 250 or color.blue() < 250:
                non_white += 1
    return non_white / max(sampled, 1)


def _legend_present(image: QImage) -> bool:
    """Detect the legend band just below the plot's curve area (orientation-agnostic)."""
    w = image.width()
    top, bottom, _left, _right = _plot_content_bounds(image)
    band_top = max(top, bottom - int((bottom - top) * 0.08))
    for y in range(band_top, bottom + 1, 2):
        for x in range(int(w * 0.35), int(w * 0.65), 2):
            color = image.pixelColor(x, y)
            if color.red() < 240 or color.green() < 240 or color.blue() < 240:
                return True
    return False


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    match, diff_rows = _make_rows()
    view = Postplot4DStatPlotView()
    view.resize(1200, 900)
    view.set_data(match, diff_rows, streamers_detected=False)
    view._tab_controls["crossline"].set_boundaries(
        [BoundaryRow(abs_boundary=5.0), BoundaryRow(abs_boundary=9.0)]
    )
    view.show()

    failures: list[str] = []

    def _verify() -> None:
        cases = (
            ("landscape_150", True, 150),
            ("landscape_600", True, 600),
            ("portrait_150", False, 150),
            ("portrait_600", False, 600),
        )
        for label, landscape, dpi in cases:
            options = Postplot4DStatPlotPdfOptions(
                output_dir=OUT_DIR,
                filename=f"{label}.pdf",
                landscape=landscape,
                dpi=dpi,
                include_inline=False,
                include_radial=False,
                include_feather=False,
                include_feather_diff=False,
            )
            pages = compose_4d_stat_plot_pages(view, options, dpi=dpi)
            if not pages:
                failures.append(f"{label}: no pages composed")
                continue
            page = pages[0]
            png_path = OUT_DIR / f"{label}.png"
            page.save(str(png_path))
            fill = _plot_fill_ratio(page)
            legend = _legend_present(page)
            print(
                f"{label}: {page.width()}x{page.height()} fill={fill:.3f} legend={legend} -> {png_path}"
            )
            if fill < 0.004:
                failures.append(f"{label}: plot area too empty (fill={fill:.3f})")
            if not legend:
                failures.append(f"{label}: legend not detected below plot")
            if landscape and page.width() <= page.height():
                failures.append(f"{label}: landscape page not wider than tall")
            if not landscape and page.height() <= page.width():
                failures.append(f"{label}: portrait page not taller than wide")

            pdf_path = OUT_DIR / f"{label}.pdf"
            export_4d_stat_plot_pdf(view, pdf_path, options)
            print(f"  pdf: {pdf_path}")

        if failures:
            print("BRUTAL 4D STAT PLOT PDF VISUAL: FAIL")
            for item in failures:
                print(f"  - {item}")
            app.quit()
            sys.exit(1)

        print("BRUTAL 4D STAT PLOT PDF VISUAL: PASS")
        app.quit()

    QTimer.singleShot(500, _verify)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
