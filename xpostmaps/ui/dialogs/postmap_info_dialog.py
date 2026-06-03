"""Editable postmap information popup with two-column drag-and-drop layout."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from xpostmaps.core.models import PostmapInfo
from xpostmaps.core.postmap_info_layout import (
    LOCKED_HEADER_KEYS,
    ensure_layout,
    info_from_board,
)
from xpostmaps.ui.dialogs.base_dialog import SingleInstanceDialog
from xpostmaps.ui.widgets.project_info_board import AutoFitLineEdit, ProjectInfoBoard


def _default_project_date(value: str = "") -> str:
    return value.strip() or date.today().isoformat()


def _autosize_project_info_dialog(
    dialog: SingleInstanceDialog,
    board: ProjectInfoBoard,
    header_edits: dict[str, AutoFitLineEdit],
) -> None:
    """Resize the dialog so all header fields and board rows are visible without clipping."""
    board.apply_fitted_geometry()
    for edit in header_edits.values():
        edit._resize_to_contents()

    header_w = max((edit.minimumWidth() for edit in header_edits.values()), default=240) + 120
    board_w = board.size().width()
    content_w = max(board_w + 96, header_w, 560)

    dialog.adjustSize()
    chrome_h = max(dialog.height() - board.height(), 220)
    content_h = board.size().height() + chrome_h

    screen = dialog.screen().availableGeometry() if dialog.screen() else None
    if screen is None:
        screen = QApplication.primaryScreen().availableGeometry()
    max_w = max(screen.width() - 48, 560)
    max_h = max(screen.height() - 48, 480)
    width = min(content_w, max_w)
    height = min(max(content_h, 480), max_h)
    if width < content_w:
        for list_widget in (board._left, board._right):
            list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    dialog.setMinimumSize(min(width, max_w), min(height, 360))
    dialog.resize(width, height)


class PostmapInfoDialog:
    KEY = "postmap_info"

    @classmethod
    def open(cls, parent, info: PostmapInfo, on_changed) -> None:
        def build(dialog: SingleInstanceDialog) -> None:
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

            title = QLabel("Project Information")
            title.setObjectName("sectionTitle")
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(title)

            header_host = QWidget()
            header_layout = QVBoxLayout(header_host)
            header_layout.setContentsMargins(40, 0, 40, 0)
            header_layout.setSpacing(8)
            header_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

            header_edits: dict[str, AutoFitLineEdit] = {}
            header_labels = {
                "client": "Client Name",
                "area": "Area",
                "project": "Project Name",
            }
            for key in LOCKED_HEADER_KEYS:
                value = getattr(info, key, "") or ""
                lbl = QLabel(header_labels[key])
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                edit = AutoFitLineEdit(value, min_chars=12)
                edit.setAlignment(Qt.AlignmentFlag.AlignLeft)
                header_edits[key] = edit
                header_layout.addWidget(lbl)
                header_layout.addWidget(edit, alignment=Qt.AlignmentFlag.AlignHCenter)

            layout.addWidget(header_host)

            ensure_layout(info)
            board = ProjectInfoBoard()
            board.set_header_fields(header_edits)
            board.load_info(info)
            layout.addWidget(board, stretch=0, alignment=Qt.AlignmentFlag.AlignHCenter)

            autosize_timer = QTimer(dialog)
            autosize_timer.setSingleShot(True)
            autosize_timer.setInterval(0)

            def schedule_autosize() -> None:
                autosize_timer.start()

            autosize_timer.timeout.connect(
                lambda: _autosize_project_info_dialog(dialog, board, header_edits)
            )

            apply_timer = QTimer(dialog)
            apply_timer.setSingleShot(True)
            apply_timer.setInterval(250)

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

            def schedule_apply() -> None:
                apply_timer.start()

            apply_timer.timeout.connect(apply)
            board.layout_edited.connect(schedule_apply)
            board.layout_edited.connect(schedule_autosize)
            for edit in header_edits.values():
                edit.textChanged.connect(schedule_apply)
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
                schedule_apply()
                schedule_autosize()

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
                schedule_apply()
                schedule_autosize()

            add_btn.clicked.connect(on_add)
            delete_btn.clicked.connect(on_delete)

            action_row = QHBoxLayout()
            apply_btn = QPushButton("Apply")
            apply_btn.setObjectName("primaryBtn")
            apply_btn.clicked.connect(apply)
            close_btn = QPushButton("Close")
            close_btn.clicked.connect(dialog.close)
            action_row.addStretch()
            action_row.addWidget(apply_btn)
            action_row.addWidget(close_btn)
            action_row.addStretch()
            layout.addLayout(action_row)
            schedule_autosize()

        SingleInstanceDialog.show_dialog(
            cls.KEY,
            "Project Information",
            build,
            parent,
            width=860,
            height=720,
        )
