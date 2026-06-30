"""Non-modal Failed/Warning Shotpoints detail window for survey spec results."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QHeaderView,
    QLayout,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from xpostmaps.core.postplot_4d_survey_spec import FailedSpecDetail
from xpostmaps.ui.dialog_size_utils import center_widget_on_screen
from xpostmaps.ui.dialogs.base_dialog import SingleInstanceDialog
from xpostmaps.ui.dialogs.legend_dialog import _configure_legend_table

_MIN_DIALOG_WIDTH = 320
_MIN_DIALOG_HEIGHT = 120
_MAX_VISIBLE_BODY_ROWS = 8
_ROW_MIN_HEIGHT = 34
_CELL_HORIZONTAL_PAD = 24
_COL_COMMENTS = 2

_HEADERS = (
    "Sequence No.",
    "Failed/Warning Shotpoints",
    "Failed/Warning Comments",
)


def _column_text_width(table: QTableWidget, col: int) -> int:
    """Column width from header and cell text (not the current column width)."""
    metrics = table.fontMetrics()
    width = 0
    header_item = table.horizontalHeaderItem(col)
    if header_item is not None:
        width = metrics.horizontalAdvance(header_item.text()) + _CELL_HORIZONTAL_PAD
    for row_idx in range(table.rowCount()):
        item = table.item(row_idx, col)
        if item is not None:
            width = max(
                width,
                metrics.horizontalAdvance(item.text()) + _CELL_HORIZONTAL_PAD,
            )
    return max(width, 48)


def _table_frame_width(table: QTableWidget) -> int:
    return table.frameWidth() * 2


def _fit_failed_shotpoints_table(
    table: QTableWidget,
    *,
    max_table_width: int | None = None,
) -> None:
    """Size columns and rows to content; wrap comments when wider than the screen."""
    header = table.horizontalHeader()
    col_count = table.columnCount()
    col_widths = [_column_text_width(table, col) for col in range(col_count)]
    frame = _table_frame_width(table)
    total = sum(col_widths) + frame

    if max_table_width is not None and total > max_table_width:
        fixed_w = col_widths[0] + col_widths[1]
        col_widths[_COL_COMMENTS] = max(max_table_width - fixed_w - frame, 160)
        table.setWordWrap(True)
    else:
        table.setWordWrap(False)

    for col_idx, width in enumerate(col_widths):
        header.setSectionResizeMode(col_idx, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(col_idx, width)

    table.resizeRowsToContents()
    for row_idx in range(table.rowCount()):
        table.setRowHeight(row_idx, max(table.rowHeight(row_idx), _ROW_MIN_HEIGHT))

    header_h = header.sizeHint().height()
    if table.rowCount() == 0:
        body_h = _ROW_MIN_HEIGHT
    else:
        visible_rows = min(table.rowCount(), _MAX_VISIBLE_BODY_ROWS)
        body_h = sum(
            max(table.rowHeight(row_idx), _ROW_MIN_HEIGHT)
            for row_idx in range(visible_rows)
        )
    viewport_h = header_h + body_h + frame

    table.setMinimumHeight(viewport_h)
    table.setMaximumHeight(viewport_h)
    if table.rowCount() > _MAX_VISIBLE_BODY_ROWS:
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    else:
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    table_w = sum(table.columnWidth(col) for col in range(col_count)) + frame
    vbar = 0
    if table.verticalScrollBarPolicy() != Qt.ScrollBarPolicy.ScrollBarAlwaysOff:
        vbar = table.verticalScrollBar().sizeHint().width()
    table.setMinimumWidth(table_w + vbar)
    table.setMaximumWidth(table_w + vbar)
    table.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)


def _autosize_dialog(
    dialog: SingleInstanceDialog,
    layout: QVBoxLayout,
    table: QTableWidget,
) -> None:
    """Resize the popup to exactly fit the table content."""
    layout.activate()
    QApplication.processEvents()

    outer = dialog.layout()
    outer_margins = outer.contentsMargins() if outer is not None else None
    glass_margins = layout.contentsMargins()
    pad_w = (
        (outer_margins.left() + outer_margins.right() if outer_margins else 0)
        + glass_margins.left()
        + glass_margins.right()
    )
    pad_h = (
        (outer_margins.top() + outer_margins.bottom() if outer_margins else 0)
        + glass_margins.top()
        + glass_margins.bottom()
    )

    screen = dialog.screen().availableGeometry() if dialog.screen() else None
    if screen is None:
        screen = QApplication.primaryScreen().availableGeometry()
    max_w = max(screen.width() - 48, _MIN_DIALOG_WIDTH)
    max_h = max(screen.height() - 48, _MIN_DIALOG_HEIGHT)

    _fit_failed_shotpoints_table(
        table,
        max_table_width=max(max_w - pad_w, _MIN_DIALOG_WIDTH),
    )

    target_w = min(max(_MIN_DIALOG_WIDTH, table.maximumWidth() + pad_w), max_w)
    target_h = min(max(_MIN_DIALOG_HEIGHT, table.maximumHeight() + pad_h), max_h)

    dialog.setMinimumSize(_MIN_DIALOG_WIDTH, _MIN_DIALOG_HEIGHT)
    dialog.setMaximumSize(max_w, max_h)
    dialog.resize(target_w, target_h)
    dialog.setMinimumSize(target_w, target_h)
    dialog.setMaximumSize(target_w, target_h)

    if outer is not None:
        outer.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
    layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    dialog._glass.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    layout.activate()
    QApplication.processEvents()
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

            if dialog.layout() is not None:
                dialog.layout().setSizeConstraint(
                    QLayout.SizeConstraint.SetDefaultConstraint
                )

            table = QTableWidget(0, 3, dialog)
            _configure_legend_table(table)
            table.setHorizontalHeaderLabels(list(_HEADERS))
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

            layout.addWidget(table)
            _autosize_dialog(dialog, layout, table)

        return SingleInstanceDialog.show_dialog(
            cls.KEY,
            title,
            build,
            parent,
            width=_MIN_DIALOG_WIDTH,
            height=_MIN_DIALOG_HEIGHT,
        )
