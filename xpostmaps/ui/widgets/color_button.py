"""Reusable color picker button with opacity control."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from collections.abc import Callable

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QColorDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QWidget,
)

from xpostmaps.ui.theme import color_dialog_stylesheet


def pick_color_with_opacity(
    color: str,
    opacity: float,
    metric_label: str,
    metric_value: float,
    metric_min: int,
    metric_max: int,
    parent=None,
) -> tuple[str, float, float] | None:
    """Show the standard color palette with opacity and size sliders."""
    initial = QColor(color)
    initial.setAlphaF(max(0.0, min(1.0, opacity)))

    dialog = QColorDialog(initial, parent)
    dialog.setWindowTitle("Choose Color")
    dialog.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
    dialog.setOption(QColorDialog.ColorDialogOption.NoButtons, True)
    dialog.setStyleSheet(color_dialog_stylesheet())

    opacity_row = QWidget()
    opacity_layout = QHBoxLayout(opacity_row)
    opacity_layout.setContentsMargins(8, 4, 8, 4)
    opacity_lbl = QLabel("Opacity")
    opacity_slider = QSlider(Qt.Orientation.Horizontal)
    opacity_slider.setRange(0, 100)
    opacity_slider.setValue(int(max(0.0, min(1.0, opacity)) * 100))
    opacity_value = QLabel(f"{opacity_slider.value()}%")
    opacity_slider.valueChanged.connect(
        lambda value: opacity_value.setText(f"{value}%")
    )
    opacity_layout.addWidget(opacity_lbl)
    opacity_layout.addWidget(opacity_slider, stretch=1)
    opacity_layout.addWidget(opacity_value)

    metric_row = QWidget()
    metric_layout = QHBoxLayout(metric_row)
    metric_layout.setContentsMargins(8, 4, 8, 4)
    metric_lbl = QLabel(metric_label)
    metric_slider = QSlider(Qt.Orientation.Horizontal)
    metric_slider.setRange(metric_min, metric_max)
    metric_slider.setSingleStep(1)
    metric_slider.setPageStep(1)
    metric_slider.setValue(int(max(metric_min, min(metric_max, round(metric_value)))))
    metric_value_lbl = QLabel(f"{metric_slider.value()} px")
    metric_slider.valueChanged.connect(
        lambda value: metric_value_lbl.setText(f"{value} px")
    )
    metric_layout.addWidget(metric_lbl)
    metric_layout.addWidget(metric_slider, stretch=1)
    metric_layout.addWidget(metric_value_lbl)

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)

    dialog.layout().addWidget(opacity_row)
    dialog.layout().addWidget(metric_row)
    dialog.layout().addWidget(buttons)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None

    chosen = dialog.selectedColor()
    if not chosen.isValid():
        return None
    return (
        chosen.name(QColor.NameFormat.HexRgb),
        opacity_slider.value() / 100.0,
        float(metric_slider.value()),
    )


class ColorButton(QPushButton):
    color_changed = Signal(str)
    opacity_changed = Signal(float)
    metric_changed = Signal(float)

    def __init__(
        self,
        color: str = "#3b82f6",
        opacity: float = 1.0,
        metric_value: float = 1.0,
        metric_provider: Callable[[], tuple[str, int, int]] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._color = color
        self._opacity = max(0.0, min(1.0, opacity))
        self._metric_value = max(1.0, float(metric_value))
        self._metric_provider = metric_provider or (lambda: ("Line thickness", 1, 10))
        self.setFixedSize(36, 28)
        self.clicked.connect(self._pick_color)
        self._apply_style()

    @property
    def color(self) -> str:
        return self._color

    @property
    def opacity(self) -> float:
        return self._opacity

    @property
    def metric_value(self) -> float:
        return self._metric_value

    def set_color(
        self,
        color: str,
        opacity: float | None = None,
        metric_value: float | None = None,
    ) -> None:
        self._color = color
        if opacity is not None:
            self._opacity = max(0.0, min(1.0, opacity))
        if metric_value is not None:
            self._metric_value = max(1.0, float(metric_value))
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
        label, minimum, maximum = self._metric_provider()
        result = pick_color_with_opacity(
            self._color,
            self._opacity,
            label,
            self._metric_value,
            minimum,
            maximum,
            self.window(),
        )
        if result is None:
            return
        chosen, opacity, metric_value = result
        self._color = chosen
        self._opacity = opacity
        self._metric_value = metric_value
        self._apply_style()
        self.color_changed.emit(self._color)
        self.opacity_changed.emit(self._opacity)
        self.metric_changed.emit(self._metric_value)
