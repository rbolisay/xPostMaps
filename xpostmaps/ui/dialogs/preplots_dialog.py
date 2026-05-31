"""Preplots management popup."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QPushButton

from xpostmaps.ui.dialogs.base_dialog import SingleInstanceDialog
from xpostmaps.ui.theme import TEXT_SECONDARY


class PreplotsDialog:
    KEY = "preplots"

    @classmethod
    def open(cls, parent, preplots_dir: str, on_directory_changed) -> None:
        def build(dialog: SingleInstanceDialog) -> None:
            layout = dialog.content_layout
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            title = QLabel("Preplots Directory")
            title.setObjectName("sectionTitle")
            layout.addWidget(title)

            path_lbl = QLabel(preplots_dir or "No directory selected")
            path_lbl.setWordWrap(True)
            path_lbl.setStyleSheet(f"color: {TEXT_SECONDARY};")
            layout.addWidget(path_lbl)

            count = 0
            if preplots_dir and Path(preplots_dir).is_dir():
                count = sum(
                    1
                    for p in Path(preplots_dir).rglob("*")
                    if p.is_file() and p.suffix.lower() in (".p111", ".p190", ".txt")
                )
            layout.addWidget(QLabel(f"Files found: {count}"))

            btn_row = QHBoxLayout()
            browse_btn = QPushButton("Browse…")
            clear_btn = QPushButton("Clear")

            def browse() -> None:
                folder = QFileDialog.getExistingDirectory(
                    dialog, "Select Preplots Directory", preplots_dir or ""
                )
                if folder:
                    on_directory_changed(folder)
                    path_lbl.setText(folder)

            browse_btn.clicked.connect(browse)
            clear_btn.clicked.connect(lambda: on_directory_changed(""))
            btn_row.addWidget(browse_btn)
            btn_row.addWidget(clear_btn)
            layout.addLayout(btn_row)
            layout.addStretch()

        SingleInstanceDialog.show_dialog(cls.KEY, "Preplots", build, parent, width=440)
