"""Application entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from xpostmaps.ui.main_window import MainWindow
from xpostmaps.ui.theme import app_stylesheet


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("xPostMaps")
    app.setOrganizationName("xPostMaps")
    app.setStyle("Fusion")
    app.setStyleSheet(app_stylesheet())

    window = MainWindow()
    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
