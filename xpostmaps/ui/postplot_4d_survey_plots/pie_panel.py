"""Survey spec pass/fail pie charts for the whole survey."""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import QFont, QFontMetrics, QImage, QPainter, QColor, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from xpostmaps.core.postplot_4d_survey_plot_data import (
    PieSlice,
    SurveySpecPieData,
    SurveySpecPieStats,
)
from xpostmaps.ui.postplot_4d_survey_plots.survey_plot_navigation import SurveyPanZoomWidget

_CARD_BG = "#161b22"
_CARD_BORDER = "#30363d"
_INFO_FG = "#8b949e"
_INFO_VALUE = "#e6edf3"
_PASS_COLOR = "#22c55e"
_FAIL_COLOR = "#ef4444"
_TITLE_FG = "#f0f6fc"
_SUBTITLE_FG = "#8b949e"
_MIN_PIE = 280

_PIE_SUB_TAB_STYLE = """
QTabWidget::pane {
    border: 1px solid #30363d;
    border-radius: 6px;
    background: #0d1117;
    top: -1px;
}
QTabBar::tab {
    background: #21262d;
    color: #8b949e;
    padding: 6px 14px;
    margin-right: 2px;
    border: 1px solid #30363d;
    border-bottom: none;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    min-width: 64px;
    font-size: 11px;
}
QTabBar::tab:selected {
    background: #30363d;
    color: #58a6ff;
    font-weight: 600;
    border-color: #58a6ff;
}
QTabBar::tab:hover:!selected {
    background: #262c36;
    color: #c9d1d9;
}
"""


def _format_count(value: int) -> str:
    return f"{value:,}"


def _format_metric(value: float | None, unit: str) -> str:
    if value is None:
        return "—"
    if unit == "deg":
        return f"{value:.2f} {unit}"
    return f"{value:.2f} {unit}"


class _PieChartWidget(SurveyPanZoomWidget):
    """Pie chart with percentage labels on slices."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(_MIN_PIE, _MIN_PIE)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._slices: list[PieSlice] = []

    def set_slices(self, slices: list[PieSlice]) -> None:
        self._slices = list(slices)
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(_MIN_PIE, _MIN_PIE)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self.begin_pan_zoom_paint(painter)

        margin = 24
        rect = QRectF(margin, margin, self.width() - 2 * margin, self.height() - 2 * margin)
        side = min(rect.width(), rect.height())
        outer = QRectF(
            rect.center().x() - side / 2,
            rect.center().y() - side / 2,
            side,
            side,
        )

        visible = [slice_ for slice_ in self._slices if slice_.value > 0.05]
        total = sum(slice_.value for slice_ in visible)
        if total <= 0:
            painter.setPen(QColor("#94a3b8"))
            font = QFont("Segoe UI", 11)
            painter.setFont(font)
            painter.drawText(outer, Qt.AlignmentFlag.AlignCenter, "No data")
            painter.end()
            return

        start = 90.0
        label_px = max(10, int(round(side * 0.042)))
        label_font = QFont("Segoe UI")
        label_font.setPixelSize(label_px)
        label_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(label_font)
        label_pad_x = max(6, int(round(label_px * 0.35)))
        label_pad_y = max(3, int(round(label_px * 0.2)))
        label_radius = max(4, int(round(label_px * 0.12)))

        for slice_ in visible:
            span = 360.0 * slice_.value / total
            color = QColor(slice_.color)
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPie(outer, int(start * 16), int(-span * 16))

            if span >= 8.0:
                mid_deg = start - span / 2.0
                mid_rad = math.radians(mid_deg)
                label_r = side * 0.31
                cx = outer.center().x()
                cy = outer.center().y()
                lx = cx + label_r * math.cos(mid_rad)
                ly = cy - label_r * math.sin(mid_rad)
                label = f"{slice_.value:.1f}%"
                metrics = painter.fontMetrics()
                text_w = metrics.horizontalAdvance(label)
                text_rect = QRectF(
                    lx - text_w / 2 - label_pad_x,
                    ly - metrics.height() / 2 - label_pad_y,
                    text_w + label_pad_x * 2,
                    metrics.height() + label_pad_y * 2,
                )
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(13, 17, 23, 170))
                painter.drawRoundedRect(text_rect, label_radius, label_radius)
                painter.setPen(QColor("#ffffff"))
                painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, label)

            start -= span

        painter.end()


class _StatsPanel(QFrame):
    _PDF_CAPTION_FG = "#4b5563"
    _PDF_VALUE_FG = "#111827"
    _PDF_SEPARATOR = "#d1d5db"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("pieStatsPanel")
        self._caption_labels: list[QLabel] = []
        self._value_labels: list[QLabel] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        pass_fail_grid = QGridLayout()
        pass_fail_grid.setHorizontalSpacing(16)
        pass_fail_grid.setVerticalSpacing(3)
        self._pass_fail_grid = pass_fail_grid
        self._labels: dict[str, QLabel] = {}
        pass_fail_rows = [
            ("pass_count", "Total No. of Shotpoints Pass"),
            ("fail_count", "Total No. of Shotpoints Failed"),
            ("pass_pct", "Total Percentage Pass"),
            ("fail_pct", "Total Percentage Failed"),
        ]
        for row_index, (key, caption) in enumerate(pass_fail_rows):
            caption_label = QLabel(caption + ":")
            self._caption_labels.append(caption_label)
            value_label = QLabel("—")
            self._value_labels.append(value_label)
            pass_fail_grid.addWidget(caption_label, row_index, 0, Qt.AlignmentFlag.AlignLeft)
            pass_fail_grid.addWidget(value_label, row_index, 1, Qt.AlignmentFlag.AlignLeft)
            self._labels[key] = value_label
        layout.addLayout(pass_fail_grid)

        self._separator = QFrame()
        self._separator.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(self._separator)

        metrics_grid = QGridLayout()
        metrics_grid.setHorizontalSpacing(16)
        metrics_grid.setVerticalSpacing(3)
        self._metrics_grid = metrics_grid
        metric_rows = [
            ("average", "Total Average"),
            ("maximum", "Total Max"),
            ("minimum", "Total Min"),
        ]
        for row_index, (key, caption) in enumerate(metric_rows):
            caption_label = QLabel(caption + ":")
            self._caption_labels.append(caption_label)
            value_label = QLabel("—")
            self._value_labels.append(value_label)
            metrics_grid.addWidget(caption_label, row_index, 0, Qt.AlignmentFlag.AlignLeft)
            metrics_grid.addWidget(value_label, row_index, 1, Qt.AlignmentFlag.AlignLeft)
            self._labels[key] = value_label
        layout.addLayout(metrics_grid)
        self._apply_screen_style()
        self._apply_label_screen_styles()

    def _apply_screen_style(self) -> None:
        self.setStyleSheet(
            f"""
            QFrame#pieStatsPanel {{
                background: #0d1117;
                border: 1px solid {_CARD_BORDER};
                border-radius: 6px;
            }}
            """
        )
        self._separator.setStyleSheet(f"color: {_CARD_BORDER};")

    def _apply_label_screen_styles(self) -> None:
        for label in self._caption_labels:
            label.setStyleSheet(f"color: {_INFO_FG}; font-size: 10px;")
        for label in self._value_labels:
            label.setStyleSheet(
                f"color: {_INFO_VALUE}; font-size: 10px; font-weight: 600;"
            )

    def _pdf_font_px(self, base_pt: float, dpi: int) -> int:
        return max(1, int(round(base_pt * dpi / 72.0)))

    def _pdf_rows(self) -> list[tuple[str, str]]:
        return [
            ("Total No. of Shotpoints Pass:", self._labels["pass_count"].text()),
            ("Total No. of Shotpoints Failed:", self._labels["fail_count"].text()),
            ("Total Percentage Pass:", self._labels["pass_pct"].text()),
            ("Total Percentage Failed:", self._labels["fail_pct"].text()),
            ("Total Average:", self._labels["average"].text()),
            ("Total Max:", self._labels["maximum"].text()),
            ("Total Min:", self._labels["minimum"].text()),
        ]

    def pdf_overlay_height(self, dpi: int, *, origin_y: int = 0) -> int:
        """Estimate vertical space used by the PDF stats block."""
        rows = self._pdf_rows()
        caption_font = QFont("Segoe UI")
        caption_font.setPixelSize(self._pdf_font_px(9.5, dpi))
        value_font = QFont("Segoe UI")
        value_font.setPixelSize(self._pdf_font_px(11.0, dpi))
        caption_metrics = QFontMetrics(caption_font)
        value_metrics = QFontMetrics(value_font)
        row_gap = max(4, int(round(5 * max(dpi / 96.0, 1.0))))
        y = origin_y
        for index in range(len(rows)):
            if index == 4:
                y += row_gap + row_gap * 2
            y += max(caption_metrics.height(), value_metrics.height()) + row_gap
        return y

    def paint_pdf_overlay(
        self,
        painter: QPainter,
        *,
        origin_x: int,
        origin_y: int,
        dpi: int,
    ) -> int:
        """Draw pass/fail stats as plain text for PDF export (no panel background)."""
        rows = self._pdf_rows()
        caption_font = QFont("Segoe UI")
        caption_font.setPixelSize(self._pdf_font_px(9.5, dpi))
        value_font = QFont("Segoe UI")
        value_font.setPixelSize(self._pdf_font_px(11.0, dpi))
        value_font.setWeight(QFont.Weight.DemiBold)

        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setFont(caption_font)
        caption_metrics = painter.fontMetrics()
        painter.setFont(value_font)
        value_metrics = painter.fontMetrics()

        row_gap = max(4, int(round(5 * max(dpi / 96.0, 1.0))))
        col_gap = max(12, int(round(16 * max(dpi / 96.0, 1.0))))
        caption_width = max(
            caption_metrics.horizontalAdvance(caption)
            for caption, _value in rows[:4]
        )
        value_width = max(
            value_metrics.horizontalAdvance(value)
            for _caption, value in rows
        )
        block_width = caption_width + col_gap + value_width

        y = origin_y
        for index, (caption, value) in enumerate(rows):
            if index == 4:
                y += row_gap
                line_y = y
                painter.setPen(
                    QPen(
                        QColor(self._PDF_SEPARATOR),
                        max(1, int(round(dpi / 300.0))),
                    )
                )
                painter.drawLine(origin_x, line_y, origin_x + block_width, line_y)
                y += row_gap * 2

            painter.setFont(caption_font)
            painter.setPen(QColor(self._PDF_CAPTION_FG))
            painter.drawText(origin_x, y + caption_metrics.ascent(), caption)
            painter.setFont(value_font)
            painter.setPen(QColor(self._PDF_VALUE_FG))
            painter.drawText(
                origin_x + caption_width + col_gap,
                y + value_metrics.ascent(),
                value,
            )
            y += max(caption_metrics.height(), value_metrics.height()) + row_gap
        return y

    def set_stats(self, stats: SurveySpecPieStats | None) -> None:
        if stats is None:
            for label in self._labels.values():
                label.setText("—")
            return
        unit = stats.unit
        self._labels["pass_count"].setText(_format_count(stats.pass_count))
        self._labels["fail_count"].setText(_format_count(stats.fail_count))
        self._labels["pass_pct"].setText(f"{stats.pass_pct:.1f}%")
        self._labels["fail_pct"].setText(f"{stats.fail_pct:.1f}%")
        self._labels["average"].setText(_format_metric(stats.average, unit))
        self._labels["maximum"].setText(_format_metric(stats.maximum, unit))
        self._labels["minimum"].setText(_format_metric(stats.minimum, unit))


class _PieChartPage(QWidget):
    """Single survey-spec pie chart card."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setSpacing(12)
        self._stats = _StatsPanel(parent=self)
        top_row.addWidget(self._stats, alignment=Qt.AlignmentFlag.AlignTop)
        top_row.addStretch()
        layout.addLayout(top_row)

        self._headline = QLabel("")
        self._headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._headline.setStyleSheet(
            f"color: {_SUBTITLE_FG}; font-size: 11px; letter-spacing: 0.5px;"
        )
        self._title = QLabel("")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setWordWrap(True)
        self._title.setStyleSheet(
            f"color: {_TITLE_FG}; font-size: 16px; font-weight: 700; padding: 0 8px;"
        )
        self._subtitle = QLabel("")
        self._subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._subtitle.setWordWrap(True)
        self._subtitle.setStyleSheet(f"color: {_SUBTITLE_FG}; font-size: 11px;")
        layout.addWidget(self._headline)
        layout.addWidget(self._title)
        layout.addWidget(self._subtitle)

        self._pie = _PieChartWidget(parent=self)
        layout.addWidget(self._pie, stretch=1)

        legend_row = QHBoxLayout()
        legend_row.addStretch()
        self._pass_legend = QLabel("● Pass")
        self._pass_legend.setStyleSheet(f"color: {_PASS_COLOR}; font-size: 11px; font-weight: 600;")
        self._fail_legend = QLabel("● Fail")
        self._fail_legend.setStyleSheet(f"color: {_FAIL_COLOR}; font-size: 11px; font-weight: 600;")
        self._fail_color = _FAIL_COLOR
        legend_row.addWidget(self._pass_legend)
        legend_row.addSpacing(16)
        legend_row.addWidget(self._fail_legend)
        legend_row.addStretch()
        layout.addLayout(legend_row)

    def set_data(self, chart: SurveySpecPieData) -> None:
        self._headline.setText(chart.headline)
        self._title.setText(chart.title)
        self._subtitle.setText(chart.subtitle)
        self._stats.set_stats(chart.stats)
        self._pie.set_slices(chart.slices)
        self._fail_color = chart.fail_color
        self._fail_legend.setStyleSheet(
            f"color: {chart.fail_color}; font-size: 11px; font-weight: 600;"
        )

    def _paint_pdf_legend(
        self,
        painter: QPainter,
        *,
        width: int,
        bottom_y: int,
        dpi: int,
    ) -> None:
        font = QFont("Segoe UI")
        font.setPixelSize(max(10, int(round(10 * dpi / 72.0))))
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        pass_text = self._pass_legend.text().strip() or "● Pass"
        fail_text = self._fail_legend.text().strip() or "● Fail"
        pass_metrics = painter.fontMetrics()
        spacing = max(16, int(round(24 * max(dpi / 96.0, 1.0))))
        pass_w = pass_metrics.horizontalAdvance(pass_text)
        fail_w = pass_metrics.horizontalAdvance(fail_text)
        total_w = pass_w + spacing + fail_w
        start_x = max(0, (width - total_w) // 2)
        text_y = bottom_y - pass_metrics.descent()
        painter.setPen(QColor(_PASS_COLOR))
        painter.drawText(start_x, text_y, pass_text)
        painter.setPen(QColor(self._fail_color))
        painter.drawText(start_x + pass_w + spacing, text_y, fail_text)


class SurveySpecPiePanel(QWidget):
    """Nested tabs — one pie chart per survey spec row."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.setStyleSheet(_PIE_SUB_TAB_STYLE)
        outer.addWidget(self._tabs)
        self._pages: list[_PieChartPage] = []
        self._placeholder = QLabel("No Survey Spec rows configured.")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: #8b949e; padding: 24px;")
        self._placeholder.hide()
        outer.addWidget(self._placeholder)

    def render(self, charts: list[SurveySpecPieData]) -> None:
        while self._tabs.count():
            widget = self._tabs.widget(0)
            self._tabs.removeTab(0)
            if widget is not None:
                widget.deleteLater()
        self._pages.clear()

        if not charts:
            self._tabs.hide()
            self._placeholder.show()
            return

        self._placeholder.hide()
        self._tabs.show()
        for chart in charts:
            page = _PieChartPage(parent=self)
            page.set_data(chart)
            self._tabs.addTab(page, chart.tab_label)
            self._pages.append(page)

    def select_page(self, index: int) -> None:
        if 0 <= index < self._tabs.count():
            self._tabs.setCurrentIndex(index)

    def capture_page_image(
        self,
        index: int,
        *,
        width: int,
        height: int,
        for_pdf: bool = False,
        dpi: int = 120,
    ) -> QImage:
        if not self._pages or index < 0 or index >= len(self._pages):
            image = QImage(width, height, QImage.Format.Format_ARGB32)
            image.fill(QColor("#ffffff" if for_pdf else "#0d1117"))
            return image
        self.select_page(index)
        return self._capture_page(
            self._pages[index],
            width=width,
            height=height,
            title="",
            for_pdf=for_pdf,
            dpi=dpi,
        )

    def capture_image(
        self,
        *,
        width: int,
        height: int,
        title: str = "",
        for_pdf: bool = False,
        dpi: int = 120,
    ) -> QImage:
        if not self._pages:
            image = QImage(width, height, QImage.Format.Format_ARGB32)
            image.fill(QColor("#0d1117"))
            return image

        if not for_pdf and self._pages:
            current = self._tabs.currentWidget()
            if isinstance(current, _PieChartPage):
                return self._capture_page(
                    current,
                    width=width,
                    height=height,
                    title=title,
                    for_pdf=False,
                    dpi=dpi,
                )

        page_height = max(1, height // max(1, len(self._pages)))
        combined = QImage(width, height, QImage.Format.Format_ARGB32)
        combined.fill(QColor("#0d1117"))
        painter = QPainter(combined)
        y_offset = 0
        for index, page in enumerate(self._pages):
            page_title = title.strip() if index == 0 and title.strip() else page._title.text()
            shot = self._capture_page(
                page,
                width=width,
                height=page_height,
                title=page_title,
                for_pdf=False,
                dpi=dpi,
            )
            painter.drawImage(0, y_offset, shot)
            y_offset += page_height
        painter.end()
        return combined

    def _capture_page(
        self,
        page: _PieChartPage,
        *,
        width: int,
        height: int,
        title: str,
        for_pdf: bool,
        dpi: int,
    ) -> QImage:
        page._pie.reset_view()
        layout_w = max(width, 960)
        layout_h = max(height, 680)
        page.resize(layout_w, layout_h)
        page.layout().activate()
        QApplication.processEvents()

        if for_pdf:
            margin = max(8, int(round(12 * max(dpi / 150.0, 1.0))))
            legend_band = max(20, int(round(28 * max(dpi / 150.0, 1.0))))

            image = QImage(width, height, QImage.Format.Format_ARGB32)
            image.fill(QColor("#ffffff"))
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

            stats_bottom = page._stats.paint_pdf_overlay(
                painter,
                origin_x=margin,
                origin_y=margin,
                dpi=dpi,
            )
            pie_top = stats_bottom + margin
            pie_h = max(1, height - pie_top - legend_band - margin)
            pie_w = width

            page._pie.reset_view()
            page._pie.resize(pie_w, pie_h)
            QApplication.processEvents()
            pie_image = QImage(pie_w, pie_h, QImage.Format.Format_ARGB32)
            pie_image.fill(QColor("#ffffff"))
            page._pie.render(pie_image)
            painter.drawImage(0, pie_top, pie_image)

            page._paint_pdf_legend(
                painter,
                width=width,
                bottom_y=height - margin,
                dpi=dpi,
            )
            painter.end()
            return image

        widget_image = page.grab().toImage()
        bg = "#0d1117"
        image = QImage(width, height, QImage.Format.Format_ARGB32)
        image.fill(QColor(bg))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        top = 0
        if title.strip():
            font = QFont("Segoe UI")
            font.setPixelSize(max(12, int(round(12 * dpi / 96.0))))
            font.setWeight(QFont.Weight.Bold)
            painter.setFont(font)
            painter.setPen(QColor("#e6edf3"))
            metrics = painter.fontMetrics()
            painter.drawText(8, metrics.ascent() + 6, title.strip())
            top = metrics.height() + 10
        scaled = widget_image.scaled(
            width,
            max(1, height - top),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter.drawImage(0, top, scaled)
        painter.end()
        return image
