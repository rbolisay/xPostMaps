"""Dialog for selecting navigation or preplot file sets."""

from __future__ import annotations

from pathlib import Path

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
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(520, 420)
        self.setStyleSheet(app_stylesheet())

        self._extensions = extensions or {".p111", ".p190", ".txt", ".nav"}
        self._file_filter = file_filter
        self._initial_dir = initial_dir
        self._selected_files: list[str] = list(initial_files or [])
        self._folder: str = initial_dir

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
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        layout.addWidget(self._list, stretch=1)

        action_row = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.setObjectName("primaryBtn")
        cancel_btn = QPushButton("Cancel")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
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
            if path.is_file() and path.suffix in self._extensions:
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
        rows = sorted({item.row() for item in self._list.selectedIndexes()}, reverse=True)
        for row in rows:
            del self._selected_files[row]
        self._refresh_list()

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
    ) -> tuple[list[str], str] | None:
        dialog = cls(
            parent,
            title=title,
            hint=hint,
            extensions=extensions,
            file_filter=file_filter,
            initial_dir=initial_dir,
            initial_files=initial_files,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        if not dialog.selected_files:
            return None
        return dialog.selected_files, dialog.selected_folder
