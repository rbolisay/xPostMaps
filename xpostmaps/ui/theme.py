"""Dark theme palette and stylesheet helpers."""

from __future__ import annotations

# Color palette
BG_DARK = "#0d1117"
BG_MAP = "#121a24"
GLASS_BG = "rgba(22, 30, 42, 0.72)"
GLASS_BORDER = "rgba(255, 255, 255, 0.12)"
ACCENT = "#3b82f6"
ACCENT_HOVER = "#2563eb"
TEXT_PRIMARY = "#e6edf3"
TEXT_SECONDARY = "#8b949e"
UP_LINE = "#ef4444"
DOWN_LINE = "#3b82f6"
SURVEY_BOUNDARY = "#22c55e"
OVERLAY_LINE = "#a855f7"
PREPLOT_LINE = "#f59e0b"
GRID_COLOR = (80, 90, 110, 80)

# Print / postplot sheet theme (map + right pane — PDF output)
BG_PRINT = "#ffffff"
BG_MAP_PRINT = "#c8dce8"
TEXT_PRINT = "#000000"
TEXT_PRINT_SECONDARY = "#444444"
BORDER_PRINT = "#999999"
MINIMAP_OCEAN = "#d4e8f2"
MINIMAP_LAND = "#c8d3a6"
MINIMAP_COAST = "#6b5344"
GRID_PRINT_ALPHA = 0.45


def app_stylesheet() -> str:
    return f"""
    QMainWindow, QDialog {{
        background-color: {BG_DARK};
        color: {TEXT_PRIMARY};
    }}
    QWidget {{
        color: {TEXT_PRIMARY};
        font-family: "Segoe UI", "Inter", sans-serif;
        font-size: 13px;
    }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: rgba(255, 255, 255, 0.06);
        border: 1px solid {GLASS_BORDER};
        border-radius: 8px;
        padding: 8px 12px;
        color: {TEXT_PRIMARY};
        selection-background-color: {ACCENT};
    }}
    QLineEdit#projectInfoLineEdit {{
        font-size: 12px;
        padding: 7px 11px;
    }}
    QComboBox:focus {{
        border: 1px solid {ACCENT};
    }}
    QComboBox QAbstractItemView {{
        background-color: #1e293b;
        color: {TEXT_PRIMARY};
        border: 1px solid {GLASS_BORDER};
        selection-background-color: {ACCENT};
        selection-color: {TEXT_PRIMARY};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 20px;
    }}
    QTableWidget QLineEdit {{
        background: #1e293b;
        color: {TEXT_PRIMARY};
        border: 1px solid {GLASS_BORDER};
        padding: 4px 6px;
    }}
    QTableWidget QComboBox {{
        background: #1e293b;
        color: {TEXT_PRIMARY};
        border: 1px solid {GLASS_BORDER};
        padding: 4px 6px;
        min-height: 24px;
    }}
    QTableWidget QLineEdit {{
        background: #1e293b;
        color: {TEXT_PRIMARY};
        border: 1px solid {GLASS_BORDER};
        border-radius: 6px;
        padding: 4px 8px;
        min-height: 24px;
        font-size: 12px;
    }}
    QPushButton#tableCellBtn {{
        background: rgba(59, 130, 246, 0.18);
        border: 1px solid rgba(59, 130, 246, 0.45);
        border-radius: 6px;
        padding: 4px 10px;
        color: {TEXT_PRIMARY};
        font-size: 11px;
        font-weight: 500;
        min-height: 26px;
    }}
    QPushButton#tableCellBtn:hover {{
        background: rgba(59, 130, 246, 0.32);
        border-color: {ACCENT};
    }}
    QPushButton#tableCellBtn:disabled {{
        color: {TEXT_SECONDARY};
        background: rgba(255, 255, 255, 0.04);
        border-color: {GLASS_BORDER};
    }}
    QPushButton {{
        background: rgba(59, 130, 246, 0.18);
        border: 1px solid rgba(59, 130, 246, 0.45);
        border-radius: 8px;
        padding: 9px 14px;
        color: {TEXT_PRIMARY};
        font-weight: 500;
        outline: none;
    }}
    QPushButton:hover {{
        background: rgba(59, 130, 246, 0.32);
        border-color: {ACCENT};
    }}
    QPushButton:pressed {{
        background: rgba(37, 99, 235, 0.45);
    }}
    QPushButton:focus {{
        outline: none;
    }}
    QPushButton[active="true"] {{
        background: rgba(59, 130, 246, 0.55);
        border: 1px solid rgba(147, 197, 253, 0.95);
        color: #ffffff;
    }}
    QPushButton[active="true"]:hover {{
        background: rgba(59, 130, 246, 0.68);
        border-color: #bfdbfe;
    }}
    QPushButton:disabled {{
        color: #6b7280;
        background: rgba(255, 255, 255, 0.04);
        border: 1px solid rgba(255, 255, 255, 0.06);
    }}
    QPushButton#primaryBtn {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {ACCENT}, stop:1 #6366f1);
        border: 1px solid rgba(147, 197, 253, 0.7);
        font-weight: 600;
    }}
    QPushButton#primaryBtn:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {ACCENT_HOVER}, stop:1 #4f46e5);
        border: 1px solid #bfdbfe;
    }}
    QPushButton#primaryBtn:pressed {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 #1d4ed8, stop:1 #4338ca);
        border: 1px solid #dbeafe;
        padding-top: 10px;
        padding-bottom: 8px;
    }}
    QPushButton#dirBtn {{
        text-align: center;
    }}
    QLabel#sectionTitle {{
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 1px;
        color: {TEXT_SECONDARY};
        text-transform: uppercase;
    }}
    QProgressBar {{
        background: rgba(255, 255, 255, 0.06);
        border: none;
        border-radius: 4px;
        height: 6px;
        text-align: center;
    }}
    QProgressBar::chunk {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {ACCENT}, stop:1 #818cf8);
        border-radius: 4px;
    }}
    QTableWidget {{
        background: #1e293b;
        border: 1px solid {GLASS_BORDER};
        border-radius: 8px;
        gridline-color: rgba(255,255,255,0.06);
        alternate-background-color: rgba(255, 255, 255, 0.03);
    }}
    QTableWidget::item {{
        background-color: #1e293b;
        color: {TEXT_PRIMARY};
        padding: 4px 8px;
    }}
    QTableWidget::item:alternate {{
        background-color: rgba(255, 255, 255, 0.03);
    }}
    QTableWidget::item:selected {{
        background-color: {ACCENT};
        color: {TEXT_PRIMARY};
    }}
    QHeaderView::section {{
        background-color: #1e293b;
        color: {TEXT_PRIMARY};
        border: 1px solid {GLASS_BORDER};
        padding: 6px 8px;
        font-weight: 600;
    }}
    QTableWidget QHeaderView::section {{
        background-color: #1e293b;
        color: {TEXT_PRIMARY};
    }}
    QListWidget {{
        background-color: #1e293b;
        color: {TEXT_PRIMARY};
        border: 1px solid {GLASS_BORDER};
        border-radius: 8px;
        padding: 4px;
        outline: none;
    }}
    QListWidget::item {{
        padding: 6px 8px;
        border-radius: 4px;
        color: {TEXT_PRIMARY};
    }}
    QListWidget::item:selected {{
        background-color: {ACCENT};
        color: {TEXT_PRIMARY};
    }}
    QListWidget::item:hover:!selected {{
        background: rgba(59, 130, 246, 0.18);
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 8px;
    }}
    QScrollBar::handle:horizontal {{
        background: rgba(255,255,255,0.15);
        border-radius: 4px;
        min-width: 24px;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
    }}
    QScrollBar::handle:vertical {{
        background: rgba(255,255,255,0.15);
        border-radius: 4px;
        min-height: 24px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        background: none;
        border: none;
        width: 0;
        height: 0;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: none;
    }}
    QListWidget#fileList {{
        alternate-background-color: rgba(255, 255, 255, 0.03);
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border-radius: 4px;
        border: 1px solid {GLASS_BORDER};
        background: rgba(255,255,255,0.05);
    }}
    QCheckBox::indicator:checked {{
        background: {ACCENT};
        border-color: {ACCENT};
    }}
    QStatusBar {{
        background: rgba(0,0,0,0.35);
        color: {TEXT_SECONDARY};
        border-top: 1px solid {GLASS_BORDER};
    }}
    QMenu {{
        background-color: #1e293b;
        color: {TEXT_PRIMARY};
        border: 1px solid {GLASS_BORDER};
        padding: 4px 0;
    }}
    QMenu::item {{
        padding: 8px 28px;
        background-color: transparent;
    }}
    QMenu::item:selected {{
        background-color: {ACCENT};
        color: {TEXT_PRIMARY};
    }}
    QMenu::separator {{
        height: 1px;
        background: {GLASS_BORDER};
        margin: 4px 10px;
    }}
    QHeaderView {{
        background-color: #1e293b;
    }}
    QTableCornerButton::section {{
        background-color: #1e293b;
        border: 1px solid {GLASS_BORDER};
    }}
    """


def color_dialog_stylesheet() -> str:
    """Dark theme for QColorDialog (non-native)."""
    return f"""
    QColorDialog {{
        background-color: {BG_DARK};
        color: {TEXT_PRIMARY};
    }}
    QColorDialog QWidget {{
        background-color: {BG_DARK};
        color: {TEXT_PRIMARY};
    }}
    QColorDialog QLabel {{
        background-color: transparent;
        color: {TEXT_PRIMARY};
    }}
    QColorDialog QLineEdit {{
        background: rgba(255, 255, 255, 0.06);
        border: 1px solid {GLASS_BORDER};
        border-radius: 6px;
        padding: 4px 8px;
        color: {TEXT_PRIMARY};
    }}
    QColorDialog QPushButton {{
        background: rgba(59, 130, 246, 0.18);
        border: 1px solid rgba(59, 130, 246, 0.45);
        border-radius: 6px;
        padding: 6px 12px;
        color: {TEXT_PRIMARY};
    }}
    QColorDialog QPushButton:hover {{
        background: rgba(59, 130, 246, 0.32);
    }}
    QColorDialog QDialogButtonBox QPushButton {{
        min-width: 72px;
    }}
    """


def file_dialog_stylesheet() -> str:
    """Dark theme for non-native QFileDialog (folder/file pickers)."""
    return f"""
    QFileDialog {{
        background-color: {BG_DARK};
        color: {TEXT_PRIMARY};
    }}
    QFileDialog QWidget {{
        background-color: {BG_DARK};
        color: {TEXT_PRIMARY};
    }}
    QFileDialog QLabel {{
        background-color: transparent;
        color: {TEXT_PRIMARY};
    }}
    QFileDialog QLineEdit {{
        background: rgba(255, 255, 255, 0.06);
        border: 1px solid {GLASS_BORDER};
        border-radius: 6px;
        padding: 6px 10px;
        color: {TEXT_PRIMARY};
        selection-background-color: {ACCENT};
    }}
    QFileDialog QComboBox {{
        background: rgba(255, 255, 255, 0.06);
        border: 1px solid {GLASS_BORDER};
        border-radius: 6px;
        padding: 4px 8px;
        color: {TEXT_PRIMARY};
    }}
    QFileDialog QComboBox QAbstractItemView {{
        background-color: #1e293b;
        color: {TEXT_PRIMARY};
        border: 1px solid {GLASS_BORDER};
        selection-background-color: {ACCENT};
    }}
    QFileDialog QTreeView,
    QFileDialog QListView,
    QFileDialog QTableView {{
        background-color: #1e293b;
        color: {TEXT_PRIMARY};
        border: 1px solid {GLASS_BORDER};
        border-radius: 6px;
        alternate-background-color: rgba(255, 255, 255, 0.03);
        selection-background-color: {ACCENT};
        selection-color: {TEXT_PRIMARY};
        outline: none;
    }}
    QFileDialog QTreeView::item,
    QFileDialog QListView::item {{
        padding: 4px 6px;
        color: {TEXT_PRIMARY};
    }}
    QFileDialog QTreeView::item:hover,
    QFileDialog QListView::item:hover {{
        background: rgba(59, 130, 246, 0.18);
    }}
    QFileDialog QTreeView::item:selected,
    QFileDialog QListView::item:selected {{
        background-color: {ACCENT};
        color: {TEXT_PRIMARY};
    }}
    QFileDialog QHeaderView::section {{
        background-color: #161b22;
        color: {TEXT_PRIMARY};
        border: 1px solid {GLASS_BORDER};
        padding: 4px 8px;
    }}
    QFileDialog QPushButton {{
        background: rgba(59, 130, 246, 0.18);
        border: 1px solid rgba(59, 130, 246, 0.45);
        border-radius: 6px;
        padding: 6px 12px;
        color: {TEXT_PRIMARY};
    }}
    QFileDialog QPushButton:hover {{
        background: rgba(59, 130, 246, 0.32);
        border-color: {ACCENT};
    }}
    QFileDialog QToolButton {{
        background: transparent;
        color: {TEXT_PRIMARY};
        border: none;
        padding: 4px;
    }}
    QFileDialog QToolButton:hover {{
        background: rgba(59, 130, 246, 0.18);
        border-radius: 4px;
    }}
    QFileDialog QSplitter::handle {{
        background: {GLASS_BORDER};
    }}
    """


def apply_file_dialog_theme(dialog) -> None:
    """Apply dark styling to a non-native QFileDialog."""
    dialog.setStyleSheet(app_stylesheet() + file_dialog_stylesheet())


def _enable_file_dialog_multi_select(picker) -> None:
    """Ensure non-native QFileDialog list/tree views allow multi-select."""
    from PySide6.QtWidgets import QAbstractItemView, QListView, QTreeView

    for view in picker.findChildren(QTreeView):
        view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    for view in picker.findChildren(QListView):
        view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)


def _selected_files_from_picker(picker) -> list[str]:
    """Return all chosen files from a themed multi-select picker."""
    from pathlib import Path

    from PySide6.QtWidgets import QListView, QTreeView

    files = [path for path in picker.selectedFiles() if path]
    if len(files) > 1:
        return files

    directory = picker.directory().absolutePath()
    collected: list[str] = []
    seen: set[str] = set()
    for view in (*picker.findChildren(QTreeView), *picker.findChildren(QListView)):
        if view.isHidden():
            continue
        model = view.model()
        selection = view.selectionModel()
        if model is None or selection is None:
            continue
        for index in selection.selectedIndexes():
            if index.column() != 0:
                continue
            name = index.data()
            if not name or name in (".", ".."):
                continue
            candidate = Path(directory) / str(name)
            try:
                resolved = str(candidate.resolve())
            except OSError:
                resolved = str(candidate)
            if not candidate.is_file() or resolved in seen:
                continue
            seen.add(resolved)
            collected.append(resolved)
    return collected if collected else files


def apply_menu_theme(menu) -> None:
    """Apply dark styling to a popup menu."""
    menu.setStyleSheet(app_stylesheet())


def themed_open_file(
    parent,
    title: str,
    start_dir: str = "",
    file_filter: str = "",
) -> str:
    """Show a dark-themed single-file picker."""
    from PySide6.QtWidgets import QFileDialog

    picker = QFileDialog(parent, title, start_dir)
    picker.setFileMode(QFileDialog.FileMode.ExistingFile)
    if file_filter:
        picker.setNameFilter(file_filter)
    picker.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    apply_file_dialog_theme(picker)
    if picker.exec() != QFileDialog.DialogCode.Accepted:
        return ""
    selected = picker.selectedFiles()
    return selected[0] if selected else ""


def themed_open_files(
    parent,
    title: str,
    file_filter: str,
    start_dir: str = "",
) -> list[str]:
    """Show a dark-themed multi-file picker."""
    from PySide6.QtWidgets import QFileDialog

    picker = QFileDialog(parent, title, start_dir)
    picker.setFileMode(QFileDialog.FileMode.ExistingFiles)
    picker.setNameFilter(file_filter)
    picker.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    apply_file_dialog_theme(picker)
    _enable_file_dialog_multi_select(picker)
    if picker.exec() != QFileDialog.DialogCode.Accepted:
        return []
    return _selected_files_from_picker(picker)


def themed_open_directory(parent, title: str, start_dir: str = "") -> str:
    """Show a dark-themed folder picker."""
    from PySide6.QtWidgets import QFileDialog

    picker = QFileDialog(parent, title, start_dir)
    picker.setFileMode(QFileDialog.FileMode.Directory)
    picker.setOption(QFileDialog.Option.ShowDirsOnly, True)
    picker.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    picker.setLabelText(QFileDialog.DialogLabel.Accept, "Choose")
    apply_file_dialog_theme(picker)
    if picker.exec() != QFileDialog.DialogCode.Accepted:
        return ""
    selected = picker.selectedFiles()
    return selected[0] if selected else ""
