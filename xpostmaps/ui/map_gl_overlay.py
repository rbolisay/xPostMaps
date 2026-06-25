"""Optional OpenGL line overlay synced with the 2D map view."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QMatrix4x4
from PySide6.QtWidgets import QApplication

if TYPE_CHECKING:
    from pyqtgraph.opengl import GLLinePlotItem, GLViewWidget


def _bbox_intersects(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> bool:
    ax0, ax1, ay0, ay1 = a
    bx0, bx1, by0, by1 = b
    return ax1 >= bx0 and ax0 <= bx1 and ay1 >= by0 and ay0 <= by1


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
        self._run_bboxes: dict[tuple[int, int], tuple[float, float, float, float]] = {}
        self._layer_visible: dict[int, bool] = {}
        self._scatter_items: dict[tuple[int, int], object] = {}
        self._scatter_run_bboxes: dict[tuple[int, int], tuple[float, float, float, float]] = {}
        self._scatter_layer_visible: dict[int, bool] = {}
        self._viewport_cull = False
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

    def capture_image(self) -> QImage | None:
        """Grab the GL overlay as a bitmap (for PDF export compositing)."""
        if not self.available or self._view is None or not self._view.isVisible():
            return None
        self._view.update()
        self._view.repaint()
        make_current = getattr(self._view, "makeCurrent", None)
        if callable(make_current):
            make_current()
        app = QApplication.instance()
        if app is not None:
            for _ in range(6):
                app.processEvents()
        grab_fb = getattr(self._view, "grabFramebuffer", None)
        if callable(grab_fb):
            image = grab_fb()
            if not image.isNull() and self._image_has_content(image):
                return image
        pixmap = self._view.grab()
        if pixmap.isNull():
            return None
        return pixmap.toImage()

    @staticmethod
    def _image_has_content(image: QImage, *, sample_step: int = 12) -> bool:
        if image.isNull():
            return False
        visible = 0
        total = 0
        for y in range(0, image.height(), sample_step):
            for x in range(0, image.width(), sample_step):
                total += 1
                if image.pixelColor(x, y).alpha() > 8:
                    visible += 1
        return visible / max(total, 1) > 0.02

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
        if self._items or self._scatter_items:
            self._view.show()
        vb = self._plot.getViewBox()
        if vb is not None:
            (x_range, y_range) = vb.viewRange()
            self._view.set_view_range(tuple(x_range), tuple(y_range))
        if self._viewport_cull:
            self._apply_all_visibility()

    def sync_view(self) -> None:
        if not self.available:
            return
        assert self._view is not None
        vb = self._plot.getViewBox()
        if vb is None:
            return
        (x_range, y_range) = vb.viewRange()
        self._view.set_view_range(tuple(x_range), tuple(y_range))

    def set_viewport_cull(self, enabled: bool) -> None:
        self._viewport_cull = enabled
        self._apply_all_visibility()

    def _view_bbox(self) -> tuple[float, float, float, float] | None:
        vb = self._plot.getViewBox()
        if vb is None:
            return None
        (x_range, y_range) = vb.viewRange()
        x0, x1 = x_range
        y0, y1 = y_range
        pad_x = max((x1 - x0) * 0.02, 1.0)
        pad_y = max((y1 - y0) * 0.02, 1.0)
        return (x0 - pad_x, x1 + pad_x, y0 - pad_y, y1 + pad_y)

    def _apply_all_visibility(self) -> None:
        view_bbox = self._view_bbox() if self._viewport_cull else None
        for key, item in self._items.items():
            layer_id = key[0]
            if not self._layer_visible.get(layer_id, True):
                item.setVisible(False)
                continue
            run_bbox = self._run_bboxes.get(key)
            if view_bbox is None or run_bbox is None:
                item.setVisible(True)
                continue
            item.setVisible(_bbox_intersects(run_bbox, view_bbox))
        for key, item in self._scatter_items.items():
            layer_id = key[0]
            if not self._scatter_layer_visible.get(layer_id, True):
                item.setVisible(False)
                continue
            run_bbox = self._scatter_run_bboxes.get(key)
            if view_bbox is None or run_bbox is None:
                item.setVisible(True)
                continue
            item.setVisible(_bbox_intersects(run_bbox, view_bbox))

    def add_line_run(
        self,
        layer_id: int,
        run_index: int,
        rx: np.ndarray,
        ry: np.ndarray,
        *,
        color: tuple[float, float, float, float] | np.ndarray,
        width: float,
        mode: str = "line_strip",
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
            mode=mode,
        )
        self._view.addItem(item)
        self._items[storage_key] = item
        finite = np.isfinite(rx) & np.isfinite(ry)
        if np.any(finite):
            self._run_bboxes[storage_key] = (
                float(np.min(rx[finite])),
                float(np.max(rx[finite])),
                float(np.min(ry[finite])),
                float(np.max(ry[finite])),
            )
        self._layer_visible.setdefault(layer_id, True)
        layer_vis = self._layer_visible.get(layer_id, True)
        if self._viewport_cull:
            run_bbox = self._run_bboxes.get(storage_key)
            view_bbox = self._view_bbox()
            if run_bbox is not None and view_bbox is not None:
                layer_vis = layer_vis and _bbox_intersects(run_bbox, view_bbox)
        item.setVisible(layer_vis)

    def set_layer_visible(self, layer_id: int, visible: bool) -> None:
        if not self.available:
            return
        self._layer_visible[layer_id] = visible
        if self._viewport_cull:
            self._apply_all_visibility()
            return
        for key, item in self._items.items():
            if key[0] == layer_id:
                item.setVisible(visible)

    def add_scatter_run(
        self,
        layer_id: int,
        run_index: int,
        rx: np.ndarray,
        ry: np.ndarray,
        *,
        color: tuple[float, float, float, float] | np.ndarray,
        size: float,
    ) -> None:
        if not self.available:
            return
        from pyqtgraph.opengl import GLScatterPlotItem

        assert self._view is not None
        storage_key = (layer_id, run_index)
        if storage_key in self._scatter_items:
            return
        if rx.size < 1:
            return
        rx = np.asarray(rx, dtype=np.float64)
        ry = np.asarray(ry, dtype=np.float64)
        finite = np.isfinite(rx) & np.isfinite(ry)
        if not np.any(finite):
            return
        rx = rx[finite]
        ry = ry[finite]
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
        item = GLScatterPlotItem(
            pos=pos,
            color=color,
            size=max(1.0, float(size)),
            pxMode=True,
            glOptions="opaque",
        )
        self._view.addItem(item)
        self._scatter_items[storage_key] = item
        self._scatter_run_bboxes[storage_key] = (
            float(np.min(rx)),
            float(np.max(rx)),
            float(np.min(ry)),
            float(np.max(ry)),
        )
        self._scatter_layer_visible.setdefault(layer_id, True)
        layer_vis = self._scatter_layer_visible.get(layer_id, True)
        if self._viewport_cull:
            run_bbox = self._scatter_run_bboxes.get(storage_key)
            view_bbox = self._view_bbox()
            if run_bbox is not None and view_bbox is not None:
                layer_vis = layer_vis and _bbox_intersects(run_bbox, view_bbox)
        item.setVisible(layer_vis)

    def set_scatter_layer_visible(self, layer_id: int, visible: bool) -> None:
        if not self.available:
            return
        self._scatter_layer_visible[layer_id] = visible
        if self._viewport_cull:
            self._apply_all_visibility()
            return
        for key, item in self._scatter_items.items():
            if key[0] == layer_id:
                item.setVisible(visible)

    def clear_scatter_layer(self, layer_id: int) -> None:
        if not self.available:
            return
        assert self._view is not None
        remove_keys = [k for k in self._scatter_items if k[0] == layer_id]
        for key in remove_keys:
            item = self._scatter_items.pop(key)
            self._scatter_run_bboxes.pop(key, None)
            self._view.removeItem(item)
        self._scatter_layer_visible.pop(layer_id, None)

    def clear_layer(self, layer_id: int) -> None:
        if not self.available:
            return
        assert self._view is not None
        remove_keys = [k for k in self._items if k[0] == layer_id]
        for key in remove_keys:
            item = self._items.pop(key)
            self._run_bboxes.pop(key, None)
            self._view.removeItem(item)
        self._layer_visible.pop(layer_id, None)

    def clear(self) -> None:
        if not self.available:
            self._items.clear()
            self._run_bboxes.clear()
            self._layer_visible.clear()
            self._scatter_items.clear()
            self._scatter_run_bboxes.clear()
            self._scatter_layer_visible.clear()
            self._viewport_cull = False
            return
        assert self._view is not None
        for item in self._items.values():
            self._view.removeItem(item)
        for item in self._scatter_items.values():
            self._view.removeItem(item)
        self._items.clear()
        self._run_bboxes.clear()
        self._layer_visible.clear()
        self._scatter_items.clear()
        self._scatter_run_bboxes.clear()
        self._scatter_layer_visible.clear()
        self._viewport_cull = False
        self._view.hide()
