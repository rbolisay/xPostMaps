"""Postmap information card matching reference layout (print white theme)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor, QPainter, QPen
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from xpostmaps.core.models import LegendConfig, LineStyle, PostmapInfo, SurveyBounds
from xpostmaps.ui.theme import BG_PRINT, TEXT_PRINT, TEXT_PRINT_SECONDARY
from xpostmaps.ui.widgets.scale_bar import ScaleBarWidget


class _LineSwatch(QWidget):
    def __init__(self, color: str, line_style: LineStyle = LineStyle.SOLID, parent=None) -> None:
        super().__init__(parent)
        self._color = color
        self._line_style = line_style
        self.setFixedSize(28, 14)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self._color)

        if self._line_style == LineStyle.DOTTED:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            for x in (6, 12, 18, 24):
                painter.drawEllipse(x - 2, 5, 4, 4)
        elif self._line_style == LineStyle.DASH:
            painter.setPen(QPen(color, 3, Qt.PenStyle.DashLine))
            painter.drawLine(2, 7, 26, 7)
        else:
            painter.setPen(QPen(color, 3, Qt.PenStyle.SolidLine))
            painter.drawLine(2, 7, 26, 7)


class _BoxSwatch(QWidget):
    def __init__(self, color: str, parent=None) -> None:
        super().__init__(parent)
        self._color = color
        self.setFixedSize(18, 14)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(QColor(self._color), 2)
        painter.setPen(pen)
        painter.drawRect(2, 2, 14, 10)


class PostmapInfoCard(QWidget):
    """Formatted postmap card for the right pane."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(f"background: {BG_PRINT}; color: {TEXT_PRINT};")
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 4)
        layout.setSpacing(4)

        header = QVBoxLayout()
        header.setSpacing(0)
        header.setContentsMargins(0, 0, 0, 0)

        self._client = QLabel("Client Name: —")
        self._area = QLabel("Area: —")
        self._project = QLabel("Project: —")
        for lbl in (self._client, self._area, self._project):
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            lbl.setStyleSheet(
                f"color: {TEXT_PRINT}; margin: 0; padding: 0; line-height: 1.1;"
            )
            lbl.setContentsMargins(0, 0, 0, 0)
            header.addWidget(lbl)

        layout.addLayout(header)
        layout.addSpacing(4)

        self._scale = ScaleBarWidget(km=40, print_theme=True)
        layout.addWidget(self._scale)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(3)
        self._left_labels: list[QLabel] = []
        self._right_labels: list[QLabel] = []
        for i in range(6):
            left = QLabel("")
            left.setWordWrap(True)
            left.setStyleSheet(f"font-size: 10px; color: {TEXT_PRINT};")
            right = QLabel("")
            right.setWordWrap(True)
            right.setStyleSheet(f"font-size: 10px; color: {TEXT_PRINT};")
            grid.addWidget(left, i, 0)
            grid.addWidget(right, i, 1)
            self._left_labels.append(left)
            self._right_labels.append(right)
        layout.addLayout(grid)

        self._legend_title = QLabel("Legend")
        self._legend_title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._legend_title.setStyleSheet(f"color: {TEXT_PRINT};")
        layout.addWidget(self._legend_title)

        self._legend_area = QVBoxLayout()
        self._legend_postplot = QVBoxLayout()
        layout.addLayout(self._legend_area)
        layout.addLayout(self._legend_postplot)

        osm = QLabel("OpenStreetMap")
        osm.setAlignment(Qt.AlignmentFlag.AlignCenter)
        osm.setStyleSheet(f"color: {TEXT_PRINT_SECONDARY}; font-size: 9px;")
        layout.addWidget(osm)

    def _clear_layout(self, lay: QVBoxLayout) -> None:
        while lay.count():
            item = lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
                continue
            child = item.layout()
            if child is not None:
                while child.count():
                    sub = child.takeAt(0)
                    if sub.widget():
                        sub.widget().deleteLater()

    def _add_legend_row(self, lay: QVBoxLayout, swatch: QWidget, text: str) -> None:
        row = QHBoxLayout()
        row.addWidget(swatch)
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"font-size: 10px; color: {TEXT_PRINT};")
        row.addWidget(lbl, stretch=1)
        w = QWidget()
        w.setLayout(row)
        lay.addWidget(w)

    def update_content(
        self,
        info: PostmapInfo,
        bounds: SurveyBounds,
        legend: LegendConfig,
    ) -> None:
        self._client.setText(f"Client Name: {info.client or '—'}")
        self._area.setText(f"Area: {info.area or '—'}")
        self._project.setText(f"Project: {info.project or '—'}")

        if bounds.is_valid:
            width_km = (bounds.xmax - bounds.xmin) / 1000
            self._scale.set_km(max(round(width_km / 4) * 4, 4))
        else:
            self._scale.set_km(40)

        left_rows = [
            f"Title: {info.title or '—'}",
            f"Job Number: {info.job_number or '—'}",
            f"Client Project Reference: {info.client_ref or '—'}",
            f"File Name: {info.file_name or '—'}",
            f"User Name: {info.user_name or '—'}",
            f"Date: {info.date or '—'}",
        ]
        right_rows = [
            "Coordinate Reference System",
            f"Name: {info.crs_name or '—'}",
            f"Projection: {info.projection or info.crs_name or '—'}",
            f"Authority: {info.epsg_code or '—'}",
            f"Geographic Datum: {info.geographic_datum or '—'}",
            f"Spheroid: {info.spheroid or '—'}",
        ]
        for i, text in enumerate(left_rows):
            self._left_labels[i].setText(text)
        for i, text in enumerate(right_rows):
            self._right_labels[i].setText(text)

        self._clear_layout(self._legend_area)
        self._clear_layout(self._legend_postplot)

        area_hdr = QLabel("Area")
        area_hdr.setStyleSheet(f"font-size: 10px; font-weight: 600; color: {TEXT_PRINT};")
        self._legend_area.addWidget(area_hdr)
        for entry in legend.areas:
            if entry.name:
                self._add_legend_row(
                    self._legend_area,
                    _BoxSwatch(entry.color),
                    entry.name,
                )

        post_hdr = QLabel("PostPlot")
        post_hdr.setStyleSheet(
            f"font-size: 10px; font-weight: 600; margin-top: 4px; color: {TEXT_PRINT};"
        )
        self._legend_postplot.addWidget(post_hdr)
        for entry in legend.postplot_lines:
            if entry.name:
                self._add_legend_row(
                    self._legend_postplot,
                    _LineSwatch(entry.color, line_style=entry.line_style),
                    entry.name,
                )

        self.updateGeometry()
        self.adjustSize()
        self.update()
