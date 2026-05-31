"""P111/P190 sequence selection popup for legend styling."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from xpostmaps.core.models import LineSequence
from xpostmaps.ui.dialogs.base_dialog import SingleInstanceDialog


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
        on_delete: Callable[[list[str]], None] | None = None,
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
            id_by_row: dict[int, str] = {}
            selected_set = set(selected_ids)

            def _populate_table(seq_rows: list[LineSequence]) -> None:
                table = table_holder["table"]
                if table is None:
                    return
                id_by_row.clear()
                table.setRowCount(len(seq_rows))
                for row, seq in enumerate(seq_rows):
                    id_by_row[row] = seq.seq_id
                    values = [
                        seq.sequence_no,
                        seq.line_name,
                        seq.line_direction,
                        str(seq.first_sp),
                        str(seq.last_sp),
                    ]
                    for col, text in enumerate(values):
                        item = QTableWidgetItem(text)
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        item.setData(Qt.ItemDataRole.UserRole, seq.seq_id)
                        table.setItem(row, col, item)
                    if seq.seq_id in selected_set:
                        table.selectRow(row)

            def _collect_pending() -> list[str]:
                table = table_holder["table"]
                if table is None:
                    return []
                ids: list[str] = []
                for index in table.selectionModel().selectedRows():
                    seq_id = id_by_row.get(index.row())
                    if seq_id:
                        ids.append(seq_id)
                return ids

            def _collect_selected_ids() -> list[str]:
                table = table_holder["table"]
                if table is None:
                    return []
                ids: list[str] = []
                for index in table.selectionModel().selectedRows():
                    seq_id = id_by_row.get(index.row())
                    if seq_id:
                        ids.append(seq_id)
                return ids

            table = QTableWidget(0, 5)
            table.setHorizontalHeaderLabels(
                ["Sequence No.", "Line Name", "Line Direction", "First SP", "Last SP"]
            )
            table.verticalHeader().setVisible(False)
            table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
            table.horizontalHeader().setSectionResizeMode(
                QHeaderView.ResizeMode.ResizeToContents
            )
            table_holder["table"] = table
            _populate_table(sequences)

            pending_ids: list[str] = list(selected_ids)

            def select_all() -> None:
                table.selectAll()

            def clear_selection() -> None:
                table.clearSelection()

            def commit_and_close() -> None:
                pending_ids.clear()
                pending_ids.extend(_collect_pending())
                on_changed(list(pending_ids))
                dialog.close()

            def delete_selected() -> None:
                if not on_delete:
                    return
                to_delete = _collect_selected_ids()
                if not to_delete:
                    QMessageBox.information(
                        dialog,
                        "Delete Sequences",
                        "Select one or more sequences to delete.",
                    )
                    return
                answer = QMessageBox.question(
                    dialog,
                    "Delete Sequences",
                    f"Delete {len(to_delete)} selected sequence(s) and all related "
                    "navigation data from the project?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
                on_delete(to_delete)
                for seq_id in to_delete:
                    selected_set.discard(seq_id)
                refreshed = on_refresh() if on_refresh else []
                _populate_table(refreshed)

            btn_row = QHBoxLayout()
            all_btn = QPushButton("Select All")
            none_btn = QPushButton("Clear Selection")
            delete_btn = QPushButton("Delete Selected")
            delete_btn.setEnabled(on_delete is not None)
            ok_btn = QPushButton("OK")
            ok_btn.setObjectName("primaryBtn")
            close_btn = QPushButton("Close")
            all_btn.clicked.connect(select_all)
            none_btn.clicked.connect(clear_selection)
            delete_btn.clicked.connect(delete_selected)
            ok_btn.clicked.connect(commit_and_close)
            close_btn.clicked.connect(dialog.close)
            btn_row.addWidget(all_btn)
            btn_row.addWidget(none_btn)
            btn_row.addWidget(delete_btn)
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
