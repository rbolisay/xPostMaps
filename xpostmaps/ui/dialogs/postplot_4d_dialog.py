"""Postplot 4D matching window."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from xpostmaps.core.models import MapData, ProjectSettings
from xpostmaps.core.postplot_4d_matching import (
    BaselineKind,
    Postplot4DMatchRow,
    build_postplot_4d_rows,
)
from xpostmaps.ui.dialogs.base_dialog import SingleInstanceDialog

_BASELINE_BUTTON_STYLE = """
QPushButton {
    background: #263244;
    color: #e6edf3;
    border: 1px solid #3b4a5f;
    border-radius: 6px;
    padding: 5px 16px;
}
QPushButton:checked {
    background: #000000;
    color: #ffffff;
    border: 2px solid #58a6ff;
    font-weight: 700;
}
"""


def _clear_layout(layout: QVBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
            continue
        child = item.layout()
        if child is not None:
            _clear_layout(child)


def _configure_table(table: QTableWidget) -> None:
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setMinimumSectionSize(34)
    table.verticalHeader().setDefaultSectionSize(34)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    table.setWordWrap(False)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    table.setAlternatingRowColors(True)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)


def _fit_table(table: QTableWidget) -> None:
    table.resizeRowsToContents()
    for row in range(table.rowCount()):
        table.setRowHeight(row, max(table.rowHeight(row), 34))
    for col in range(table.columnCount()):
        table.resizeColumnToContents(col)


class Postplot4DDialog:
    KEY = "postplot_4d"

    @classmethod
    def open(
        cls,
        parent: QWidget,
        settings: ProjectSettings,
        map_data: MapData | None,
        on_baseline_changed: Callable[[], None] | None = None,
    ) -> SingleInstanceDialog:
        saved_baseline = settings.postplot_4d_baseline
        if saved_baseline not in ("navplan", "preplot"):
            saved_baseline = "navplan" if map_data and map_data.navplan_segments else "preplot"
        state: dict[str, BaselineKind] = {
            "baseline": saved_baseline,
        }
        row_cache: dict[BaselineKind, list[Postplot4DMatchRow]] = {}

        def rows_for(kind: BaselineKind) -> list[Postplot4DMatchRow]:
            if kind not in row_cache:
                row_cache[kind] = build_postplot_4d_rows(map_data, settings, kind)
            return row_cache[kind]

        def show_difference(row: Postplot4DMatchRow) -> None:
            QMessageBox.information(
                parent,
                "Diff Stat",
                "Diff Stat calculation is not available yet.\n\n"
                f"{row.baseline_kind.title()}: {row.baseline_name}\n"
                f"Matched line: {row.line_name}\n"
                f"Sequence No.: {row.sequence_no}\n"
                f"FSP/LSP: {row.first_sp} / {row.last_sp}",
            )

        def refresh_table() -> None:
            rows = rows_for(state["baseline"])
            name_header = (
                "Navplan Name" if state["baseline"] == "navplan" else "Preplot Name"
            )
            table.setUpdatesEnabled(False)
            table.setSortingEnabled(False)
            table.setHorizontalHeaderLabels(
                [
                    name_header,
                    "Line Name",
                    "Subline",
                    "Sequence No.",
                    "Line FSP",
                    "Line LSP",
                    "Line Direction",
                    "Diff Stat",
                ]
            )
            table.setRowCount(len(rows))
            try:
                for row_idx, match_row in enumerate(rows):
                    table.setRowHeight(row_idx, 34)
                    values = [
                        match_row.baseline_name,
                        match_row.line_name,
                        match_row.subline,
                        match_row.sequence_no,
                        str(match_row.first_sp) if match_row.has_match else "",
                        str(match_row.last_sp) if match_row.has_match else "",
                        match_row.line_direction,
                    ]
                    for col, value in enumerate(values):
                        item = QTableWidgetItem(value)
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        table.setItem(row_idx, col, item)
                    diff_btn = QPushButton("Diff Stat")
                    diff_btn.setObjectName("tableCellBtn")
                    diff_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                    diff_btn.setMinimumSize(82, 28)
                    diff_btn.setEnabled(match_row.has_match)
                    diff_btn.clicked.connect(
                        lambda _checked=False, row=match_row: show_difference(row)
                    )
                    table.setCellWidget(row_idx, 7, diff_btn)
            finally:
                table.setUpdatesEnabled(True)
            summary.setText(
                f"{len(rows)} row(s) from {state['baseline']} baseline, "
                f"{sum(1 for row in rows if row.has_match)} matched imported line(s)"
            )
            _fit_table(table)

        def set_baseline(kind: BaselineKind) -> None:
            if state["baseline"] == kind:
                return
            state["baseline"] = kind
            settings.postplot_4d_baseline = kind
            if on_baseline_changed is not None:
                on_baseline_changed()
            refresh_table()

        def build(dialog: SingleInstanceDialog) -> None:
            layout = dialog.content_layout
            _clear_layout(layout)

            title = QLabel(
                "Match imported P111/P190 line sequences against a Navplan or Preplot baseline."
            )
            title.setWordWrap(True)
            layout.addWidget(title)

            baseline_row = QHBoxLayout()
            baseline_row.addWidget(QLabel("Baseline:"))
            navplan_radio = QPushButton("Navplan")
            preplot_radio = QPushButton("Preplot")
            for button in (navplan_radio, preplot_radio):
                button.setCheckable(True)
                button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                button.setStyleSheet(_BASELINE_BUTTON_STYLE)
                button.setMinimumSize(92, 32)
            navplan_radio.setChecked(state["baseline"] == "navplan")
            preplot_radio.setChecked(state["baseline"] == "preplot")
            group = QButtonGroup(dialog)
            group.setExclusive(True)
            group.addButton(navplan_radio)
            group.addButton(preplot_radio)
            navplan_radio.toggled.connect(lambda checked: checked and set_baseline("navplan"))
            preplot_radio.toggled.connect(lambda checked: checked and set_baseline("preplot"))
            baseline_row.addWidget(navplan_radio)
            baseline_row.addWidget(preplot_radio)
            baseline_row.addStretch()
            layout.addLayout(baseline_row)

            nonlocal summary
            summary = QLabel("")
            summary.setStyleSheet("color: #8b949e; font-size: 11px;")
            layout.addWidget(summary)

            nonlocal table
            table = QTableWidget(0, 8)
            _configure_table(table)
            layout.addWidget(table, stretch=1)

            refresh_table()

            close_row = QHBoxLayout()
            close_btn = QPushButton("Close")
            close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            close_btn.clicked.connect(dialog.close)
            close_row.addStretch()
            close_row.addWidget(close_btn)
            layout.addLayout(close_row)

        summary = QLabel("")
        table = QTableWidget()

        return SingleInstanceDialog.show_dialog(
            cls.KEY,
            "Postplot 4D",
            build,
            parent,
            width=1120,
            height=680,
        )
