"""Helpers for sizing dialogs relative to the main map sheet."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QWidget

# Outer dialog margins + title bar (approximate client chrome).
_DIALOG_CHROME_WIDTH = 48
_DIALOG_CHROME_HEIGHT = 88
# Slightly shorter than the map sheet so the bottom Survey Specs pane fits on laptop screens.
_POSTPLOT_4D_HEIGHT_SCALE = 0.76
_SCREEN_HEIGHT_MARGIN = 0.90
_SCREEN_WIDTH_MARGIN = 0.96


def _available_screen_geometry(parent: QWidget | None):
    if parent is not None:
        screen_obj = parent.screen()
        if screen_obj is not None:
            return screen_obj.availableGeometry()
    primary = QApplication.primaryScreen()
    if primary is not None:
        return primary.availableGeometry()
    return None


def map_sheet_dialog_size(parent: QWidget | None) -> tuple[int, int]:
    """Return outer window size matching the host map + right pane area."""
    sheet_w, sheet_h = 1264, 860
    if parent is not None:
        size_fn = getattr(parent, "map_sheet_size", None)
        if callable(size_fn):
            sheet_w, sheet_h = size_fn()
        else:
            map_widget = getattr(parent, "_map", None)
            right_pane = getattr(parent, "_right", None)
            if map_widget is not None and right_pane is not None:
                sheet_w = map_widget.width() + right_pane.width()
                sheet_h = map_widget.height()
    return (
        max(640, sheet_w + _DIALOG_CHROME_WIDTH),
        max(480, sheet_h + _DIALOG_CHROME_HEIGHT),
    )


def postplot_4d_dialog_size(parent: QWidget | None) -> tuple[int, int]:
    """Postplot 4D / 4D Stat Plot window size — map sheet width, reduced height."""
    width, height = map_sheet_dialog_size(parent)
    height = max(480, int(height * _POSTPLOT_4D_HEIGHT_SCALE))
    screen = _available_screen_geometry(parent)
    if screen is not None:
        width = min(width, int(screen.width() * _SCREEN_WIDTH_MARGIN))
        height = min(height, int(screen.height() * _SCREEN_HEIGHT_MARGIN))
    return max(640, width), max(480, height)


def center_widget_on_screen(widget: QWidget) -> None:
    """Move *widget* so its frame is centered and fully on the available screen."""
    screen = _available_screen_geometry(widget)
    if screen is None:
        return
    frame = widget.frameGeometry()
    if frame.height() > screen.height():
        widget.resize(frame.width(), int(screen.height() * _SCREEN_HEIGHT_MARGIN))
        frame = widget.frameGeometry()
    if frame.width() > screen.width():
        widget.resize(int(screen.width() * _SCREEN_WIDTH_MARGIN), frame.height())
        frame = widget.frameGeometry()
    frame.moveCenter(screen.center())
    if frame.bottom() > screen.bottom():
        frame.moveTop(screen.bottom() - frame.height())
    if frame.top() < screen.top():
        frame.moveTop(screen.top())
    widget.move(frame.topLeft())
