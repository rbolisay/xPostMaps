"""Postmap information card matching reference layout (print white theme)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontMetrics, QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from xpostmaps.core.crs_utils import epsg_label
from xpostmaps.core.models import LegendConfig, LineStyle, PostmapInfo, SurveyBounds
from xpostmaps.core.polygon_import_service import non_imported_polygon_entries
from xpostmaps.ui.theme import BG_PRINT, TEXT_PRINT
from xpostmaps.ui.widgets.scale_bar import ScaleBarWidget

# Right-pane vertical rhythm (postplot sheet layout)
_SCALE_MARGIN = 8
_METADATA_TOP = 6
_LEGEND_TOP = 10
_LEGEND_TITLE_GAP = 6
_LEGEND_SECTION_GAP = 8
_LEGEND_ITEM_GAP = 3


class _LineSwatch(QWidget):
    def __init__(self, color: str, line_style: LineStyle = LineStyle.SOLID, parent=None) -> None:
        super().__init__(parent)
        self._color = color
        self._line_style = line_style
        self.setFixedSize(24, 12)

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
        self.setFixedSize(16, 12)

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
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Maximum,
        )

        header = QVBoxLayout()
        header.setSpacing(0)
        header.setContentsMargins(0, 0, 0, 0)

        header_font = QFont("Segoe UI", 10, QFont.Weight.Bold)
        header_line_h = QFontMetrics(header_font).height()

        self._client = QLabel("Client Name: —")
        self._area = QLabel("Area: —")
        self._project = QLabel("Project: —")
        for lbl in (self._client, self._area, self._project):
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setFont(header_font)
            lbl.setStyleSheet(
                f"color: {TEXT_PRINT}; margin: 0; padding: 0; line-height: 1.0;"
            )
            lbl.setContentsMargins(0, 0, 0, 0)
            lbl.setFixedHeight(header_line_h)
            header.addWidget(lbl)

        layout.addLayout(header)
        layout.addSpacing(_SCALE_MARGIN)

        self._scale = ScaleBarWidget(km=40, print_theme=True)
        layout.addWidget(self._scale)
        layout.addSpacing(_SCALE_MARGIN)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(4)
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
        layout.addSpacing(_METADATA_TOP)

        legend_block = QWidget()
        legend_block.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Maximum,
        )
        self._legend_content = QVBoxLayout(legend_block)
        self._legend_content.setSpacing(_LEGEND_ITEM_GAP)
        self._legend_content.setContentsMargins(0, 0, 0, 0)

        self._legend_title = QLabel("Legend")
        self._legend_title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self._legend_title.setStyleSheet(
            f"color: {TEXT_PRINT}; margin: 0; padding: 0; line-height: 1.0;"
        )
        self._legend_title.setContentsMargins(0, 0, 0, 0)
        self._legend_content.addWidget(self._legend_title)

        layout.addSpacing(_LEGEND_TOP)
        layout.addWidget(legend_block)
        layout.addStretch(1)

    def _clear_legend_entries(self) -> None:
        """Remove dynamic legend rows but keep the Legend title."""
        while self._legend_content.count() > 1:
            item = self._legend_content.takeAt(1)
            if item is None:
                break
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

    @staticmethod
    def _legend_section_header(text: str) -> QLabel:
        hdr = QLabel(text)
        hdr.setStyleSheet(
            f"font-size: 10px; font-weight: 600; color: {TEXT_PRINT};"
            " margin: 0; padding: 0; line-height: 1.0;"
        )
        hdr.setContentsMargins(0, 0, 0, 0)
        hdr.setFixedHeight(hdr.fontMetrics().height())
        return hdr

    def _legend_row_widget(self, swatch: QWidget, text: str) -> QWidget:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        row.addWidget(swatch)
        lbl = QLabel(text)
        lbl.setWordWrap(False)
        lbl.setStyleSheet(
            f"font-size: 9px; color: {TEXT_PRINT}; margin: 0; padding: 0; line-height: 1.0;"
        )
        lbl.setContentsMargins(0, 0, 0, 0)
        row.addWidget(lbl, stretch=1)
        w = QWidget()
        w.setLayout(row)
        w.setFixedHeight(14)
        return w

    def _add_legend_grid(
        self,
        lay: QVBoxLayout,
        rows: list[tuple[QWidget, str]],
    ) -> None:
        if not rows:
            return
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(2)
        for index, (swatch, text) in enumerate(rows):
            grid.addWidget(self._legend_row_widget(swatch, text), index // 2, index % 2)
        w = QWidget()
        w.setLayout(grid)
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
            f"Job Number: {info.job_number or '—'}",
            f"Client Project Reference: {info.client_ref or '—'}",
            f"File Name: {info.file_name or '—'}",
            f"User Name: {info.user_name or '—'}",
            f"Date: {info.date or '—'}",
        ]
        authority = epsg_label(info.epsg_code) if info.epsg_code else "—"
        right_rows = [
            "Coordinate Reference System",
            f"Name: {info.crs_name or '—'}",
            f"Projection: {info.projection or info.crs_name or '—'}",
            f"Authority: {authority}",
            f"Geographic Datum: {info.geographic_datum or '—'}",
            f"Spheroid: {info.spheroid or '—'}",
        ]
        for i, text in enumerate(left_rows):
            self._left_labels[i].setText(text)
        for i in range(len(left_rows), len(self._left_labels)):
            self._left_labels[i].setText("")
        for i, text in enumerate(right_rows):
            self._right_labels[i].setText(text)

        self._clear_legend_entries()

        visible_areas = [
            entry
            for entry in non_imported_polygon_entries(legend.areas)
            if entry.name and not entry.hidden
        ]
        visible_preplot = [
            entry for entry in legend.preplot_lines if entry.name and not entry.hidden
        ]
        visible_postplot = [
            entry for entry in legend.postplot_lines if entry.name and not entry.hidden
        ]

        if visible_areas or visible_preplot or visible_postplot:
            self._legend_content.addSpacing(_LEGEND_TITLE_GAP)

        first_section = True
        if visible_areas:
            self._legend_content.addWidget(self._legend_section_header("Area"))
            self._add_legend_grid(
                self._legend_content,
                [(_BoxSwatch(entry.color), entry.name) for entry in visible_areas],
            )
            first_section = False

        if visible_preplot:
            if not first_section:
                self._legend_content.addSpacing(_LEGEND_SECTION_GAP)
            self._legend_content.addWidget(self._legend_section_header("Preplot"))
            self._add_legend_grid(
                self._legend_content,
                [
                    (_LineSwatch(entry.color, line_style=entry.line_style), entry.name)
                    for entry in visible_preplot
                ],
            )
            first_section = False

        if visible_postplot:
            if not first_section:
                self._legend_content.addSpacing(_LEGEND_SECTION_GAP)
            self._legend_content.addWidget(self._legend_section_header("PostPlot"))
            self._add_legend_grid(
                self._legend_content,
                [
                    (_LineSwatch(entry.color, line_style=entry.line_style), entry.name)
                    for entry in visible_postplot
                ],
            )

        self.updateGeometry()
        self.adjustSize()
        self.update()
