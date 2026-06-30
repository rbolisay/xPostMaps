"""Non-modal Failed/Warning Shotpoints detail window for survey spec results."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from xpostmaps.core.postplot_4d_survey_spec import FailedSpecDetail
from xpostmaps.ui.dialog_size_utils import center_widget_on_screen
from xpostmaps.ui.dialogs.base_dialog import SingleInstanceDialog
from xpostmaps.ui.dialogs.legend_dialog import _configure_legend_table
from xpostmaps.ui.postplot_4d_stat_plot.controls import _fit_table_to_content

_MIN_DIALOG_WIDTH = 480
_MIN_DIALOG_HEIGHT = 160
_MAX_BODY_ROWS = 10
_DIALOG_PAD_W = 12 * 2 + 16 * 2 + 4
_DIALOG_PAD_H = 12 * 2 + 16 * 2 + 4


def _autosize_dialog(dialog: SingleInstanceDialog, table: QTableWidget) -> None:
    """Resize the popup to fit the table without horizontal scrolling."""
    _fit_table_to_content(table, max_body_rows=_MAX_BODY_ROWS)

    screen = dialog.screen().availableGeometry() if dialog.screen() else None
    if screen is None:
        screen = QApplication.primaryScreen().availableGeometry()
    max_w = max(screen.width() - 48, _MIN_DIALOG_WIDTH)
    max_h = max(screen.height() - 48, _MIN_DIALOG_HEIGHT)

    target_w = min(max(_MIN_DIALOG_WIDTH, table.maximumWidth() + _DIALOG_PAD_W), max_w)
    target_h = min(max(_MIN_DIALOG_HEIGHT, table.minimumHeight() + _DIALOG_PAD_H), max_h)

    dialog.setMinimumWidth(_MIN_DIALOG_WIDTH)
    dialog.setMaximumWidth(max_w)
    dialog.setMinimumHeight(_MIN_DIALOG_HEIGHT)
    dialog.setMaximumHeight(max_h)
    dialog.resize(target_w, target_h)
    center_widget_on_screen(dialog)


class FailedShotpointsDialog:
    """Single-instance popup listing failed shotpoints by sequence."""

    KEY = "postplot_4d_failed_shotpoints"

    @classmethod
    def show(
        cls,
        parent: QWidget | None,
        entries: list[FailedSpecDetail],
        *,
        sequence_no: str | None = None,
    ) -> SingleInstanceDialog:
        title = "Failed/Warning Shotpoints"
        if sequence_no:
            title = f"Failed/Warning Shotpoints — Sequence {sequence_no}"

        def build(dialog: SingleInstanceDialog) -> None:
            dialog.setWindowTitle(title)
            layout = dialog.content_layout
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

            table = QTableWidget(0, 3, dialog)
            _configure_legend_table(table)
            table.setHorizontalHeaderLabels(
                ["Sequence No.", "Failed/Warning Shotpoints", "Failed 4D Statistic"]
            )
            table.horizontalHeader().setSectionResizeMode(
                QHeaderView.ResizeMode.ResizeToContents
            )
            table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)

            visible = list(entries)
            if sequence_no:
                visible = [
                    entry
                    for entry in entries
                    if entry.applies_to_all_sequences or entry.sequence_no == sequence_no
                ]

            table.setRowCount(len(visible))
            for row_idx, entry in enumerate(visible):
                for col_idx, text in enumerate(
                    (entry.sequence_no, entry.shotpoints_text, entry.statistic_text)
                ):
                    item = QTableWidgetItem(text)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    table.setItem(row_idx, col_idx, item)
                table.setRowHeight(row_idx, 34)

            wrapper = QWidget(dialog)
            wrapper_layout = QVBoxLayout(wrapper)
            wrapper_layout.setContentsMargins(0, 0, 0, 0)
            wrapper_layout.addWidget(table)
            layout.addWidget(wrapper)

            _autosize_dialog(dialog, table)

        return SingleInstanceDialog.show_dialog(
            cls.KEY,
            title,
            build,
            parent,
            width=_MIN_DIALOG_WIDTH,
            height=_MIN_DIALOG_HEIGHT,
        )
