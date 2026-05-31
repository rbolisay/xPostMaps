"""Right pane: logo, minimap, postmap card (print-ready white theme)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from xpostmaps.core.models import GeoBounds, MapData, PostmapInfo, ProjectSettings, SurveyBounds
from xpostmaps.ui.minimap_widget import MinimapWidget
from xpostmaps.ui.postmap_card import PostmapInfoCard
from xpostmaps.ui.print_panel import PrintPanel
from xpostmaps.ui.theme import BG_PRINT, TEXT_PRINT


class RightPane(PrintPanel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(300)
        self._logo_path = ""
        self.setStyleSheet(f"background: {BG_PRINT}; color: {TEXT_PRINT};")
        self._build_ui()

    def _build_ui(self) -> None:
        layout = self.content_layout
        layout.setSpacing(6)

        self._logo_label = QLabel()
        self._logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._logo_label.setFixedHeight(56)
        self._logo_label.setStyleSheet(f"background: {BG_PRINT};")
        layout.addWidget(self._logo_label)

        self._minimap = MinimapWidget()
        layout.addWidget(self._minimap)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"background: {BG_PRINT}; border: none;")

        card_host = QWidget()
        card_host.setStyleSheet(f"background: {BG_PRINT};")
        card_layout = QVBoxLayout(card_host)
        card_layout.setContentsMargins(0, 0, 0, 0)
        self._card = PostmapInfoCard()
        card_layout.addWidget(self._card)
        scroll.setWidget(card_host)
        layout.addWidget(scroll, stretch=1)

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

    def update_from_project(
        self,
        settings: ProjectSettings,
        map_data: MapData | None,
    ) -> None:
        if settings.logo_path:
            self.set_logo(settings.logo_path)

        info = map_data.postmap_info if map_data else PostmapInfo()
        bounds = map_data.bounds if map_data else SurveyBounds()
        geo = map_data.geo_bounds if map_data else GeoBounds()

        self._card.update_content(info, bounds, settings.legend_config)
        self._card.updateGeometry()
        self._card.repaint()
        if geo.is_valid:
            self._minimap.set_location(geo)
