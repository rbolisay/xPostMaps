"""Optional OpenGL line overlay synced with the 2D map view."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QMatrix4x4

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
            # Top-down map: ignore default 45° perspective camera.
            self.opts["elevation"] = 90
            self.opts["azimuth"] = 0
            self.opts["distance"] = 1.0

        def set_view_range(
            self,
            x_range: tuple[float, float],
            y_range: tuple[float, float],
        ) -> None:
            if self._x_range == x_range and self._y_range == y_range:
                return
            self._x_range = x_range
            self._y_range = y_range
            self.update()

        def projectionMatrix(self, region, viewport):  # noqa: N802
            x0, x1 = self._x_range
            y0, y1 = self._y_range
            matrix = QMatrix4x4()
            # Same axis order as pyqtgraph ViewBox (y increases upward).
            matrix.ortho(x0, x1, y0, y1, -1000.0, 1000.0)
            return matrix

        def viewMatrix(self):  # noqa: N802
            # Identity — ortho already uses pyqtgraph ViewBox y-up world coords.
            return QMatrix4x4()

    return MapOrthoGLView(parent=parent)


class MapGlLineOverlay:
    """Manages GL line layers over the plot viewport (transform-only pan/zoom)."""

    def __init__(self, plot: pg.PlotWidget, parent) -> None:
        self._plot = plot
        self._available = gl_lines_available()
        self._view = _create_ortho_gl_view(parent) if self._available else None
        self._items: dict[tuple[int, int], object] = {}
        self._layer_visible: dict[int, bool] = {}
        if self._view is not None:
            self._view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self._view.setAttribute(Qt.WidgetAttribute.WA_AlwaysStackOnTop, True)
            self._view.setStyleSheet("background: transparent;")
            self._view.hide()

    @property
    def available(self) -> bool:
        return self._available and self._view is not None

    def _viewbox_widget_rect(self) -> tuple[int, int, int, int] | None:
        """ViewBox scene rect in ``PlotWidget`` coordinates (excludes axis margins)."""
        vb = self._plot.getViewBox()
        if vb is None:
            return None
        scene_rect = vb.sceneBoundingRect()
        if scene_rect.width() <= 4 or scene_rect.height() <= 4:
            return None
        top_left = self._plot.mapFromScene(scene_rect.topLeft())
        bottom_right = self._plot.mapFromScene(scene_rect.bottomRight())
        x = int(round(top_left.x()))
        y = int(round(top_left.y()))
        w = int(round(bottom_right.x() - top_left.x()))
        h = int(round(bottom_right.y() - top_left.y()))
        if w <= 0 or h <= 0:
            return None
        return x, y, w, h

    def hide_for_export(self) -> None:
        if self._view is not None:
            self._view.hide()

    def sync_geometry(self) -> None:
        if not self.available:
            return
        assert self._view is not None
        rect = self._viewbox_widget_rect()
        if rect is None:
            self._view.hide()
            return
        x, y, w, h = rect
        self._view.setGeometry(x, y, w, h)
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

    def _apply_layer_visibility(self, layer_id: int) -> None:
        visible = self._layer_visible.get(layer_id, True)
        for key, item in self._items.items():
            if key[0] == layer_id:
                item.setVisible(visible)

    def add_line_run(
        self,
        layer_id: int,
        run_index: int,
        rx: np.ndarray,
        ry: np.ndarray,
        *,
        color: tuple[float, float, float, float],
        width: float,
    ) -> None:
        if not self.available:
            return
        from pyqtgraph.opengl import GLLinePlotItem

        assert self._view is not None
        storage_key = (layer_id, run_index)
        if storage_key in self._items:
            return
        if rx.size < 2:
            return
        rx = np.asarray(rx, dtype=np.float64)
        ry = np.asarray(ry, dtype=np.float64)
        pos = np.ascontiguousarray(
            np.column_stack(
                [
                    rx.astype(np.float32, copy=False),
                    ry.astype(np.float32, copy=False),
                    np.zeros(rx.size, dtype=np.float32),
                ]
            ),
            dtype=np.float32,
        )
        item = GLLinePlotItem(
            pos=pos,
            color=color,
            width=width,
            antialias=True,
            mode="line_strip",
        )
        self._view.addItem(item)
        self._items[storage_key] = item
        self._layer_visible.setdefault(layer_id, True)
        item.setVisible(self._layer_visible.get(layer_id, True))
        self._view.show()

    def set_layer_visible(self, layer_id: int, visible: bool) -> None:
        if not self.available:
            return
        self._layer_visible[layer_id] = visible
        self._apply_layer_visibility(layer_id)

    def clear_layer(self, layer_id: int) -> None:
        if not self.available:
            return
        assert self._view is not None
        remove_keys = [k for k in self._items if k[0] == layer_id]
        for key in remove_keys:
            item = self._items.pop(key)
            self._view.removeItem(item)
        self._layer_visible.pop(layer_id, None)

    def clear(self) -> None:
        if not self.available:
            self._items.clear()
            self._layer_visible.clear()
            return
        assert self._view is not None
        for item in self._items.values():
            self._view.removeItem(item)
        self._items.clear()
        self._layer_visible.clear()
        self._view.hide()
