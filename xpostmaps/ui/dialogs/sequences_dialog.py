"""P111/P190 sequence selection popup for legend styling."""

from __future__ import annotations

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
    QVBoxLayout,
)

from xpostmaps.core.models import LineSequence
from xpostmaps.ui.dialogs.base_dialog import SingleInstanceDialog

_UNASSIGNED_LABEL = "(Unassigned)"


class _SortableTableWidgetItem(QTableWidgetItem):
    """Table cell that sorts by an explicit key (numeric or text)."""

    def __init__(self, text: str, sort_key: float | str, seq_id: str) -> None:
        super().__init__(text)
        self._sort_key = sort_key
        self.setFlags(self.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.setData(Qt.ItemDataRole.UserRole, seq_id)

    def set_sort_key(self, sort_key: float | str, text: str | None = None) -> None:
        self._sort_key = sort_key
        if text is not None:
            self.setText(text)

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


def _text_sort_key(value: str) -> str:
    return value.casefold().strip()


def _assignment_display(name: str) -> str:
    return name if name else _UNASSIGNED_LABEL


def _assignment_sort_key(name: str) -> str:
    return name.lower() if name else "\uffff"


class SequencesDialog:
    KEY_PREFIX = "sequences_"

    @classmethod
    def open(
        cls,
        parent,
        sequences: list[LineSequence],
        postplot_names: list[str],
        assignments: dict[str, str],
        on_assignments_changed: Callable[[dict[str, str]], None],
        on_refresh: Callable[[], list[LineSequence]] | None = None,
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
            postplot_options = [name for name in postplot_names if name.strip()]
            pending_assignments: dict[str, str] = dict(assignments)

            def _assignment_combo(
                assigned_name: str,
                sort_item: _SortableTableWidgetItem,
                seq_id: str,
            ) -> QComboBox:
                combo = QComboBox()
                combo.addItem(_UNASSIGNED_LABEL, "")
                for name in postplot_options:
                    combo.addItem(name, name)
                target = assigned_name if assigned_name in postplot_options else ""
                index = combo.findData(target)
                combo.setCurrentIndex(index if index >= 0 else 0)

                def sync_sort(_index: int, item=sort_item, box=combo, sid=seq_id) -> None:
                    value = str(box.currentData() or "")
                    item.set_sort_key(_assignment_sort_key(value), _assignment_display(value))
                    if value:
                        pending_assignments[sid] = value
                    else:
                        pending_assignments.pop(sid, None)

                combo.currentIndexChanged.connect(sync_sort)
                return combo

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
                        (seq.line_name, _text_sort_key(seq.line_name)),
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
                    assigned = pending_assignments.get(seq.seq_id, "")
                    sort_item = _SortableTableWidgetItem(
                        _assignment_display(assigned),
                        _assignment_sort_key(assigned),
                        seq.seq_id,
                    )
                    table.setItem(row, 5, sort_item)
                    table.setCellWidget(
                        row,
                        5,
                        _assignment_combo(assigned, sort_item, seq.seq_id),
                    )
                table.setSortingEnabled(was_sorting or True)

            def _sync_assignment_widgets() -> None:
                """Rebind dropdowns after sort; Qt keeps cell widgets on row indices."""
                table = table_holder["table"]
                if table is None:
                    return
                for row in range(table.rowCount()):
                    id_item = table.item(row, 0)
                    if id_item is None:
                        continue
                    seq_id = str(id_item.data(Qt.ItemDataRole.UserRole) or "")
                    if not seq_id:
                        continue
                    sort_item = table.item(row, 5)
                    if not isinstance(sort_item, _SortableTableWidgetItem):
                        continue
                    assigned = pending_assignments.get(seq_id, "")
                    existing = table.cellWidget(row, 5)
                    if isinstance(existing, QComboBox):
                        assigned = str(existing.currentData() or "")
                    table.removeCellWidget(row, 5)
                    table.setCellWidget(
                        row,
                        5,
                        _assignment_combo(assigned, sort_item, seq_id),
                    )

            def _collect_assignments() -> dict[str, str]:
                table = table_holder["table"]
                if table is None:
                    return {}
                result: dict[str, str] = {}
                for row in range(table.rowCount()):
                    id_item = table.item(row, 0)
                    if id_item is None:
                        continue
                    seq_id = id_item.data(Qt.ItemDataRole.UserRole)
                    if not seq_id:
                        continue
                    combo = table.cellWidget(row, 5)
                    if not isinstance(combo, QComboBox):
                        continue
                    postplot_name = str(combo.currentData() or "").strip()
                    if postplot_name:
                        result[str(seq_id)] = postplot_name
                return result

            def _assign_rows(rows: set[int], postplot_name: str) -> None:
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
                    target = postplot_name if postplot_name in postplot_options else ""
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
                for name in postplot_options:
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
                    "Sequence No.",
                    "Line Name",
                    "Line Direction",
                    "First SP",
                    "Last SP",
                    "Assigned Postplot",
                ]
            )
            table.verticalHeader().setVisible(False)
            table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
            table.setSortingEnabled(True)
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
            _populate_table(sequences)

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
            "P111/P190 Sequences",
            build,
            parent,
            width=820,
        )
