"""World minimap showing project location (print white theme)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from pyqtgraph import functions as fn
from pyqtgraph.Point import Point
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from xpostmaps.core.models import GeoBounds
from xpostmaps.ui.theme import MINIMAP_COAST, MINIMAP_OCEAN


_ASSETS = Path(__file__).resolve().parents[1] / "assets" / "world_coastlines.json"


class MinimapViewBox(pg.ViewBox):
    """Interactive minimap view: wheel zoom, right-drag pan, right-double-click extent."""

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("enableMenu", False)
        super().__init__(*args, **kwargs)
        self._extent_x: tuple[float, float] | None = None
        self._extent_y: tuple[float, float] | None = None

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
        self.setRange(xRange=self._extent_x, yRange=self._extent_y, padding=0, update=True)
        self.sigRangeChangedManually.emit(self.state["mouseEnabled"])

    def mouseClickEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.RightButton and ev.double():
            ev.accept()
            self.zoom_to_extent()
            return
        super().mouseClickEvent(ev)

    def mouseDragEvent(self, ev, axis=None) -> None:
        if ev.button() == Qt.MouseButton.RightButton:
            ev.accept()
            if ev.isStart() or ev.isFinish():
                return
            mouse_enabled = np.array(self.state["mouseEnabled"], dtype=np.float64)
            mask = mouse_enabled.copy()
            if axis is not None:
                mask[1 - axis] = 0.0
            tr = fn.invertQTransform(self.childGroup.transform())
            delta = tr.map((ev.pos() - ev.lastPos()) * -1 * mask) - tr.map(Point(0, 0))
            self._resetTarget()
            self.translateBy(
                x=delta.x() if mask[0] == 1 else None,
                y=delta.y() if mask[1] == 1 else None,
            )
            self.sigRangeChangedManually.emit(self.state["mouseEnabled"])
            return
        super().mouseDragEvent(ev, axis)


class MinimapWidget(QWidget):
    view_changed = Signal(dict)

    _HEIGHT = 215  # 150 px + 30%, then +10% (195 × 1.1)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(self._HEIGHT)
        self._suppress_view_changed = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._view_box = MinimapViewBox()
        self._plot = pg.PlotWidget(background=MINIMAP_OCEAN, viewBox=self._view_box)
        self._plot.setStyleSheet("border: 1px solid #111111;")
        self._plot.setMenuEnabled(False)
        self._plot.hideAxis("bottom")
        self._plot.hideAxis("left")
        self._plot.setAspectLocked(True)
        self._plot.setMouseEnabled(x=True, y=True)
        layout.addWidget(self._plot)

        self._coast_segments: list[tuple[list[float], list[list[float]]]] = []
        self._coast_items: list[pg.PlotDataItem] = []
        self._export_mode = False
        # Marker / area polygons kept so pens can be rebuilt for export without
        # changing the current minimap view.
        self._marker_xy: tuple[list[float], list[float]] | None = None
        self._area_polys: list[tuple[list[float], list[float]]] = []
        self._coast_pen = pg.mkPen(MINIMAP_COAST, width=self._coast_width())
        self._coast_refresh_timer = QTimer(self)
        self._coast_refresh_timer.setSingleShot(True)
        self._coast_refresh_timer.setInterval(16)
        self._coast_refresh_timer.timeout.connect(self._refresh_visible_coastlines)
        self._marker: pg.PlotDataItem | None = None
        self._area_items: list[pg.PlotDataItem] = []
        self._view_box.sigRangeChanged.connect(self._schedule_coast_refresh)
        self._view_box.sigRangeChangedManually.connect(self._schedule_coast_refresh)
        self._view_box.sigRangeChangedManually.connect(self._emit_view_changed)
        self._load_coastline_data()

    def _coast_width(self) -> float:
        return 2.4 if self._export_mode else 0.9

    def _marker_width(self) -> float:
        return 4.0 if self._export_mode else 2.0

    def _area_width(self) -> float:
        return 3.2 if self._export_mode else 1.6

    def set_export_mode(self, enabled: bool) -> None:
        """Thicken pens and enable antialiasing so the minimap stays crisp in the PDF."""
        if enabled == self._export_mode:
            return
        self._export_mode = enabled
        self._coast_pen = pg.mkPen(MINIMAP_COAST, width=self._coast_width())
        self._refresh_visible_coastlines()
        self._rebuild_marker_items()

    def _rebuild_marker_items(self) -> None:
        """Recreate marker + area items with the current pen widths / antialiasing."""
        if self._marker is not None:
            self._plot.removeItem(self._marker)
            self._marker = None
        for item in self._area_items:
            self._plot.removeItem(item)
        self._area_items.clear()

        if self._marker_xy is not None:
            xs, ys = self._marker_xy
            self._marker = pg.PlotDataItem(
                xs, ys,
                pen=pg.mkPen("#cc0000", width=self._marker_width()),
                connect="all",
                antialias=self._export_mode,
            )
            self._plot.addItem(self._marker)
        for lons, lats in self._area_polys:
            area_item = pg.PlotDataItem(
                lons, lats,
                pen=pg.mkPen("#00a651", width=self._area_width()),
                connect="all",
                antialias=self._export_mode,
            )
            self._plot.addItem(area_item)
            self._area_items.append(area_item)

    @staticmethod
    def _valid_saved_view(view: dict | None) -> tuple[tuple[float, float], tuple[float, float]] | None:
        if not isinstance(view, dict):
            return None
        try:
            lon_min = float(view.get("lon_min", 0.0))
            lon_max = float(view.get("lon_max", 0.0))
            lat_min = float(view.get("lat_min", 0.0))
            lat_max = float(view.get("lat_max", 0.0))
        except (TypeError, ValueError):
            return None
        if lon_max <= lon_min or lat_max <= lat_min:
            return None
        return (lon_min, lon_max), (lat_min, lat_max)

    def current_view(self) -> dict[str, float]:
        x_range, y_range = self._view_box.viewRange()
        return {
            "lon_min": float(x_range[0]),
            "lon_max": float(x_range[1]),
            "lat_min": float(y_range[0]),
            "lat_max": float(y_range[1]),
        }

    def _emit_view_changed(self, *_args) -> None:
        if not self._suppress_view_changed:
            self.view_changed.emit(self.current_view())

    def _load_coastline_data(self) -> None:
        if not _ASSETS.exists():
            return
        data = json.loads(_ASSETS.read_text(encoding="utf-8"))
        segments = data.get("segments")
        if segments:
            self._coast_segments = [
                (seg["b"], seg["p"])
                for seg in segments
                if len(seg.get("p", [])) >= 2
            ]
        else:
            self._coast_segments = []
            for line in data.get("lines", []):
                if len(line) < 2:
                    continue
                lons = [pt[0] for pt in line]
                lats = [pt[1] for pt in line]
                self._coast_segments.append(
                    ([min(lons), min(lats), max(lons), max(lats)], line),
                )
        self._plot.setRange(xRange=(-30, 45), yRange=(50, 72), padding=0.02)
        self._refresh_visible_coastlines()

    def _schedule_coast_refresh(self, *_args) -> None:
        if not self._coast_segments:
            return
        self._coast_refresh_timer.start()

    @staticmethod
    def _segment_in_view(
        bbox: list[float],
        x0: float,
        x1: float,
        y0: float,
        y1: float,
    ) -> bool:
        b0, b1, b2, b3 = bbox
        if b0 > b2:
            return True
        return not (b2 < x0 or b0 > x1 or b3 < y0 or b1 > y1)

    def _clear_coast_items(self) -> None:
        for item in self._coast_items:
            self._plot.removeItem(item)
        self._coast_items.clear()

    def _refresh_visible_coastlines(self) -> None:
        if not self._coast_segments:
            return
        x_range, y_range = self._view_box.viewRange()
        x0, x1 = float(x_range[0]), float(x_range[1])
        y0, y1 = float(y_range[0]), float(y_range[1])
        pad_x = (x1 - x0) * 0.08
        pad_y = (y1 - y0) * 0.08
        x0 -= pad_x
        x1 += pad_x
        y0 -= pad_y
        y1 += pad_y

        self._clear_coast_items()
        for bbox, points in self._coast_segments:
            if not self._segment_in_view(bbox, x0, x1, y0, y1):
                continue
            lons = [pt[0] for pt in points]
            lats = [pt[1] for pt in points]
            item = pg.PlotDataItem(
                lons,
                lats,
                pen=self._coast_pen,
                connect="all",
                antialias=self._export_mode,
            )
            self._plot.addItem(item)
            self._coast_items.append(item)

    def set_location(
        self,
        geo: GeoBounds,
        area_polygons: list[tuple[list[float], list[float]]] | None = None,
        saved_view: dict | None = None,
        tight_zoom: bool = False,
    ) -> None:
        if self._marker:
            self._plot.removeItem(self._marker)
            self._marker = None
        for item in self._area_items:
            self._plot.removeItem(item)
        self._area_items.clear()
        self._marker_xy = None
        self._area_polys = []
        if not geo.is_valid:
            self._view_box.set_extent_range(None, None)
            return

        pad_lat = max((geo.lat_max - geo.lat_min) * 0.15, 0.2)
        pad_lon = max((geo.lon_max - geo.lon_min) * 0.15, 0.2)
        xs = [
            geo.lon_min - pad_lon,
            geo.lon_max + pad_lon,
            geo.lon_max + pad_lon,
            geo.lon_min - pad_lon,
            geo.lon_min - pad_lon,
        ]
        ys = [
            geo.lat_min - pad_lat,
            geo.lat_min - pad_lat,
            geo.lat_max + pad_lat,
            geo.lat_max + pad_lat,
            geo.lat_min - pad_lat,
        ]
        self._marker_xy = (xs, ys)
        self._marker = pg.PlotDataItem(
            xs, ys,
            pen=pg.mkPen("#cc0000", width=self._marker_width()),
            connect="all",
            antialias=self._export_mode,
        )
        self._plot.addItem(self._marker)
        for lons, lats in area_polygons or []:
            if len(lons) < 2 or len(lons) != len(lats):
                continue
            self._area_polys.append((lons, lats))
            area_item = pg.PlotDataItem(
                lons,
                lats,
                pen=pg.mkPen("#00a651", width=self._area_width()),
                connect="all",
                antialias=self._export_mode,
            )
            self._plot.addItem(area_item)
            self._area_items.append(area_item)

        if tight_zoom:
            # Frame the survey/main-map extent with enough surrounding context
            # that it does not fill the whole minimap as a single square, while
            # still staying far closer than the wide 4x context view.
            pad_lon = max((geo.lon_max - geo.lon_min) * 0.9, 0.6)
            pad_lat = max((geo.lat_max - geo.lat_min) * 0.9, 0.6)
            x_range = (geo.lon_min - pad_lon, geo.lon_max + pad_lon)
            y_range = (geo.lat_min - pad_lat, geo.lat_max + pad_lat)
        else:
            cx = (geo.lon_min + geo.lon_max) / 2
            cy = (geo.lat_min + geo.lat_max) / 2
            span = max(geo.lon_max - geo.lon_min, geo.lat_max - geo.lat_min, 0.5) * 4.0
            x_range = (cx - span, cx + span)
            y_range = (cy - span * 0.6, cy + span * 0.6)
        self._view_box.set_extent_range(x_range, y_range)
        saved_ranges = self._valid_saved_view(saved_view)
        target_x, target_y = saved_ranges if saved_ranges is not None else (x_range, y_range)
        self._suppress_view_changed = True
        self._plot.setRange(
            xRange=target_x,
            yRange=target_y,
            padding=0.05,
        )
        self._suppress_view_changed = False
        self._refresh_visible_coastlines()
