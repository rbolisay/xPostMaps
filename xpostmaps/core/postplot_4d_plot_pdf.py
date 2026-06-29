"""PDF export for 4D Stat time-series plots."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QFont,
    QImage,
    QPainter,
    QPdfWriter,
    QPixmap,
    QColor,
)
from PySide6.QtWidgets import QApplication

from xpostmaps.core.pdf_export import page_dimensions_mm, page_layout_for
from xpostmaps.core.postplot_4d_plot_data import (
    PlotKind,
    default_pdf_time_series_description,
    line_title,
    pdf_page_key,
)
from xpostmaps.ui.postplot_4d_stat_plot.plot_view import Postplot4DStatPlotView

DEFAULT_4D_STAT_PDF_REPORT_TITLE = "EOL 4D Report"
STAT_PLOT_PDF_DEFAULT_DPI = 600
STAT_PLOT_PDF_PREVIEW_DPI = 150

_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Postplot4DStatPlotPdfOptions:
    output_dir: Path
    filename: str
    paper: str = "A4"
    dpi: int = STAT_PLOT_PDF_DEFAULT_DPI
    landscape: bool = True
    margin_mm: float = 12.0
    report_title: str = DEFAULT_4D_STAT_PDF_REPORT_TITLE
    include_crossline: bool = True
    include_inline: bool = True
    include_radial: bool = True
    include_feather: bool = True
    include_feather_diff: bool = True
    time_series_descriptions: dict[str, str] = field(default_factory=dict)


@dataclass
class PlotPageSpec:
    kind: PlotKind
    export_sources: list[str]
    combine: bool
    page_key: str
    default_time_series_description: str


def resolve_4d_stat_output_path(options: Postplot4DStatPlotPdfOptions) -> Path:
    name = options.filename.strip() or "4d_stat_plot"
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"
    return options.output_dir / name


def _paper_size_mm(paper: str, *, landscape: bool) -> tuple[float, float]:
    return page_dimensions_mm(paper, landscape)


def resolve_logo_path(logo_path: str) -> Path | None:
    if logo_path.strip():
        candidate = Path(logo_path.strip())
        if candidate.is_file():
            return candidate
    for fallback in (
        _REPO_ROOT / "TierMaps_Logo.png",
        _REPO_ROOT / "TierMaps_Logo_grey.png",
        _REPO_ROOT / "TierMaps.png",
    ):
        if fallback.is_file():
            return fallback
    return None


def _font_pixel_size(base_pt: float, dpi: int) -> int:
    return max(1, int(round(base_pt * dpi / 72.0)))


def _page_header_height(dpi: int) -> int:
    pad = max(4, int(4 / 25.4 * dpi))
    gap = max(2, int(2 / 25.4 * dpi))
    logo_h = max(18, int(14 / 25.4 * dpi))
    title_h = _font_pixel_size(13, dpi) + 2
    meta_h = _font_pixel_size(8.5, dpi) + 1
    return pad + max(title_h, logo_h) + gap + meta_h * 2 + gap + max(3, int(3 / 25.4 * dpi))


def _draw_page_header(
    painter: QPainter,
    *,
    content_left: int,
    content_top: int,
    content_width: int,
    dpi: int,
    report_title: str,
    line_label: str,
    time_series_label: str,
    logo_file: Path | None,
) -> None:
    pad = max(4, int(4 / 25.4 * dpi))
    gap = max(2, int(2 / 25.4 * dpi))
    logo_h = max(18, int(14 / 25.4 * dpi))
    y = content_top + pad

    if logo_file is not None:
        logo = QPixmap(str(logo_file))
        if not logo.isNull():
            logo = logo.scaledToHeight(
                logo_h,
                Qt.TransformationMode.SmoothTransformation,
            )
            logo_x = content_left + content_width - logo.width()
            painter.drawPixmap(logo_x, y, logo)

    title_font = QFont("Segoe UI")
    title_font.setPixelSize(_font_pixel_size(13, dpi))
    title_font.setWeight(QFont.Weight.DemiBold)
    painter.setFont(title_font)
    painter.setPen(QColor("#111827"))
    title_metrics = painter.fontMetrics()
    painter.drawText(
        content_left,
        y + title_metrics.ascent(),
        report_title.strip() or DEFAULT_4D_STAT_PDF_REPORT_TITLE,
    )

    title_row_h = max(title_metrics.height(), logo_h)
    y += title_row_h + gap

    meta_font = QFont("Segoe UI")
    meta_font.setPixelSize(_font_pixel_size(8.5, dpi))
    painter.setFont(meta_font)
    painter.setPen(QColor("#4b5563"))
    meta_metrics = painter.fontMetrics()
    if line_label:
        painter.drawText(content_left, y + meta_metrics.ascent(), line_label)
        y += meta_metrics.height() + 1
    if time_series_label:
        painter.drawText(
            content_left,
            y + meta_metrics.ascent(),
            f"Time Series: {time_series_label}",
        )


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
    if options.include_feather_diff and "feather_diff" in available:
        selected.append("feather_diff")
    return selected


def default_4d_stat_pdf_filename(match_row) -> str:
    name = match_row.line_name or "4d_stat_plot"
    if match_row.subline:
        name = f"{name}_{match_row.subline}"
    return f"{name}_4d_stat_plot.pdf"


def iter_4d_stat_plot_page_specs(
    view: Postplot4DStatPlotView,
    options: Postplot4DStatPlotPdfOptions,
) -> list[PlotPageSpec]:
    match_row = view.match_row()
    if match_row is None:
        return []
    combine = view.combine_sources()
    specs: list[PlotPageSpec] = []
    for kind in resolved_plot_kinds(view, options):
        kind_styles = view.source_styles_for_kind(kind)
        export_source_nos = [row.source_no for row in kind_styles]
        export_sets = (
            [export_source_nos]
            if combine
            else [[source_no] for source_no in export_source_nos]
        )
        for export_sources in export_sets:
            page_key = pdf_page_key(
                kind,
                export_sources[0] if export_sources and not combine else None,
                combine=combine,
            )
            specs.append(
                PlotPageSpec(
                    kind=kind,
                    export_sources=export_sources,
                    combine=combine,
                    page_key=page_key,
                    default_time_series_description=default_pdf_time_series_description(
                        match_row,
                        source_nos=export_sources,
                        kind=kind,
                    ),
                )
            )
    return specs


def time_series_description_for_page(
    spec: PlotPageSpec,
    options: Postplot4DStatPlotPdfOptions,
) -> str:
    return options.time_series_descriptions.get(
        spec.page_key,
        spec.default_time_series_description,
    )


def _page_layout_pixels(
    options: Postplot4DStatPlotPdfOptions,
    *,
    dpi: int,
) -> tuple[int, int, int, int, int]:
    """Return page_w, page_h, content_left, content_top, content_width."""
    layout = page_layout_for(options.paper, options.landscape)
    page_rect = layout.paintRectPixels(dpi)
    page_w = page_rect.width()
    page_h = page_rect.height()
    margin_px = int(options.margin_mm / 25.4 * dpi)
    content_left = margin_px
    content_top = margin_px
    content_width = max(page_w - 2 * margin_px, 1)
    return page_w, page_h, content_left, content_top, content_width


@dataclass(frozen=True)
class _PlotPageGeometry:
    page_w: int
    page_h: int
    content_left: int
    content_top: int
    content_width: int
    header_height: int
    plot_width: int
    plot_height: int


def _plot_page_geometry(
    options: Postplot4DStatPlotPdfOptions,
    dpi: int,
) -> _PlotPageGeometry:
    """Shared page/plot pixel geometry for both raster preview and vector export."""
    page_w, page_h, content_left, content_top, content_width = _page_layout_pixels(
        options, dpi=dpi
    )
    header_height = _page_header_height(dpi)

    # Keep the plot's width:height aspect identical to landscape in every
    # orientation; in portrait the plot is simply scaled down (anchored under
    # the header) instead of being stretched to fill the tall page.
    margin_px = int(options.margin_mm / 25.4 * dpi)
    land_rect = page_layout_for(options.paper, True).paintRectPixels(dpi)
    land_plot_w = max(land_rect.width() - 2 * margin_px, 1)
    land_plot_h = max(land_rect.height() - 2 * margin_px - header_height, 1)
    landscape_aspect = land_plot_w / land_plot_h

    available_height = max(page_h - 2 * content_top - header_height, 1)
    plot_width = content_width
    plot_height = min(available_height, max(1, int(round(plot_width / landscape_aspect))))
    return _PlotPageGeometry(
        page_w=page_w,
        page_h=page_h,
        content_left=content_left,
        content_top=content_top,
        content_width=content_width,
        header_height=header_height,
        plot_width=plot_width,
        plot_height=plot_height,
    )


def _render_canvas_for_spec(
    view: Postplot4DStatPlotView,
    spec: PlotPageSpec,
    *,
    y_min,
    y_max,
    auto_y,
):
    """Render the canvas for one page spec; return (canvas, has_data).

    Series come from the view's combined builder so a multi-sequence plot
    exports every (source, sequence) line with the same data, framing and
    quality as on screen — the export just has more lines.
    """
    canvas = view.canvas_for_kind(spec.kind)
    if canvas is None:
        return None, False
    styles = view.source_styles_for_kind(spec.kind)
    boundaries = view.boundaries_for_kind(spec.kind)
    series_by_key = {
        series.source_no: series for series in view.build_series_for_kind(spec.kind)
    }
    series_list = [
        series_by_key[src]
        for src in spec.export_sources
        if src in series_by_key and series_by_key[src].shotpoints
    ]
    if not series_list:
        return canvas, False

    render_series = series_list if spec.combine else series_list[:1]
    canvas.set_combine_sources(spec.combine)
    canvas.render(
        render_series,
        styles,
        boundaries,
        y_min=y_min,
        y_max=y_max,
        auto_y=auto_y,
    )
    if not spec.combine and spec.export_sources:
        select_tab = getattr(canvas, "select_source_tab", None)
        if callable(select_tab):
            select_tab(spec.export_sources[0])
    QApplication.processEvents()
    return canvas, True


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

    page_specs = iter_4d_stat_plot_page_specs(view, options)
    if not page_specs:
        raise ValueError("Select at least one plot type to include in the PDF.")

    render_dpi = dpi if dpi is not None else options.dpi
    y_min, y_max = view.y_axis_range()
    auto_y = view.y_axis_auto()
    line_label = f"Line: {line_title(match_row)}"
    logo_file = resolve_logo_path(logo_path)

    geom = _plot_page_geometry(options, render_dpi)
    screen_ref_width = view.onscreen_plot_width()
    pages: list[QImage] = []

    for spec in page_specs:
        canvas, has_data = _render_canvas_for_spec(
            view, spec, y_min=y_min, y_max=y_max, auto_y=auto_y
        )
        if not has_data or canvas is None:
            continue

        time_series_text = time_series_description_for_page(spec, options)
        plot_image = canvas.capture_image(
            width=geom.plot_width,
            height=geom.plot_height,
            for_pdf=True,
            dpi=render_dpi,
            screen_ref_width=screen_ref_width,
        )

        page = QImage(geom.page_w, geom.page_h, QImage.Format.Format_ARGB32)
        page.fill(Qt.GlobalColor.white)
        painter = QPainter(page)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        _draw_page_header(
            painter,
            content_left=geom.content_left,
            content_top=geom.content_top,
            content_width=geom.content_width,
            dpi=render_dpi,
            report_title=options.report_title,
            line_label=line_label,
            time_series_label=time_series_text,
            logo_file=logo_file,
        )
        plot_top = geom.content_top + geom.header_height
        painter.drawImage(geom.content_left, plot_top, plot_image)
        painter.end()
        pages.append(page)

    if not pages:
        raise ValueError("No plot pages to export.")
    return pages


def render_4d_stat_plot_preview_pages(
    view: Postplot4DStatPlotView,
    options: Postplot4DStatPlotPdfOptions,
    *,
    logo_path: str = "",
    dpi: int = STAT_PLOT_PDF_PREVIEW_DPI,
) -> list[QImage]:
    """Render all export pages at preview resolution."""
    if not resolved_plot_kinds(view, options):
        return [_preview_placeholder_image("Select at least one plot")]
    try:
        return compose_4d_stat_plot_pages(
            view,
            options,
            logo_path=logo_path,
            dpi=dpi,
        )
    except ValueError:
        return [_preview_placeholder_image("Select at least one plot")]


def _preview_placeholder_image(message: str) -> QImage:
    image = QImage(640, 480, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    painter.setPen(Qt.GlobalColor.darkGray)
    painter.drawText(image.rect(), Qt.AlignmentFlag.AlignCenter, message)
    painter.end()
    return image


def render_4d_stat_plot_preview(
    view: Postplot4DStatPlotView,
    options: Postplot4DStatPlotPdfOptions,
    *,
    logo_path: str = "",
) -> QImage:
    """Render a lightweight preview of the first export page."""
    pages = render_4d_stat_plot_preview_pages(view, options, logo_path=logo_path)
    return pages[0]


def export_4d_stat_plot_pdf(
    view: Postplot4DStatPlotView,
    output_path: Path,
    options: Postplot4DStatPlotPdfOptions,
    *,
    logo_path: str = "",
) -> None:
    """Export the selected 4D Stat plots to a PDF.

    Hybrid composition mirroring the map export: the report header (title, line
    metadata, logo) is painted as true vector content directly onto the
    ``QPdfWriter`` painter, while the pyqtgraph plot body is embedded as a
    high-resolution (export-DPI) raster. pyqtgraph's axis tick layout does not
    survive being painted straight onto a PDF paint device, so the plot itself
    is rasterised at full export resolution exactly like the map's right pane.
    """
    match_row = view.match_row()
    if match_row is None:
        raise ValueError("No 4D Stat match row loaded for PDF export.")

    page_specs = iter_4d_stat_plot_page_specs(view, options)
    if not page_specs:
        raise ValueError("Select at least one plot type to include in the PDF.")

    export_dpi = options.dpi
    y_min, y_max = view.y_axis_range()
    auto_y = view.y_axis_auto()
    line_label = f"Line: {line_title(match_row)}"
    logo_file = resolve_logo_path(logo_path)

    geom = _plot_page_geometry(options, export_dpi)
    # Measure the on-screen plot width once, before any export re-render replaces
    # the live plot widgets, so markers keep their on-screen size on every page.
    screen_ref_width = view.onscreen_plot_width()

    layout = page_layout_for(options.paper, options.landscape)
    writer = QPdfWriter(str(output_path))
    writer.setResolution(export_dpi)
    writer.setPageLayout(layout)
    page_rect = layout.paintRectPixels(export_dpi)
    origin_x = page_rect.x()
    origin_y = page_rect.y()

    painter = QPainter(writer)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    rendered_any = False
    try:
        for spec in page_specs:
            canvas, has_data = _render_canvas_for_spec(
                view,
                spec,
                y_min=y_min,
                y_max=y_max,
                auto_y=auto_y,
            )
            if not has_data or canvas is None:
                continue

            if rendered_any:
                writer.newPage()
            rendered_any = True

            painter.fillRect(page_rect, Qt.GlobalColor.white)
            time_series_text = time_series_description_for_page(spec, options)
            _draw_page_header(
                painter,
                content_left=origin_x + geom.content_left,
                content_top=origin_y + geom.content_top,
                content_width=geom.content_width,
                dpi=export_dpi,
                report_title=options.report_title,
                line_label=line_label,
                time_series_label=time_series_text,
                logo_file=logo_file,
            )
            plot_image = canvas.capture_image(
                width=geom.plot_width,
                height=geom.plot_height,
                for_pdf=True,
                dpi=export_dpi,
                screen_ref_width=screen_ref_width,
            )
            plot_x = origin_x + geom.content_left
            plot_y = origin_y + geom.content_top + geom.header_height
            painter.drawImage(plot_x, plot_y, plot_image)
    finally:
        painter.end()

    if not rendered_any:
        raise ValueError("No plot pages to export.")
