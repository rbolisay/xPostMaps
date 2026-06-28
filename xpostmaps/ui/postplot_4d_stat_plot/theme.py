"""Dark-theme styling for the 4D Stat Plot view (plot canvas stays white)."""

from __future__ import annotations

STAT_PLOT_TAB_STYLE = """
QTabWidget::pane {
    border: 1px solid #3b4a5f;
    border-radius: 6px;
    background: #161b22;
    top: -1px;
}
QTabBar::tab {
    background: #263244;
    color: #8b949e;
    padding: 8px 18px;
    margin-right: 3px;
    border: 1px solid #3b4a5f;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    min-width: 72px;
}
QTabBar::tab:selected {
    background: #2563eb;
    color: #ffffff;
    font-weight: 600;
    border-color: #58a6ff;
}
QTabBar::tab:hover:!selected {
    background: #1e293b;
    color: #e6edf3;
}
QTabBar::tab:disabled {
    color: #484f58;
    background: #1a1f27;
}
"""

STAT_PLOT_SOURCE_TAB_STYLE = """
QTabWidget::pane {
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    background: #ffffff;
    top: -1px;
}
QTabBar::tab {
    background: #e2e8f0;
    color: #475569;
    padding: 4px 12px;
    margin-right: 2px;
    border: 1px solid #cbd5e1;
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    min-width: 48px;
    font-size: 11px;
}
QTabBar::tab:selected {
    background: #ffffff;
    color: #1e293b;
    font-weight: 600;
    border-color: #94a3b8;
}
QTabBar::tab:hover:!selected {
    background: #f1f5f9;
    color: #334155;
}
"""

STAT_PLOT_VIEW_STYLE = """
QWidget#statPlotRoot {
    background: transparent;
}
QScrollArea {
    background: #0d1117;
    border: none;
}
QScrollArea > QWidget > QWidget {
    background: #0d1117;
}
QLabel#statPlotSection {
    color: #8b949e;
    font-size: 12px;
    font-weight: 600;
}
QWidget#statPlotWhiteFrame {
    background: #ffffff;
    border: 1px solid #3b4a5f;
    border-radius: 4px;
}
"""
