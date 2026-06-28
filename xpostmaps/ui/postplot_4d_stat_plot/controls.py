"""Control tables and Y-axis inputs for 4D Stat Plot."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from xpostmaps.core.models import LineStyle
from xpostmaps.core.postplot_4d_plot_data import BoundaryRow, SourceStyleRow
from xpostmaps.ui.dialogs.legend_dialog import (
    LayerStylesDialog,
    _configure_legend_table,
    _fit_table_columns,
    _fit_table_height,
    _legend_section_toolbar_button,
)
from xpostmaps.ui.widgets.color_button import ColorButton


class _StyleComboBox(QComboBox):
    _LABELS = ("Solid", "Dotted", "Dash")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.addItems(list(self._LABELS))
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)

    @staticmethod
    def style_from_index(index: int) -> LineStyle:
        return LayerStylesDialog._style_from_index(index)

    @staticmethod
    def index_from_style(style: LineStyle) -> int:
        return LayerStylesDialog._index_from_style(style)


def _make_boundary_abs_spin(value: float) -> QDoubleSpinBox:
    """Compact ABS boundary input for table cells — no arrows, readable text."""
    spin = QDoubleSpinBox()
    spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    spin.setRange(0.0, 99999.0)
    spin.setDecimals(2)
    spin.setValue(abs(value))
    spin.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    spin.setFixedHeight(26)
    spin.setStyleSheet(
        "QDoubleSpinBox {"
        "background: #1e293b;"
        "color: #e6edf3;"
        "border: 1px solid rgba(255, 255, 255, 0.12);"
        "border-radius: 6px;"
        "padding: 2px 8px;"
        "font-size: 12px;"
        "}"
    )
    return spin


class SourceStyleTable(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[SourceStyleRow] = []
        self._widths: list[float] = []
        self._dots: list[float] = []
        self._dashes: list[float] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        section = QLabel("Source Style")
        section.setObjectName("statPlotSection")
        layout.addWidget(section)
        self._table = QTableWidget(0, 3)
        _configure_legend_table(self._table)
        self._table.setHorizontalHeaderLabels(["Source No.", "Line Style", "Source Color"])
        layout.addWidget(self._table)

    def set_sources(self, rows: list[SourceStyleRow]) -> None:
        self._rows = list(rows)
        self._widths = [row.line_width_mm for row in rows]
        self._dots = [row.dot_radius_mm for row in rows]
        self._dashes = [row.dash_length_mm for row in rows]
        self._rebuild()

    def rows(self) -> list[SourceStyleRow]:
        result: list[SourceStyleRow] = []
        for row_idx in range(self._table.rowCount()):
            source_item = self._table.item(row_idx, 0)
            source_no = source_item.text() if source_item else ""
            style_combo = self._table.cellWidget(row_idx, 1)
            color_btn = self._table.cellWidget(row_idx, 2)
            style = LineStyle.SOLID
            color = "#22c55e"
            opacity = 1.0
            line_width = 0.35
            dot_radius = 0.8
            dash_length = 3.0
            if isinstance(style_combo, _StyleComboBox):
                style = _StyleComboBox.style_from_index(style_combo.currentIndex())
            if isinstance(color_btn, ColorButton):
                color = color_btn.color
                opacity = color_btn.opacity
                if style == LineStyle.DOTTED:
                    dot_radius = color_btn.metric_value
                else:
                    line_width = color_btn.metric_value
                if style == LineStyle.DASH:
                    dash_length = color_btn.secondary_metric_value
            result.append(
                SourceStyleRow(
                    source_no=source_no,
                    line_style=style,
                    color=color,
                    opacity=opacity,
                    line_width_mm=line_width,
                    dot_radius_mm=dot_radius,
                    dash_length_mm=dash_length,
                )
            )
        return result

    def _rebuild(self) -> None:
        self._table.blockSignals(True)
        self._table.setRowCount(len(self._rows))
        for row_idx, row in enumerate(self._rows):
            item = QTableWidgetItem(row.source_no)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row_idx, 0, item)
            style_combo = _StyleComboBox()
            style_combo.setCurrentIndex(_StyleComboBox.index_from_style(row.line_style))
            self._table.setCellWidget(row_idx, 1, style_combo)

            def metric_provider(style_combo=style_combo):
                style = _StyleComboBox.style_from_index(style_combo.currentIndex())
                return LayerStylesDialog._metric_config_for_style(style)

            def secondary_provider(style_combo=style_combo):
                style = _StyleComboBox.style_from_index(style_combo.currentIndex())
                return LayerStylesDialog._secondary_metric_config_for_style(style)

            color_btn = ColorButton(
                row.color,
                row.opacity,
                metric_value=(
                    row.dot_radius_mm
                    if row.line_style == LineStyle.DOTTED
                    else row.line_width_mm
                ),
                metric_provider=metric_provider,
                secondary_metric_value=row.dash_length_mm,
                secondary_metric_provider=secondary_provider,
            )

            def bind_style(row_idx=row_idx, style_combo=style_combo, color_btn=color_btn) -> None:
                def on_style_changed() -> None:
                    style = _StyleComboBox.style_from_index(style_combo.currentIndex())
                    metric = (
                        self._dots[row_idx]
                        if style == LineStyle.DOTTED
                        else self._widths[row_idx]
                    )
                    secondary = (
                        self._dashes[row_idx] if style == LineStyle.DASH else 3.0
                    )
                    color_btn.set_color(
                        color_btn.color,
                        color_btn.opacity,
                        metric_value=metric,
                        secondary_metric_value=secondary,
                    )
                    self.changed.emit()

                style_combo.currentIndexChanged.connect(on_style_changed)
                color_btn.color_changed.connect(lambda *_: self.changed.emit())
                color_btn.metric_changed.connect(lambda value: self._on_metric(row_idx, value))
                color_btn.secondary_metric_changed.connect(
                    lambda value: self._on_dash(row_idx, value)
                )

            bind_style()
            self._table.setCellWidget(row_idx, 2, color_btn)
            self._table.setRowHeight(row_idx, 34)
        self._table.blockSignals(False)
        _fit_table_columns(self._table)
        _fit_table_height(self._table)
        self.adjustSize()

    def _on_metric(self, row_idx: int, value: float) -> None:
        while len(self._widths) <= row_idx:
            self._widths.append(0.35)
        while len(self._dots) <= row_idx:
            self._dots.append(0.8)
        style_combo = self._table.cellWidget(row_idx, 1)
        if isinstance(style_combo, _StyleComboBox):
            style = _StyleComboBox.style_from_index(style_combo.currentIndex())
            if style == LineStyle.DOTTED:
                self._dots[row_idx] = value
            else:
                self._widths[row_idx] = value
        self.changed.emit()

    def _on_dash(self, row_idx: int, value: float) -> None:
        while len(self._dashes) <= row_idx:
            self._dashes.append(3.0)
        self._dashes[row_idx] = value
        self.changed.emit()


class BoundaryTable(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[BoundaryRow] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        toolbar = QHBoxLayout()
        add_btn = _legend_section_toolbar_button("Add Row", kind="add")
        remove_btn = _legend_section_toolbar_button("Remove Selected", kind="remove")
        add_btn.clicked.connect(self._add_row)
        remove_btn.clicked.connect(self._remove_selected)
        toolbar.addWidget(add_btn)
        toolbar.addWidget(remove_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        boundary_title = QLabel("Boundary")
        boundary_title.setObjectName("statPlotSection")
        layout.addWidget(boundary_title)
        self._table = QTableWidget(0, 3)
        _configure_legend_table(self._table)
        self._table.setHorizontalHeaderLabels(
            ["ABS Boundary Value", "Boundary Style", "Boundary Color"]
        )
        layout.addWidget(self._table)

    def _abs_spin(self, row_idx: int) -> QDoubleSpinBox | None:
        widget = self._table.cellWidget(row_idx, 0)
        return widget if isinstance(widget, QDoubleSpinBox) else None

    def set_rows(self, rows: list[BoundaryRow]) -> None:
        self._rows = list(rows)
        self._rebuild()

    def rows(self) -> list[BoundaryRow]:
        result: list[BoundaryRow] = []
        for row_idx in range(self._table.rowCount()):
            abs_spin = self._abs_spin(row_idx)
            abs_value = abs_spin.value() if abs_spin is not None else 0.0
            style_combo = self._table.cellWidget(row_idx, 1)
            color_btn = self._table.cellWidget(row_idx, 2)
            style = LineStyle.DASH
            color = "#3b82f6"
            opacity = 1.0
            line_width = 0.35
            dot_radius = 0.8
            dash_length = 3.0
            if isinstance(style_combo, _StyleComboBox):
                style = _StyleComboBox.style_from_index(style_combo.currentIndex())
            if isinstance(color_btn, ColorButton):
                color = color_btn.color
                opacity = color_btn.opacity
                if style == LineStyle.DOTTED:
                    dot_radius = color_btn.metric_value
                else:
                    line_width = color_btn.metric_value
                if style == LineStyle.DASH:
                    dash_length = color_btn.secondary_metric_value
            result.append(
                BoundaryRow(
                    abs_boundary=abs(abs_value),
                    line_style=style,
                    color=color,
                    opacity=opacity,
                    line_width_mm=line_width,
                    dot_radius_mm=dot_radius,
                    dash_length_mm=dash_length,
                )
            )
        return result

    def _add_row(self) -> None:
        self._rows.append(BoundaryRow())
        self._rebuild()
        self.changed.emit()

    def _remove_selected(self) -> None:
        selected = sorted({index.row() for index in self._table.selectedIndexes()}, reverse=True)
        if not selected:
            return
        for row_idx in selected:
            if 0 <= row_idx < len(self._rows):
                del self._rows[row_idx]
        self._rebuild()
        self.changed.emit()

    def _rebuild(self) -> None:
        self._table.blockSignals(True)
        self._table.setRowCount(len(self._rows))
        for row_idx, row in enumerate(self._rows):
            abs_spin = _make_boundary_abs_spin(row.abs_boundary)
            abs_spin.valueChanged.connect(lambda *_: self.changed.emit())
            self._table.setCellWidget(row_idx, 0, abs_spin)

            style_combo = _StyleComboBox()
            style_combo.setCurrentIndex(_StyleComboBox.index_from_style(row.line_style))
            self._table.setCellWidget(row_idx, 1, style_combo)

            def metric_provider(style_combo=style_combo):
                style = _StyleComboBox.style_from_index(style_combo.currentIndex())
                return LayerStylesDialog._metric_config_for_style(style)

            def secondary_provider(style_combo=style_combo):
                style = _StyleComboBox.style_from_index(style_combo.currentIndex())
                return LayerStylesDialog._secondary_metric_config_for_style(style)

            color_btn = ColorButton(
                row.color,
                row.opacity,
                metric_value=(
                    row.dot_radius_mm
                    if row.line_style == LineStyle.DOTTED
                    else row.line_width_mm
                ),
                metric_provider=metric_provider,
                secondary_metric_value=row.dash_length_mm,
                secondary_metric_provider=secondary_provider,
            )

            def bind_style(style_combo=style_combo, color_btn=color_btn) -> None:
                def on_style_changed() -> None:
                    style = _StyleComboBox.style_from_index(style_combo.currentIndex())
                    metric = (
                        row.dot_radius_mm
                        if style == LineStyle.DOTTED
                        else row.line_width_mm
                    )
                    secondary = row.dash_length_mm if style == LineStyle.DASH else 3.0
                    color_btn.set_color(
                        color_btn.color,
                        color_btn.opacity,
                        metric_value=metric,
                        secondary_metric_value=secondary,
                    )
                    self.changed.emit()

                style_combo.currentIndexChanged.connect(on_style_changed)
                color_btn.color_changed.connect(lambda *_: self.changed.emit())
                color_btn.metric_changed.connect(lambda *_: self.changed.emit())
                color_btn.secondary_metric_changed.connect(lambda *_: self.changed.emit())

            bind_style()
            self._table.setCellWidget(row_idx, 2, color_btn)
            self._table.setRowHeight(row_idx, 34)
        self._table.blockSignals(False)
        _fit_table_columns(self._table)
        _fit_table_height(self._table)
        self.adjustSize()


class PlotTabControls(QWidget):
    """Per-tab source style and boundary tables (side by side)."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        tables_row = QHBoxLayout()
        tables_row.setSpacing(12)
        self._source_table = SourceStyleTable(parent=self)
        self._source_table.changed.connect(self.changed.emit)
        tables_row.addWidget(self._source_table, stretch=1)
        self._boundary_table = BoundaryTable(parent=self)
        self._boundary_table.changed.connect(self.changed.emit)
        tables_row.addWidget(self._boundary_table, stretch=1)
        layout.addLayout(tables_row)

    def set_sources(self, rows: list[SourceStyleRow]) -> None:
        self._source_table.set_sources(rows)

    def set_boundaries(self, rows: list[BoundaryRow]) -> None:
        self._boundary_table.set_rows(rows)

    def source_styles(self) -> list[SourceStyleRow]:
        return self._source_table.rows()

    def boundaries(self) -> list[BoundaryRow]:
        return self._boundary_table.rows()


class YAxisControls(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        y_min_lbl = QLabel("Y axis Min")
        y_min_lbl.setStyleSheet("color: #e6edf3;")
        row.addWidget(y_min_lbl)
        self._min_spin = QDoubleSpinBox()
        self._min_spin.setRange(-99999.0, 99999.0)
        self._min_spin.setDecimals(2)
        self._min_spin.setValue(-10.0)
        self._min_spin.valueChanged.connect(lambda *_: self._on_manual_changed())
        row.addWidget(self._min_spin)
        y_max_lbl = QLabel("Y axis Max")
        y_max_lbl.setStyleSheet("color: #e6edf3;")
        row.addWidget(y_max_lbl)
        self._max_spin = QDoubleSpinBox()
        self._max_spin.setRange(-99999.0, 99999.0)
        self._max_spin.setDecimals(2)
        self._max_spin.setValue(10.0)
        self._max_spin.valueChanged.connect(lambda *_: self._on_manual_changed())
        row.addWidget(self._max_spin)
        self._auto_box = QCheckBox("Auto Y axis")
        self._auto_box.setStyleSheet("color: #e6edf3;")
        self._auto_box.setChecked(True)
        self._auto_box.toggled.connect(self._on_auto_toggled)
        row.addWidget(self._auto_box)
        row.addStretch()
        self._on_auto_toggled(True)

    def _on_auto_toggled(self, checked: bool) -> None:
        self._min_spin.setEnabled(not checked)
        self._max_spin.setEnabled(not checked)
        self.changed.emit()

    def _on_manual_changed(self) -> None:
        if not self._auto_box.isChecked():
            self.changed.emit()

    def auto_y(self) -> bool:
        return self._auto_box.isChecked()

    def y_range(self) -> tuple[float | None, float | None]:
        if self._auto_box.isChecked():
            return None, None
        return self._min_spin.value(), self._max_spin.value()
