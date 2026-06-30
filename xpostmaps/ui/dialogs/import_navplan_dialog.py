"""Manage navplan source-position files in a dedicated non-modal window."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from xpostmaps.core.crs_utils import epsg_label
from xpostmaps.core.models import ProjectSettings
from xpostmaps.core.navplan_catalog_utils import (
    catalog_for_saved_files,
    collect_navplan_files_from_folder,
    refresh_navplan_catalog,
    renumber_navplan_catalog,
)
from xpostmaps.ui.dialogs.base_dialog import SingleInstanceDialog
from xpostmaps.ui.theme import themed_open_directory, themed_open_files

_NAVPLAN_FILTER = (
    "Navplan Files (*.navplan *.p190 *.190 *.p111);;"
    "All Files (*)"
)


def _clear_layout(layout) -> None:
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
    table.horizontalHeader().setSectionResizeMode(
        QHeaderView.ResizeMode.ResizeToContents
    )
    table.setWordWrap(False)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
    table.setAlternatingRowColors(True)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)


def _fit_table(table: QTableWidget) -> None:
    table.resizeRowsToContents()
    for row in range(table.rowCount()):
        table.setRowHeight(row, max(table.rowHeight(row), 34))
    for col in range(table.columnCount()):
        table.resizeColumnToContents(col)


def _set_table_viewport_rows(table: QTableWidget, visible_rows: int = 8) -> None:
    table.resizeRowsToContents()
    header_h = table.horizontalHeader().sizeHint().height()
    row_h = table.verticalHeader().defaultSectionSize()
    if table.rowCount() > 0:
        row_h = max(row_h, max(table.rowHeight(r) for r in range(table.rowCount())))
    frame = table.frameWidth() * 2
    viewport_h = header_h + row_h * visible_rows + frame
    table.setMinimumHeight(viewport_h)
    table.setMaximumHeight(viewport_h)


def _split_folders(value: str) -> list[str]:
    if not value:
        return []
    return [folder for folder in value.split(os.pathsep) if folder]


def _folders_to_string(folders: list[str]) -> str:
    return os.pathsep.join(folders)


def _unique_existing_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in paths:
        path = Path(raw)
        try:
            resolved = str(path.resolve())
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        result.append(resolved)
    return result


def _collect_from_folders(folders: list[str]) -> list[str]:
    files: list[str] = []
    for folder in folders:
        files.extend(collect_navplan_files_from_folder(folder))
    return _unique_existing_paths(files)


def _themed_open_directories(parent: QWidget, title: str, initial_dir: str = "") -> list[str]:
    """Show a folder picker; native on Windows so network shares are browsable."""
    folder = themed_open_directory(parent, title, initial_dir)
    if not folder:
        return []
    return _unique_existing_paths([folder])


class ImportNavplanDialog:
    KEY = "import_navplan"

    @classmethod
    def open(
        cls,
        parent: QWidget,
        settings: ProjectSettings,
        on_apply: Callable[[ProjectSettings], None],
        initial_dir: str = "",
    ) -> None:
        initial_folders = _split_folders(settings.navplans_dir)
        if not initial_folders and settings.navplans_dir:
            initial_folders = [settings.navplans_dir]
        if not initial_folders and initial_dir:
            initial_folders = [initial_dir]
        state = {
            "folders": _unique_existing_paths(
                [folder for folder in initial_folders if Path(folder).is_dir()]
            ),
            "files": list(settings.navplan_files),
            "catalog": list(settings.navplan_catalog),
        }

        def rebuild_catalog(*, force: bool = False) -> None:
            state["catalog"] = refresh_navplan_catalog(
                state["files"],
                state["catalog"],
                force=force,
            )

        def load_saved_catalog() -> None:
            state["catalog"] = catalog_for_saved_files(
                state["files"],
                settings.navplan_catalog,
            )

        def apply_changes() -> None:
            settings.navplan_files = list(state["files"])
            settings.navplan_files_explicit = True
            settings.navplans_dir = _folders_to_string(state["folders"])
            settings.navplan_catalog = list(state["catalog"])
            on_apply(settings)

        def refresh_table(table: QTableWidget) -> None:
            table.setRowCount(0)
            for entry in state["catalog"]:
                row = table.rowCount()
                table.insertRow(row)
                table.setItem(row, 0, QTableWidgetItem(str(entry.navplan_number)))
                table.setItem(
                    row,
                    1,
                    QTableWidgetItem(
                        entry.navplan_name or Path(entry.file_path).name
                    ),
                )
                table.setItem(row, 2, QTableWidgetItem(entry.line_direction or ""))
                crs_text = epsg_label(entry.crs_code) if entry.crs_code else "Unknown"
                table.setItem(row, 3, QTableWidgetItem(crs_text))
            _fit_table(table)
            _set_table_viewport_rows(table, 8)
            folder_count = len(state["folders"])
            folder_text = (
                f" from {folder_count} folder(s)"
                if folder_count
                else ""
            )
            summary.setText(f"{len(state['catalog'])} navplan file(s){folder_text}")

        def browse_folder() -> None:
            initial = state["folders"][0] if state["folders"] else initial_dir
            folders = _themed_open_directories(
                parent,
                "Import Navplan — Add Folders",
                initial,
            )
            if not folders:
                return
            state["folders"] = _unique_existing_paths([*state["folders"], *folders])
            state["files"] = _unique_existing_paths(
                [*state["files"], *_collect_from_folders(folders)]
            )
            rebuild_catalog()
            refresh_table(table)

        def select_files() -> None:
            paths = themed_open_files(
                parent,
                "Import Navplan — Select Files",
                _NAVPLAN_FILTER,
            )
            if not paths:
                return
            state["folders"] = _unique_existing_paths(
                [*state["folders"], str(Path(paths[0]).parent)]
            )
            existing = set(state["files"])
            for path in paths:
                resolved = str(Path(path).resolve())
                if resolved not in existing:
                    state["files"].append(resolved)
                    existing.add(resolved)
            rebuild_catalog()
            refresh_table(table)

        def rescan() -> None:
            if state["folders"]:
                state["files"] = _collect_from_folders(state["folders"])
            else:
                state["files"] = _unique_existing_paths(
                    [path for path in state["files"] if Path(path).is_file()]
                )
            rebuild_catalog(force=False)
            refresh_table(table)

        def remove_selected() -> None:
            rows = sorted({index.row() for index in table.selectedIndexes()}, reverse=True)
            if not rows:
                return
            remove_paths = {
                state["catalog"][row].file_path
                for row in rows
                if 0 <= row < len(state["catalog"])
            }
            state["files"] = [
                path for path in state["files"] if path not in remove_paths
            ]
            remaining_dirs = {str(Path(path).parent.resolve()) for path in state["files"]}
            state["folders"] = [
                folder for folder in state["folders"] if folder in remaining_dirs
            ]
            state["catalog"] = [
                entry
                for entry in state["catalog"]
                if entry.file_path not in remove_paths
            ]
            renumber_navplan_catalog(state["catalog"])
            refresh_table(table)

        def build(dialog: SingleInstanceDialog) -> None:
            state["files"] = list(settings.navplan_files)
            folders = _split_folders(settings.navplans_dir)
            if not folders and initial_dir:
                folders = [initial_dir]
            state["folders"] = _unique_existing_paths(
                [folder for folder in folders if Path(folder).is_dir()]
            )
            load_saved_catalog()
            layout = dialog.content_layout
            _clear_layout(layout)

            hint = QLabel(
                "Import navplan source positions from .navplan, .p190, .190, "
                ".p111, or extensionless files."
            )
            hint.setWordWrap(True)
            layout.addWidget(hint)

            btn_row = QHBoxLayout()
            browse_btn = QPushButton("Browse Folder…")
            files_btn = QPushButton("Add Files…")
            remove_btn = QPushButton("Remove Selected")
            for btn in (browse_btn, files_btn, remove_btn):
                btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                btn.setAutoDefault(False)
            browse_btn.clicked.connect(browse_folder)
            files_btn.clicked.connect(select_files)
            remove_btn.clicked.connect(remove_selected)
            btn_row.addWidget(browse_btn)
            btn_row.addWidget(files_btn)
            btn_row.addWidget(remove_btn)
            btn_row.addStretch()
            layout.addLayout(btn_row)

            nonlocal summary
            summary = QLabel("")
            summary.setStyleSheet("color: #8b949e; font-size: 11px;")
            layout.addWidget(summary)

            nonlocal table
            table = QTableWidget(0, 4)
            table.setHorizontalHeaderLabels(
                ["Navplan No.", "Navplan Name", "Navplan Line Direction", "CRS Code"]
            )
            _configure_table(table)
            layout.addWidget(table)

            refresh_table(table)

            def apply_and_close() -> None:
                apply_changes()
                dialog.close()

            close_row = QHBoxLayout()
            rescan_btn = QPushButton("Rescan")
            rescan_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            rescan_btn.clicked.connect(rescan)
            apply_btn = QPushButton("Apply")
            apply_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            apply_btn.clicked.connect(apply_changes)
            ok_btn = QPushButton("OK")
            ok_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            ok_btn.clicked.connect(apply_and_close)
            close_btn = QPushButton("Close")
            close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            close_btn.clicked.connect(dialog.close)
            close_row.addWidget(rescan_btn)
            close_row.addStretch()
            close_row.addWidget(apply_btn)
            close_row.addWidget(ok_btn)
            close_row.addWidget(close_btn)
            layout.addLayout(close_row)

        summary = QLabel("")
        table = QTableWidget()

        return SingleInstanceDialog.show_dialog(
            cls.KEY,
            "Import Navplan",
            build,
            parent,
            width=780,
            height=540,
        )
