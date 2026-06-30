"""PDF export for survey-wide 4D plots (aerials, histograms, spec pies)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QPdfWriter
from PySide6.QtWidgets import QApplication

from xpostmaps.core.pdf_export import page_layout_for
from xpostmaps.core.postplot_4d_plot_data import (
    PlotKind,
    default_source_styles,
)
from xpostmaps.core.postplot_4d_plot_pdf import (
    STAT_PLOT_PDF_DEFAULT_DPI,
    STAT_PLOT_PDF_PREVIEW_DPI,
    _PlotPageGeometry,
    _draw_page_header,
    _font_pixel_size,
    _page_header_height,
    _page_layout_pixels,
    resolve_logo_path,
)
from xpostmaps.core.survey_plot_pdf_guardrails import validate_aerial_plot_body
from xpostmaps.ui.postplot_4d_survey_plots.survey_plots_view import Postplot4DSurveyPlotsView

DEFAULT_SURVEY_PLOT_PDF_REPORT_TITLE = "Survey 4D Report"


class SurveyPlotPageKind(str, Enum):
    AERIAL = "aerial"
    HISTOGRAM = "histogram"
    PIE = "pie"


@dataclass
class SurveyPlotPageSpec:
    page_kind: SurveyPlotPageKind
    metric_kind: PlotKind | None
    page_key: str
    plot_title: str
    description: str
    pie_index: int | None = None


@dataclass
class Postplot4DSurveyPlotPdfOptions:
    output_dir: Path
    filename: str
    paper: str = "A4"
    dpi: int = STAT_PLOT_PDF_DEFAULT_DPI
    landscape: bool = True
    margin_mm: float = 12.0
    report_title: str = DEFAULT_SURVEY_PLOT_PDF_REPORT_TITLE
    include_aerial_crossline: bool = True
    include_aerial_inline: bool = True
    include_aerial_radial: bool = True
    include_aerial_feather: bool = True
    include_aerial_feather_diff: bool = True
    include_histogram_crossline: bool = True
    include_histogram_inline: bool = True
    include_histogram_radial: bool = True
    include_histogram_feather: bool = True
    include_histogram_feather_diff: bool = True
    include_survey_specs_pie: bool = True
    page_descriptions: dict[str, str] = field(default_factory=dict)


@dataclass
class ComposedSurveyPlotPage:
    spec: SurveyPlotPageSpec
    image: QImage


@dataclass
class _GeometryAdapter:
    paper: str
    landscape: bool
    margin_mm: float


def resolve_survey_plot_output_path(options: Postplot4DSurveyPlotPdfOptions) -> Path:
    name = options.filename.strip() or "survey_plots"
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"
    return options.output_dir / name


def default_survey_plot_pdf_filename(baseline_kind: str = "survey") -> str:
    return f"{baseline_kind}_survey_plots.pdf"


def _aerial_flag(options: Postplot4DSurveyPlotPdfOptions, kind: PlotKind) -> bool:
    return {
        "crossline": options.include_aerial_crossline,
        "inline": options.include_aerial_inline,
        "radial": options.include_aerial_radial,
        "feather": options.include_aerial_feather,
        "feather_diff": options.include_aerial_feather_diff,
    }.get(kind, False)


def _histogram_flag(options: Postplot4DSurveyPlotPdfOptions, kind: PlotKind) -> bool:
    return {
        "crossline": options.include_histogram_crossline,
        "inline": options.include_histogram_inline,
        "radial": options.include_histogram_radial,
        "feather": options.include_histogram_feather,
        "feather_diff": options.include_histogram_feather_diff,
    }.get(kind, False)


def iter_survey_plot_page_specs(
    view: Postplot4DSurveyPlotsView,
    options: Postplot4DSurveyPlotPdfOptions,
) -> list[SurveyPlotPageSpec]:
    sets = view.diff_sets()
    cache = view.metric_cache()
    if not sets:
        return []
    available = set(view.available_plot_kinds())
    specs: list[SurveyPlotPageSpec] = []
    for kind in ("crossline", "inline", "radial", "feather", "feather_diff"):
        if kind not in available:
            continue
        metric: PlotKind = kind  # type: ignore[assignment]
        if _aerial_flag(options, metric):
            heatmap = view.heatmap_cache().get(metric)
            if heatmap is None:
                continue
            page_key = f"aerial:{metric}"
            plot_title = view.aerial_title(metric)
            specs.append(
                SurveyPlotPageSpec(
                    page_kind=SurveyPlotPageKind.AERIAL,
                    metric_kind=metric,
                    page_key=page_key,
                    plot_title=plot_title,
                    description=options.page_descriptions.get(page_key, ""),
                )
            )
        if _histogram_flag(options, metric):
            if metric not in view.histogram_cache():
                continue
            page_key = f"histogram:{metric}"
            specs.append(
                SurveyPlotPageSpec(
                    page_kind=SurveyPlotPageKind.HISTOGRAM,
                    metric_kind=metric,
                    page_key=page_key,
                    plot_title=view.histogram_title(metric),
                    description=options.page_descriptions.get(page_key, ""),
                )
            )
    if options.include_survey_specs_pie:
        for index, chart in enumerate(view.pie_charts()):
            page_key = f"survey_specs_pie:{index}"
            specs.append(
                SurveyPlotPageSpec(
                    page_kind=SurveyPlotPageKind.PIE,
                    metric_kind=None,
                    page_key=page_key,
                    plot_title=f"{chart.headline} — {chart.title}",
                    description=chart.subtitle,
                    pie_index=index,
                )
            )
    return specs


def description_for_page(
    spec: SurveyPlotPageSpec,
    options: Postplot4DSurveyPlotPdfOptions,
) -> str:
    return options.page_descriptions.get(spec.page_key, spec.description)


def _survey_page_header_height(dpi: int) -> int:
    """Header with report title + plot title only (no survey line label row)."""
    meta_h = _font_pixel_size(8.5, dpi) + 1
    return _page_header_height(dpi) - meta_h


def _draw_survey_page_header(
    painter: QPainter,
    *,
    content_left: int,
    content_top: int,
    content_width: int,
    dpi: int,
    report_title: str,
    plot_title: str,
    logo_file: Path | None,
) -> None:
    _draw_page_header(
        painter,
        content_left=content_left,
        content_top=content_top,
        content_width=content_width,
        dpi=dpi,
        report_title=report_title,
        line_label="",
        time_series_label=plot_title.strip(),
        logo_file=logo_file,
        time_series_prefix=None,
    )


def _geometry(options: Postplot4DSurveyPlotPdfOptions, dpi: int) -> _PlotPageGeometry:
    adapter = _GeometryAdapter(
        paper=options.paper,
        landscape=options.landscape,
        margin_mm=options.margin_mm,
    )
    page_w, page_h, content_left, content_top, content_width = _page_layout_pixels(
        adapter,
        dpi=dpi,
    )
    header_height = _survey_page_header_height(dpi)
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


def _header_plot_label(
    spec: SurveyPlotPageSpec,
    options: Postplot4DSurveyPlotPdfOptions,
) -> str:
    title = spec.plot_title.strip()
    desc = description_for_page(spec, options).strip()
    if desc and desc != title:
        return f"{title} — {desc}" if title else desc
    return title


def _prepare_view_for_capture(
    view: Postplot4DSurveyPlotsView,
    spec: SurveyPlotPageSpec,
) -> None:
    view.prepare_for_pdf_capture(
        page_kind=spec.page_kind.value,
        metric_kind=spec.metric_kind,
        pie_index=spec.pie_index,
    )


def _render_page_image(
    view: Postplot4DSurveyPlotsView,
    spec: SurveyPlotPageSpec,
    *,
    width: int,
    height: int,
    dpi: int,
) -> QImage | None:
    _prepare_view_for_capture(view, spec)
    sets = view.diff_sets()
    cache = view.metric_cache()
    if spec.page_kind == SurveyPlotPageKind.PIE:
        charts = view.pie_charts()
        if not charts:
            return None
        pie_index = spec.pie_index if spec.pie_index is not None else 0
        view.pie_panel().render(charts)
        QApplication.processEvents()
        return view.pie_panel().capture_page_image(
            pie_index,
            width=width,
            height=height,
            for_pdf=True,
            dpi=dpi,
        )
    if spec.metric_kind is None:
        return None
    kind = spec.metric_kind
    if spec.page_kind == SurveyPlotPageKind.AERIAL:
        canvas = view.aerial_canvas(kind)
        if canvas is None:
            return None
        heatmap = view.heatmap_cache().get(kind)
        if heatmap is None:
            return None
        canvas.render(heatmap, force=True)
        QApplication.processEvents()
        image = canvas.capture_image(
            width=width,
            height=height,
            for_pdf=True,
            dpi=dpi,
        )
        errors = validate_aerial_plot_body(image, page_key=spec.page_key)
        if errors:
            raise RuntimeError(
                "Survey plot PDF aerial layout regression: "
                + "; ".join(errors)
            )
        return image
    if spec.page_kind == SurveyPlotPageKind.HISTOGRAM:
        hist_canvas = view.histogram_canvas(kind)
        if hist_canvas is None:
            return None
        histogram = view.histogram_cache().get(kind)
        if histogram is None:
            return None
        hist_canvas.render(histogram)
        QApplication.processEvents()
        return hist_canvas.capture_image(
            width=width,
            height=height,
            for_pdf=True,
            dpi=dpi,
        )
    return None


def _restore_view_state(view: Postplot4DSurveyPlotsView) -> None:
    view.restore_after_pdf_export()
    QApplication.processEvents()


def _compose_survey_plot_page(
    view: Postplot4DSurveyPlotsView,
    options: Postplot4DSurveyPlotPdfOptions,
    spec: SurveyPlotPageSpec,
    *,
    geom: _PlotPageGeometry,
    logo_file: Path | None,
    report_title: str,
    dpi: int,
) -> ComposedSurveyPlotPage | None:
    image = _render_page_image(
        view,
        spec,
        width=geom.plot_width,
        height=geom.plot_height,
        dpi=dpi,
    )
    if image is None or image.isNull():
        return None
    composed = QImage(geom.page_w, geom.page_h, QImage.Format.Format_ARGB32)
    composed.fill(Qt.GlobalColor.white)
    painter = QPainter(composed)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    _draw_survey_page_header(
        painter,
        content_left=geom.content_left,
        content_top=geom.content_top,
        content_width=geom.content_width,
        dpi=dpi,
        report_title=report_title,
        plot_title=_header_plot_label(spec, options),
        logo_file=logo_file,
    )
    plot_y = geom.content_top + geom.header_height
    painter.drawImage(geom.content_left, plot_y, image)
    painter.end()
    return ComposedSurveyPlotPage(spec=spec, image=composed)


def compose_survey_plot_pages(
    view: Postplot4DSurveyPlotsView,
    options: Postplot4DSurveyPlotPdfOptions,
    *,
    logo_path: str = "",
    dpi: int | None = None,
) -> list[ComposedSurveyPlotPage]:
    page_specs = iter_survey_plot_page_specs(view, options)
    if not page_specs:
        raise ValueError("Select at least one survey plot to include in the PDF.")

    render_dpi = dpi if dpi is not None else options.dpi
    logo_file = resolve_logo_path(logo_path)
    geom = _geometry(options, render_dpi)
    report_title = options.report_title.strip() or DEFAULT_SURVEY_PLOT_PDF_REPORT_TITLE
    pages: list[ComposedSurveyPlotPage] = []
    try:
        for spec in page_specs:
            page = _compose_survey_plot_page(
                view,
                options,
                spec,
                geom=geom,
                logo_file=logo_file,
                report_title=report_title,
                dpi=render_dpi,
            )
            if page is not None:
                pages.append(page)
    finally:
        _restore_view_state(view)
    if not pages:
        raise ValueError("No survey plot pages to export.")
    return pages


def render_survey_plot_preview_pages(
    view: Postplot4DSurveyPlotsView,
    options: Postplot4DSurveyPlotPdfOptions,
    *,
    logo_path: str = "",
) -> list[ComposedSurveyPlotPage]:
    """Preview pages at lower DPI; first aerial page is re-captured after compose."""
    dpi = STAT_PLOT_PDF_PREVIEW_DPI
    pages = compose_survey_plot_pages(
        view,
        options,
        logo_path=logo_path,
        dpi=dpi,
    )
    if not pages:
        return pages
    first = pages[0]
    if first.spec.page_kind != SurveyPlotPageKind.AERIAL:
        return pages

    geom = _geometry(options, dpi)
    logo_file = resolve_logo_path(logo_path)
    report_title = options.report_title.strip() or DEFAULT_SURVEY_PLOT_PDF_REPORT_TITLE
    view.refresh_all()
    QApplication.processEvents()
    try:
        refreshed = _compose_survey_plot_page(
            view,
            options,
            first.spec,
            geom=geom,
            logo_file=logo_file,
            report_title=report_title,
            dpi=dpi,
        )
    finally:
        _restore_view_state(view)
    if refreshed is not None:
        pages[0] = refreshed
    return pages


def export_survey_plot_pdf(
    view: Postplot4DSurveyPlotsView,
    output_path: Path,
    options: Postplot4DSurveyPlotPdfOptions,
    *,
    logo_path: str = "",
) -> None:
    page_specs = iter_survey_plot_page_specs(view, options)
    if not page_specs:
        raise ValueError("Select at least one survey plot to include in the PDF.")

    export_dpi = options.dpi
    logo_file = resolve_logo_path(logo_path)
    geom = _geometry(options, export_dpi)
    report_title = options.report_title.strip() or DEFAULT_SURVEY_PLOT_PDF_REPORT_TITLE
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
            image = _render_page_image(
                view,
                spec,
                width=geom.plot_width,
                height=geom.plot_height,
                dpi=export_dpi,
            )
            if image is None or image.isNull():
                continue
            if rendered_any:
                writer.newPage()
            rendered_any = True
            painter.fillRect(page_rect, Qt.GlobalColor.white)
            _draw_survey_page_header(
                painter,
                content_left=origin_x + geom.content_left,
                content_top=origin_y + geom.content_top,
                content_width=geom.content_width,
                dpi=export_dpi,
                report_title=report_title,
                plot_title=_header_plot_label(spec, options),
                logo_file=logo_file,
            )
            plot_x = origin_x + geom.content_left
            plot_y = origin_y + geom.content_top + geom.header_height
            painter.drawImage(plot_x, plot_y, image)
    finally:
        painter.end()
        _restore_view_state(view)

    if not rendered_any:
        raise ValueError("No survey plot pages to export.")
