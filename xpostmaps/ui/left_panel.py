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

from xpostmaps.core.branding import APP_NAME, APP_SUBTITLE
from xpostmaps.ui.glass_widget import GlassPanel


class LeftPanel(GlassPanel):
    project_name_changed = Signal(str)
    browse_load_project = Signal()
    save_project = Signal()
    select_preplot_navplan = Signal()
    import_navplan = Signal()
    select_p111_p190_dir = Signal()
    open_import_polygons = Signal()
    select_logo = Signal()
    open_postmap_info = Signal()
    open_legend = Signal()
    open_pdf_export = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent, radius=16)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = self.content_layout

        header = QLabel(APP_NAME)
        header.setStyleSheet("font-size: 20px; font-weight: 700; letter-spacing: 0.5px;")
        layout.addWidget(header)

        sub = QLabel(APP_SUBTITLE)
        sub.setStyleSheet("color: #8b949e; font-size: 12px; margin-bottom: 4px;")
        layout.addWidget(sub)

        proj_title = QLabel("Project")
        proj_title.setObjectName("sectionTitle")
        layout.addWidget(proj_title)

        name_row = QHBoxLayout()
        self._project_input = QLineEdit()
        self._project_input.setPlaceholderText("Enter project name…")
        self._project_input.textChanged.connect(self.project_name_changed.emit)
        name_row.addWidget(self._project_input, stretch=1)

        self._save_btn = QPushButton("Save")
        self._save_btn.setObjectName("primaryBtn")
        self._save_btn.clicked.connect(self.save_project.emit)
        name_row.addWidget(self._save_btn)

        self._browse_load_btn = QPushButton("Browse/Load")
        self._browse_load_btn.clicked.connect(self.browse_load_project.emit)
        name_row.addWidget(self._browse_load_btn)

        layout.addLayout(name_row)

        layout.addSpacing(8)

        dirs_title = QLabel("Data Sources")
        dirs_title.setObjectName("sectionTitle")
        layout.addWidget(dirs_title)

        self._preplot_btn = QPushButton("Import Preplot")
        self._preplot_btn.setObjectName("dirBtn")
        self._preplot_path = QLabel("Not set")
        self._preplot_path.setWordWrap(True)
        self._preplot_path.setStyleSheet("color: #8b949e; font-size: 11px;")

        self._navplan_btn = QPushButton("Import Navplan")
        self._navplan_btn.setObjectName("dirBtn")
        self._navplan_path = QLabel("Not set")
        self._navplan_path.setWordWrap(True)
        self._navplan_path.setStyleSheet("color: #8b949e; font-size: 11px;")

        self._p111_btn = QPushButton("Import P111/P190")
        self._p111_btn.setObjectName("dirBtn")
        self._p111_path = QLabel("Not set")
        self._p111_path.setWordWrap(True)
        self._p111_path.setStyleSheet("color: #8b949e; font-size: 11px;")

        for btn, path_lbl in (
            (self._preplot_btn, self._preplot_path),
            (self._navplan_btn, self._navplan_path),
            (self._p111_btn, self._p111_path),
        ):
            layout.addWidget(btn)
            layout.addWidget(path_lbl)

        self._preplot_btn.clicked.connect(self.select_preplot_navplan.emit)
        self._navplan_btn.clicked.connect(self.import_navplan.emit)
        self._p111_btn.clicked.connect(self.select_p111_p190_dir.emit)

        self._import_polygons_btn = QPushButton("Import Polygons")
        self._import_polygons_btn.setObjectName("dirBtn")
        self._import_polygons_path = QLabel("Not set")
        self._import_polygons_path.setWordWrap(True)
        self._import_polygons_path.setStyleSheet("color: #8b949e; font-size: 11px;")
        layout.addWidget(self._import_polygons_btn)
        layout.addWidget(self._import_polygons_path)
        self._import_polygons_btn.clicked.connect(self.open_import_polygons.emit)

        layout.addSpacing(8)

        tools_title = QLabel("Tools")
        tools_title.setObjectName("sectionTitle")
        layout.addWidget(tools_title)

        self._logo_btn = QPushButton("Set Logo")
        self._logo_btn.setObjectName("dirBtn")
        layout.addWidget(self._logo_btn)
        self._logo_btn.clicked.connect(self.select_logo.emit)

        self._legend_btn = QPushButton("Legend")
        self._legend_btn.setObjectName("dirBtn")
        self._pdf_btn = QPushButton("Export to PDF")
        self._pdf_btn.setObjectName("dirBtn")
        self._info_btn = QPushButton("Project Information")
        self._info_btn.setObjectName("dirBtn")

        for btn in (self._info_btn, self._legend_btn, self._pdf_btn):
            layout.addWidget(btn)

        self._legend_btn.clicked.connect(self.open_legend.emit)
        self._pdf_btn.clicked.connect(self.open_pdf_export.emit)
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

    def project_name(self) -> str:
        return self._project_input.text().strip()

    def set_p111_p190_dir(self, path: str) -> None:
        self._p111_path.setText(self._short_path(path))

    def set_preplot_navplan(self, path: str) -> None:
        self._preplot_path.setText(self._short_path(path) if path else "Not set")

    def set_navplan(self, path: str) -> None:
        self._navplan_path.setText(self._short_path(path) if path else "Not set")

    def set_import_polygons(self, summary: str) -> None:
        self._import_polygons_path.setText(summary if summary else "Not set")

    def set_preplot_dependent_controls_enabled(self, enabled: bool) -> None:
        """Enable nav/tools only after preplot/navplan files are loaded."""
        for widget in (
            self._navplan_btn,
            self._p111_btn,
            self._import_polygons_btn,
            self._logo_btn,
            self._legend_btn,
            self._pdf_btn,
            self._info_btn,
        ):
            widget.setEnabled(enabled)

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
