"""Survey Specs panel: acceptance limits table plus per-sequence result summary."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from xpostmaps.core.postplot_4d_survey_spec import (
    METRIC_KINDS,
    METRIC_LABELS,
    SEVERITY_LABELS,
    STAT_TYPE_LABELS,
    FailedSpecDetail,
    Severity,
    StatType,
    SurveyEvaluation,
    SurveySpecRow,
    failed_details_for_sequence,
    metric_kind_from_str,
    severity_from_str,
    stat_uses_reference,
    stat_uses_absolute,
    stat_type_from_str,
)
from xpostmaps.ui.dialogs.legend_dialog import (
    _configure_legend_table,
    _legend_section_toolbar_button,
    _table_cell_button,
)
from xpostmaps.ui.postplot_4d_stat_plot.failed_shotpoints_dialog import (
    FailedShotpointsDialog,
)
from xpostmaps.ui.postplot_4d_stat_plot.controls import (
    _checkbox_in,
    _fit_table_to_content,
    _make_absolute_checkbox,
    _make_boundary_value_spin,
    _set_boundary_value_spin_enabled,
)

_COMBO_STYLE = (
    "QComboBox {"
    "background: #1e293b;"
    "color: #e6edf3;"
    "border: 1px solid rgba(255, 255, 255, 0.12);"
    "border-radius: 6px;"
    "padding: 2px 8px;"
    "font-size: 12px;"
    "}"
)

_EXCLUDED_STYLE = (
    "QLineEdit {"
    "background: #1e293b;"
    "color: #e6edf3;"
    "border: 1px solid rgba(255, 255, 255, 0.12);"
    "border-radius: 6px;"
    "padding: 2px 8px;"
    "font-size: 12px;"
    "}"
)

_PASS_STYLE = "color: #3fb950; font-weight: 700;"
_FAIL_STYLE = "color: #f85149; font-weight: 700;"
_WARN_STYLE = "color: #d29922; font-weight: 700;"

# Survey Specs table: Statistic Limit caps the computed statistic; Metric Limit
# is the per-shot metric threshold (failure stats only) beside 4D Metric.
_COL_4D_STATISTIC = 0
_COL_STATISTIC_LIMIT = 1
_COL_4D_METRIC = 2
_COL_METRIC_LIMIT = 3
_COL_ABSOLUTE = 4
_COL_SEVERITY = 5

_SURVEY_SPEC_HEADERS = (
    "4D Statistic",
    "Statistic Limit",
    "4D Metric",
    "Metric Limit",
    "Absolute",
    "Severity",
)


def _make_combo(items: list[tuple[str, object]], current: object) -> QComboBox:
    combo = QComboBox()
    combo.setStyleSheet(_COMBO_STYLE)
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
    for label, value in items:
        combo.addItem(label, value)
    index = combo.findData(current)
    if index >= 0:
        combo.setCurrentIndex(index)
    return combo


def _make_excluded_edit(text: str) -> QLineEdit:
    edit = QLineEdit(text)
    edit.setStyleSheet(_EXCLUDED_STYLE)
    edit.setPlaceholderText("e.g. 1001, 1005-1010")
    edit.setFixedHeight(26)
    edit.setMinimumWidth(140)
    return edit


class SurveySpecsPanel(QWidget):
    """Editable survey spec table with Add/Remove and a result summary."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._rows: list[SurveySpecRow] = []
        self._sequence_nos: list[str] = []
        self._excluded_by_sequence: dict[str, str] = {}
        self._rebuilding = False

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)
        root.setAlignment(Qt.AlignmentFlag.AlignTop)

        left = QWidget()
        left.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        title = QLabel("Survey Specs")
        title.setObjectName("statPlotSection")
        left_layout.addWidget(title)

        toolbar = QHBoxLayout()
        add_btn = _legend_section_toolbar_button("Add Spec Row", kind="add")
        remove_btn = _legend_section_toolbar_button("Remove Selected", kind="remove")
        add_btn.clicked.connect(self._add_row)
        remove_btn.clicked.connect(self._remove_selected)
        toolbar.addWidget(add_btn)
        toolbar.addWidget(remove_btn)
        toolbar.addStretch()
        left_layout.addLayout(toolbar)

        self._table = QTableWidget(0, 6)
        _configure_legend_table(self._table)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self._table.setHorizontalHeaderLabels(list(_SURVEY_SPEC_HEADERS))
        left_layout.addWidget(self._table)
        root.addWidget(left, alignment=Qt.AlignmentFlag.AlignTop)

        self._summary = _ResultSummary()
        self._summary.changed.connect(self.changed.emit)
        root.addWidget(self._summary, alignment=Qt.AlignmentFlag.AlignTop)

    # ----- public API ------------------------------------------------------
    def set_rows(self, rows: list[SurveySpecRow]) -> None:
        self._rows = [self._clone(row) for row in rows]
        self._rebuild()

    def set_sequences(
        self,
        sequence_nos: list[str],
        excluded_by_sequence: dict[str, str] | None = None,
    ) -> None:
        self._sequence_nos = list(sequence_nos)
        if excluded_by_sequence is not None:
            self._excluded_by_sequence = dict(excluded_by_sequence)
        self._summary.set_sequences(
            self._sequence_nos,
            self._excluded_by_sequence,
        )

    def rows(self) -> list[SurveySpecRow]:
        result: list[SurveySpecRow] = []
        for row_idx in range(self._table.rowCount()):
            result.append(self._row_from_widgets(row_idx))
        return result

    def excluded_shotpoints(self) -> dict[str, str]:
        return self._summary.excluded_shotpoints()

    def set_evaluation(
        self,
        evaluation: SurveyEvaluation | None,
        sequence_nos: list[str] | None = None,
    ) -> None:
        if sequence_nos is not None:
            self._sequence_nos = list(sequence_nos)
        self._summary.set_evaluation(evaluation, self._sequence_nos)

    # ----- row helpers -----------------------------------------------------
    @staticmethod
    def _clone(row: SurveySpecRow) -> SurveySpecRow:
        return SurveySpecRow(
            metric=row.metric,
            statistic=row.statistic,
            reference_value=row.reference_value,
            stat_value=row.stat_value,
            absolute=row.absolute,
            severity=row.severity,
        )

    def _add_row(self) -> None:
        self._rows = self.rows()
        self._rows.append(SurveySpecRow())
        self._rebuild()
        self.changed.emit()

    def _remove_selected(self) -> None:
        selected = sorted(
            {index.row() for index in self._table.selectedIndexes()}, reverse=True
        )
        if not selected:
            return
        self._rows = self.rows()
        for row_idx in selected:
            if 0 <= row_idx < len(self._rows):
                del self._rows[row_idx]
        self._rebuild()
        self.changed.emit()

    def _emit_changed(self) -> None:
        if not self._rebuilding:
            self.changed.emit()

    def _statistic_from_combo(self, stat_combo: QComboBox | None) -> StatType:
        if not isinstance(stat_combo, QComboBox):
            return StatType.MAX_VALUE
        statistic_raw = stat_combo.currentData()
        if isinstance(statistic_raw, StatType):
            return statistic_raw
        return stat_type_from_str(str(statistic_raw or StatType.MAX_VALUE.value))

    def _update_metric_limit_for_row(self, row_idx: int) -> None:
        stat_combo = self._table.cellWidget(row_idx, _COL_4D_STATISTIC)
        reference_spin = self._table.cellWidget(row_idx, _COL_METRIC_LIMIT)
        if not isinstance(reference_spin, QDoubleSpinBox):
            return
        enabled = stat_uses_reference(self._statistic_from_combo(stat_combo))
        _set_boundary_value_spin_enabled(reference_spin, enabled)

    def _update_absolute_for_row(self, row_idx: int) -> None:
        stat_combo = self._table.cellWidget(row_idx, _COL_4D_STATISTIC)
        abs_box = _checkbox_in(self._table.cellWidget(row_idx, _COL_ABSOLUTE))
        if abs_box is None:
            return
        enabled = stat_uses_absolute(self._statistic_from_combo(stat_combo))
        abs_box.setEnabled(enabled)

    def _on_statistic_changed(self, row_idx: int) -> None:
        self._update_metric_limit_for_row(row_idx)
        self._update_absolute_for_row(row_idx)
        self._emit_changed()

    def _row_from_widgets(self, row_idx: int) -> SurveySpecRow:
        stat_combo = self._table.cellWidget(row_idx, _COL_4D_STATISTIC)
        stat_spin = self._table.cellWidget(row_idx, _COL_STATISTIC_LIMIT)
        metric_combo = self._table.cellWidget(row_idx, _COL_4D_METRIC)
        reference_spin = self._table.cellWidget(row_idx, _COL_METRIC_LIMIT)
        abs_box = _checkbox_in(self._table.cellWidget(row_idx, _COL_ABSOLUTE))
        severity_combo = self._table.cellWidget(row_idx, _COL_SEVERITY)
        metric_raw = (
            metric_combo.currentData()
            if isinstance(metric_combo, QComboBox)
            else "crossline"
        )
        statistic_raw = (
            stat_combo.currentData()
            if isinstance(stat_combo, QComboBox)
            else StatType.MAX_VALUE
        )
        severity_raw = (
            severity_combo.currentData()
            if isinstance(severity_combo, QComboBox)
            else Severity.ERROR
        )
        metric = (
            metric_raw
            if isinstance(metric_raw, str) and metric_raw in METRIC_KINDS
            else metric_kind_from_str(str(metric_raw or "crossline"))
        )
        statistic = (
            statistic_raw
            if isinstance(statistic_raw, StatType)
            else stat_type_from_str(str(statistic_raw or StatType.MAX_VALUE.value))
        )
        severity = (
            severity_raw
            if isinstance(severity_raw, Severity)
            else severity_from_str(str(severity_raw or Severity.ERROR.value))
        )
        reference_value = reference_spin.value() if reference_spin is not None else 0.0
        stat_value = stat_spin.value() if stat_spin is not None else 0.0
        absolute = abs_box.isChecked() if abs_box is not None else False
        return SurveySpecRow(
            metric=metric,
            statistic=statistic,
            reference_value=float(reference_value),
            stat_value=float(stat_value),
            absolute=bool(absolute),
            severity=severity,
        )

    def _rebuild(self) -> None:
        self._rebuilding = True
        self._table.blockSignals(True)
        self._table.setRowCount(len(self._rows))
        for row_idx, row in enumerate(self._rows):
            stat_combo = _make_combo(
                [(STAT_TYPE_LABELS[stat], stat) for stat in StatType],
                row.statistic,
            )
            stat_combo.currentIndexChanged.connect(
                lambda *_args, idx=row_idx: self._on_statistic_changed(idx)
            )
            self._table.setCellWidget(row_idx, _COL_4D_STATISTIC, stat_combo)

            stat_spin = _make_boundary_value_spin(row.stat_value)
            stat_spin.valueChanged.connect(lambda *_: self._emit_changed())
            self._table.setCellWidget(row_idx, _COL_STATISTIC_LIMIT, stat_spin)

            metric_combo = _make_combo(
                [(METRIC_LABELS[kind], kind) for kind in METRIC_KINDS],
                row.metric,
            )
            metric_combo.currentIndexChanged.connect(lambda *_: self._emit_changed())
            self._table.setCellWidget(row_idx, _COL_4D_METRIC, metric_combo)

            reference_spin = _make_boundary_value_spin(row.reference_value)
            reference_spin.valueChanged.connect(lambda *_: self._emit_changed())
            self._table.setCellWidget(row_idx, _COL_METRIC_LIMIT, reference_spin)
            self._update_metric_limit_for_row(row_idx)

            abs_container = _make_absolute_checkbox(row.absolute)
            abs_box = _checkbox_in(abs_container)
            if abs_box is not None:
                abs_box.toggled.connect(lambda *_: self._emit_changed())
            self._table.setCellWidget(row_idx, _COL_ABSOLUTE, abs_container)
            self._update_absolute_for_row(row_idx)

            severity_combo = _make_combo(
                [(SEVERITY_LABELS[sev], sev) for sev in Severity],
                row.severity,
            )
            severity_combo.currentIndexChanged.connect(lambda *_: self._emit_changed())
            self._table.setCellWidget(row_idx, _COL_SEVERITY, severity_combo)
            self._table.setRowHeight(row_idx, 34)
        self._table.blockSignals(False)
        self._rebuilding = False
        _fit_table_to_content(self._table)
        self.adjustSize()


class _ResultSummary(QWidget):
    """Combined sequence results beside the spec table."""

    changed = Signal()

    _COL_SEQUENCE = 0
    _COL_EXCLUDED = 1
    _COL_FAILED = 2

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._sequence_nos: list[str] = []
        self._excluded_by_sequence: dict[str, str] = {}
        self._failed_details: list[FailedSpecDetail] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        title = QLabel("Sequence(s) Results")
        title.setObjectName("statPlotSection")
        layout.addWidget(title)

        self._overall = QLabel("Acceptance: —")
        self._overall.setStyleSheet("color: #e6edf3; font-size: 12px;")
        layout.addWidget(self._overall)

        self._table = QTableWidget(0, 3)
        _configure_legend_table(self._table)
        self._table.setHorizontalHeaderLabels(
            ["Sequence No.", "Excluded Shotpoints", "Failed Shotpoints"]
        )
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        layout.addWidget(self._table)

    def set_sequences(
        self,
        sequence_nos: list[str],
        excluded_by_sequence: dict[str, str],
    ) -> None:
        self._sequence_nos = list(sequence_nos)
        self._excluded_by_sequence = dict(excluded_by_sequence)
        self._rebuild_rows()

    def excluded_shotpoints(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for row_idx, sequence_no in enumerate(self._sequence_nos):
            edit = self._table.cellWidget(row_idx, self._COL_EXCLUDED)
            if isinstance(edit, QLineEdit):
                mapping[sequence_no] = edit.text().strip()
            else:
                mapping[sequence_no] = self._excluded_by_sequence.get(sequence_no, "")
        return mapping

    def set_evaluation(
        self,
        evaluation: SurveyEvaluation | None,
        sequence_nos: list[str],
    ) -> None:
        self._sequence_nos = list(sequence_nos)
        if not sequence_nos:
            self._failed_details = []
            self._overall.setText("Acceptance: —")
            self._overall.setStyleSheet("color: #8b949e; font-size: 12px;")
            self._table.setRowCount(0)
            return

        if evaluation is None or evaluation.spec_count == 0:
            self._failed_details = []
            self._overall.setText("Acceptance: — (no specs)")
            self._overall.setStyleSheet("color: #8b949e; font-size: 12px;")
            self._rebuild_rows()
            return

        self._failed_details = list(evaluation.failed_details)
        if evaluation.accepted and evaluation.has_warning:
            self._overall.setText("Acceptance: PASS (warn)")
            self._overall.setStyleSheet(f"font-size: 13px; {_WARN_STYLE}")
        elif evaluation.accepted:
            self._overall.setText("Acceptance: PASS")
            self._overall.setStyleSheet(f"font-size: 13px; {_PASS_STYLE}")
        else:
            self._overall.setText("Acceptance: FAIL")
            self._overall.setStyleSheet(f"font-size: 13px; {_FAIL_STYLE}")
        self._rebuild_rows()

    def _failed_button_label(self, sequence_no: str) -> str:
        count = len(failed_details_for_sequence(self._failed_details, sequence_no))
        if count == 0:
            return "View"
        return f"View ({count})"

    def _open_failed_shotpoints(self, sequence_no: str) -> None:
        entries = failed_details_for_sequence(self._failed_details, sequence_no)
        if not entries and self._failed_details:
            entries = list(self._failed_details)
        FailedShotpointsDialog.show(
            self.window(),
            entries,
            sequence_no=sequence_no,
        )

    def _rebuild_rows(self) -> None:
        self._table.blockSignals(True)
        self._table.setRowCount(len(self._sequence_nos))
        for row_idx, sequence_no in enumerate(self._sequence_nos):
            seq_item = QTableWidgetItem(sequence_no or "—")
            seq_item.setFlags(seq_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row_idx, self._COL_SEQUENCE, seq_item)

            excluded_edit = _make_excluded_edit(
                self._excluded_by_sequence.get(sequence_no, "")
            )
            excluded_edit.textChanged.connect(self._on_excluded_changed)
            self._table.setCellWidget(row_idx, self._COL_EXCLUDED, excluded_edit)

            failed_btn = _table_cell_button(self._failed_button_label(sequence_no))
            has_failures = bool(
                failed_details_for_sequence(self._failed_details, sequence_no)
            )
            failed_btn.setEnabled(has_failures)
            failed_btn.clicked.connect(
                lambda *_args, seq=sequence_no: self._open_failed_shotpoints(seq)
            )
            failed_container = QWidget()
            failed_layout = QHBoxLayout(failed_container)
            failed_layout.setContentsMargins(0, 0, 0, 0)
            failed_layout.setSpacing(0)
            failed_layout.addStretch()
            failed_layout.addWidget(failed_btn)
            failed_layout.addStretch()
            self._table.setCellWidget(row_idx, self._COL_FAILED, failed_container)
            self._table.setRowHeight(row_idx, 34)
        self._table.blockSignals(False)
        _fit_table_to_content(self._table)
        self.adjustSize()

    def _on_excluded_changed(self) -> None:
        self._excluded_by_sequence = self.excluded_shotpoints()
        self.changed.emit()
