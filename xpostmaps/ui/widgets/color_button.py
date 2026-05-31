"""Reusable color picker button with opacity control."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QColorDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
)

from xpostmaps.ui.theme import color_dialog_stylesheet


class ColorPickerDialog(QDialog):
    """Dark-themed color picker with opacity slider below the palette."""

    def __init__(self, color: str, opacity: float, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Choose Color")
        self.setStyleSheet(color_dialog_stylesheet())
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)

        self._color_dialog = QColorDialog(QColor(color), self)
        self._color_dialog.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
        self._color_dialog.setOption(QColorDialog.ColorDialogOption.NoButtons, True)
        self._color_dialog.setStyleSheet(color_dialog_stylesheet())
        layout.addWidget(self._color_dialog)

        opacity_row = QHBoxLayout()
        opacity_lbl = QLabel("Opacity")
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(0, 100)
        self._opacity_slider.setValue(int(max(0.0, min(1.0, opacity)) * 100))
        self._opacity_value = QLabel(f"{self._opacity_slider.value()}%")
        self._opacity_slider.valueChanged.connect(
            lambda value: self._opacity_value.setText(f"{value}%")
        )
        opacity_row.addWidget(opacity_lbl)
        opacity_row.addWidget(self._opacity_slider, stretch=1)
        opacity_row.addWidget(self._opacity_value)
        layout.addLayout(opacity_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._chosen_color = QColor(color)
        self._color_dialog.currentColorChanged.connect(self._on_color_changed)

    def _on_color_changed(self, color: QColor) -> None:
        if color.isValid():
            self._chosen_color = color

    def selected_color(self) -> str:
        return self._chosen_color.name(QColor.NameFormat.HexRgb)

    def selected_opacity(self) -> float:
        return self._opacity_slider.value() / 100.0


class ColorButton(QPushButton):
    color_changed = Signal(str)
    opacity_changed = Signal(float)

    def __init__(
        self,
        color: str = "#3b82f6",
        opacity: float = 1.0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._color = color
        self._opacity = max(0.0, min(1.0, opacity))
        self.setFixedSize(36, 28)
        self.clicked.connect(self._pick_color)
        self._apply_style()

    @property
    def color(self) -> str:
        return self._color

    @property
    def opacity(self) -> float:
        return self._opacity

    def set_color(self, color: str, opacity: float | None = None) -> None:
        self._color = color
        if opacity is not None:
            self._opacity = max(0.0, min(1.0, opacity))
        self._apply_style()

    def _apply_style(self) -> None:
        c = QColor(self._color)
        c.setAlphaF(self._opacity)
        self.setStyleSheet(
            f"background-color: rgba({c.red()}, {c.green()}, {c.blue()}, {c.alpha()});"
            " border: 1px solid rgba(255,255,255,0.3);"
            " border-radius: 6px;"
        )

    def _pick_color(self) -> None:
        dialog = ColorPickerDialog(self._color, self._opacity, self.window())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        chosen = dialog.selected_color()
        if not chosen:
            return
        self._color = chosen
        self._opacity = dialog.selected_opacity()
        self._apply_style()
        self.color_changed.emit(self._color)
        self.opacity_changed.emit(self._opacity)
