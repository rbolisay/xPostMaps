"""Editable plot title field for survey aerial / histogram tabs."""

from __future__ import annotations

from PySide6.QtWidgets import QLineEdit


class SurveyPlotTitleEdit(QLineEdit):
    """Single-line editable plot title; resets to a new default on survey reload."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._default_text = ""
        self.setStyleSheet(
            "QLineEdit {"
            "  font-weight: 600;"
            "  color: #e6edf3;"
            "  font-size: 11px;"
            "  padding-left: 4px;"
            "  border: 1px solid transparent;"
            "  background: transparent;"
            "}"
            "QLineEdit:hover {"
            "  border-color: #30363d;"
            "  background: #161b22;"
            "}"
            "QLineEdit:focus {"
            "  border-color: #58a6ff;"
            "  background: #161b22;"
            "}"
        )
        self.setPlaceholderText("Plot title")
        self.setClearButtonEnabled(False)

    def reset_default(self, text: str) -> None:
        """Replace the default title and display text (e.g. after loading new survey data)."""
        self._default_text = text.strip()
        self.blockSignals(True)
        self.setText(self._default_text)
        self.blockSignals(False)

    def default_text(self) -> str:
        return self._default_text

    def title_text(self) -> str:
        text = self.text().strip()
        return text or self._default_text

    def is_customized(self) -> bool:
        return self.title_text() != self._default_text
