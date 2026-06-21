"""Optional OpenGL line overlay synced with the 2D map view."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QMatrix4x4

from xpostmaps.utils.spatial_clip import polyline_runs

if TYPE_CHECKING:
    from pyqtgraph.opengl import GLLinePlotItem, GLViewWidget


def gl_lines_available() -> bool:
    try:
        import OpenGL  # noqa: F401
        from pyqtgraph.opengl import GLLinePlotItem  # noqa: F401
    except ImportError:
        return False
    return True


def _create_ortho_gl_view(parent):
    from pyqtgraph.opengl import GLViewWidget

    class MapOrthoGLView(GLViewWidget):
        """Top-down orthographic GL view matching ``PlotWidget`` world coordinates."""

        def __init__(self, parent=None) -> None:
            super().__init__(parent)
            self._x_range = (-1.0, 1.0)
            self._y_range = (-1.0, 1.0)
            self.setBackgroundColor((0, 0, 0, 0))

        def set_view_range(
            self,
            x_range: tuple[float, float],
            y_range: tuple[float, float],
        ) -> None:
            self._x_range = x_range
            self._y_range = y_range
            self.update()

        def projectionMatrix(self, region, viewport):  # noqa: N802
            x0, x1 = self._x_range
            y0, y1 = self._y_range
            matrix = QMatrix4x4()
            matrix.ortho(x0, x1, y0, y1, -1000.0, 1000.0)
            return matrix

        def viewMatrix(self):  # noqa: N802
            return QMatrix4x4()

    return MapOrthoGLView(parent=parent)


class MapGlLineOverlay:
    """Manages GL line tiles over the plot viewport (transform-only pan/zoom)."""

    def __init__(self, plot: pg.PlotWidget, parent) -> None:
        self._plot = plot
        self._available = gl_lines_available()
        self._view = _create_ortho_gl_view(parent) if self._available else None
        self._items: dict[tuple[int, tuple[int, int], int], object] = {}
        if self._view is not None:
            self._view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self._view.setAttribute(Qt.WidgetAttribute.WA_AlwaysStackOnTop, True)
            self._view.setStyleSheet("background: transparent;")
            self._view.hide()

    @property
    def available(self) -> bool:
        return self._available and self._view is not None

    def hide_for_export(self) -> None:
        if self._view is not None:
            self._view.hide()

    def sync_geometry(self) -> None:
        if not self.available:
            return
        assert self._view is not None
        self._view.setGeometry(self._plot.geometry())
        self._view.raise_()
        if self._items:
            self._view.show()
        vb = self._plot.getViewBox()
        if vb is not None:
            (x_range, y_range) = vb.viewRange()
            self._view.set_view_range(tuple(x_range), tuple(y_range))

    def sync_view(self) -> None:
        if not self.available:
            return
        assert self._view is not None
        vb = self._plot.getViewBox()
        if vb is None:
            return
        (x_range, y_range) = vb.viewRange()
        self._view.set_view_range(tuple(x_range), tuple(y_range))

    def add_tile(
        self,
        layer_id: int,
        key: tuple[int, int],
        xs: np.ndarray,
        ys: np.ndarray,
        *,
        color: tuple[float, float, float, float],
        width: float,
    ) -> None:
        if not self.available:
            return
        from pyqtgraph.opengl import GLLinePlotItem

        assert self._view is not None
        for run_index, (rx, ry) in enumerate(polyline_runs(xs, ys)):
            storage_key = (layer_id, key, run_index)
            if storage_key in self._items:
                continue
            pos = np.ascontiguousarray(
                np.column_stack([rx, ry, np.zeros(rx.size, dtype=np.float32)]),
                dtype=np.float32,
            )
            item = GLLinePlotItem(
                pos=pos,
                color=color,
                width=width,
                antialias=False,
                mode="line_strip",
            )
            self._view.addItem(item)
            self._items[storage_key] = item
        self._view.show()
        self.sync_geometry()

    def set_tile_visible(
        self,
        layer_id: int,
        key: tuple[int, int],
        visible: bool,
    ) -> None:
        if not self.available:
            return
        prefix = (layer_id, key)
        for storage_key, item in self._items.items():
            if storage_key[0] == prefix[0] and storage_key[1] == prefix[1]:
                item.setVisible(visible)

    def clear_layer(self, layer_id: int) -> None:
        if not self.available:
            return
        assert self._view is not None
        remove_keys = [k for k in self._items if k[0] == layer_id]
        for key in remove_keys:
            item = self._items.pop(key)
            self._view.removeItem(item)

    def clear(self) -> None:
        if not self.available:
            self._items.clear()
            return
        assert self._view is not None
        for item in self._items.values():
            self._view.removeItem(item)
        self._items.clear()
        self._view.hide()
