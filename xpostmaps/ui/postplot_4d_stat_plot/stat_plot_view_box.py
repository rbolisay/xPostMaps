"""ViewBox for 4D Stat plots — pan, shotpoint selection, point pick, context menu."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu

from xpostmaps.ui.map_view_box import MapViewBox
from xpostmaps.ui.theme import apply_menu_theme


class StatPlotViewBox(MapViewBox):
    """Right-drag pan, left-drag shotpoint selection, double right-click reset."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._center_average_cb: Callable[[], None] | None = None
        self._reset_zoom_cb: Callable[[], None] | None = None
        self._left_click_cb: Callable[[object], None] | None = None
        self._selection_drag_start_cb: Callable[[], None] | None = None
        self._selection_drag_move_cb: Callable[[float, float, float, float], None] | None = None
        self._selection_drag_finish_cb: Callable[[float, float, float, float], None] | None = None
        self._populate_context_menu_cb: Callable[[QMenu], None] | None = None
        self._left_press_pos = None
        self._left_drag_moved = False
        self._left_drag_active = False

    def set_handlers(
        self,
        *,
        center_average: Callable[[], None] | None = None,
        reset_zoom: Callable[[], None] | None = None,
        left_click: Callable[[object], None] | None = None,
        selection_drag_start: Callable[[], None] | None = None,
        selection_drag_move: Callable[[float, float, float, float], None] | None = None,
        selection_drag_finish: Callable[[float, float, float, float], None] | None = None,
        populate_context_menu: Callable[[QMenu], None] | None = None,
    ) -> None:
        self._center_average_cb = center_average
        self._reset_zoom_cb = reset_zoom
        self._left_click_cb = left_click
        self._selection_drag_start_cb = selection_drag_start
        self._selection_drag_move_cb = selection_drag_move
        self._selection_drag_finish_cb = selection_drag_finish
        self._populate_context_menu_cb = populate_context_menu

    def left_click_was_drag(self) -> bool:
        """Return whether the last left press included a selection drag."""
        dragged = self._left_drag_moved
        self._left_drag_moved = False
        return dragged

    def _view_point(self, ev) -> tuple[float, float]:
        pos = self.mapSceneToView(ev.scenePos())
        return float(pos.x()), float(pos.y())

    def _view_point_from_scene(self, scene_pos) -> tuple[float, float]:
        pos = self.mapSceneToView(scene_pos)
        return float(pos.x()), float(pos.y())

    def mouseDragEvent(self, ev, axis=None) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            if ev.isStart():
                self._left_press_pos = ev.scenePos()
                self._left_drag_moved = False
                self._left_drag_active = True
                if self._selection_drag_start_cb is not None:
                    self._selection_drag_start_cb()
            elif ev.isFinish():
                if (
                    self._left_drag_moved
                    and self._left_press_pos is not None
                    and self._selection_drag_finish_cb is not None
                ):
                    x0, y0 = self._view_point_from_scene(self._left_press_pos)
                    x1, y1 = self._view_point(ev)
                    self._selection_drag_finish_cb(x0, y0, x1, y1)
                self._left_press_pos = None
                self._left_drag_active = False
            else:
                if self._left_press_pos is not None:
                    if (
                        ev.scenePos() - self._left_press_pos
                    ).manhattanLength() > self._DRAG_THRESHOLD:
                        self._left_drag_moved = True
                    if self._left_drag_moved and self._selection_drag_move_cb is not None:
                        x0, y0 = self._view_point_from_scene(self._left_press_pos)
                        x1, y1 = self._view_point(ev)
                        self._selection_drag_move_cb(x0, y0, x1, y1)
            ev.accept()
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
        if self._populate_context_menu_cb is not None:
            self._populate_context_menu_cb(menu)
        menu.addSeparator()
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
