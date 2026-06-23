"""Dialog for selecting navigation or preplot file sets."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from xpostmaps.ui.theme import app_stylesheet


class NavFilePickerDialog(QDialog):
    """Modal picker: browse folder or add multiple files."""

    _DEFAULT_WIDTH = 676
    _DEFAULT_HEIGHT = 819  # 546 + 50%
    _MAX_SCREEN_FRACTION = 0.92

    def __init__(
        self,
        parent=None,
        *,
        title: str = "Select Files",
        hint: str = "Select a folder or add individual files.",
        extensions: set[str] | None = None,
        file_filter: str = "All Files (*)",
        initial_dir: str = "",
        initial_files: list[str] | None = None,
        file_summaries: dict[str, tuple[str, str, str, str, str]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(self._DEFAULT_WIDTH, self._DEFAULT_HEIGHT)
        self.setStyleSheet(app_stylesheet())

        self._extensions = {ext.lower() for ext in (extensions or {".p111", ".p190", ".txt", ".nav"})}
        self._file_filter = file_filter
        self._initial_dir = initial_dir
        self._selected_files: list[str] = list(initial_files or [])
        self._folder: str = initial_dir
        self._file_summaries = {
            Path(key).name.lower(): value
            for key, value in (file_summaries or {}).items()
        }

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        hint_lbl = QLabel(hint)
        hint_lbl.setWordWrap(True)
        layout.addWidget(hint_lbl)

        btn_row = QHBoxLayout()
        folder_btn = QPushButton("Browse Folder…")
        files_btn = QPushButton("Add Files…")
        remove_btn = QPushButton("Remove Selected")
        for btn in (folder_btn, files_btn, remove_btn):
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setAutoDefault(False)
        folder_btn.clicked.connect(self._browse_folder)
        files_btn.clicked.connect(self._add_files)
        remove_btn.clicked.connect(self._remove_selected)
        btn_row.addWidget(folder_btn)
        btn_row.addWidget(files_btn)
        btn_row.addWidget(remove_btn)
        layout.addLayout(btn_row)

        self._summary = QLabel("")
        layout.addWidget(self._summary)

        self._table = QTableWidget(0, 6)
        self._table.setObjectName("fileTable")
        self._table.setHorizontalHeaderLabels(
            ["File Name", "Line Name", "Subline", "Line Direction", "FSP", "LSP"]
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        for col in range(self._table.columnCount()):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self._table, stretch=1)

        action_row = QHBoxLayout()
        rescan_btn = QPushButton("Rescan")
        rescan_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        rescan_btn.setAutoDefault(False)
        rescan_btn.clicked.connect(self._rescan)
        ok_btn = QPushButton("OK")
        ok_btn.setObjectName("primaryBtn")
        cancel_btn = QPushButton("Cancel")
        ok_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        cancel_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        action_row.addWidget(rescan_btn)
        action_row.addStretch()
        action_row.addWidget(ok_btn)
        action_row.addWidget(cancel_btn)
        layout.addLayout(action_row)

        self._refresh_table()
        self._fit_to_table_content()

    @property
    def selected_files(self) -> list[str]:
        return list(self._selected_files)

    @property
    def selected_folder(self) -> str:
        return self._folder

    def _collect_from_folder(self, folder: str) -> list[str]:
        root = Path(folder)
        if not root.is_dir():
            return []
        files: list[str] = []
        for path in sorted(root.iterdir()):
            if path.is_file() and path.suffix.lower() in self._extensions:
                files.append(str(path.resolve()))
        return files

    def _summary_for_path(self, file_path: str) -> tuple[str, str, str, str, str]:
        return self._file_summaries.get(Path(file_path).name.lower(), ("", "", "", "", ""))

    def _refresh_table(self) -> None:
        self._table.setRowCount(0)
        for path in self._selected_files:
            row = self._table.rowCount()
            self._table.insertRow(row)
            line_name, subline, line_direction, fsp, lsp = self._summary_for_path(path)
            values = [
                Path(path).name,
                line_name or "-",
                subline or "-",
                line_direction or "-",
                fsp or "-",
                lsp or "-",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, path)
                self._table.setItem(row, col, item)
        self._table.resizeColumnsToContents()
        self._table.resizeRowsToContents()
        count = len(self._selected_files)
        folder_text = self._folder or "(none)"
        self._summary.setText(f"Folder: {folder_text}  —  {count} file(s) selected")
        self._fit_to_table_content()

    def _fit_to_table_content(self) -> None:
        header = self._table.horizontalHeader()
        content_w = self._table.verticalHeader().width() + self._table.frameWidth() * 2
        for col in range(self._table.columnCount()):
            content_w += header.sectionSize(col)
        if self._table.verticalScrollBar().isVisible():
            content_w += self._table.verticalScrollBar().sizeHint().width()
        margins = self.layout().contentsMargins()
        desired_w = content_w + margins.left() + margins.right() + 24
        desired_h = self._DEFAULT_HEIGHT

        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            max_w = int(available.width() * self._MAX_SCREEN_FRACTION)
            max_h = int(available.height() * self._MAX_SCREEN_FRACTION)
            desired_w = min(max(desired_w, self._DEFAULT_WIDTH), max_w)
            desired_h = min(max(desired_h, self._DEFAULT_HEIGHT), max_h)
        else:
            desired_w = max(desired_w, self._DEFAULT_WIDTH)
        self.resize(desired_w, desired_h)

    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Folder",
            self._folder or self._initial_dir or "",
        )
        if not folder:
            return
        self._folder = folder
        self._selected_files = self._collect_from_folder(folder)
        self._refresh_table()

    def _add_files(self) -> None:
        start_dir = self._folder or self._initial_dir or ""
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Files",
            start_dir,
            self._file_filter,
        )
        if not paths:
            return
        existing = set(self._selected_files)
        for path in paths:
            resolved = str(Path(path).resolve())
            if resolved not in existing:
                self._selected_files.append(resolved)
                existing.add(resolved)
        if paths:
            self._folder = str(Path(paths[0]).parent)
        self._refresh_table()

    def _remove_selected(self) -> None:
        selected_rows = {index.row() for index in self._table.selectionModel().selectedRows()}
        if not selected_rows:
            return
        remove_paths = {
            self._table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            for row in selected_rows
            if self._table.item(row, 0) is not None
        }
        self._selected_files = [path for path in self._selected_files if path not in remove_paths]
        self._refresh_table()

    def _rescan(self) -> None:
        """Refresh the file list from disk and notify the host to re-parse."""
        before = len(self._selected_files)
        if self._folder:
            self._selected_files = self._collect_from_folder(self._folder)
        else:
            self._selected_files = [
                path for path in self._selected_files if Path(path).is_file()
            ]
        self._refresh_table()
        after = len(self._selected_files)
        if self._folder:
            note = f"Rescanned folder — {after} file(s)"
        else:
            removed = before - after
            note = f"{after} file(s)"
            if removed:
                note += f" ({removed} removed)"
            else:
                note += " (list unchanged)"
        self._summary.setText(f"Folder: {self._folder or '(none)'}  —  {note}")
        QApplication.processEvents()
        self.accept()

    @classmethod
    def pick(
        cls,
        parent=None,
        *,
        title: str = "Select Files",
        hint: str = "Select a folder or add individual files.",
        extensions: set[str] | None = None,
        file_filter: str = "All Files (*)",
        initial_dir: str = "",
        initial_files: list[str] | None = None,
        file_summaries: dict[str, tuple[str, str, str, str, str]] | None = None,
    ) -> tuple[list[str], str] | None:
        started = time.perf_counter()
        dialog = cls(
            parent,
            title=title,
            hint=hint,
            extensions=extensions,
            file_filter=file_filter,
            initial_dir=initial_dir,
            initial_files=initial_files,
            file_summaries=file_summaries,
        )
        print(
            "[xPostMaps timing] File picker dialog construction: "
            f"{(time.perf_counter() - started) * 1000:.1f} ms"
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.selected_files, dialog.selected_folder
