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
    QPushButton {{
        background: rgba(59, 130, 246, 0.18);
        border: 1px solid rgba(59, 130, 246, 0.45);
        border-radius: 8px;
        padding: 9px 14px;
        color: {TEXT_PRIMARY};
        font-weight: 500;
    }}
    QPushButton:hover {{
        background: rgba(59, 130, 246, 0.32);
        border-color: {ACCENT};
    }}
    QPushButton:pressed {{
        background: rgba(37, 99, 235, 0.45);
    }}
    QPushButton#primaryBtn {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {ACCENT}, stop:1 #6366f1);
        border: none;
        font-weight: 600;
    }}
    QPushButton#primaryBtn:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {ACCENT_HOVER}, stop:1 #4f46e5);
    }}
    QPushButton#dirBtn {{
        text-align: left;
        padding-left: 14px;
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
        background: transparent;
        border: 1px solid {GLASS_BORDER};
        border-radius: 8px;
        gridline-color: rgba(255,255,255,0.06);
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
    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
    }}
    QScrollBar::handle:vertical {{
        background: rgba(255,255,255,0.15);
        border-radius: 4px;
        min-height: 24px;
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
