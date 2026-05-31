"""Left control panel."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from xpostmaps.ui.glass_widget import GlassPanel


class LeftPanel(GlassPanel):
    project_name_changed = Signal(str)
    browse_project = Signal()
    load_project = Signal()
    save_project = Signal()
    select_preplot_navplan = Signal()
    select_p111_p190_dir = Signal()
    select_logo = Signal()
    open_postmap_info = Signal()
    open_legend = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent, radius=16)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = self.content_layout

        header = QLabel("xPostMaps")
        header.setStyleSheet("font-size: 20px; font-weight: 700; letter-spacing: 0.5px;")
        layout.addWidget(header)

        sub = QLabel("Postplot Navigation Viewer")
        sub.setStyleSheet("color: #8b949e; font-size: 12px; margin-bottom: 4px;")
        layout.addWidget(sub)

        proj_title = QLabel("Project")
        proj_title.setObjectName("sectionTitle")
        layout.addWidget(proj_title)

        self._project_input = QLineEdit()
        self._project_input.setPlaceholderText("Enter project name…")
        self._project_input.textChanged.connect(self.project_name_changed.emit)
        layout.addWidget(self._project_input)

        btn_row = QHBoxLayout()
        self._browse_btn = QPushButton("Browse")
        self._load_btn = QPushButton("Load")
        self._save_btn = QPushButton("Save")
        self._save_btn.setObjectName("primaryBtn")
        for btn in (self._browse_btn, self._load_btn, self._save_btn):
            btn_row.addWidget(btn)
        layout.addLayout(btn_row)

        self._browse_btn.clicked.connect(self.browse_project.emit)
        self._load_btn.clicked.connect(self.load_project.emit)
        self._save_btn.clicked.connect(self.save_project.emit)

        layout.addSpacing(8)

        dirs_title = QLabel("Data Sources")
        dirs_title.setObjectName("sectionTitle")
        layout.addWidget(dirs_title)

        self._preplot_btn = QPushButton("Preplot / Navplan")
        self._preplot_btn.setObjectName("dirBtn")
        self._preplot_path = QLabel("Not set")
        self._preplot_path.setWordWrap(True)
        self._preplot_path.setStyleSheet("color: #8b949e; font-size: 11px;")

        self._p111_btn = QPushButton("P111 / P190 Directory")
        self._p111_btn.setObjectName("dirBtn")
        self._p111_path = QLabel("Not set")
        self._p111_path.setWordWrap(True)
        self._p111_path.setStyleSheet("color: #8b949e; font-size: 11px;")

        for btn, path_lbl in (
            (self._preplot_btn, self._preplot_path),
            (self._p111_btn, self._p111_path),
        ):
            layout.addWidget(btn)
            layout.addWidget(path_lbl)

        self._preplot_btn.clicked.connect(self.select_preplot_navplan.emit)
        self._p111_btn.clicked.connect(self.select_p111_p190_dir.emit)

        layout.addSpacing(8)

        tools_title = QLabel("Tools")
        tools_title.setObjectName("sectionTitle")
        layout.addWidget(tools_title)

        self._logo_btn = QPushButton("Set Logo")
        self._logo_btn.setObjectName("dirBtn")
        layout.addWidget(self._logo_btn)
        self._logo_btn.clicked.connect(self.select_logo.emit)

        self._legend_btn = QPushButton("Legend")
        self._info_btn = QPushButton("Postmap Information")

        for btn in (self._legend_btn, self._info_btn):
            layout.addWidget(btn)

        self._legend_btn.clicked.connect(self.open_legend.emit)
        self._info_btn.clicked.connect(self.open_postmap_info.emit)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setTextVisible(False)
        layout.addWidget(self._progress)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color: #8b949e; font-size: 11px;")
        layout.addWidget(self._status)

        layout.addStretch()

    def set_project_name(self, name: str) -> None:
        self._project_input.blockSignals(True)
        self._project_input.setText(name)
        self._project_input.blockSignals(False)

    def set_p111_p190_dir(self, path: str) -> None:
        self._p111_path.setText(self._short_path(path))

    def set_preplot_navplan(self, path: str) -> None:
        self._preplot_path.setText(self._short_path(path) if path else "Not set")

    def set_status(self, message: str) -> None:
        self._status.setText(message)

    def set_progress(self, value: int, visible: bool = True) -> None:
        self._progress.setVisible(visible)
        self._progress.setValue(value)

    @staticmethod
    def _short_path(path: str) -> str:
        if not path:
            return "Not set"
        p = Path(path)
        return str(p) if len(str(p)) < 48 else f"…{str(p)[-45:]}"
