"""Shared PDF rendering helpers for survey plot canvases."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

import pyqtgraph as pg

_PLOT_BG = "#ffffff"
_PLOT_FG = "#111827"
_TITLE_FONT_PT = 11.0


def _font_pixel_size(base_pt: float, dpi: int) -> int:
    return max(1, int(round(base_pt * dpi / 72.0)))


def survey_plot_title_font(*, dpi: int) -> QFont:
    font = QFont("Segoe UI")
    font.setPixelSize(_font_pixel_size(_TITLE_FONT_PT, dpi))
    font.setWeight(QFont.Weight.DemiBold)
    return font


def draw_survey_plot_title(
    painter: QPainter,
    *,
    x: int,
    y: int,
    width: int,
    title: str,
    dpi: int,
) -> int:
    """Draw a left-aligned plot title; return total vertical space used."""
    text = title.strip()
    if not text:
        return 0
    scale = max(dpi / 96.0, 1.0)
    pad_top = max(4, int(round(6 * scale)))
    pad_bottom = max(6, int(round(10 * scale)))
    font = survey_plot_title_font(dpi=dpi)
    painter.setFont(font)
    painter.setPen(QColor(_PLOT_FG))
    metrics = painter.fontMetrics()
    text_rect = metrics.boundingRect(0, 0, max(1, width - x * 2), 0, int(Qt.TextFlag.TextWordWrap), text)
    painter.drawText(
        x,
        y + pad_top + metrics.ascent(),
        max(1, width - x * 2),
        text_rect.height(),
        int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft),
        text,
    )
    return pad_top + text_rect.height() + pad_bottom


def render_pyqtgraph_plot_for_pdf(
    plot_widget: pg.PlotWidget,
    *,
    width: int,
    height: int,
    dpi: int,
) -> QImage:
    """Render a PlotWidget at exact pixel dimensions (no widget grab / stretch)."""
    width = max(int(width), 1)
    height = max(int(height), 1)
    plot_item = plot_widget.getPlotItem()
    scene = plot_widget.scene()
    prev_rect = plot_item.geometry()

    scale = max(dpi / 96.0, 1.0)
    axis_font = QFont("Arial")
    axis_font.setPixelSize(max(7, int(round(8 * scale))))
    for axis_name in ("left", "bottom", "top", "right"):
        axis = plot_item.getAxis(axis_name)
        if axis is not None:
            axis.setStyle(tickFont=axis_font)

    plot_item.setGeometry(QRectF(0, 0, width, height))
    if scene is not None:
        scene.setSceneRect(0, 0, width, height)
    plot_item.layout.activate()
    QApplication.processEvents()
    plot_item.layout.activate()
    QApplication.processEvents()

    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor(_PLOT_BG))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    try:
        if scene is not None:
            scene.render(
                painter,
                QRectF(0, 0, width, height),
                QRectF(0, 0, width, height),
            )
    finally:
        painter.end()

    plot_item.setGeometry(prev_rect)
    QApplication.processEvents()
    return image


def compose_survey_plot_image(
    plot_widget: pg.PlotWidget,
    *,
    width: int,
    height: int,
    title: str,
    dpi: int,
) -> QImage:
    """White plot area with a consistent title band and rendered pyqtgraph body."""
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor(_PLOT_BG))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    top_pad = draw_survey_plot_title(
        painter,
        x=8,
        y=0,
        width=width,
        title=title,
        dpi=dpi,
    )
    painter.end()

    plot_h = max(1, height - top_pad)
    body = render_pyqtgraph_plot_for_pdf(
        plot_widget,
        width=width,
        height=plot_h,
        dpi=dpi,
    )
    composed = QImage(width, height, QImage.Format.Format_ARGB32)
    composed.fill(QColor(_PLOT_BG))
    composer = QPainter(composed)
    composer.drawImage(0, 0, image)
    composer.drawImage(0, top_pad, body)
    composer.end()
    return composed
