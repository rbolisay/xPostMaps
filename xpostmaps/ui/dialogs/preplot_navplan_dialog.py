"""Manage preplot files in a dedicated non-modal window."""

from __future__ import annotations

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
from xpostmaps.core.models import PreplotCatalogEntry, ProjectSettings
from xpostmaps.core.preplot_catalog_utils import (
    build_preplot_catalog,
    renumber_preplot_catalog,
)
from xpostmaps.parsers.preplot_parser import PREPLOT_EXTENSIONS
from xpostmaps.ui.dialogs.base_dialog import SingleInstanceDialog
from xpostmaps.ui.theme import themed_open_directory, themed_open_files

_PREPLOT_FILTER = (
    "Preplot Files (*.p111 *.p190 *.190 *.txt);;"
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


def _collect_from_folder(folder: str) -> list[str]:
    root = Path(folder)
    if not root.is_dir():
        return []
    files: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in {ext.lower() for ext in PREPLOT_EXTENSIONS}:
            files.append(str(path.resolve()))
    return files


class PreplotNavplanDialog:
    KEY = "preplot_navplan"

    @classmethod
    def open(
        cls,
        parent: QWidget,
        settings: ProjectSettings,
        on_apply: Callable[[ProjectSettings], None],
        initial_dir: str = "",
    ) -> None:
        state = {
            "folder": settings.preplots_dir or initial_dir,
            "files": list(settings.preplot_files),
            "catalog": list(settings.preplot_catalog),
        }

        def rebuild_catalog() -> None:
            paths = [Path(path) for path in state["files"] if Path(path).is_file()]
            state["catalog"] = build_preplot_catalog(paths) if paths else []
            renumber_preplot_catalog(state["catalog"])

        def apply_changes() -> None:
            settings.preplot_files = list(state["files"])
            settings.preplot_files_explicit = True
            settings.preplots_dir = state["folder"]
            settings.preplot_catalog = list(state["catalog"])
            on_apply(settings)

        def refresh_table(table: QTableWidget) -> None:
            table.setRowCount(0)
            for entry in state["catalog"]:
                row = table.rowCount()
                table.insertRow(row)
                table.setItem(row, 0, QTableWidgetItem(str(entry.preplot_number)))
                table.setItem(row, 1, QTableWidgetItem(Path(entry.file_path).name))
                crs_text = (
                    epsg_label(entry.crs_code) if entry.crs_code else "Unknown"
                )
                table.setItem(row, 2, QTableWidgetItem(crs_text))
                table.setItem(row, 3, QTableWidgetItem(str(entry.total_lines)))
            _fit_table(table)
            _set_table_viewport_rows(table, 8)
            summary.setText(f"{len(state['catalog'])} preplot file(s)")

        def refresh_files_from_catalog() -> None:
            state["files"] = [entry.file_path for entry in state["catalog"]]

        def browse_folder() -> None:
            folder = themed_open_directory(
                parent,
                "Import Preplot — Select Folder",
            )
            if not folder:
                return
            state["folder"] = folder
            state["files"] = _collect_from_folder(folder)
            rebuild_catalog()
            refresh_table(table)

        def add_files() -> None:
            paths = themed_open_files(
                parent,
                "Import Preplot — Select Files",
                _PREPLOT_FILTER,
            )
            if not paths:
                return
            state["folder"] = str(Path(paths[0]).parent)
            existing = set(state["files"])
            for path in paths:
                resolved = str(Path(path).resolve())
                if resolved not in existing:
                    state["files"].append(resolved)
                    existing.add(resolved)
            rebuild_catalog()
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
            rebuild_catalog()
            refresh_table(table)

        def rescan() -> None:
            if state["folder"]:
                state["files"] = _collect_from_folder(state["folder"])
            else:
                state["files"] = [
                    path for path in state["files"] if Path(path).is_file()
                ]
            rebuild_catalog()
            refresh_table(table)

        def build(dialog: SingleInstanceDialog) -> None:
            state["files"] = list(settings.preplot_files)
            state["folder"] = settings.preplots_dir or initial_dir
            rebuild_catalog()
            layout = dialog.content_layout
            _clear_layout(layout)

            hint = QLabel(
                "Import preplot files (.p111/.p190/.190 start/end lines and doglegs)."
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
            files_btn.clicked.connect(add_files)
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
                ["Preplot No.", "Filename", "CRS Code", "Total Preplot Lines"]
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
            "Import Preplot",
            build,
            parent,
            width=860,
            height=560,
        )
