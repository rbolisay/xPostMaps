"""Dialog for selecting navigation or preplot file sets."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
)

from xpostmaps.ui.theme import app_stylesheet


class NavFilePickerDialog(QDialog):
    """Modal picker: browse folder or add multiple files."""

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
        on_rescan: Callable[[list[str], str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(520, 420)
        self.setStyleSheet(app_stylesheet())

        self._extensions = {ext.lower() for ext in (extensions or {".p111", ".p190", ".txt", ".nav"})}
        self._file_filter = file_filter
        self._initial_dir = initial_dir
        self._selected_files: list[str] = list(initial_files or [])
        self._folder: str = initial_dir
        self._on_rescan = on_rescan

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

        self._list = QListWidget()
        self._list.setObjectName("fileList")
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._list.setAlternatingRowColors(True)
        layout.addWidget(self._list, stretch=1)

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

        self._refresh_list()

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
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix.lower() in self._extensions:
                files.append(str(path.resolve()))
        return files

    def _refresh_list(self) -> None:
        self._list.clear()
        for path in self._selected_files:
            self._list.addItem(path)
        count = len(self._selected_files)
        folder_text = self._folder or "(none)"
        self._summary.setText(f"Folder: {folder_text}  —  {count} file(s) selected")

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
        self._refresh_list()

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
        self._refresh_list()

    def _remove_selected(self) -> None:
        selected = self._list.selectedItems()
        if not selected:
            return
        remove_paths = {item.text() for item in selected}
        self._selected_files = [path for path in self._selected_files if path not in remove_paths]
        self._refresh_list()

    def _rescan(self) -> None:
        """Refresh the file list from disk and notify the host to re-parse."""
        before = len(self._selected_files)
        if self._folder:
            self._selected_files = self._collect_from_folder(self._folder)
        else:
            self._selected_files = [
                path for path in self._selected_files if Path(path).is_file()
            ]
        self._refresh_list()
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
        if self._on_rescan:
            self._on_rescan(self._selected_files, self._folder)

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
        on_rescan: Callable[[list[str], str], None] | None = None,
    ) -> tuple[list[str], str] | None:
        dialog = cls(
            parent,
            title=title,
            hint=hint,
            extensions=extensions,
            file_filter=file_filter,
            initial_dir=initial_dir,
            initial_files=initial_files,
            on_rescan=on_rescan,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.selected_files, dialog.selected_folder
