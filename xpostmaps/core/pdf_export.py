"""Compose the survey map and right pane into a print-ready PDF."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QMarginsF, QPoint, QRectF, QSizeF
from PySide6.QtGui import (
    QImage,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QPixmap,
    QRegion,
)
from PySide6.QtWidgets import QApplication, QWidget

# Portrait width × height in millimetres (ISO / common North American sizes).
PAPER_SIZES_MM: dict[str, tuple[float, float]] = {
    "A0": (841.0, 1189.0),
    "A1": (594.0, 841.0),
    "A2": (420.0, 594.0),
    "A3": (297.0, 420.0),
    "A4": (210.0, 297.0),
    "A5": (148.0, 210.0),
    "Letter": (216.0, 279.0),
    "Legal": (216.0, 356.0),
    "Tabloid": (279.0, 432.0),
}

PAPER_SIZE_NAMES: tuple[str, ...] = tuple(PAPER_SIZES_MM.keys())
DPI_OPTIONS: tuple[int, ...] = (150, 200, 300, 600, 1200)
# Full widget grab + upscale above this creates multi‑GB images and freezes the UI.
MAX_RASTER_DPI = 500

MARGIN_PRESETS_MM: dict[str, float] = {
    "Default": 10.0,
    "Narrow": 5.0,
    "Wide": 15.0,
}
MARGIN_PRESET_NAMES: tuple[str, ...] = (*MARGIN_PRESETS_MM.keys(), "Custom")

SCALE_MODES: tuple[str, ...] = ("Default", "Actual size", "Custom")

# Right pane is rendered at the full map height in the PDF (its box matches the map).
PANE_PDF_SCALE = 1.0


@dataclass
class PdfExportOptions:
    output_dir: Path
    filename: str
    paper: str = "A2"
    dpi: int = 300
    landscape: bool = True
    margin_mm: float = 10.0
    scale_mode: str = "Default"
    scale_percent: int = 100


def effective_raster_dpi(dpi: int, *, preview: bool = False) -> int:
    """DPI used for raster compositing (capped so export stays responsive)."""
    if preview:
        return min(max(dpi, 72), 120)
    return min(max(dpi, 72), MAX_RASTER_DPI)


def raster_dpi_clamped(requested_dpi: int) -> bool:
    return requested_dpi > MAX_RASTER_DPI


def portrait_dimensions_mm(paper: str) -> tuple[float, float]:
    """ISO size in portrait orientation (short edge × long edge)."""
    return PAPER_SIZES_MM.get(paper, PAPER_SIZES_MM["A2"])


def page_dimensions_mm(paper: str, landscape: bool) -> tuple[float, float]:
    """Effective page width × height in mm after applying orientation."""
    portrait_w, portrait_h = portrait_dimensions_mm(paper)
    if landscape:
        return portrait_h, portrait_w
    return portrait_w, portrait_h


def page_layout_for(paper: str, landscape: bool) -> QPageLayout:
    """Build Qt page layout — size is always portrait; orientation selects landscape."""
    portrait_w, portrait_h = portrait_dimensions_mm(paper)
    page_size = QPageSize(QSizeF(portrait_w, portrait_h), QPageSize.Unit.Millimeter)
    orientation = (
        QPageLayout.Orientation.Landscape
        if landscape
        else QPageLayout.Orientation.Portrait
    )
    return QPageLayout(page_size, orientation, QMarginsF(0, 0, 0, 0))


def default_pdf_filename(project_name: str, file_name: str) -> str:
    if file_name.strip():
        stem = Path(file_name.strip()).stem
        if stem:
            return stem
    if project_name.strip():
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in project_name.strip())
        return safe or "postmap"
    return "postmap"


def resolve_output_path(options: PdfExportOptions) -> Path:
    name = options.filename.strip() or "postmap"
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"
    return options.output_dir / name


def strip_target_height(options: "PdfExportOptions", raster_dpi: int) -> int:
    """Pixel height the captured widgets should be rendered at (the printable height)."""
    _page_w_mm, page_h_mm = page_dimensions_mm(options.paper, options.landscape)
    page_h_px = int(page_h_mm / 25.4 * raster_dpi)
    margin_px = int(options.margin_mm / 25.4 * raster_dpi)
    return max(page_h_px - 2 * margin_px, 1)


def render_map_wysiwyg(
    widget: QWidget,
    target_height: int,
    *,
    use_screen_grab: bool = False,
) -> QImage:
    """Capture the map exactly as displayed, scaled to ``target_height``.

    Composites the pyqtgraph scene, OpenGL overlay and frame overlays so export
    matches on-screen detail (a plain ``QWidget.grab`` misses GL line layers).
    """
    capture = getattr(widget, "capture_wysiwyg_image", None)
    if callable(capture):
        return capture(target_height, use_screen_grab=use_screen_grab)
    target_height = max(int(target_height), 1)
    app = QApplication.instance()
    if app is not None:
        app.processEvents()
    pixmap = widget.grab()
    if pixmap.isNull():
        return QImage()
    if pixmap.height() == target_height:
        return pixmap.toImage()
    return pixmap.toImage().scaledToHeight(
        target_height,
        Qt.TransformationMode.SmoothTransformation,
    )


def render_pane_for_export(right_pane: QWidget, target_height: int) -> QImage:
    """Render the right pane with sharp text and a painted minimap."""
    render = getattr(right_pane, "render_for_export", None)
    if callable(render):
        return render(target_height)
    return render_widget_to_height(right_pane, target_height)


def render_widget_to_height(widget: QWidget, target_height: int) -> QImage:
    """Re-render a widget (vector-sharp) scaled so its height equals ``target_height``.

    Using ``QWidget.render`` with a scaled painter rasterises text and lines at the
    target resolution instead of upscaling a screen grab, so output stays crisp.
    """
    target_height = max(int(target_height), 1)
    src_w = max(widget.width(), 1)
    src_h = max(widget.height(), 1)
    scale = target_height / src_h
    out_w = max(int(round(src_w * scale)), 1)

    image = QImage(out_w, target_height, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.scale(scale, scale)
    try:
        # Force QWidget.render: pyqtgraph's GraphicsView overrides render() with an
        # incompatible signature, so bind the base-class method explicitly. This paints
        # the widget and all children (plot, overlays) at the scaled resolution.
        QWidget.render(
            widget,
            painter,
            QPoint(0, 0),
            QRegion(widget.rect()),
            QWidget.RenderFlag.DrawWindowBackground | QWidget.RenderFlag.DrawChildren,
        )
    finally:
        painter.end()

    if image.isNull():
        # Fallback: screen grab upscaled (less sharp but never empty).
        pixmap = widget.grab()
        if pixmap.isNull():
            return QImage()
        return pixmap.toImage().scaledToHeight(
            target_height,
            Qt.TransformationMode.SmoothTransformation,
        )
    return image


def capture_export_images(
    map_widget: QWidget,
    right_pane: QWidget,
    options: "PdfExportOptions",
    *,
    preview: bool = False,
    use_screen_grab: bool | None = None,
) -> tuple[QImage, QImage]:
    """Render map and right pane on the UI thread at the final print resolution."""
    if use_screen_grab is None:
        # Screen grab matches on-screen GPU compositing; manual composite misses GL colours.
        use_screen_grab = True
    raster_dpi = effective_raster_dpi(options.dpi, preview=preview)
    target_h = strip_target_height(options, raster_dpi)
    map_height = max(map_widget.height(), 1)
    prepare = getattr(map_widget, "prepare_for_export", None)
    end_export = getattr(map_widget, "end_export", None)
    if callable(prepare):
        prepare(wysiwyg=True)
    right_pane.prepare_export_snapshot(map_height=map_height)
    try:
        map_image = render_map_wysiwyg(
            map_widget,
            target_h,
            use_screen_grab=use_screen_grab,
        )
        pane_image = render_pane_for_export(right_pane, target_h)
        return map_image, pane_image
    finally:
        right_pane.reset_export_snapshot()
        if callable(end_export):
            end_export(wysiwyg=True)


def _scale_uniform(image: QImage, factor: float) -> QImage:
    if image.isNull() or abs(factor - 1.0) < 0.01:
        return image
    width = max(int(image.width() * factor), 1)
    height = max(int(image.height() * factor), 1)
    return image.scaled(
        width,
        height,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _scale_to_height(image: QImage, height: int) -> QImage:
    if image.isNull() or height < 1:
        return image
    if image.height() == height:
        return image
    return image.scaledToHeight(
        height,
        Qt.TransformationMode.SmoothTransformation,
    )


def _build_content_strip(
    map_image: QImage,
    pane_image: QImage,
    export_dpi: int,
    strip_height: int,
) -> QImage:
    """Compose map + right pane side-by-side without horizontal squeeze.

    The map keeps the full printable height; the right pane is rendered 20% smaller
    than the map so it does not dominate the sheet (it is top-aligned with the map).
    """
    gap_px = max(int(export_dpi * 0.02), 2)
    map_col = _scale_to_height(map_image, strip_height)
    pane_col = _scale_to_height(pane_image, max(int(strip_height * PANE_PDF_SCALE), 1))
    strip_h = max(map_col.height(), pane_col.height(), 1)
    strip_w = map_col.width() + gap_px + pane_col.width()

    strip = QImage(strip_w, strip_h, QImage.Format.Format_ARGB32)
    strip.fill(Qt.GlobalColor.white)
    painter = QPainter(strip)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    painter.drawImage(0, 0, map_col)
    painter.drawImage(map_col.width() + gap_px, 0, pane_col)
    painter.end()
    return strip


def _fit_strip_uniform(strip: QImage, max_w: int, max_h: int) -> QImage:
    """Uniformly scale strip to fit inside max_w × max_h (true aspect, no squeeze)."""
    if strip.isNull() or strip.width() < 1 or strip.height() < 1:
        return strip
    fit = min(max_w / strip.width(), max_h / strip.height())
    if fit >= 0.999:
        return strip
    return _scale_uniform(strip, fit)


def _place_strip_on_page(
    sheet: QImage,
    strip: QImage,
    *,
    inner_x: int,
    inner_y: int,
    inner_w: int,
    inner_h: int,
    scale_mode: str,
    scale_percent: int,
) -> None:
    if strip.isNull() or strip.width() < 1 or strip.height() < 1:
        return

    mode = scale_mode.strip().lower()
    if mode == "actual size":
        placed = strip
    elif mode == "custom":
        factor = max(scale_percent, 1) / 100.0
        placed = _scale_uniform(strip, factor)
    else:
        placed = _fit_strip_uniform(strip, inner_w, inner_h)

    x = inner_x + max(0, (inner_w - placed.width()) // 2)
    y = inner_y + max(0, (inner_h - placed.height()) // 2)

    painter = QPainter(sheet)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    painter.drawImage(x, y, placed)
    painter.end()


def render_sheet_from_captures(
    map_image: QImage,
    pane_image: QImage,
    *,
    paper: str,
    landscape: bool,
    raster_dpi: int,
    margin_mm: float,
    scale_mode: str = "Default",
    scale_percent: int = 100,
) -> QImage:
    """Build the page image from pre-captured widgets (safe to call off the UI thread)."""
    page_w_mm, page_h_mm = page_dimensions_mm(paper, landscape)
    page_w_px = int(page_w_mm / 25.4 * raster_dpi)
    page_h_px = int(page_h_mm / 25.4 * raster_dpi)
    margin_px = int(margin_mm / 25.4 * raster_dpi)
    inner_w = max(page_w_px - 2 * margin_px, 1)
    inner_h = max(page_h_px - 2 * margin_px, 1)

    # Widgets are already captured at print resolution, so compose at their native
    # height (no second upscale) and let placement handle the scale mode.
    strip_height = max(map_image.height(), pane_image.height(), 1)

    strip = _build_content_strip(
        map_image,
        pane_image,
        raster_dpi,
        strip_height,
    )

    sheet = QImage(page_w_px, page_h_px, QImage.Format.Format_ARGB32)
    sheet.fill(Qt.GlobalColor.white)
    _place_strip_on_page(
        sheet,
        strip,
        inner_x=margin_px,
        inner_y=margin_px,
        inner_w=inner_w,
        inner_h=inner_h,
        scale_mode=scale_mode,
        scale_percent=scale_percent,
    )
    return sheet


def render_sheet_image(
    map_widget: QWidget,
    right_pane: QWidget,
    *,
    paper: str,
    landscape: bool,
    dpi: int,
    margin_mm: float,
    scale_mode: str = "Default",
    scale_percent: int = 100,
    preview: bool = False,
) -> QImage:
    """Lay out map + right pane on the selected paper (preview or export DPI)."""
    raster_dpi = effective_raster_dpi(dpi, preview=preview)
    capture_options = PdfExportOptions(
        output_dir=Path("."),
        filename="",
        paper=paper,
        dpi=dpi,
        landscape=landscape,
        margin_mm=margin_mm,
        scale_mode=scale_mode,
        scale_percent=scale_percent,
    )
    map_image, pane_image = capture_export_images(
        map_widget,
        right_pane,
        capture_options,
        preview=preview,
    )
    return render_sheet_from_captures(
        map_image,
        pane_image,
        paper=paper,
        landscape=landscape,
        raster_dpi=raster_dpi,
        margin_mm=margin_mm,
        scale_mode=scale_mode,
        scale_percent=scale_percent,
    )


def render_sheet_preview(
    map_widget: QWidget,
    right_pane: QWidget,
    *,
    paper: str,
    landscape: bool,
    margin_mm: float,
    scale_mode: str = "Default",
    scale_percent: int = 100,
) -> QPixmap:
    image = render_sheet_image(
        map_widget,
        right_pane,
        paper=paper,
        landscape=landscape,
        dpi=120,
        margin_mm=margin_mm,
        scale_mode=scale_mode,
        scale_percent=scale_percent,
        preview=True,
    )
    return QPixmap.fromImage(image)


def compose_pdf_to_path(
    path: Path,
    map_image: QImage,
    pane_image: QImage,
    options: PdfExportOptions,
) -> None:
    """Compose and write PDF from captures (no QWidget access)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    raster_dpi = effective_raster_dpi(options.dpi, preview=False)
    sheet = render_sheet_from_captures(
        map_image,
        pane_image,
        paper=options.paper,
        landscape=options.landscape,
        raster_dpi=raster_dpi,
        margin_mm=options.margin_mm,
        scale_mode=options.scale_mode,
        scale_percent=options.scale_percent,
    )

    layout = page_layout_for(options.paper, options.landscape)
    writer = QPdfWriter(str(path))
    writer.setResolution(raster_dpi)
    writer.setPageLayout(layout)

    painter = QPainter(writer)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    page_rect = layout.paintRectPixels(raster_dpi)
    if sheet.width() == page_rect.width() and sheet.height() == page_rect.height():
        painter.drawImage(page_rect.topLeft(), sheet)
    else:
        scaled = sheet.scaled(
            page_rect.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = page_rect.x() + (page_rect.width() - scaled.width()) // 2
        y = page_rect.y() + (page_rect.height() - scaled.height()) // 2
        painter.drawImage(x, y, scaled)
    painter.end()


def write_pdf(
    path: Path,
    map_widget: QWidget,
    right_pane: QWidget,
    options: PdfExportOptions,
) -> None:
    """Write a single-page PDF (captures on UI thread, then composes)."""
    map_image, pane_image = capture_export_images(map_widget, right_pane, options)
    compose_pdf_to_path(path, map_image, pane_image, options)


# Vector export: resolution only sets coordinate precision / embedded-raster DPI;
# lines, dots and text are written as scalable vector objects either way.
VECTOR_DEVICE_DPI = 600


def _render_widget_into(painter: QPainter, widget: QWidget, target: QRectF) -> None:
    """Paint a widget (and children) into ``target`` as vector content."""
    src_w = max(widget.width(), 1)
    src_h = max(widget.height(), 1)
    painter.save()
    painter.translate(target.x(), target.y())
    painter.scale(target.width() / src_w, target.height() / src_h)
    QWidget.render(
        widget,
        painter,
        QPoint(0, 0),
        QRegion(widget.rect()),
        QWidget.RenderFlag.DrawWindowBackground | QWidget.RenderFlag.DrawChildren,
    )
    painter.restore()


def compose_pdf_vector_from_captures(
    path: Path,
    map_image: QImage,
    pane_image: QImage,
    options: PdfExportOptions,
) -> None:
    """Write a PDF page from pre-captured map and right-pane images."""
    path.parent.mkdir(parents=True, exist_ok=True)
    device_dpi = min(max(options.dpi, 150), VECTOR_DEVICE_DPI)
    layout = page_layout_for(options.paper, options.landscape)
    writer = QPdfWriter(str(path))
    writer.setResolution(device_dpi)
    writer.setPageLayout(layout)
    page_rect = layout.paintRectPixels(device_dpi)

    painter = QPainter(writer)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.fillRect(page_rect, Qt.GlobalColor.white)

    inner_w = float(page_rect.width())
    inner_h = float(page_rect.height())
    ox = float(page_rect.x())
    oy = float(page_rect.y())

    map_w = max(map_image.width(), 1)
    map_h = max(map_image.height(), 1)
    pane_w = max(pane_image.width(), 1)
    pane_h = max(pane_image.height(), 1)

    base_h = inner_h
    map_disp_w = map_w * (base_h / map_h)
    pane_disp_h = base_h * PANE_PDF_SCALE
    pane_disp_w = pane_w * (pane_disp_h / pane_h)
    gap = max(inner_w * 0.004, 2.0)
    strip_w = map_disp_w + gap + pane_disp_w

    fit = min(inner_w / strip_w, inner_h / base_h)
    mode = options.scale_mode.strip().lower()
    if mode == "custom":
        fit *= max(options.scale_percent, 1) / 100.0

    placed_w = strip_w * fit
    placed_h = base_h * fit
    x0 = ox + max(0.0, (inner_w - placed_w) / 2.0)
    y0 = oy + max(0.0, (inner_h - placed_h) / 2.0)

    map_rect = QRectF(x0, y0, map_disp_w * fit, base_h * fit)
    pane_rect = QRectF(
        x0 + (map_disp_w + gap) * fit,
        y0,
        pane_disp_w * fit,
        pane_disp_h * fit,
    )

    if not map_image.isNull():
        painter.fillRect(map_rect, Qt.GlobalColor.white)
        painter.drawImage(map_rect, map_image)
    if not pane_image.isNull():
        painter.drawImage(pane_rect, pane_image)
    painter.end()


def compose_pdf_vector(
    path: Path,
    map_widget: QWidget,
    right_pane: QWidget,
    options: PdfExportOptions,
) -> None:
    """Write a PDF with WYSIWYG map capture and a sharp-rendered right pane."""
    map_image, pane_image = capture_export_images(map_widget, right_pane, options)
    compose_pdf_vector_from_captures(path, map_image, pane_image, options)


def write_pdf_vector(
    path: Path,
    map_widget: QWidget,
    right_pane: QWidget,
    options: PdfExportOptions,
) -> None:
    """Prepare widgets and write a scalable vector PDF (UI thread only)."""
    map_image, pane_image = capture_export_images(map_widget, right_pane, options)
    compose_pdf_vector_from_captures(path, map_image, pane_image, options)
