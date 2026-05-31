"""World minimap showing project location (print white theme)."""

from __future__ import annotations

import json
from pathlib import Path

import pyqtgraph as pg
from PySide6.QtWidgets import QVBoxLayout, QWidget

from xpostmaps.core.models import GeoBounds
from xpostmaps.ui.theme import MINIMAP_COAST, MINIMAP_OCEAN


_ASSETS = Path(__file__).resolve().parents[1] / "assets" / "world_coastlines.json"


class MinimapWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(150)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._plot = pg.PlotWidget(background=MINIMAP_OCEAN)
        self._plot.setMenuEnabled(False)
        self._plot.hideAxis("bottom")
        self._plot.hideAxis("left")
        self._plot.setAspectLocked(True)
        self._plot.setMouseEnabled(x=False, y=False)
        layout.addWidget(self._plot)

        self._coast_items: list[pg.PlotDataItem] = []
        self._marker: pg.PlotDataItem | None = None
        self._load_coastlines()

    def _load_coastlines(self) -> None:
        if not _ASSETS.exists():
            return
        data = json.loads(_ASSETS.read_text(encoding="utf-8"))
        for line in data.get("lines", []):
            lons = [pt[0] for pt in line]
            lats = [pt[1] for pt in line]
            item = pg.PlotDataItem(
                lons, lats,
                pen=pg.mkPen(MINIMAP_COAST, width=0.9),
                connect="all",
            )
            self._plot.addItem(item)
            self._coast_items.append(item)
        self._plot.setRange(xRange=(-30, 45), yRange=(50, 72), padding=0.02)

    def set_location(self, geo: GeoBounds) -> None:
        if self._marker:
            self._plot.removeItem(self._marker)
            self._marker = None
        if not geo.is_valid:
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
        self._marker = pg.PlotDataItem(
            xs, ys,
            pen=pg.mkPen("#cc0000", width=2),
            connect="all",
        )
        self._plot.addItem(self._marker)

        cx = (geo.lon_min + geo.lon_max) / 2
        cy = (geo.lat_min + geo.lat_max) / 2
        span = max(geo.lon_max - geo.lon_min, geo.lat_max - geo.lat_min, 2.0) * 8
        self._plot.setRange(
            xRange=(cx - span, cx + span),
            yRange=(cy - span * 0.6, cy + span * 0.6),
            padding=0.05,
        )
