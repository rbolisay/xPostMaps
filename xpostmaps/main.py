"""Application entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from xpostmaps.core.branding import APP_NAME
from xpostmaps.core.crs_utils import pyproj_available
from xpostmaps.ui.main_window import MainWindow
from xpostmaps.ui.theme import app_stylesheet


def _warn_if_pyproj_missing() -> None:
    """Loudly warn when pyproj is absent.

    Without pyproj, CRS resolution silently degrades to a narrow set of
    hardcoded fallbacks and any cross-CRS reprojection raises at runtime.
    """
    if pyproj_available():
        return
    message = (
        "WARNING: pyproj is not installed. Coordinate reprojection between "
        "different CRS is unavailable and EPSG inference is limited to a small "
        "set of built-in fallbacks. Install it with: pip install pyproj"
    )
    print(message, file=sys.stderr)


def main() -> int:
    _warn_if_pyproj_missing()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setStyle("Fusion")
    app.setStyleSheet(app_stylesheet())

    window = MainWindow()
    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
