"""Left control panel."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from xpostmaps.core.branding import APP_LOGO_PATH, APP_SUBTITLE
from xpostmaps.ui.glass_widget import GlassPanel


def _trim_logo_pixmap(path: str) -> QPixmap:
    """Load the transparent logo and trim empty margins."""
    img = QImage(path)
    if img.isNull():
        return QPixmap()
    img = img.convertToFormat(QImage.Format.Format_ARGB32)

    width = img.width()
    height = img.height()
    min_x, min_y, max_x, max_y = width, height, -1, -1
    for y in range(height):
        for x in range(width):
            if img.pixelColor(x, y).alpha() != 0:
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)

    if max_x >= min_x and max_y >= min_y:
        img = img.copy(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)

    return QPixmap.fromImage(img)


class _BrandLogoHeader(QWidget):
    """Full-width brand strip with a darker gradient and centered logo."""

    _LOGO_TARGET_WIDTH = 210
    _VERT_PAD = 12

    def __init__(self, logo_path: str, parent=None) -> None:
        super().__init__(parent)
        self._source = _trim_logo_pixmap(logo_path)
        self._logo = QPixmap()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._sync_logo_size()

    def _sync_logo_size(self) -> None:
        if self._source.isNull():
            self.setFixedHeight(48)
            return
        self._logo = self._source.scaledToWidth(
            self._LOGO_TARGET_WIDTH,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setFixedHeight(self._logo.height() + self._VERT_PAD * 2)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = self.width()
        height = self.height()
        gradient = QLinearGradient(0, 0, width, height)
        gradient.setColorAt(0.0, QColor("#b8c5d4"))
        gradient.setColorAt(0.45, QColor("#8fa3b8"))
        gradient.setColorAt(1.0, QColor("#6b849c"))

        painter.setBrush(QBrush(gradient))
        painter.setPen(QColor(255, 255, 255, 55))
        painter.drawRoundedRect(QRectF(0.5, 0.5, width - 1, height - 1), 10, 10)

        if not self._logo.isNull():
            x = (width - self._logo.width()) // 2
            y = (height - self._logo.height()) // 2
            painter.drawPixmap(x, y, self._logo)

        painter.end()


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
    open_layer_styles = Signal()
    open_pdf_export = Signal()
    open_postplot_4d = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent, radius=16)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = self.content_layout
        layout.setContentsMargins(0, 16, 0, 16)

        header = _BrandLogoHeader(str(APP_LOGO_PATH))
        layout.addWidget(header)

        sub = QLabel(APP_SUBTITLE)
        sub.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        sub.setStyleSheet(
            "color: #8b949e; font-size: 12px; margin: 0 16px 4px 16px;"
        )
        layout.addWidget(sub)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(16, 0, 16, 0)
        body_layout.setSpacing(12)
        layout.addWidget(body, stretch=1)

        proj_title = QLabel("Project")
        proj_title.setObjectName("sectionTitle")
        body_layout.addWidget(proj_title)

        name_row = QHBoxLayout()
        self._project_input = QLineEdit()
        self._project_input.setPlaceholderText("Enter project name…")
        self._project_input.textChanged.connect(self.project_name_changed.emit)
        name_row.addWidget(self._project_input, stretch=1)

        self._save_btn = QPushButton("Save")
        self._save_btn.setObjectName("primaryBtn")
        self._save_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._save_btn.clicked.connect(self.save_project.emit)
        name_row.addWidget(self._save_btn)

        self._browse_load_btn = QPushButton("Browse/Load")
        self._browse_load_btn.clicked.connect(self.browse_load_project.emit)
        name_row.addWidget(self._browse_load_btn)

        body_layout.addLayout(name_row)

        body_layout.addSpacing(8)

        dirs_title = QLabel("Data Sources")
        dirs_title.setObjectName("sectionTitle")
        body_layout.addWidget(dirs_title)

        self._preplot_btn = QPushButton("Preplot")
        self._preplot_btn.setObjectName("dirBtn")
        self._preplot_path = QLabel("Not set")
        self._preplot_path.setWordWrap(True)
        self._preplot_path.setStyleSheet("color: #8b949e; font-size: 11px;")

        self._navplan_btn = QPushButton("Navplan")
        self._navplan_btn.setObjectName("dirBtn")
        self._navplan_path = QLabel("Not set")
        self._navplan_path.setWordWrap(True)
        self._navplan_path.setStyleSheet("color: #8b949e; font-size: 11px;")

        self._p111_btn = QPushButton("P111/P190")
        self._p111_btn.setObjectName("dirBtn")
        self._p111_path = QLabel("Not set")
        self._p111_path.setWordWrap(True)
        self._p111_path.setStyleSheet("color: #8b949e; font-size: 11px;")

        for btn, path_lbl in (
            (self._preplot_btn, self._preplot_path),
            (self._navplan_btn, self._navplan_path),
            (self._p111_btn, self._p111_path),
        ):
            body_layout.addWidget(btn)
            body_layout.addWidget(path_lbl)

        self._preplot_btn.clicked.connect(self.select_preplot_navplan.emit)
        self._navplan_btn.clicked.connect(self.import_navplan.emit)
        self._p111_btn.clicked.connect(self.select_p111_p190_dir.emit)

        self._import_polygons_btn = QPushButton("Polygons")
        self._import_polygons_btn.setObjectName("dirBtn")
        self._import_polygons_path = QLabel("Not set")
        self._import_polygons_path.setWordWrap(True)
        self._import_polygons_path.setStyleSheet("color: #8b949e; font-size: 11px;")
        body_layout.addWidget(self._import_polygons_btn)
        body_layout.addWidget(self._import_polygons_path)
        self._import_polygons_btn.clicked.connect(self.open_import_polygons.emit)

        body_layout.addSpacing(8)

        tools_title = QLabel("Tools")
        tools_title.setObjectName("sectionTitle")
        body_layout.addWidget(tools_title)

        self._logo_btn = QPushButton("Set Logo")
        self._logo_btn.setObjectName("dirBtn")
        body_layout.addWidget(self._logo_btn)
        self._logo_btn.clicked.connect(self.select_logo.emit)

        self._layer_styles_btn = QPushButton("Layer Styles")
        self._layer_styles_btn.setObjectName("dirBtn")
        self._pdf_btn = QPushButton("Export Map")
        self._pdf_btn.setObjectName("dirBtn")
        self._info_btn = QPushButton("Project Information")
        self._info_btn.setObjectName("dirBtn")

        for btn in (self._info_btn, self._layer_styles_btn, self._pdf_btn):
            body_layout.addWidget(btn)

        self._layer_styles_btn.clicked.connect(self.open_layer_styles.emit)
        self._pdf_btn.clicked.connect(self.open_pdf_export.emit)
        self._info_btn.clicked.connect(self.open_postmap_info.emit)

        body_layout.addSpacing(8)

        four_d_title = QLabel("4D Tools")
        four_d_title.setObjectName("sectionTitle")
        body_layout.addWidget(four_d_title)

        self._postplot_4d_btn = QPushButton("Postplot 4D")
        self._postplot_4d_btn.setObjectName("dirBtn")
        body_layout.addWidget(self._postplot_4d_btn)
        self._postplot_4d_btn.clicked.connect(self.open_postplot_4d.emit)

        self._active_buttons = {
            "browse_load": self._browse_load_btn,
            "preplot": self._preplot_btn,
            "navplan": self._navplan_btn,
            "p111": self._p111_btn,
            "import_polygons": self._import_polygons_btn,
            "logo": self._logo_btn,
            "layer_styles": self._layer_styles_btn,
            "pdf": self._pdf_btn,
            "info": self._info_btn,
            "postplot_4d": self._postplot_4d_btn,
        }
        for button in (self._save_btn, *self._active_buttons.values()):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setTextVisible(False)
        body_layout.addWidget(self._progress)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color: #8b949e; font-size: 11px;")
        body_layout.addWidget(self._status)

        body_layout.addStretch()

        tips = QLabel(
            "Hold Right Click to Pan on Main Map and Mini Map\n"
            "Double right click on Main Map and Mini Map to Zoom Extent\n"
            "Use Mouse Scroll to Zoom In/Out"
        )
        tips.setWordWrap(True)
        tips.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        tips.setStyleSheet("color: #6e7681; font-size: 10px; padding-top: 8px;")
        body_layout.addWidget(tips)

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

    def set_button_active(self, key: str, active: bool) -> None:
        button = self._active_buttons.get(key)
        if button is None:
            return
        button.setProperty("active", active)
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def set_preplot_dependent_controls_enabled(self, enabled: bool) -> None:
        """Enable nav/tools only after preplot/navplan files are loaded."""
        for widget in (
            self._navplan_btn,
            self._p111_btn,
            self._import_polygons_btn,
            self._logo_btn,
            self._layer_styles_btn,
            self._pdf_btn,
            self._info_btn,
            self._postplot_4d_btn,
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
