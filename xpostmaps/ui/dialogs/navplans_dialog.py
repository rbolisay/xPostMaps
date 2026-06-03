"""Navplan selection popup for legend styling."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
)

from xpostmaps.core.models import NavplanCatalogEntry
from xpostmaps.ui.dialogs.base_dialog import SingleInstanceDialog


class _SortableTableWidgetItem(QTableWidgetItem):
    def __init__(self, text: str, sort_key: float | str, source_index: int) -> None:
        super().__init__(text)
        self._sort_key = sort_key
        self.setFlags(self.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.setData(Qt.ItemDataRole.UserRole, source_index)

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, _SortableTableWidgetItem):
            return self._sort_key < other._sort_key
        return super().__lt__(other)


class NavplansDialog:
    KEY_PREFIX = "navplans_"

    @classmethod
    def open(
        cls,
        parent,
        legend_row_name: str,
        catalog: list[NavplanCatalogEntry],
        selected_indices: list[int],
        on_changed,
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

            selected_set = set(selected_indices)
            table = QTableWidget(0, 4)
            table.setHorizontalHeaderLabels(
                ["Navplan No.", "Navplan Name", "FSP", "LSP"]
            )
            table.verticalHeader().setVisible(False)
            table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
            table.horizontalHeader().setSortIndicatorShown(True)
            table.horizontalHeader().setSectionsClickable(True)
            table.horizontalHeader().setSectionResizeMode(
                QHeaderView.ResizeMode.ResizeToContents
            )
            # Populate with sorting disabled: enabling it first makes Qt re-sort on
            # every setItem, scrambling which cells land in which row (blank
            # Name/FSP/LSP and stray selections). Re-enable once fully populated.
            table.setSortingEnabled(False)
            table.setRowCount(len(catalog))
            rows_to_select: list[int] = []
            for row, entry in enumerate(catalog):
                source_index = max(entry.navplan_number - 1, 0)
                columns = [
                    (str(entry.navplan_number), float(entry.navplan_number)),
                    (
                        entry.navplan_name or Path(entry.file_path).name,
                        (entry.navplan_name or Path(entry.file_path).name).lower(),
                    ),
                    (str(entry.fsp or ""), float(entry.fsp or 0)),
                    (str(entry.lsp or ""), float(entry.lsp or 0)),
                ]
                for col, (text, sort_key) in enumerate(columns):
                    table.setItem(
                        row,
                        col,
                        _SortableTableWidgetItem(text, sort_key, source_index),
                    )
                if source_index in selected_set:
                    rows_to_select.append(row)
            table.setSortingEnabled(True)
            for row in rows_to_select:
                table.selectRow(row)

            def collect_selection() -> list[int]:
                indices: list[int] = []
                for index in table.selectionModel().selectedRows():
                    item = table.item(index.row(), 0)
                    if item is None:
                        continue
                    source_index = item.data(Qt.ItemDataRole.UserRole)
                    if source_index is not None and int(source_index) not in indices:
                        indices.append(int(source_index))
                return indices

            def commit_selection() -> None:
                on_changed(collect_selection())

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
            "Select Navplans",
            build,
            parent,
            width=640,
        )
