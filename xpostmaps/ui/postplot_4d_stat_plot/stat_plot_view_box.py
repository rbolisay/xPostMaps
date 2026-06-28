"""ViewBox for 4D Stat plots — pan, zoom window, point pick, context menu."""

from __future__ import annotations

from collections.abc import Callable

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu

from xpostmaps.ui.map_view_box import MapViewBox
from xpostmaps.ui.theme import apply_menu_theme


class StatPlotViewBox(MapViewBox):
    """Right-drag pan, left-drag zoom window, double right-click reset, context menu."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._center_average_cb: Callable[[], None] | None = None
        self._reset_zoom_cb: Callable[[], None] | None = None
        self._left_click_cb: Callable[[object], None] | None = None
        self._left_press_pos = None
        self._left_drag_moved = False

    def set_handlers(
        self,
        *,
        center_average: Callable[[], None] | None = None,
        reset_zoom: Callable[[], None] | None = None,
        left_click: Callable[[object], None] | None = None,
    ) -> None:
        self._center_average_cb = center_average
        self._reset_zoom_cb = reset_zoom
        self._left_click_cb = left_click

    def left_click_was_drag(self) -> bool:
        """Return whether the last left press included a zoom-window drag."""
        dragged = self._left_drag_moved
        self._left_drag_moved = False
        return dragged

    def mouseDragEvent(self, ev, axis=None) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            if ev.isStart():
                self._left_press_pos = ev.scenePos()
                self._left_drag_moved = False
            elif ev.isFinish():
                self._left_press_pos = None
            else:
                if (
                    self._left_press_pos is not None
                    and (ev.scenePos() - self._left_press_pos).manhattanLength()
                    > self._DRAG_THRESHOLD
                ):
                    self._left_drag_moved = True
            ev.accept()
            super().mouseDragEvent(ev, axis)
            return
        super().mouseDragEvent(ev, axis)

    def mouseClickEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            ev.accept()
            if self._left_drag_moved:
                self._left_drag_moved = False
                return
            if self._left_click_cb is not None:
                self._left_click_cb(ev)
            return
        super().mouseClickEvent(ev)

    def _show_pending_menu(self) -> None:
        if self._pending_menu_pos is None:
            return
        menu = QMenu()
        apply_menu_theme(menu)
        center_average = menu.addAction("Center Average")
        reset_zoom = menu.addAction("Reset Zoom")
        chosen = menu.exec(self._pending_menu_pos)
        self._pending_menu_pos = None
        if chosen is center_average and self._center_average_cb is not None:
            self._center_average_cb()
        elif chosen is reset_zoom:
            if self._reset_zoom_cb is not None:
                self._reset_zoom_cb()
            else:
                self.zoom_to_extent()
