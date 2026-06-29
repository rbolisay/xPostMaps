"""Control tables and Y-axis inputs for 4D Stat Plot."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from xpostmaps.core.models import LineStyle
from xpostmaps.core.postplot_4d_plot_data import (
    BoundaryRow,
    SourceStyleRow,
    combined_source_key,
)
from xpostmaps.ui.dialogs.legend_dialog import (
    LayerStylesDialog,
    _configure_legend_table,
    _fit_table_columns,
    _fit_table_height,
    _legend_section_toolbar_button,
)
from xpostmaps.ui.widgets.color_button import ColorButton


def _fit_table_to_content(table: QTableWidget) -> None:
    """Size a 4D Stat control table to its content.

    Each column is sized to its header/cell content (Resize To Contents), and
    the table widget width is then locked to the total so no column is ever
    truncated. Horizontal overflow is handled by the surrounding scroll area
    rather than an in-table scrollbar.
    """
    _fit_table_columns(table)
    _fit_table_height(table)
    total = sum(table.columnWidth(col) for col in range(table.columnCount()))
    frame = table.frameWidth() * 2
    vbar = 0
    if table.verticalScrollBarPolicy() != Qt.ScrollBarPolicy.ScrollBarAlwaysOff:
        vbar = table.verticalScrollBar().sizeHint().width()
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    width = total + frame + vbar + 2
    table.setMinimumWidth(width)
    table.setMaximumWidth(width)


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


def _make_boundary_value_spin(value: float) -> QDoubleSpinBox:
    """Compact numeric input for boundary limit/reference cells.

    Allows negative values: a limit or reference may sit below zero, and with
    Absolute off the limit is plotted directly at ``reference + limit``.
    """
    spin = QDoubleSpinBox()
    spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    spin.setRange(-99999.0, 99999.0)
    spin.setDecimals(2)
    spin.setValue(value)
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


def _make_absolute_checkbox(checked: bool) -> QWidget:
    """Centered checkbox cell; the QCheckBox is the container's only child."""
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    box = QCheckBox()
    box.setChecked(checked)
    layout.addStretch()
    layout.addWidget(box)
    layout.addStretch()
    return container


def _checkbox_in(container: QWidget | None) -> QCheckBox | None:
    if container is None:
        return None
    return container.findChild(QCheckBox)


class SourceStyleTable(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[SourceStyleRow] = []
        self._widths: list[float] = []
        self._dots: list[float] = []
        self._dashes: list[float] = []
        # Multi-sequence (combined) state: one column of colours per sequence.
        self._multi = False
        self._source_nos: list[str] = []
        self._sequence_nos: list[str] = []
        self._style_by_key: dict[str, SourceStyleRow] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        section = QLabel("Source Style")
        section.setObjectName("statPlotSection")
        layout.addWidget(section)
        self._table = QTableWidget(0, 3)
        _configure_legend_table(self._table)
        self._table.setHorizontalHeaderLabels(["Source No.", "Line Style", "Source Color"])
        layout.addWidget(self._table)

    def set_sources(self, rows: list[SourceStyleRow]) -> None:
        """Single-sequence layout: one row per source, one Source Color column."""
        self._multi = False
        self._rows = list(rows)
        self._widths = [row.line_width_mm for row in rows]
        self._dots = [row.dot_radius_mm for row in rows]
        self._dashes = [row.dash_length_mm for row in rows]
        self._rebuild_single()

    def set_source_matrix(
        self,
        source_nos: list[str],
        sequence_nos: list[str],
        style_by_key: dict[str, SourceStyleRow],
    ) -> None:
        """Combined layout: one row per source, one Source Color column per sequence."""
        self._multi = True
        self._source_nos = list(source_nos)
        self._sequence_nos = list(sequence_nos)
        self._style_by_key = dict(style_by_key)
        self._rebuild_multi()

    def rows(self) -> list[SourceStyleRow]:
        if self._multi:
            return self._rows_multi()
        return self._rows_single()

    # ----- single-sequence mode -------------------------------------------
    def _rows_single(self) -> list[SourceStyleRow]:
        result: list[SourceStyleRow] = []
        for row_idx in range(self._table.rowCount()):
            source_item = self._table.item(row_idx, 0)
            source_no = source_item.text() if source_item else ""
            style_combo = self._table.cellWidget(row_idx, 1)
            color_btn = self._table.cellWidget(row_idx, 2)
            style = LineStyle.SOLID
            if isinstance(style_combo, _StyleComboBox):
                style = _StyleComboBox.style_from_index(style_combo.currentIndex())
            result.append(self._row_from_widgets(source_no, style, color_btn))
        return result

    def _rebuild_single(self) -> None:
        self._table.blockSignals(True)
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["Source No.", "Line Style", "Source Color"])
        self._table.setRowCount(len(self._rows))
        for row_idx, row in enumerate(self._rows):
            self._set_source_item(row_idx, row.source_no)
            style_combo = self._make_style_combo(row.line_style)
            self._table.setCellWidget(row_idx, 1, style_combo)
            color_btn = self._make_color_button(style_combo, row)

            def bind(row_idx=row_idx, style_combo=style_combo, color_btn=color_btn) -> None:
                def on_style_changed() -> None:
                    style = _StyleComboBox.style_from_index(style_combo.currentIndex())
                    metric = (
                        self._dots[row_idx]
                        if style == LineStyle.DOTTED
                        else self._widths[row_idx]
                    )
                    secondary = self._dashes[row_idx] if style == LineStyle.DASH else 3.0
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

            bind()
            self._table.setCellWidget(row_idx, 2, color_btn)
            self._table.setRowHeight(row_idx, 34)
        self._table.blockSignals(False)
        _fit_table_to_content(self._table)
        self.adjustSize()

    # ----- combined (multi-sequence) mode ---------------------------------
    def _rows_multi(self) -> list[SourceStyleRow]:
        result: list[SourceStyleRow] = []
        for row_idx, source_no in enumerate(self._source_nos):
            style_combo = self._table.cellWidget(row_idx, 1)
            style = LineStyle.SOLID
            if isinstance(style_combo, _StyleComboBox):
                style = _StyleComboBox.style_from_index(style_combo.currentIndex())
            for col_offset, sequence_no in enumerate(self._sequence_nos):
                color_btn = self._table.cellWidget(row_idx, 2 + col_offset)
                key = combined_source_key(source_no, sequence_no)
                result.append(self._row_from_widgets(key, style, color_btn))
        return result

    def _rebuild_multi(self) -> None:
        self._table.blockSignals(True)
        headers = ["Source No.", "Line Style"] + [
            f"Source Color - {seq}" for seq in self._sequence_nos
        ]
        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        self._table.setRowCount(len(self._source_nos))
        for row_idx, source_no in enumerate(self._source_nos):
            self._set_source_item(row_idx, source_no)
            first_key = combined_source_key(source_no, self._sequence_nos[0])
            base_style = self._style_by_key.get(
                first_key, SourceStyleRow(source_no=source_no)
            )
            style_combo = self._make_style_combo(base_style.line_style)
            self._table.setCellWidget(row_idx, 1, style_combo)

            color_buttons: list[ColorButton] = []
            for col_offset, sequence_no in enumerate(self._sequence_nos):
                key = combined_source_key(source_no, sequence_no)
                style_row = self._style_by_key.get(key, SourceStyleRow(source_no=key))
                color_btn = self._make_color_button(style_combo, style_row)
                color_btn.color_changed.connect(lambda *_: self.changed.emit())
                color_btn.metric_changed.connect(lambda *_: self.changed.emit())
                color_btn.secondary_metric_changed.connect(lambda *_: self.changed.emit())
                self._table.setCellWidget(row_idx, 2 + col_offset, color_btn)
                color_buttons.append(color_btn)

            def bind(style_combo=style_combo, color_buttons=color_buttons) -> None:
                def on_style_changed() -> None:
                    for btn in color_buttons:
                        btn.set_color(
                            btn.color,
                            btn.opacity,
                            metric_value=btn.metric_value,
                            secondary_metric_value=btn.secondary_metric_value,
                        )
                    self.changed.emit()

                style_combo.currentIndexChanged.connect(on_style_changed)

            bind()
            self._table.setRowHeight(row_idx, 34)
        self._table.blockSignals(False)
        _fit_table_to_content(self._table)
        self.adjustSize()

    # ----- shared widget builders -----------------------------------------
    def _set_source_item(self, row_idx: int, text: str) -> None:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row_idx, 0, item)

    def _make_style_combo(self, style: LineStyle) -> _StyleComboBox:
        combo = _StyleComboBox()
        combo.setCurrentIndex(_StyleComboBox.index_from_style(style))
        return combo

    def _make_color_button(
        self,
        style_combo: _StyleComboBox,
        style_row: SourceStyleRow,
    ) -> ColorButton:
        def metric_provider(style_combo=style_combo):
            style = _StyleComboBox.style_from_index(style_combo.currentIndex())
            return LayerStylesDialog._metric_config_for_style(style)

        def secondary_provider(style_combo=style_combo):
            style = _StyleComboBox.style_from_index(style_combo.currentIndex())
            return LayerStylesDialog._secondary_metric_config_for_style(style)

        return ColorButton(
            style_row.color,
            style_row.opacity,
            metric_value=(
                style_row.dot_radius_mm
                if style_row.line_style == LineStyle.DOTTED
                else style_row.line_width_mm
            ),
            metric_provider=metric_provider,
            secondary_metric_value=style_row.dash_length_mm,
            secondary_metric_provider=secondary_provider,
        )

    def _row_from_widgets(
        self,
        source_no: str,
        style: LineStyle,
        color_btn: QWidget | None,
    ) -> SourceStyleRow:
        color = "#22c55e"
        opacity = 1.0
        line_width = 0.35
        dot_radius = 0.8
        dash_length = 3.0
        if isinstance(color_btn, ColorButton):
            color = color_btn.color
            opacity = color_btn.opacity
            if style == LineStyle.DOTTED:
                dot_radius = color_btn.metric_value
            else:
                line_width = color_btn.metric_value
            if style == LineStyle.DASH:
                dash_length = color_btn.secondary_metric_value
        return SourceStyleRow(
            source_no=source_no,
            line_style=style,
            color=color,
            opacity=opacity,
            line_width_mm=line_width,
            dot_radius_mm=dot_radius,
            dash_length_mm=dash_length,
        )

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
        self._widths: list[float] = []
        self._dots: list[float] = []
        self._dashes: list[float] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        boundary_title = QLabel("Boundary Limits")
        boundary_title.setObjectName("statPlotSection")
        layout.addWidget(boundary_title)
        toolbar = QHBoxLayout()
        add_btn = _legend_section_toolbar_button("Add Row", kind="add")
        remove_btn = _legend_section_toolbar_button("Remove Selected", kind="remove")
        add_btn.clicked.connect(self._add_row)
        remove_btn.clicked.connect(self._remove_selected)
        toolbar.addWidget(add_btn)
        toolbar.addWidget(remove_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        self._table = QTableWidget(0, 5)
        _configure_legend_table(self._table)
        self._table.setHorizontalHeaderLabels(
            [
                "Limit Value",
                "Reference Value",
                "Absolute",
                "Boundary Style",
                "Boundary Color",
            ]
        )
        layout.addWidget(self._table)

    def _value_spin(self, row_idx: int, column: int) -> QDoubleSpinBox | None:
        widget = self._table.cellWidget(row_idx, column)
        return widget if isinstance(widget, QDoubleSpinBox) else None

    def set_rows(self, rows: list[BoundaryRow]) -> None:
        self._rows = list(rows)
        self._widths = [row.line_width_mm for row in rows]
        self._dots = [row.dot_radius_mm for row in rows]
        self._dashes = [row.dash_length_mm for row in rows]
        self._rebuild()

    def rows(self) -> list[BoundaryRow]:
        result: list[BoundaryRow] = []
        for row_idx in range(self._table.rowCount()):
            limit_spin = self._value_spin(row_idx, 0)
            reference_spin = self._value_spin(row_idx, 1)
            abs_box = _checkbox_in(self._table.cellWidget(row_idx, 2))
            limit_value = limit_spin.value() if limit_spin is not None else 0.0
            reference_value = reference_spin.value() if reference_spin is not None else 0.0
            absolute = abs_box.isChecked() if abs_box is not None else False
            style_combo = self._table.cellWidget(row_idx, 3)
            color_btn = self._table.cellWidget(row_idx, 4)
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
                    limit_value=limit_value,
                    reference_value=reference_value,
                    absolute=absolute,
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
            limit_spin = _make_boundary_value_spin(row.limit_value)
            limit_spin.valueChanged.connect(lambda *_: self.changed.emit())
            self._table.setCellWidget(row_idx, 0, limit_spin)

            reference_spin = _make_boundary_value_spin(row.reference_value)
            reference_spin.valueChanged.connect(lambda *_: self.changed.emit())
            self._table.setCellWidget(row_idx, 1, reference_spin)

            abs_container = _make_absolute_checkbox(row.absolute)
            abs_box = _checkbox_in(abs_container)
            if abs_box is not None:
                abs_box.toggled.connect(lambda *_: self.changed.emit())
            self._table.setCellWidget(row_idx, 2, abs_container)

            style_combo = _StyleComboBox()
            style_combo.setCurrentIndex(_StyleComboBox.index_from_style(row.line_style))
            self._table.setCellWidget(row_idx, 3, style_combo)

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
                color_btn.metric_changed.connect(
                    lambda value: self._on_metric(row_idx, value)
                )
                color_btn.secondary_metric_changed.connect(
                    lambda value: self._on_dash(row_idx, value)
                )

            bind_style()
            self._table.setCellWidget(row_idx, 4, color_btn)
            self._table.setRowHeight(row_idx, 34)
        self._table.blockSignals(False)
        _fit_table_to_content(self._table)
        self.adjustSize()

    def _on_metric(self, row_idx: int, value: float) -> None:
        while len(self._widths) <= row_idx:
            self._widths.append(0.35)
        while len(self._dots) <= row_idx:
            self._dots.append(0.8)
        style_combo = self._table.cellWidget(row_idx, 3)
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


class PlotTabControls(QWidget):
    """Per-tab source style and boundary tables (side by side)."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Each table sizes itself to its content width; place them side by side
        # inside a horizontal scroll area so wide tables (e.g. a combined plot
        # with one Source Color column per sequence) stay fully visible and
        # scrollable instead of being squeezed/truncated.
        inner = QWidget()
        inner_row = QHBoxLayout(inner)
        inner_row.setContentsMargins(0, 0, 0, 0)
        inner_row.setSpacing(12)
        self._source_table = SourceStyleTable(parent=inner)
        self._source_table.changed.connect(self.changed.emit)
        inner_row.addWidget(self._source_table)
        self._boundary_table = BoundaryTable(parent=inner)
        self._boundary_table.changed.connect(self.changed.emit)
        inner_row.addWidget(self._boundary_table)
        inner_row.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(inner)
        self._inner = inner
        self._scroll = scroll
        layout.addWidget(scroll)
        self._sync_height()

    def _sync_height(self) -> None:
        """Fit the scroll area height to the taller table plus scrollbar room."""
        content_h = self._inner.sizeHint().height()
        content_h += self._scroll.horizontalScrollBar().sizeHint().height()
        self._scroll.setMinimumHeight(content_h)
        self._scroll.setMaximumHeight(content_h)

    def set_sources(self, rows: list[SourceStyleRow]) -> None:
        self._source_table.set_sources(rows)
        self._sync_height()

    def set_source_matrix(
        self,
        source_nos: list[str],
        sequence_nos: list[str],
        style_by_key: dict[str, SourceStyleRow],
    ) -> None:
        self._source_table.set_source_matrix(source_nos, sequence_nos, style_by_key)
        self._sync_height()

    def set_boundaries(self, rows: list[BoundaryRow]) -> None:
        self._boundary_table.set_rows(rows)
        self._sync_height()

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
