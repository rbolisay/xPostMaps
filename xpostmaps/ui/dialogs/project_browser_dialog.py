"""Non-modal project database browser (TierSeis-style)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from xpostmaps.core.db_browser_utils import (
    format_file_size,
    format_mtime,
    sqlite_project_rows,
)
from xpostmaps.ui.dialogs.base_dialog import SingleInstanceDialog
from xpostmaps.ui.theme import apply_file_dialog_theme

_PROJECT_NAME_ROLE = Qt.ItemDataRole.UserRole + 1


class ProjectBrowserDialog:
    """Browse saved projects in SQLite database files."""

    KEY = "project_browser"

    @classmethod
    def open(
        cls,
        parent: QWidget | None,
        start_directory: str,
        *,
        on_load: Callable[[str, str], None],
        on_delete: Callable[[str, str], None],
        on_directory_changed: Callable[[str], None] | None = None,
    ) -> None:
        state = {"directory": start_directory or str(Path.cwd())}
        directory_dialog: list[QFileDialog | None] = [None]

        def build(dialog: SingleInstanceDialog) -> None:
            layout = dialog.content_layout
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

            folder_row = QHBoxLayout()
            folder_row.addWidget(QLabel("Database folder:"))
            directory_edit = QLineEdit()
            directory_edit.setReadOnly(True)
            folder_row.addWidget(directory_edit, stretch=1)
            select_folder_btn = QPushButton("Select Folder")
            folder_row.addWidget(select_folder_btn)
            layout.addLayout(folder_row)

            table = QTableWidget(0, 5)
            table.setAlternatingRowColors(True)
            table.setHorizontalHeaderLabels(
                ["Project", "Database File", "Size", "Modified", "Path"]
            )
            table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.verticalHeader().setVisible(False)
            table.horizontalHeader().setSectionResizeMode(
                QHeaderView.ResizeMode.ResizeToContents
            )
            layout.addWidget(table, stretch=1)

            message_label = QLabel(
                "Each saved project is stored in a SQLite .db file. "
                "Legacy projects may share one database file."
            )
            message_label.setWordWrap(True)
            message_label.setStyleSheet("color: #94a3b8; font-size: 11px;")
            layout.addWidget(message_label)

            def selected_entry() -> tuple[str, str]:
                items = table.selectedItems()
                if not items:
                    return "", ""
                item = items[0]
                path = str(item.data(Qt.ItemDataRole.UserRole) or "")
                project = str(item.data(_PROJECT_NAME_ROLE) or "")
                return path, project

            def selected_entries() -> list[tuple[str, str]]:
                entries: list[tuple[str, str]] = []
                for row in sorted({index.row() for index in table.selectedIndexes()}):
                    item = table.item(row, 0)
                    if item is None:
                        continue
                    path = str(item.data(Qt.ItemDataRole.UserRole) or "")
                    project = str(item.data(_PROJECT_NAME_ROLE) or "")
                    if path and project and (path, project) not in entries:
                        entries.append((path, project))
                return entries

            def refresh() -> None:
                rows = sqlite_project_rows(state["directory"])
                table.setRowCount(0)
                for row_data in rows:
                    row = table.rowCount()
                    table.insertRow(row)
                    values = [
                        row_data.get("project_name") or "",
                        row_data.get("database") or "",
                        format_file_size(row_data.get("size")),
                        format_mtime(float(row_data.get("mtime") or 0)),
                        row_data.get("path") or "",
                    ]
                    for col, value in enumerate(values):
                        item = QTableWidgetItem(str(value))
                        item.setData(Qt.ItemDataRole.UserRole, row_data.get("path") or "")
                        item.setData(_PROJECT_NAME_ROLE, row_data.get("project_name") or "")
                        table.setItem(row, col, item)
                for col in range(table.columnCount()):
                    table.resizeColumnToContents(col)
                if rows:
                    table.selectRow(0)
                    message_label.setText(f"{len(rows)} saved project(s) found.")
                else:
                    message_label.setText(
                        "No saved projects found. Enter a project name and click Save "
                        "to create a new SQLite database file in this folder."
                    )

            def set_directory(directory: str) -> None:
                state["directory"] = directory or str(Path.cwd())
                directory_edit.setText(state["directory"])
                refresh()

            def open_selected() -> None:
                path, project = selected_entry()
                if not path or not project:
                    message_label.setText("Select a project first.")
                    return
                on_load(path, project)
                dialog.close()

            def delete_selected() -> None:
                entries = selected_entries()
                if not entries:
                    message_label.setText("Select one or more projects to delete.")
                    return
                if len(entries) == 1:
                    project, db_name = entries[0][1], Path(entries[0][0]).name
                    text = f"Delete project '{project}' from '{db_name}'?"
                else:
                    text = f"Delete {len(entries)} selected projects?"
                reply = QMessageBox.question(
                    dialog,
                    "Delete Project",
                    text + "\n\nThis cannot be undone.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
                failures: list[str] = []
                deleted = 0
                for path, project in entries:
                    try:
                        on_delete(path, project)
                        deleted += 1
                    except Exception as exc:  # noqa: BLE001
                        failures.append(f"{project}: {exc}")
                refresh()
                if failures:
                    QMessageBox.warning(
                        dialog,
                        "Delete Project",
                        f"Deleted {deleted} project(s), but some could not be removed:\n\n"
                        + "\n".join(failures),
                    )
                else:
                    message_label.setText(f"Deleted {deleted} project(s).")

            def pick_folder() -> None:
                existing = directory_dialog[0]
                if existing is not None and existing.isVisible():
                    existing.raise_()
                    existing.activateWindow()
                    return
                picker = QFileDialog(dialog, "Select Database Folder", state["directory"])
                picker.setFileMode(QFileDialog.FileMode.Directory)
                picker.setOption(QFileDialog.Option.ShowDirsOnly, True)
                picker.setOption(QFileDialog.Option.DontUseNativeDialog, True)
                picker.setModal(False)
                picker.setWindowModality(Qt.WindowModality.NonModal)
                apply_file_dialog_theme(picker)
                directory_dialog[0] = picker

                def on_finished(result: int) -> None:
                    try:
                        if result == int(QFileDialog.DialogCode.Accepted):
                            selected = picker.selectedFiles()
                            if selected:
                                folder = selected[0]
                                set_directory(folder)
                                if on_directory_changed:
                                    on_directory_changed(folder)
                    finally:
                        if directory_dialog[0] is picker:
                            directory_dialog[0] = None
                        picker.deleteLater()

                picker.finished.connect(on_finished)
                picker.open()

            btn_row = QHBoxLayout()
            refresh_btn = QPushButton("Refresh")
            delete_btn = QPushButton("Delete Selected")
            open_btn = QPushButton("Open Selected")
            open_btn.setObjectName("primaryBtn")
            close_btn = QPushButton("Close")
            refresh_btn.clicked.connect(refresh)
            delete_btn.clicked.connect(delete_selected)
            open_btn.clicked.connect(open_selected)
            close_btn.clicked.connect(dialog.close)
            table.itemDoubleClicked.connect(lambda _item: open_selected())
            select_folder_btn.clicked.connect(pick_folder)
            btn_row.addWidget(refresh_btn)
            btn_row.addWidget(delete_btn)
            btn_row.addStretch()
            btn_row.addWidget(open_btn)
            btn_row.addWidget(close_btn)
            layout.addLayout(btn_row)

            set_directory(state["directory"])

        SingleInstanceDialog.show_dialog(
            cls.KEY,
            "Browse / Load Project Database",
            build,
            parent,
            width=900,
            height=520,
        )
