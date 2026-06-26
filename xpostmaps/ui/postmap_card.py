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

from xpostmaps.core.legend_utils import legend_section_title
from xpostmaps.core.models import LegendConfig, LineStyle, PostmapInfo, SurveyBounds
from xpostmaps.core.postmap_info_layout import column_display_lines, ensure_layout
from xpostmaps.core.polygon_import_service import non_imported_polygon_entries
from xpostmaps.ui.theme import BG_PRINT, TEXT_PRINT
from xpostmaps.ui.widgets.scale_bar import ScaleBarWidget
from xpostmaps.utils.symbology_units import DEFAULT_SCREEN_DPI, mm_to_pixels, scatter_size_px

# Right-pane vertical rhythm (postplot sheet layout)
_SCALE_MARGIN = 8
_METADATA_TOP = 6
_LEGEND_TOP = 10
_LEGEND_TITLE_GAP = 6
_LEGEND_SECTION_GAP = 8
_LEGEND_ITEM_GAP = 3


class _LineSwatch(QWidget):
    def __init__(
        self,
        color: str,
        line_style: LineStyle = LineStyle.SOLID,
        scale: float = 1.0,
        line_width_mm: float = 0.35,
        dot_radius_mm: float = 0.8,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._color = color
        self._line_style = line_style
        self._scale = scale
        self._line_width_mm = line_width_mm
        self._dot_radius_mm = dot_radius_mm
        self.setFixedSize(int(round(24 * scale)), int(round(12 * scale)))

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(self._scale, self._scale)
        color = QColor(self._color)

        if self._line_style == LineStyle.DOTTED:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            dot_px = scatter_size_px(DEFAULT_SCREEN_DPI, self._dot_radius_mm)
            radius_px = max(1.0, dot_px * 0.5)
            y_center = 6.0
            for x in (6.0, 12.0, 18.0, 24.0):
                painter.drawEllipse(
                    x - radius_px,
                    y_center - radius_px,
                    radius_px * 2.0,
                    radius_px * 2.0,
                )
        elif self._line_style == LineStyle.DASH:
            width_px = max(1.0, mm_to_pixels(DEFAULT_SCREEN_DPI, self._line_width_mm))
            painter.setPen(QPen(color, width_px, Qt.PenStyle.DashLine))
            painter.drawLine(2, 7, 26, 7)
        else:
            width_px = max(1.0, mm_to_pixels(DEFAULT_SCREEN_DPI, self._line_width_mm))
            painter.setPen(QPen(color, width_px, Qt.PenStyle.SolidLine))
            painter.drawLine(2, 7, 26, 7)


class _BoxSwatch(QWidget):
    def __init__(self, color: str, scale: float = 1.0, parent=None) -> None:
        super().__init__(parent)
        self._color = color
        self._scale = scale
        self.setFixedSize(int(round(16 * scale)), int(round(12 * scale)))

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.scale(self._scale, self._scale)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(QColor(self._color), 2)
        painter.setPen(pen)
        painter.drawRect(2, 2, 14, 10)


class PostmapInfoCard(QWidget):
    """Formatted postmap card for the right pane."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(f"background: {BG_PRINT}; color: {TEXT_PRINT};")
        self._text_scale = 1.0
        self._last_args: tuple | None = None
        self._build_ui()

    def _px(self, value: float) -> int:
        return max(int(round(value * self._text_scale)), 1)

    def _header_font(self) -> QFont:
        font = QFont("Segoe UI")
        font.setPointSizeF(13 * self._text_scale)
        font.setWeight(QFont.Weight.Bold)
        return font

    def set_text_scale(self, scale: float) -> None:
        """Scale all card text/swatches (applied to both the GUI and PDF export)."""
        scale = max(scale, 0.5)
        if abs(scale - self._text_scale) < 0.001:
            return
        self._text_scale = scale
        header_font = self._header_font()
        header_line_h = QFontMetrics(header_font).height()
        for lbl in (self._client, self._area, self._project):
            lbl.setFont(header_font)
            lbl.setFixedHeight(header_line_h)
        title_font = QFont("Segoe UI")
        title_font.setPointSizeF(11 * self._text_scale)
        title_font.setWeight(QFont.Weight.Bold)
        self._legend_title.setFont(title_font)
        if self._last_args is not None:
            self.update_content(*self._last_args)

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

        header_font = self._header_font()
        header_line_h = QFontMetrics(header_font).height()

        self._client = QLabel("Client Name: —")
        self._area = QLabel("Area: —")
        self._project = QLabel("Project Name: —")
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

        self._metadata_grid = QGridLayout()
        self._metadata_grid.setHorizontalSpacing(14)
        self._metadata_grid.setVerticalSpacing(4)
        self._metadata_labels: list[QLabel] = []
        layout.addLayout(self._metadata_grid)
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
        _title_font = QFont("Segoe UI")
        _title_font.setPointSizeF(11 * self._text_scale)
        _title_font.setWeight(QFont.Weight.Bold)
        self._legend_title.setFont(_title_font)
        self._legend_title.setStyleSheet(
            f"color: {TEXT_PRINT}; margin: 0; padding: 0; line-height: 1.0;"
        )
        self._legend_title.setContentsMargins(0, 0, 0, 0)
        self._legend_content.addWidget(self._legend_title)

        layout.addSpacing(_LEGEND_TOP)
        layout.addWidget(legend_block)
        layout.addStretch(1)

    def _clear_metadata_labels(self) -> None:
        for lbl in self._metadata_labels:
            self._metadata_grid.removeWidget(lbl)
            lbl.deleteLater()
        self._metadata_labels.clear()

    def _set_metadata_columns(self, left_lines: list[str], right_lines: list[str]) -> None:
        self._clear_metadata_labels()
        row_count = max(len(left_lines), len(right_lines), 1)
        label_style = f"font-size: {self._px(10)}px; color: {TEXT_PRINT};"
        for row in range(row_count):
            left_text = left_lines[row] if row < len(left_lines) else ""
            right_text = right_lines[row] if row < len(right_lines) else ""
            for col, text in ((0, left_text), (1, right_text)):
                lbl = QLabel(text)
                lbl.setWordWrap(True)
                lbl.setStyleSheet(label_style)
                self._metadata_grid.addWidget(lbl, row, col)
                self._metadata_labels.append(lbl)

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

    def _legend_section_header(self, text: str) -> QLabel:
        hdr = QLabel(text)
        hdr.setStyleSheet(
            f"font-size: {self._px(10)}px; font-weight: 600; color: {TEXT_PRINT};"
            " margin: 0; padding: 0; line-height: 1.0;"
        )
        hdr.setContentsMargins(0, 0, 0, 0)
        hdr.setFixedHeight(hdr.fontMetrics().height())
        return hdr

    def _legend_row_widget(self, swatch: QWidget, text: str) -> QWidget:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(self._px(2))
        row.addWidget(swatch)
        lbl = QLabel(text)
        lbl.setWordWrap(False)
        lbl.setStyleSheet(
            f"font-size: {self._px(9)}px; color: {TEXT_PRINT};"
            " margin: 0; padding: 0; line-height: 1.0;"
        )
        lbl.setContentsMargins(0, 0, 0, 0)
        row.addWidget(lbl, stretch=1)
        w = QWidget()
        w.setLayout(row)
        w.setFixedHeight(self._px(14))
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

    def update_info_section(
        self,
        info: PostmapInfo,
        bounds: SurveyBounds,
    ) -> None:
        """Update project header and metadata only (skip legend rebuild)."""
        if self._last_args:
            self._last_args = (info, bounds, self._last_args[2])
        else:
            self._last_args = (info, bounds, LegendConfig.default())

        self._client.setText(f"Client Name: {info.client or '—'}")
        self._area.setText(f"Area: {info.area or '—'}")
        self._project.setText(f"Project Name: {info.project or '—'}")

        if bounds.is_valid:
            width_km = (bounds.xmax - bounds.xmin) / 1000
            self._scale.set_km(max(round(width_km / 4) * 4, 4))
        else:
            self._scale.set_km(40)

        ensure_layout(info)
        left_rows = column_display_lines(info, 0)
        right_rows = column_display_lines(info, 1)
        self._set_metadata_columns(left_rows, right_rows)
        self.updateGeometry()
        self.adjustSize()
        self.update()

    def update_content(
        self,
        info: PostmapInfo,
        bounds: SurveyBounds,
        legend: LegendConfig,
    ) -> None:
        self._last_args = (info, bounds, legend)
        self._client.setText(f"Client Name: {info.client or '—'}")
        self._area.setText(f"Area: {info.area or '—'}")
        self._project.setText(f"Project Name: {info.project or '—'}")

        if bounds.is_valid:
            width_km = (bounds.xmax - bounds.xmin) / 1000
            self._scale.set_km(max(round(width_km / 4) * 4, 4))
        else:
            self._scale.set_km(40)

        ensure_layout(info)
        left_rows = column_display_lines(info, 0)
        right_rows = column_display_lines(info, 1)
        self._set_metadata_columns(left_rows, right_rows)

        self._clear_legend_entries()

        visible_areas = [
            entry
            for entry in non_imported_polygon_entries(legend.areas)
            if entry.name and not entry.hidden
        ]
        visible_preplot = [
            entry for entry in legend.preplot_lines if entry.name and not entry.hidden
        ]
        visible_navplan = [
            entry for entry in legend.navplan_lines if entry.name and not entry.hidden
        ]
        visible_postplot = [
            entry for entry in legend.postplot_lines if entry.name and not entry.hidden
        ]

        if visible_areas or visible_preplot or visible_navplan or visible_postplot:
            self._legend_content.addSpacing(_LEGEND_TITLE_GAP)

        first_section = True
        if visible_areas:
            self._legend_content.addWidget(
                self._legend_section_header(
                    legend_section_title(legend.area_section_title, "Area")
                )
            )
            self._add_legend_grid(
                self._legend_content,
                [
                    (_BoxSwatch(entry.color, scale=self._text_scale), entry.name)
                    for entry in visible_areas
                ],
            )
            first_section = False

        if visible_preplot:
            if not first_section:
                self._legend_content.addSpacing(_LEGEND_SECTION_GAP)
            self._legend_content.addWidget(
                self._legend_section_header(
                    legend_section_title(legend.preplot_section_title, "Preplot")
                )
            )
            self._add_legend_grid(
                self._legend_content,
                [
                    (
                        _LineSwatch(
                            entry.color,
                            line_style=entry.line_style,
                            scale=self._text_scale,
                            line_width_mm=entry.line_width,
                            dot_radius_mm=entry.dot_radius,
                        ),
                        entry.name,
                    )
                    for entry in visible_preplot
                ],
            )
            first_section = False

        if visible_navplan:
            if not first_section:
                self._legend_content.addSpacing(_LEGEND_SECTION_GAP)
            self._legend_content.addWidget(
                self._legend_section_header(
                    legend_section_title(legend.navplan_section_title, "Navplan")
                )
            )
            self._add_legend_grid(
                self._legend_content,
                [
                    (
                        _LineSwatch(
                            entry.color,
                            line_style=entry.line_style,
                            scale=self._text_scale,
                            line_width_mm=entry.line_width,
                            dot_radius_mm=entry.dot_radius,
                        ),
                        entry.name,
                    )
                    for entry in visible_navplan
                ],
            )
            first_section = False

        if visible_postplot:
            if not first_section:
                self._legend_content.addSpacing(_LEGEND_SECTION_GAP)
            self._legend_content.addWidget(
                self._legend_section_header(
                    legend_section_title(legend.postplot_section_title, "PostPlot")
                )
            )
            self._add_legend_grid(
                self._legend_content,
                [
                    (
                        _LineSwatch(
                            entry.color,
                            line_style=entry.line_style,
                            scale=self._text_scale,
                            line_width_mm=entry.line_width,
                            dot_radius_mm=entry.dot_radius,
                        ),
                        entry.name,
                    )
                    for entry in visible_postplot
                ],
            )

        self.updateGeometry()
        self.adjustSize()
        self.update()
