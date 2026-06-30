"""Shared PDF rendering helpers for survey plot canvases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

import pyqtgraph as pg

_PLOT_BG = "#ffffff"
_PLOT_FG = "#111827"
_TITLE_FONT_PT = 11.0
_SCREEN_AXIS_FONT = QFont("Arial", 8)


@dataclass
class _PlotRenderSnapshot:
    axis_styles: dict[str, dict[str, Any]]
    plot_geometry: QRectF
    scene_rect: QRectF | None


def apply_screen_axis_styles(
    plot_widget: pg.PlotWidget,
    *,
    bottom_tick_offset: int = 4,
) -> None:
    """Re-apply on-screen axis tick fonts after PDF capture."""
    plot_item = plot_widget.getPlotItem()
    tick_font = QFont(_SCREEN_AXIS_FONT)
    left = plot_item.getAxis("left")
    bottom = plot_item.getAxis("bottom")
    if left is not None:
        left.setStyle(tickFont=tick_font, autoExpandTextSpace=True)
    if bottom is not None:
        bottom.setStyle(
            tickFont=tick_font,
            tickTextOffset=bottom_tick_offset,
            autoExpandTextSpace=True,
        )
    plot_item.layout.activate()
    QApplication.processEvents()


def _snapshot_plot_render_state(
    plot_widget: pg.PlotWidget,
) -> _PlotRenderSnapshot:
    plot_item = plot_widget.getPlotItem()
    axis_styles: dict[str, dict[str, Any]] = {}
    for axis_name in ("left", "bottom", "top", "right"):
        axis = plot_item.getAxis(axis_name)
        if axis is None:
            continue
        style = axis.style
        tick_font = style.get("tickFont")
        saved: dict[str, Any] = {
            "tickFont": QFont(tick_font) if tick_font is not None else None,
        }
        if axis_name in ("left", "right"):
            saved["width"] = axis.width()
        axis_styles[axis_name] = saved
    scene = plot_widget.scene()
    scene_rect = QRectF(scene.sceneRect()) if scene is not None else None
    return _PlotRenderSnapshot(
        axis_styles=axis_styles,
        plot_geometry=QRectF(plot_item.geometry()),
        scene_rect=scene_rect,
    )


def _restore_plot_render_state(
    plot_widget: pg.PlotWidget,
    snapshot: _PlotRenderSnapshot,
) -> None:
    plot_item = plot_widget.getPlotItem()
    for axis_name, saved in snapshot.axis_styles.items():
        axis = plot_item.getAxis(axis_name)
        if axis is None:
            continue
        style_kwargs: dict[str, Any] = {}
        tick_font = saved.get("tickFont")
        if tick_font is not None:
            style_kwargs["tickFont"] = QFont(tick_font)
        if style_kwargs:
            axis.setStyle(**style_kwargs)
        width = saved.get("width")
        if width is not None and axis_name in ("left", "right"):
            axis.setWidth(width)
    plot_item.setGeometry(snapshot.plot_geometry)
    scene = plot_widget.scene()
    if scene is not None and snapshot.scene_rect is not None:
        scene.setSceneRect(snapshot.scene_rect)
    plot_item.layout.activate()
    QApplication.processEvents()


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
    snapshot = _snapshot_plot_render_state(plot_widget)

    scale = max(dpi / 96.0, 1.0)
    axis_font = QFont("Arial")
    axis_font.setPixelSize(max(7, int(round(8 * scale))))
    try:
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
        return image
    finally:
        _restore_plot_render_state(plot_widget, snapshot)


def compose_survey_plot_image(
    plot_widget: pg.PlotWidget,
    *,
    width: int,
    height: int,
    title: str = "",
    dpi: int,
    include_title: bool = True,
) -> QImage:
    """White plot area with optional title band and rendered pyqtgraph body."""
    composed = QImage(width, height, QImage.Format.Format_ARGB32)
    composed.fill(QColor(_PLOT_BG))
    top_pad = 0
    if include_title and title.strip():
        painter = QPainter(composed)
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
    composer = QPainter(composed)
    composer.drawImage(0, top_pad, body)
    composer.end()
    return composed
