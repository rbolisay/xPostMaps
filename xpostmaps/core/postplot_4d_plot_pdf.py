"""PDF export for 4D Stat time-series plots."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QMarginsF, Qt, QSizeF
from PySide6.QtGui import (
    QFont,
    QImage,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem, QWidget

from xpostmaps.core.pdf_export import page_dimensions_mm
from xpostmaps.core.postplot_4d_plot_data import (
    PLOT_KIND_LABELS,
    PLOT_KIND_PDF_LABELS,
    PLOT_KIND_UNITS,
    PlotKind,
    SeriesStats,
    build_plot_series,
    compute_series_stats,
    line_title,
    primary_vessel_id,
    time_series_title,
)
from xpostmaps.ui.postplot_4d_stat_plot.plot_view import Postplot4DStatPlotView


@dataclass
class Postplot4DStatPlotPdfOptions:
    output_dir: Path
    filename: str
    paper: str = "A4"
    dpi: int = 300
    landscape: bool = False
    margin_mm: float = 12.0
    include_crossline: bool = True
    include_inline: bool = True
    include_radial: bool = True
    include_feather: bool = True


def resolve_4d_stat_output_path(options: Postplot4DStatPlotPdfOptions) -> Path:
    name = options.filename.strip() or "4d_stat_plot"
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"
    return options.output_dir / name


def _paper_size_mm(paper: str, *, landscape: bool) -> tuple[float, float]:
    return page_dimensions_mm(paper, landscape)


def resolved_plot_kinds(
    view: Postplot4DStatPlotView,
    options: Postplot4DStatPlotPdfOptions,
) -> list[PlotKind]:
    available = set(view.available_plot_kinds())
    selected: list[PlotKind] = []
    if options.include_crossline and "crossline" in available:
        selected.append("crossline")
    if options.include_inline and "inline" in available:
        selected.append("inline")
    if options.include_radial and "radial" in available:
        selected.append("radial")
    if options.include_feather and "feather" in available:
        selected.append("feather")
    return selected


def default_4d_stat_pdf_filename(match_row) -> str:
    name = match_row.line_name or "4d_stat_plot"
    if match_row.subline:
        name = f"{name}_{match_row.subline}"
    return f"{name}_4d_stat_plot.pdf"


def _render_plot_image(canvas, *, width: int, height: int) -> QImage:
    capture = getattr(canvas, "capture_image", None)
    if callable(capture):
        return capture(width=width, height=height)
    return _render_widget_image(canvas, width=width, height=height)


def _render_widget_image(widget: QWidget, *, width: int, height: int) -> QImage:
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.white)
    widget.resize(width, height)
    widget.render(image)
    QApplication.processEvents()
    return image


def _stats_table_widget(stats_rows: list[SeriesStats]) -> QTableWidget:
    table = QTableWidget(len(stats_rows), 6)
    table.setHorizontalHeaderLabels(
        ["Attribute", "Min", "Max", "Mean", "Std dev", "RMS"]
    )
    for row_idx, stats in enumerate(stats_rows):
        values = [
            stats.attribute,
            f"{stats.minimum:.2f}",
            f"{stats.maximum:.2f}",
            f"{stats.mean:.2f}",
            f"{stats.std_dev:.2f}",
            f"{stats.rms:.2f}",
        ]
        for col, text in enumerate(values):
            item = QTableWidgetItem(text)
            if col > 0:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(row_idx, col, item)
    table.resizeColumnsToContents()
    table.resizeRowsToContents()
    table.setFixedSize(table.sizeHint())
    return table


def _page_layout_pixels(
    options: Postplot4DStatPlotPdfOptions,
    *,
    dpi: int,
) -> tuple[int, int, int, int, int]:
    """Return page_w, page_h, content_left, content_top, content_width."""
    width_mm, height_mm = _paper_size_mm(options.paper, landscape=options.landscape)
    page_w = int(width_mm / 25.4 * dpi)
    page_h = int(height_mm / 25.4 * dpi)
    margin_px = int(options.margin_mm / 25.4 * dpi)
    content_left = margin_px
    content_top = margin_px
    content_width = page_w - 2 * margin_px
    return page_w, page_h, content_left, content_top, content_width


def compose_4d_stat_plot_pages(
    view: Postplot4DStatPlotView,
    options: Postplot4DStatPlotPdfOptions,
    *,
    logo_path: str = "",
    dpi: int | None = None,
) -> list[QImage]:
    """Render each selected plot type (and source when uncombined) to a page image."""
    match_row = view.match_row()
    if match_row is None:
        raise ValueError("No 4D Stat match row loaded for PDF export.")

    render_dpi = dpi if dpi is not None else options.dpi
    kinds = resolved_plot_kinds(view, options)
    if not kinds:
        raise ValueError("Select at least one plot type to include in the PDF.")

    diff_rows = view.diff_rows()
    vessel_id = primary_vessel_id(diff_rows)
    y_min, y_max = view.y_axis_range()
    auto_y = view.y_axis_auto()
    combine = view.combine_sources()

    page_w, page_h, content_left, content_top, content_width = _page_layout_pixels(
        options,
        dpi=render_dpi,
    )
    plot_width = content_width
    plot_height = int(plot_width * 0.42)

    title_font = QFont("Segoe UI", 11)
    body_font = QFont("Segoe UI", 9)
    line_label = f"Line: {line_title(match_row)}"

    pages: list[QImage] = []

    def _draw_plot_page(
        painter: QPainter,
        y_cursor: int,
        kind: PlotKind,
        export_sources: list[str],
        *,
        page_combine: bool,
    ) -> int:
        canvas = view.canvas_for_kind(kind)
        if canvas is None:
            return y_cursor
        styles = view.source_styles_for_kind(kind)
        boundaries = view.boundaries_for_kind(kind)
        sources = [row.source_no for row in styles]
        series_list = [
            build_plot_series(diff_rows, match_row, kind, src)
            for src in export_sources
        ]
        series_list = [item for item in series_list if item.shotpoints]
        if not series_list:
            return y_cursor

        for source_no in export_sources if not page_combine else export_sources[:1]:
            header_source = source_no if not page_combine else ", ".join(export_sources)
            header = time_series_title(
                match_row,
                vessel_id=vessel_id,
                source_no=header_source if page_combine else source_no,
                kind=kind,
            )
            painter.setFont(body_font)
            painter.drawText(content_left, y_cursor + painter.fontMetrics().ascent(), header)
            y_cursor += int(painter.fontMetrics().height() * 1.4)

            render_sources = export_sources if page_combine else [source_no]
            canvas.set_combine_sources(page_combine)
            canvas.render(
                [
                    build_plot_series(diff_rows, match_row, kind, src)
                    for src in render_sources
                ],
                styles,
                boundaries,
                y_min=y_min,
                y_max=y_max,
                auto_y=auto_y,
            )
            if not page_combine and export_sources:
                select_tab = getattr(canvas, "select_source_tab", None)
                if callable(select_tab):
                    select_tab(export_sources[0])
            plot_image = _render_plot_image(canvas, width=plot_width, height=plot_height)
            painter.drawImage(content_left, y_cursor, plot_image)
            y_cursor += plot_height + int(painter.fontMetrics().height() * 0.8)

            caption = (
                f"Figure 1: Time-series ({PLOT_KIND_PDF_LABELS[kind]}, "
                f"{PLOT_KIND_UNITS[kind]})"
            )
            painter.drawText(content_left, y_cursor + painter.fontMetrics().ascent(), caption)
            y_cursor += int(painter.fontMetrics().height() * 1.2)

            stats_rows: list[SeriesStats] = []
            for src in render_sources:
                src_series = build_plot_series(diff_rows, match_row, kind, src)
                stats = compute_series_stats(src, src_series.values)
                if stats is not None:
                    stats_rows.append(stats)
            if stats_rows:
                table = _stats_table_widget(stats_rows)
                table_h = max(table.sizeHint().height(), 40)
                table_image = _render_widget_image(table, width=plot_width, height=table_h)
                painter.drawImage(content_left, y_cursor, table_image)
                y_cursor += table_h + int(painter.fontMetrics().height() * 0.5)

            if not page_combine:
                break
        return y_cursor

    for kind in kinds:
        kind_styles = view.source_styles_for_kind(kind)
        export_source_nos = [row.source_no for row in kind_styles]
        export_sets = [export_source_nos] if combine else [[source_no] for source_no in export_source_nos]
        for export_sources in export_sets:
            page = QImage(page_w, page_h, QImage.Format.Format_ARGB32)
            page.fill(Qt.GlobalColor.white)
            painter = QPainter(page)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            y_cursor = content_top

            if logo_path and Path(logo_path).is_file():
                logo = QPixmap(logo_path)
                if not logo.isNull():
                    logo_height = int(18 / 25.4 * render_dpi)
                    logo = logo.scaledToHeight(
                        logo_height,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    logo_x = content_left + content_width - logo.width()
                    painter.drawPixmap(logo_x, y_cursor, logo)

            painter.setFont(title_font)
            painter.drawText(content_left, y_cursor + painter.fontMetrics().ascent(), line_label)
            y_cursor += int(painter.fontMetrics().height() * 1.8)

            _draw_plot_page(
                painter,
                y_cursor,
                kind,
                export_sources,
                page_combine=combine,
            )
            painter.end()
            pages.append(page)

    return pages


def render_4d_stat_plot_preview(
    view: Postplot4DStatPlotView,
    options: Postplot4DStatPlotPdfOptions,
    *,
    logo_path: str = "",
) -> QImage:
    """Render a lightweight preview of the first export page."""
    try:
        pages = compose_4d_stat_plot_pages(
            view,
            options,
            logo_path=logo_path,
            dpi=120,
        )
    except ValueError:
        image = QImage(640, 480, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.white)
        painter = QPainter(image)
        painter.setPen(Qt.GlobalColor.darkGray)
        painter.drawText(image.rect(), Qt.AlignmentFlag.AlignCenter, "Select at least one plot")
        painter.end()
        return image
    return pages[0]


def export_4d_stat_plot_pdf(
    view: Postplot4DStatPlotView,
    output_path: Path,
    options: Postplot4DStatPlotPdfOptions,
    *,
    logo_path: str = "",
) -> None:
    pages = compose_4d_stat_plot_pages(view, options, logo_path=logo_path)
    if not pages:
        raise ValueError("No plot pages to export.")

    writer = QPdfWriter(str(output_path))
    page_w_mm, page_h_mm = page_dimensions_mm(options.paper, options.landscape)
    writer.setPageSize(
        QPageSize(QSizeF(page_w_mm, page_h_mm), QPageSize.Unit.Millimeter)
    )
    writer.setPageOrientation(
        QPageLayout.Orientation.Landscape
        if options.landscape
        else QPageLayout.Orientation.Portrait
    )
    writer.setResolution(options.dpi)
    margins = QMarginsF(
        options.margin_mm,
        options.margin_mm,
        options.margin_mm,
        options.margin_mm,
    )
    writer.setPageMargins(margins, QPageLayout.Unit.Millimeter)

    painter = QPainter(writer)
    for index, page in enumerate(pages):
        if index > 0:
            writer.newPage()
        target = writer.pageLayout().paintRectPixels(writer.resolution())
        scaled = page.scaled(
            target.size(),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter.drawImage(target.topLeft(), scaled)
    painter.end()
