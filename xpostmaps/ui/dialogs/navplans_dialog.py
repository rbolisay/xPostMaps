"""Navplan selection popup for legend styling."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QMenu,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
)

from xpostmaps.core.models import NavplanCatalogEntry
from xpostmaps.ui.dialogs.base_dialog import SingleInstanceDialog

_UNASSIGNED_LABEL = "(Unassigned)"


class _SortableTableWidgetItem(QTableWidgetItem):
    def __init__(self, text: str, sort_key: float | str, source_index: int) -> None:
        super().__init__(text)
        self._sort_key = sort_key
        self.setFlags(self.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.setData(Qt.ItemDataRole.UserRole, source_index)

    def set_sort_key(self, sort_key: float | str, text: str | None = None) -> None:
        self._sort_key = sort_key
        if text is not None:
            self.setText(text)

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, _SortableTableWidgetItem):
            return self._sort_key < other._sort_key
        return super().__lt__(other)


def _text_sort_key(value: str) -> str:
    return value.casefold().strip()


def _assignment_display(name: str) -> str:
    return name if name else _UNASSIGNED_LABEL


def _assignment_sort_key(name: str) -> str:
    return name.lower() if name else "\uffff"


class NavplansDialog:
    KEY_PREFIX = "navplans_"

    @classmethod
    def open(
        cls,
        parent,
        catalog: list[NavplanCatalogEntry],
        navplan_legend_names: list[str],
        assignments: dict[int, str],
        on_assignments_changed: Callable[[dict[int, str]], None],
        row_key: str = "",
    ) -> None:
        dialog_key = f"{cls.KEY_PREFIX}{row_key or 'all'}"

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
            legend_options = [name for name in navplan_legend_names if name.strip()]
            pending_assignments: dict[int, str] = dict(assignments)

            def _assignment_combo(
                assigned_name: str,
                sort_item: _SortableTableWidgetItem,
                source_index: int,
            ) -> QComboBox:
                combo = QComboBox()
                combo.addItem(_UNASSIGNED_LABEL, "")
                for name in legend_options:
                    combo.addItem(name, name)
                target = assigned_name if assigned_name in legend_options else ""
                index = combo.findData(target)
                combo.setCurrentIndex(index if index >= 0 else 0)

                def sync_sort(
                    _combo_index: int,
                    item=sort_item,
                    box=combo,
                    sid=source_index,
                ) -> None:
                    value = str(box.currentData() or "")
                    item.set_sort_key(_assignment_sort_key(value), _assignment_display(value))
                    if value:
                        pending_assignments[sid] = value
                    else:
                        pending_assignments.pop(sid, None)

                combo.currentIndexChanged.connect(sync_sort)
                return combo

            def _populate_table(entries: list[NavplanCatalogEntry]) -> None:
                table = table_holder["table"]
                if table is None:
                    return
                was_sorting = table.isSortingEnabled()
                table.setSortingEnabled(False)
                table.setRowCount(len(entries))
                for row, entry in enumerate(entries):
                    source_index = max(entry.navplan_number - 1, 0)
                    navplan_name = entry.navplan_name or Path(entry.file_path).name
                    columns = [
                        (str(entry.navplan_number), float(entry.navplan_number)),
                        (navplan_name, _text_sort_key(navplan_name)),
                        (entry.line_direction or "", _text_sort_key(entry.line_direction or "")),
                        (str(entry.fsp or ""), float(entry.fsp or 0)),
                        (str(entry.lsp or ""), float(entry.lsp or 0)),
                    ]
                    for col, (text, sort_key) in enumerate(columns):
                        table.setItem(
                            row,
                            col,
                            _SortableTableWidgetItem(text, sort_key, source_index),
                        )
                    assigned = pending_assignments.get(source_index, "")
                    sort_item = _SortableTableWidgetItem(
                        _assignment_display(assigned),
                        _assignment_sort_key(assigned),
                        source_index,
                    )
                    table.setItem(row, 5, sort_item)
                    table.setCellWidget(
                        row,
                        5,
                        _assignment_combo(assigned, sort_item, source_index),
                    )
                table.setSortingEnabled(was_sorting or True)

            def _sync_assignment_widgets() -> None:
                table = table_holder["table"]
                if table is None:
                    return
                for row in range(table.rowCount()):
                    id_item = table.item(row, 0)
                    if id_item is None:
                        continue
                    source_index = id_item.data(Qt.ItemDataRole.UserRole)
                    if source_index is None:
                        continue
                    sid = int(source_index)
                    sort_item = table.item(row, 5)
                    if not isinstance(sort_item, _SortableTableWidgetItem):
                        continue
                    assigned = pending_assignments.get(sid, "")
                    existing = table.cellWidget(row, 5)
                    if isinstance(existing, QComboBox):
                        assigned = str(existing.currentData() or "")
                    table.removeCellWidget(row, 5)
                    table.setCellWidget(
                        row,
                        5,
                        _assignment_combo(assigned, sort_item, sid),
                    )

            def _collect_assignments() -> dict[int, str]:
                table = table_holder["table"]
                if table is None:
                    return {}
                result: dict[int, str] = {}
                for row in range(table.rowCount()):
                    id_item = table.item(row, 0)
                    if id_item is None:
                        continue
                    source_index = id_item.data(Qt.ItemDataRole.UserRole)
                    if source_index is None:
                        continue
                    combo = table.cellWidget(row, 5)
                    if not isinstance(combo, QComboBox):
                        continue
                    legend_name = str(combo.currentData() or "").strip()
                    if legend_name:
                        result[int(source_index)] = legend_name
                return result

            def _assign_rows(rows: set[int], legend_name: str) -> None:
                table = table_holder["table"]
                if table is None:
                    return
                for row in rows:
                    combo = table.cellWidget(row, 5)
                    sort_item = table.item(row, 5)
                    if not isinstance(combo, QComboBox) or not isinstance(
                        sort_item, _SortableTableWidgetItem
                    ):
                        continue
                    target = legend_name if legend_name in legend_options else ""
                    index = combo.findData(target)
                    combo.setCurrentIndex(index if index >= 0 else 0)
                    sort_item.set_sort_key(
                        _assignment_sort_key(target),
                        _assignment_display(target),
                    )

            def _show_context_menu(pos: QPoint) -> None:
                table = table_holder["table"]
                if table is None:
                    return
                index = table.indexAt(pos)
                selected_rows = {
                    model_index.row()
                    for model_index in table.selectionModel().selectedRows()
                }
                if index.isValid():
                    selected_rows.add(index.row())
                if not selected_rows:
                    return
                menu = QMenu(table)
                assign_menu = menu.addMenu("Assign to")
                for name in legend_options:
                    action = assign_menu.addAction(name)
                    action.triggered.connect(
                        lambda _checked=False, n=name, rows=set(selected_rows): _assign_rows(
                            rows, n
                        )
                    )
                unassigned_action = assign_menu.addAction(_UNASSIGNED_LABEL)
                unassigned_action.triggered.connect(
                    lambda _checked=False, rows=set(selected_rows): _assign_rows(rows, "")
                )
                menu.exec(table.viewport().mapToGlobal(pos))

            table = QTableWidget(0, 6)
            table.setHorizontalHeaderLabels(
                [
                    "Navplan No.",
                    "Navplan Name",
                    "Navplan Line Direction",
                    "FSP",
                    "LSP",
                    "Assigned Navplan Name",
                ]
            )
            table.verticalHeader().setVisible(False)
            table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
            table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            table.customContextMenuRequested.connect(_show_context_menu)
            header = table.horizontalHeader()
            header.setSortIndicatorShown(True)
            header.setSectionsClickable(True)
            header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            header.sortIndicatorChanged.connect(
                lambda _section, _order: QTimer.singleShot(0, _sync_assignment_widgets)
            )
            table_holder["table"] = table
            _populate_table(catalog)

            def commit_assignments() -> None:
                pending_assignments.clear()
                pending_assignments.update(_collect_assignments())
                on_assignments_changed(dict(pending_assignments))

            def commit_and_close() -> None:
                commit_assignments()
                dialog.close()

            btn_row = QHBoxLayout()
            all_btn = QPushButton("Select All")
            none_btn = QPushButton("Clear Selection")
            apply_btn = QPushButton("Apply")
            apply_btn.setObjectName("primaryBtn")
            ok_btn = QPushButton("OK")
            close_btn = QPushButton("Close")
            all_btn.clicked.connect(lambda: table.selectAll())
            none_btn.clicked.connect(table.clearSelection)
            apply_btn.clicked.connect(commit_assignments)
            ok_btn.clicked.connect(commit_and_close)
            close_btn.clicked.connect(dialog.close)
            btn_row.addWidget(all_btn)
            btn_row.addWidget(none_btn)
            btn_row.addStretch()
            btn_row.addWidget(apply_btn)
            btn_row.addWidget(ok_btn)
            btn_row.addWidget(close_btn)

            layout.addWidget(table)
            layout.addLayout(btn_row)

        SingleInstanceDialog.show_dialog(
            dialog_key,
            "Select Navplans",
            build,
            parent,
            width=820,
        )
