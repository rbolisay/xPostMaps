"""Helpers for sizing dialogs relative to the main map sheet."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

# Outer dialog margins + title bar (approximate client chrome).
_DIALOG_CHROME_WIDTH = 48
_DIALOG_CHROME_HEIGHT = 88
_POSTPLOT_4D_HEIGHT_SCALE = 0.85


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
    """Postplot 4D / 4D Stat Plot window size — map sheet width, 15% shorter height."""
    width, height = map_sheet_dialog_size(parent)
    return width, max(480, int(height * _POSTPLOT_4D_HEIGHT_SCALE))
