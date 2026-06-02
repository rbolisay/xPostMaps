"""P111/P190 sequence selection popup for legend styling."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from xpostmaps.core.models import LineSequence
from xpostmaps.ui.dialogs.base_dialog import SingleInstanceDialog


class _SortableTableWidgetItem(QTableWidgetItem):
    """Table cell that sorts by an explicit key (numeric or text)."""

    def __init__(self, text: str, sort_key: float | str, seq_id: str) -> None:
        super().__init__(text)
        self._sort_key = sort_key
        self.setFlags(self.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.setData(Qt.ItemDataRole.UserRole, seq_id)

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, _SortableTableWidgetItem):
            return self._sort_key < other._sort_key
        return super().__lt__(other)


def _numeric_sort_key(value: str) -> float:
    text = value.strip().rstrip("°").strip()
    try:
        return float(text)
    except ValueError:
        return float("inf")


class SequencesDialog:
    KEY_PREFIX = "sequences_"

    @classmethod
    def open(
        cls,
        parent,
        legend_row_name: str,
        sequences: list[LineSequence],
        selected_ids: list[str],
        on_changed,
        on_refresh: Callable[[], list[LineSequence]] | None = None,
        row_key: str = "",
    ) -> None:
        dialog_key = f"{cls.KEY_PREFIX}{row_key or legend_row_name}"

        def build(dialog: SingleInstanceDialog) -> None:
            layout = dialog.content_layout
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
                else:
                    child = item.layout()
                    if child is not None:
                        while child.count():
                            sub = child.takeAt(0)
                            w = sub.widget()
                            if w is not None:
                                w.deleteLater()

            table_holder: dict[str, QTableWidget | None] = {"table": None}
            selected_set = set(selected_ids)

            def _populate_table(seq_rows: list[LineSequence]) -> None:
                table = table_holder["table"]
                if table is None:
                    return
                was_sorting = table.isSortingEnabled()
                table.setSortingEnabled(False)
                table.setRowCount(len(seq_rows))
                for row, seq in enumerate(seq_rows):
                    columns = [
                        (seq.sequence_no, _numeric_sort_key(seq.sequence_no)),
                        (seq.line_name, _numeric_sort_key(seq.line_name)),
                        (seq.line_direction, _numeric_sort_key(seq.line_direction)),
                        (str(seq.first_sp), float(seq.first_sp)),
                        (str(seq.last_sp), float(seq.last_sp)),
                    ]
                    for col, (text, sort_key) in enumerate(columns):
                        table.setItem(
                            row,
                            col,
                            _SortableTableWidgetItem(text, sort_key, seq.seq_id),
                        )
                    if seq.seq_id in selected_set:
                        table.selectRow(row)
                table.setSortingEnabled(was_sorting or True)

            def _collect_pending() -> list[str]:
                table = table_holder["table"]
                if table is None:
                    return []
                ids: list[str] = []
                for index in table.selectionModel().selectedRows():
                    item = table.item(index.row(), 0)
                    if item is None:
                        continue
                    seq_id = item.data(Qt.ItemDataRole.UserRole)
                    if seq_id and seq_id not in ids:
                        ids.append(str(seq_id))
                return ids

            table = QTableWidget(0, 5)
            table.setHorizontalHeaderLabels(
                ["Sequence No.", "Line Name", "Line Direction", "First SP", "Last SP"]
            )
            table.verticalHeader().setVisible(False)
            table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
            table.setSortingEnabled(True)
            table.horizontalHeader().setSortIndicatorShown(True)
            table.horizontalHeader().setSectionsClickable(True)
            table.horizontalHeader().setSectionResizeMode(
                QHeaderView.ResizeMode.ResizeToContents
            )
            table_holder["table"] = table
            _populate_table(sequences)

            pending_ids: list[str] = list(selected_ids)

            def commit_selection() -> None:
                pending_ids.clear()
                pending_ids.extend(_collect_pending())
                on_changed(list(pending_ids))

            def select_all() -> None:
                table.selectAll()

            def clear_selection() -> None:
                table.clearSelection()
                commit_selection()

            def commit_and_close() -> None:
                commit_selection()
                dialog.close()

            btn_row = QHBoxLayout()
            all_btn = QPushButton("Select All")
            none_btn = QPushButton("Clear Selection")
            ok_btn = QPushButton("OK")
            ok_btn.setObjectName("primaryBtn")
            close_btn = QPushButton("Close")
            all_btn.clicked.connect(select_all)
            none_btn.clicked.connect(clear_selection)
            ok_btn.clicked.connect(commit_and_close)
            close_btn.clicked.connect(commit_and_close)
            btn_row.addWidget(all_btn)
            btn_row.addWidget(none_btn)
            btn_row.addStretch()
            btn_row.addWidget(ok_btn)
            btn_row.addWidget(close_btn)

            layout.addWidget(table)
            layout.addLayout(btn_row)

        SingleInstanceDialog.show_dialog(
            dialog_key,
            "P111/P190 Sequences",
            build,
            parent,
            width=640,
        )

