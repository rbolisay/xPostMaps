"""Editable postmap information popup with two-column drag-and-drop layout."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from xpostmaps.core.models import PostmapInfo
from xpostmaps.core.postmap_info_layout import (
    LOCKED_HEADER_KEYS,
    ensure_layout,
    info_from_board,
)
from xpostmaps.ui.dialogs.base_dialog import SingleInstanceDialog
from xpostmaps.ui.theme import TEXT_SECONDARY
from xpostmaps.ui.widgets.project_info_board import AutoFitLineEdit, ProjectInfoBoard

_MIN_DIALOG_WIDTH = 420
_MIN_DIALOG_HEIGHT = 280
_HEADER_TABLE_GAP = 32


def _default_project_date(value: str = "") -> str:
    return value.strip() or date.today().isoformat()


def _autosize_project_info_dialog(
    dialog: SingleInstanceDialog,
    board: ProjectInfoBoard,
) -> None:
    """Fit dialog to visible rows; grow and shrink with content changes."""
    board.apply_fitted_geometry()
    content_layout = dialog.content_layout
    content_layout.activate()
    QApplication.processEvents()

    hint = content_layout.sizeHint()
    outer = dialog.layout()
    outer_margins = outer.contentsMargins() if outer is not None else None
    glass_margins = content_layout.contentsMargins()
    pad_w = (outer_margins.left() + outer_margins.right() if outer_margins else 0) + glass_margins.left() + glass_margins.right()
    pad_h = (outer_margins.top() + outer_margins.bottom() if outer_margins else 0) + glass_margins.top() + glass_margins.bottom()

    screen = dialog.screen().availableGeometry() if dialog.screen() else None
    if screen is None:
        screen = QApplication.primaryScreen().availableGeometry()
    max_w = max(screen.width() - 48, _MIN_DIALOG_WIDTH)
    max_h = max(screen.height() - 48, _MIN_DIALOG_HEIGHT)

    target_w = min(max(hint.width() + pad_w, _MIN_DIALOG_WIDTH), max_w)
    target_h = min(max(hint.height() + pad_h, _MIN_DIALOG_HEIGHT), max_h)

    for list_widget in (board._left, board._right):
        list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    dialog.setMinimumSize(_MIN_DIALOG_WIDTH, _MIN_DIALOG_HEIGHT)
    dialog.setMaximumSize(max_w, max_h)
    dialog.resize(target_w, target_h)
    dialog.adjustSize()
    final_w = min(max(dialog.width(), _MIN_DIALOG_WIDTH), max_w)
    final_h = min(max(dialog.height(), _MIN_DIALOG_HEIGHT), max_h)
    dialog.resize(final_w, final_h)


class PostmapInfoDialog:
    KEY = "postmap_info"

    @classmethod
    def open(cls, parent, info: PostmapInfo, on_changed) -> None:
        def build(dialog: SingleInstanceDialog) -> None:
            dialog.setMinimumSize(_MIN_DIALOG_WIDTH, _MIN_DIALOG_HEIGHT)
            dialog.setMaximumSize(16777215, 16777215)

            layout = dialog.content_layout
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            btn_row = QHBoxLayout()
            add_btn = QPushButton("Add Custom Information")
            delete_btn = QPushButton("Delete Selected")
            btn_row.addWidget(add_btn)
            btn_row.addWidget(delete_btn)
            btn_row.addStretch()
            layout.addLayout(btn_row)

            drag_hint = QLabel("Drag and Drop rows to arrange.")
            hint_font = QFont(drag_hint.font())
            hint_font.setItalic(True)
            drag_hint.setFont(hint_font)
            drag_hint.setStyleSheet(f"color: {TEXT_SECONDARY};")
            layout.addWidget(drag_hint)

            title = QLabel("Project Information")
            title.setObjectName("sectionTitle")
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(title)

            header_labels = {
                "client": "Client Name",
                "area": "Area",
                "project": "Project Name",
            }
            header_edits: dict[str, AutoFitLineEdit] = {}
            header_inner = QWidget()
            header_inner_layout = QVBoxLayout(header_inner)
            header_inner_layout.setContentsMargins(0, 0, 0, 4)
            header_inner_layout.setSpacing(6)

            edit_h = AutoFitLineEdit.preferred_height()
            row_h = edit_h + 10
            label_min_w = max(
                header_inner.fontMetrics().horizontalAdvance(text)
                for text in header_labels.values()
            ) + 12
            for key in LOCKED_HEADER_KEYS:
                value = getattr(info, key, "") or ""
                row_host = QWidget()
                row_host.setFixedHeight(row_h)
                row = QHBoxLayout(row_host)
                row.setContentsMargins(0, 0, 0, 0)
                row.setSpacing(8)
                lbl = QLabel(header_labels[key])
                lbl.setStyleSheet("font-size: 12px; padding: 4px 0;")
                lbl.setMinimumWidth(label_min_w)
                lbl.setFixedHeight(edit_h)
                lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                edit = AutoFitLineEdit(value, min_chars=12)
                edit.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
                header_edits[key] = edit
                row.addWidget(lbl)
                row.addWidget(edit, stretch=0)
                header_inner_layout.addWidget(row_host)

            header_row = QHBoxLayout()
            header_row.setContentsMargins(0, 0, 0, 0)
            header_row.addStretch(1)
            header_row.addWidget(header_inner, 0, Qt.AlignmentFlag.AlignHCenter)
            header_row.addStretch(1)
            layout.addLayout(header_row)
            layout.addSpacing(_HEADER_TABLE_GAP)

            ensure_layout(info)
            board = ProjectInfoBoard()
            board.set_header_fields(header_edits)
            board.load_info(info)
            layout.addWidget(board, stretch=0, alignment=Qt.AlignmentFlag.AlignHCenter)

            autosize_timer = QTimer(dialog)
            autosize_timer.setSingleShot(True)
            autosize_timer.setInterval(0)

            def autosize_now() -> None:
                _autosize_project_info_dialog(dialog, board)

            def schedule_autosize() -> None:
                autosize_timer.start()

            autosize_timer.timeout.connect(autosize_now)

            def apply() -> None:
                header = board.collect_header()
                field_values = board.collect_field_values()
                if "date" in field_values:
                    field_values["date"] = _default_project_date(field_values["date"])
                updated = info_from_board(
                    info,
                    header,
                    board.collect_layout(),
                    field_values,
                    board.collect_custom_fields(),
                )
                on_changed(updated)

            board.layout_edited.connect(schedule_autosize)
            for edit in header_edits.values():
                edit.textChanged.connect(schedule_autosize)

            def on_add() -> None:
                label, ok = QInputDialog.getText(
                    dialog,
                    "Custom Information",
                    "Field label:",
                )
                if not ok or not label.strip():
                    return
                board.add_custom_field(label.strip())
                autosize_now()

            def on_delete() -> None:
                keys = board.selected_keys()
                if not keys:
                    QMessageBox.information(
                        dialog,
                        "Delete Selected",
                        "Select one or more fields to delete.",
                    )
                    return
                if not board.delete_selected():
                    return
                autosize_now()

            add_btn.clicked.connect(on_add)
            delete_btn.clicked.connect(on_delete)

            action_row = QHBoxLayout()
            apply_btn = QPushButton("Apply")
            apply_btn.setObjectName("primaryBtn")
            apply_btn.clicked.connect(apply)
            close_btn = QPushButton("Close")
            close_btn.clicked.connect(lambda: (apply(), dialog.close()))
            action_row.addStretch()
            action_row.addWidget(apply_btn)
            action_row.addWidget(close_btn)
            action_row.addStretch()
            layout.addLayout(action_row)
            autosize_now()

            def refit_after_dialog_show() -> None:
                board.apply_fitted_geometry()
                autosize_now()

            if not getattr(dialog, "_project_info_show_hooked", False):
                dialog._project_info_show_hooked = True
                original_show = dialog.showEvent

                def show_event(event) -> None:  # noqa: ANN001
                    if original_show is not None:
                        original_show(event)
                    QTimer.singleShot(0, refit_after_dialog_show)

                dialog.showEvent = show_event  # type: ignore[method-assign]

        return SingleInstanceDialog.show_dialog(
            cls.KEY,
            "Project Information",
            build,
            parent,
            width=_MIN_DIALOG_WIDTH,
            height=_MIN_DIALOG_HEIGHT,
        )
