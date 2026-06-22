"""Verify Project Information dialog sizing and spheroid visibility."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from xpostmaps.core.database import Database
from xpostmaps.core.postmap_info_layout import LOCKED_HEADER_KEYS, ensure_layout, get_layout
from xpostmaps.ui.dialogs.base_dialog import SingleInstanceDialog
from xpostmaps.ui.dialogs.postmap_info_dialog import _autosize_project_info_dialog
from xpostmaps.ui.theme import app_stylesheet
from xpostmaps.ui.widgets.project_info_board import AutoFitLineEdit, ProjectInfoBoard


def _last_row_visible(list_widget) -> bool:
    count = list_widget.count()
    if count == 0:
        return True
    last = list_widget.item(count - 1)
    rect = list_widget.visualItemRect(last)
    return rect.bottom() + 4 <= list_widget.viewport().height()


def _build_dialog(info) -> tuple[SingleInstanceDialog, ProjectInfoBoard]:
    dialog = SingleInstanceDialog("test_pi", "Project Information", width=420, height=280)
    dialog.setStyleSheet(app_stylesheet())
    layout = dialog.content_layout
    layout.addLayout(QHBoxLayout())
    layout.addWidget(QLabel("Project Information"))

    header_edits = {}
    header_inner = QWidget()
    inner_layout = QVBoxLayout(header_inner)
    for key in LOCKED_HEADER_KEYS:
        edit = AutoFitLineEdit(getattr(info, key, "") or "", min_chars=12)
        header_edits[key] = edit
        row = QHBoxLayout()
        row.addWidget(QLabel(key))
        row.addWidget(edit)
        inner_layout.addLayout(row)
    header_row = QHBoxLayout()
    header_row.addStretch(1)
    header_row.addWidget(header_inner)
    header_row.addStretch(1)
    layout.addLayout(header_row)

    board = ProjectInfoBoard()
    board.set_header_fields(header_edits)
    board.load_info(info)
    layout.addWidget(board, stretch=0, alignment=Qt.AlignmentFlag.AlignHCenter)
    action = QHBoxLayout()
    action.addWidget(QPushButton("Apply"))
    layout.addLayout(action)
    return dialog, board


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(app_stylesheet())
    db_path = ROOT / "data" / "7027.db"
    if not db_path.exists():
        print("SKIP: data/7027.db not found")
        return 0

    db = Database(db_path)
    _settings, map_data = db.load_project("7027", with_positions=False)
    info = map_data.postmap_info
    ensure_layout(info)
    layout_keys = [e["key"] for e in get_layout(info)]
    assert "spheroid" in layout_keys, "spheroid missing from layout"

    dialog, board = _build_dialog(info)
    _autosize_project_info_dialog(dialog, board)
    dialog.show()
    app.processEvents()
    board.apply_fitted_geometry()
    _autosize_project_info_dialog(dialog, board)
    app.processEvents()

    right = board._right
    viewport_ok = _last_row_visible(right)
    last = right.itemWidget(right.item(right.count() - 1))
    print(
        f"rows={right.count()} board_h={board.height()} right_h={right.height()} "
        f"viewport={right.viewport().height()} last_key={last.key} visible={viewport_ok}"
    )

    before_h = board.height()
    board.add_custom_field("Test Custom A")
    board.add_custom_field("Test Custom B")
    board.apply_fitted_geometry()
    _autosize_project_info_dialog(dialog, board)
    app.processEvents()
    grow_ok = board.height() > before_h and _last_row_visible(right)
    print(f"board before={before_h} after_add={board.height()} grew={grow_ok}")

    db.close()
    if not viewport_ok:
        print("FAIL: spheroid row clipped in column box")
        return 1
    if not grow_ok:
        print("FAIL: column box did not grow after add")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
