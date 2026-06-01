"""Map ViewBox — right-drag pan, zoom window, zoom extent, context menu."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from pyqtgraph import functions as fn
from pyqtgraph.Point import Point
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QMenu


class MapViewBox(pg.ViewBox):
    """ViewBox with GIS-style navigation: right-drag pan, zoom window/extent."""

    _DRAG_THRESHOLD = 4

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("enableMenu", False)
        super().__init__(*args, **kwargs)
        self.setMouseMode(pg.ViewBox.PanMode)

        self._extent_x: tuple[float, float] | None = None
        self._extent_y: tuple[float, float] | None = None
        self._zoom_window_mode = False
        self._right_press_pos = None
        self._right_drag_moved = False
        self._pending_menu_pos = None

        self._menu_timer = QTimer()
        self._menu_timer.setSingleShot(True)
        self._menu_timer.setInterval(250)
        self._menu_timer.timeout.connect(self._show_pending_menu)

    def set_extent_range(
        self,
        x_range: tuple[float, float] | None,
        y_range: tuple[float, float] | None,
    ) -> None:
        self._extent_x = x_range
        self._extent_y = y_range

    def zoom_to_extent(self) -> None:
        if self._extent_x is None or self._extent_y is None:
            return
        self.setRange(xRange=self._extent_x, yRange=self._extent_y, padding=0)

    def start_zoom_window(self) -> None:
        self._zoom_window_mode = True
        self.setMouseMode(pg.ViewBox.RectMode)

    def _translate_from_drag(self, ev, axis=None) -> None:
        pos = ev.pos()
        last_pos = ev.lastPos()
        dif = (pos - last_pos) * -1

        mouse_enabled = np.array(self.state["mouseEnabled"], dtype=np.float64)
        mask = mouse_enabled.copy()
        if axis is not None:
            mask[1 - axis] = 0.0

        tr = fn.invertQTransform(self.childGroup.transform())
        delta = tr.map(dif * mask) - tr.map(Point(0, 0))

        x = delta.x() if mask[0] == 1 else None
        y = delta.y() if mask[1] == 1 else None

        self._resetTarget()
        if x is not None or y is not None:
            self.translateBy(x=x, y=y)
        self.sigRangeChangedManually.emit(self.state["mouseEnabled"])

    def mouseDragEvent(self, ev, axis=None) -> None:
        if ev.button() == Qt.MouseButton.RightButton:
            ev.accept()
            if ev.isStart():
                self._right_press_pos = ev.scenePos()
                self._right_drag_moved = False
                self._menu_timer.stop()
            elif ev.isFinish():
                self._right_press_pos = None
            else:
                if (
                    self._right_press_pos is not None
                    and (ev.scenePos() - self._right_press_pos).manhattanLength()
                    > self._DRAG_THRESHOLD
                ):
                    self._right_drag_moved = True
                self._translate_from_drag(ev, axis)
            return

        if (
            ev.button() == Qt.MouseButton.LeftButton
            and self._zoom_window_mode
            and self.state["mouseMode"] == pg.ViewBox.RectMode
        ):
            super().mouseDragEvent(ev, axis)
            if ev.isFinish():
                self._zoom_window_mode = False
                self.setMouseMode(pg.ViewBox.PanMode)
            return

        if ev.button() == Qt.MouseButton.LeftButton:
            super().mouseDragEvent(ev, axis)
            return

        super().mouseDragEvent(ev, axis)

    def mouseClickEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.RightButton:
            ev.accept()
            if self._right_drag_moved:
                self._right_drag_moved = False
                return
            if ev.double():
                self._menu_timer.stop()
                self.zoom_to_extent()
                return
            self._pending_menu_pos = ev.screenPos().toPoint()
            self._menu_timer.start()
            return
        super().mouseClickEvent(ev)

    def _show_pending_menu(self) -> None:
        if self._pending_menu_pos is None:
            return
        menu = QMenu()
        zoom_window = menu.addAction("Zoom Window")
        zoom_extent = menu.addAction("Zoom Extent")
        chosen = menu.exec(self._pending_menu_pos)
        self._pending_menu_pos = None
        if chosen is zoom_window:
            self.start_zoom_window()
        elif chosen is zoom_extent:
            self.zoom_to_extent()
