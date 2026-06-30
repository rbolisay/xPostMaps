"""Shared pan/zoom navigation for Survey Plots (matches map / 4D Stat behavior)."""

from __future__ import annotations

from collections.abc import Callable

import pyqtgraph as pg
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent, QPainter
from PySide6.QtWidgets import QMenu, QWidget

from xpostmaps.ui.map_view_box import MapViewBox
from xpostmaps.ui.theme import apply_menu_theme


class SurveyPlotViewBox(MapViewBox):
    """Survey plot navigation: right-drag pan, scroll zoom, reset-only context menu."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._after_reset_cb: Callable[[], None] | None = None

    def set_after_reset(self, callback: Callable[[], None] | None) -> None:
        self._after_reset_cb = callback

    def zoom_to_extent(self) -> None:
        super().zoom_to_extent()
        if self._after_reset_cb is not None:
            self._after_reset_cb()

    def _show_pending_menu(self) -> None:
        if self._pending_menu_pos is None:
            return
        menu = QMenu()
        apply_menu_theme(menu)
        reset_zoom = menu.addAction("Reset Zoom")
        chosen = menu.exec(self._pending_menu_pos)
        self._pending_menu_pos = None
        if chosen is reset_zoom:
            self.zoom_to_extent()


def create_survey_plot_widget(*, background: str) -> tuple[pg.PlotWidget, SurveyPlotViewBox]:
    """PlotWidget with right-drag pan, scroll zoom, and reset-only context menu."""
    viewbox = SurveyPlotViewBox(enableMenu=False)
    plot = pg.PlotWidget(viewBox=viewbox, background=background)
    plot.setMenuEnabled(False)
    return plot, viewbox


def apply_plot_extent(
    viewbox: SurveyPlotViewBox,
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    *,
    reset_view: bool = True,
) -> None:
    viewbox.set_extent_range(x_range, y_range)
    if reset_view:
        viewbox.zoom_to_extent()


class SurveyPanZoomWidget(QWidget):
    """Right-drag pan and double right-click reset for non-pyqtgraph survey plots."""

    _DRAG_THRESHOLD = 4

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._pan = QPointF(0.0, 0.0)
        self._zoom = 1.0
        self._right_press: QPointF | None = None
        self._right_dragged = False
        self._last_move_pos: QPointF | None = None
        self.setMouseTracking(True)

    def reset_view(self) -> None:
        self._pan = QPointF(0.0, 0.0)
        self._zoom = 1.0
        self.update()

    def begin_pan_zoom_paint(self, painter: QPainter) -> None:
        center = self.rect().center()
        painter.translate(center)
        painter.scale(self._zoom, self._zoom)
        painter.translate(-center)
        painter.translate(self._pan)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self._right_press = event.position()
            self._last_move_pos = event.position()
            self._right_dragged = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            event.buttons() & Qt.MouseButton.RightButton
            and self._right_press is not None
            and self._last_move_pos is not None
        ):
            if (
                event.position() - self._right_press
            ).manhattanLength() > self._DRAG_THRESHOLD:
                self._right_dragged = True
            if self._right_dragged:
                self._pan += event.position() - self._last_move_pos
                self.update()
            self._last_move_pos = event.position()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self._right_press = None
            self._last_move_pos = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            if self._right_dragged:
                self._right_dragged = False
                return
            self.reset_view()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
