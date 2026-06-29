"""Non-modal Failed Shotpoints detail window for survey spec results."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from xpostmaps.core.postplot_4d_survey_spec import FailedSpecDetail
from xpostmaps.ui.dialogs.base_dialog import SingleInstanceDialog
from xpostmaps.ui.dialogs.legend_dialog import _configure_legend_table


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
        title = "Failed Shotpoints"
        if sequence_no:
            title = f"Failed Shotpoints — Sequence {sequence_no}"

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
                ["Sequence No.", "Failed Shotpoints", "Failed 4D Statistic"]
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

        return SingleInstanceDialog.show_dialog(
            cls.KEY,
            title,
            build,
            parent,
            width=920,
            height=420,
        )
