"""Right pane: logo, minimap, postmap card (print-ready white theme)."""

from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

# Qt maximum widget dimension (same role as QWIDGETSIZE_MAX).
_MAX_WIDGET_SIZE = 16777215

from xpostmaps.core.area_utils import resolve_area_polygon
from xpostmaps.core.crs_utils import WGS84_EPSG, normalize_epsg, transform_coordinates
from xpostmaps.core.models import GeoBounds, MapData, PostmapInfo, ProjectSettings, SurveyBounds
from xpostmaps.core.polygon_import_service import non_imported_polygon_entries
from xpostmaps.ui.minimap_widget import MinimapWidget

_MINIMAP_HEIGHT = MinimapWidget._HEIGHT
from xpostmaps.ui.postmap_card import PostmapInfoCard
from xpostmaps.ui.print_panel import PrintPanel
from xpostmaps.ui.theme import BG_PRINT, TEXT_PRINT


class RightPane(PrintPanel):
    minimap_view_changed = Signal(dict)

    # Panel is 20% wider than the original 360 px and its text scales to match,
    # applied in both the live GUI and the PDF export.
    _BASE_WIDTH = 432
    _TEXT_SCALE = 1.2
    # The PDF pane is an extra 20% wider than the on-screen panel.
    _EXPORT_WIDTH_SCALE = 1.2

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(self._BASE_WIDTH)
        self._logo_path = ""
        self.setStyleSheet(f"background: {BG_PRINT}; color: {TEXT_PRINT};")
        self._build_ui()
        self._card.set_text_scale(self._TEXT_SCALE)

    def _build_ui(self) -> None:
        layout = self.content_layout
        layout.setSpacing(6)

        self._logo_label = QLabel()
        self._logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._logo_label.setFixedHeight(56)
        self._logo_label.setStyleSheet(f"background: {BG_PRINT};")
        layout.addWidget(self._logo_label)

        self._minimap = MinimapWidget()
        self._minimap.view_changed.connect(self.minimap_view_changed.emit)
        layout.addWidget(self._minimap)

        self._card_scroll = QScrollArea()
        self._card_scroll.setWidgetResizable(True)
        self._card_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._card_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._card_scroll.setStyleSheet(f"background: {BG_PRINT}; border: none;")

        self._card_host = QWidget()
        self._card_host.setStyleSheet(f"background: {BG_PRINT};")
        card_layout = QVBoxLayout(self._card_host)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._card = PostmapInfoCard()
        card_layout.addWidget(self._card, 0, Qt.AlignmentFlag.AlignTop)
        self._card_scroll.setWidget(self._card_host)
        layout.addWidget(self._card_scroll, stretch=1)

    def set_logo(self, path: str) -> None:
        self._logo_path = path
        if path and Path(path).is_file():
            pix = QPixmap(path)
            if not pix.isNull():
                max_w = max(self.width() - 24, 200)
                scaled = pix.scaledToWidth(max_w, Qt.TransformationMode.SmoothTransformation)
                if scaled.height() > 56:
                    scaled = pix.scaledToHeight(56, Qt.TransformationMode.SmoothTransformation)
                self._logo_label.setPixmap(scaled)
                return
        self._logo_label.setPixmap(QPixmap())

    @staticmethod
    def _bounds_from_xy(xs: list[float], ys: list[float]) -> SurveyBounds:
        valid = [
            (x, y)
            for x, y in zip(xs, ys)
            if math.isfinite(x) and math.isfinite(y)
        ]
        if not valid:
            return SurveyBounds()
        vx, vy = zip(*valid)
        return SurveyBounds(min(vx), max(vx), min(vy), max(vy))

    @staticmethod
    def _geo_bounds_from_lon_lat(lons: list[float], lats: list[float]) -> GeoBounds:
        valid = [
            (lon, lat)
            for lon, lat in zip(lons, lats)
            if math.isfinite(lon) and math.isfinite(lat)
        ]
        if not valid:
            return GeoBounds()
        vlon, vlat = zip(*valid)
        return GeoBounds(min(vlat), max(vlat), min(vlon), max(vlon))

    def _right_pane_focus(
        self,
        settings: ProjectSettings,
        map_data: MapData | None,
        info: PostmapInfo,
    ) -> tuple[SurveyBounds, GeoBounds, list[tuple[list[float], list[float]]]]:
        if map_data is None:
            return SurveyBounds(), GeoBounds(), []

        visible_areas = [
            entry
            for entry in non_imported_polygon_entries(settings.legend_config.areas)
            if entry.name and not entry.hidden
        ]
        fullfold_areas = [
            entry for entry in visible_areas if "fullfold" in entry.name.lower()
        ]
        focus_areas = fullfold_areas or visible_areas

        focus_xs: list[float] = []
        focus_ys: list[float] = []
        focus_lons: list[float] = []
        focus_lats: list[float] = []
        focus_polygons: list[tuple[list[float], list[float]]] = []
        map_epsg = normalize_epsg(info.epsg_code)

        for entry in focus_areas:
            xs, ys = resolve_area_polygon(entry, map_data, settings.legend_config.areas)
            if len(xs) < 2 or len(xs) != len(ys):
                continue
            focus_xs.extend(xs)
            focus_ys.extend(ys)
            if not map_epsg:
                continue
            try:
                lons, lats = transform_coordinates(xs, ys, map_epsg, WGS84_EPSG)
            except Exception:
                continue
            if len(lons) < 2:
                continue
            focus_lons.extend(lons)
            focus_lats.extend(lats)
            focus_polygons.append((lons, lats))

        projected_bounds = self._bounds_from_xy(focus_xs, focus_ys)
        geo_bounds = self._geo_bounds_from_lon_lat(focus_lons, focus_lats)
        if not projected_bounds.is_valid:
            projected_bounds = map_data.bounds
        if not geo_bounds.is_valid:
            geo_bounds = map_data.geo_bounds
        return projected_bounds, geo_bounds, focus_polygons

    def update_from_project(
        self,
        settings: ProjectSettings,
        map_data: MapData | None,
    ) -> None:
        if settings.logo_path:
            self.set_logo(settings.logo_path)

        info = map_data.postmap_info if map_data else PostmapInfo()
        bounds, geo, minimap_polygons = self._right_pane_focus(settings, map_data, info)

        self._card.update_content(info, bounds, settings.legend_config)
        self._card.updateGeometry()
        self._card.repaint()
        self._minimap.set_location(geo, minimap_polygons, settings.minimap_view)

    def prepare_export_snapshot(self, map_height: int | None = None) -> None:
        """Prepare right pane for PDF capture at true aspect (same height as map)."""
        self._minimap.set_export_mode(True)
        # Widen the panel 20% for the PDF so content reflows wider (no text squeeze).
        self.setFixedWidth(int(round(self._BASE_WIDTH * self._EXPORT_WIDTH_SCALE)))
        # Match GUI minimap proportions: height scales with export width (432×215 ratio).
        self._minimap.setFixedHeight(
            int(round(_MINIMAP_HEIGHT * self._EXPORT_WIDTH_SCALE))
        )
        self._card.adjustSize()
        self._card_host.adjustSize()
        card_need = max(self._card.sizeHint().height(), self._card.height()) + 8
        self._card_host.setMinimumHeight(card_need)

        if map_height is not None and map_height > 0:
            self.setFixedHeight(map_height)
            chrome_h = self._logo_label.height() + self._minimap.height() + 12
            scroll_h = max(map_height - chrome_h, 100)
            self._card_scroll.setMinimumHeight(min(card_need, scroll_h))
            self._card_scroll.setMaximumHeight(scroll_h)
        else:
            self._card_scroll.setMinimumHeight(min(card_need, 2400))
            self._card_scroll.setMaximumHeight(_MAX_WIDGET_SIZE)

        self.adjustSize()
        self.repaint()

    def reset_export_snapshot(self) -> None:
        self.setMinimumHeight(0)
        self.setMaximumHeight(_MAX_WIDGET_SIZE)
        self._card_host.setMinimumHeight(0)
        self._card_scroll.setMinimumHeight(0)
        self._card_scroll.setMaximumHeight(_MAX_WIDGET_SIZE)
        self._minimap.set_export_mode(False)
        self._minimap.setFixedHeight(_MINIMAP_HEIGHT)
        self.setFixedWidth(self._BASE_WIDTH)
