"""Two-column draggable project information field board."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from xpostmaps.core.models import PostmapInfo
from xpostmaps.core.postmap_info_layout import (
    BUILTIN_LABELS,
    READONLY_KEYS,
    field_label,
    field_value,
    get_custom_fields,
    get_layout,
    new_custom_key,
)

_EDIT_FRAME_PAD = 28
_LABEL_PAD = 8
_EDIT_STYLE = "font-size: 12px; padding: 7px 11px;"
_EDIT_MIN_HEIGHT = 36
_ROW_EXTRA = 10
_COL_GAP = 14
_LIST_FRAME_PAD = 6
_MIN_COLUMN_WIDTH = 360
_ROW_HPAD = 16


def _line_edit_height(metrics: QFontMetrics) -> int:
    return max(metrics.lineSpacing() + 16, _EDIT_MIN_HEIGHT)


class AutoFitLineEdit(QLineEdit):
    """Line edit sized to fit text width and font line height without clipping."""

    def __init__(self, text: str = "", *, min_chars: int = 10, parent=None) -> None:
        super().__init__(text, parent)
        self._min_chars = min_chars
        self.setObjectName("projectInfoLineEdit")
        self.setStyleSheet(_EDIT_STYLE)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.textChanged.connect(self._resize_to_contents)
        self._apply_vertical_size()
        self._resize_to_contents()
        self.home(False)

    @staticmethod
    def preferred_height() -> int:
        probe = QLineEdit()
        probe.setStyleSheet(_EDIT_STYLE)
        return _line_edit_height(probe.fontMetrics())

    def _text_width(self, text: str) -> int:
        metrics = QFontMetrics(self.font())
        sample = text if text else " "
        return metrics.horizontalAdvance(sample)

    def _apply_vertical_size(self) -> None:
        height = _line_edit_height(self.fontMetrics())
        self.setMinimumHeight(height)
        self.setFixedHeight(height)

    def _resize_to_contents(self, *_args) -> None:
        self._apply_vertical_size()
        text = self.text() or self.placeholderText()
        content_w = self._text_width(text) + _EDIT_FRAME_PAD
        floor_w = self._text_width(" " * self._min_chars) + _EDIT_FRAME_PAD
        self.setMinimumWidth(max(content_w, floor_w, 72))
        self.updateGeometry()

    def resize_to_available(self, available: int) -> None:
        """Fill the column; grow past it when the text needs more space (horizontal scroll)."""
        text = self.text() or self.placeholderText()
        content_w = self._text_width(text) + _EDIT_FRAME_PAD
        floor_w = self._text_width(" " * self._min_chars) + _EDIT_FRAME_PAD
        self.setMinimumWidth(max(available, content_w, floor_w, 72))
        self.updateGeometry()


class _FieldRowWidget(QWidget):
    def __init__(
        self,
        key: str,
        label: str,
        value: str,
        *,
        readonly: bool = False,
        parent=None,
        on_resize=None,
    ) -> None:
        super().__init__(parent)
        self.key = key
        self._on_resize = on_resize
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 5, 4, 5)
        row.setSpacing(8)
        title = QLabel(label)
        title.setStyleSheet("font-size: 12px; padding: 4px 0;")
        title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        title.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        label_w = QFontMetrics(title.font()).horizontalAdvance(label) + _LABEL_PAD
        title.setMinimumWidth(label_w)
        row.addWidget(title)
        edit_h = AutoFitLineEdit.preferred_height()
        if readonly:
            self.edit: AutoFitLineEdit | None = None
            title.setMinimumHeight(edit_h)
            spacer = QLabel("")
            spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            row.addWidget(spacer, stretch=1)
        else:
            self.edit = AutoFitLineEdit(value, min_chars=6)
            self.edit.textChanged.connect(self._notify_resize)
            row.addWidget(self.edit, stretch=1)
        row_h = edit_h + 10
        self.setMinimumHeight(row_h)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _notify_resize(self, *_args) -> None:
        if self.edit is not None:
            self.edit._resize_to_contents()
        if self._on_resize is not None:
            self._on_resize()

    def sync_to_column_width(self, column_width: int) -> None:
        metrics = QFontMetrics(self.font())
        label = self.findChild(QLabel)
        label_w = label.minimumWidth() if label is not None else 0
        available = max(column_width - label_w - _ROW_HPAD, 120)
        self.setMinimumWidth(column_width)
        if self.edit is not None:
            self.edit.resize_to_available(available)

    def value_text(self) -> str:
        if self.edit is None:
            return ""
        return self.edit.text().strip()


class _FieldColumnList(QListWidget):
    def __init__(self, column_index: int, board: ProjectInfoBoard, parent=None) -> None:
        super().__init__(parent)
        self._column_index = column_index
        self._board = board
        self.setDragDropMode(QListWidget.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.setSpacing(6)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._board._sync_column_row_widths(self)

    def dropEvent(self, event) -> None:  # noqa: N802
        self._board._snapshot_values_from_widgets()
        super().dropEvent(event)
        self._board._repair_item_widgets(snapshot=False)


class ProjectInfoBoard(QWidget):
    layout_edited = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._header_edits: dict[str, QLineEdit] = {}
        self._field_values: dict[str, str] = {}
        self._custom_labels: dict[str, str] = {}
        self._left = _FieldColumnList(0, self)
        self._right = _FieldColumnList(1, self)
        self._build_ui()
        self._left.model().rowsMoved.connect(self._repair_item_widgets)
        self._right.model().rowsMoved.connect(self._repair_item_widgets)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        columns = QHBoxLayout()
        columns.setSpacing(_COL_GAP)
        columns.addWidget(self._left)
        columns.addWidget(self._right)
        root.addLayout(columns)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    def _on_layout_edited(self, *_args) -> None:
        self.layout_edited.emit()

    def _custom_fields_dict(self) -> dict[str, dict[str, str]]:
        return {
            key: {
                "label": label,
                "value": self._field_values.get(key, ""),
            }
            for key, label in self._custom_labels.items()
        }

    def _snapshot_values_from_widgets(self) -> None:
        for list_widget in (self._left, self._right):
            for row in range(list_widget.count()):
                item = list_widget.item(row)
                widget = list_widget.itemWidget(item)
                if not isinstance(widget, _FieldRowWidget):
                    continue
                if widget.edit is not None:
                    self._field_values[widget.key] = widget.value_text()
                title = widget.findChild(QLabel)
                if widget.key.startswith("custom:") and title is not None:
                    self._custom_labels[widget.key] = title.text().strip() or "Custom"

    def _repair_item_widgets(self, *_args, snapshot: bool = True) -> None:
        """Rebuild row widgets after drag-drop (Qt drops item widgets across lists)."""
        if snapshot:
            self._snapshot_values_from_widgets()
        for list_widget in (self._left, self._right):
            for row in range(list_widget.count()):
                item = list_widget.item(row)
                key = str(item.data(Qt.ItemDataRole.UserRole) or "")
                if not key:
                    continue
                widget = list_widget.itemWidget(item)
                if isinstance(widget, _FieldRowWidget) and widget.key == key:
                    continue
                if widget is not None:
                    list_widget.removeItemWidget(item)
                    widget.deleteLater()
                label = field_label(key, self._custom_fields_dict())
                value = self._field_values.get(key, "")
                if key == "date" and not value.strip():
                    value = date.today().isoformat()
                self._attach_field_row(list_widget, item, key, label, value)
        self._sync_column_row_widths(self._left)
        self._sync_column_row_widths(self._right)
        self.apply_fitted_geometry()
        self._on_layout_edited()

    def _widget_for_item(self, item: QListWidgetItem) -> _FieldRowWidget | None:
        widget = self._left.itemWidget(item)
        if widget is None:
            widget = self._right.itemWidget(item)
        return widget

    @staticmethod
    def _row_required_width(widget: _FieldRowWidget) -> int:
        label = widget.findChild(QLabel)
        label_w = label.minimumWidth() if label is not None else 0
        edit_w = 80
        if widget.edit is not None:
            widget.edit._resize_to_contents()
            edit_w = max(widget.edit.minimumWidth(), 80)
        return label_w + edit_w + _ROW_HPAD + 12

    def _column_fitted_width(self, list_widget: QListWidget) -> int:
        width = _MIN_COLUMN_WIDTH
        for row in range(list_widget.count()):
            item = list_widget.item(row)
            widget = list_widget.itemWidget(item)
            if isinstance(widget, _FieldRowWidget):
                width = max(width, self._row_required_width(widget))
        return width + _LIST_FRAME_PAD

    def _column_fitted_height(self, list_widget: QListWidget) -> int:
        count = list_widget.count()
        if count == 0:
            return 0
        row_h = AutoFitLineEdit.preferred_height() + _ROW_EXTRA
        spacing = list_widget.spacing()
        total = 0
        for row in range(count):
            item = list_widget.item(row)
            total += max(item.sizeHint().height(), row_h)
        return total + spacing * max(0, count - 1) + _LIST_FRAME_PAD

    def apply_fitted_geometry(self) -> QSize:
        """Size columns to fit all rows and values without internal scrollbars."""
        left_w = self._column_fitted_width(self._left)
        right_w = self._column_fitted_width(self._right)
        self._left.setFixedWidth(left_w)
        self._right.setFixedWidth(right_w)
        self._sync_column_row_widths(self._left)
        self._sync_column_row_widths(self._right)
        col_h = max(self._column_fitted_height(self._left), self._column_fitted_height(self._right))
        if col_h > 0:
            self._left.setFixedHeight(col_h)
            self._right.setFixedHeight(col_h)
        for list_widget in (self._left, self._right):
            list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        board_w = left_w + right_w + _COL_GAP
        board_h = col_h if col_h > 0 else AutoFitLineEdit.preferred_height() + _ROW_EXTRA
        self.setFixedSize(board_w, board_h)
        return QSize(board_w, board_h)

    def _sync_column_row_widths(self, list_widget: QListWidget) -> None:
        width = max(list_widget.width(), list_widget.viewport().width(), 200)
        for row in range(list_widget.count()):
            item = list_widget.item(row)
            widget = list_widget.itemWidget(item)
            if not isinstance(widget, _FieldRowWidget):
                continue
            widget.sync_to_column_width(width)
            item.setSizeHint(QSize(width, max(widget.minimumHeight(), AutoFitLineEdit.preferred_height() + 10)))

    def _attach_field_row(
        self,
        list_widget: QListWidget,
        item: QListWidgetItem,
        key: str,
        label: str,
        value: str,
    ) -> _FieldRowWidget:
        readonly = key in READONLY_KEYS

        def refresh_row() -> None:
            self._sync_column_row_widths(list_widget)

        row_widget = _FieldRowWidget(
            key,
            label,
            value,
            readonly=readonly,
            on_resize=refresh_row,
        )
        item.setData(Qt.ItemDataRole.UserRole, key)
        list_widget.setItemWidget(item, row_widget)
        item.setSizeHint(
            QSize(
                list_widget.width(),
                max(row_widget.minimumHeight(), AutoFitLineEdit.preferred_height() + 10),
            )
        )
        refresh_row()
        self._field_values[key] = value
        if key.startswith("custom:"):
            self._custom_labels[key] = label
        if row_widget.edit is not None:

            def on_text_changed(text: str, field_key: str = key) -> None:
                self._field_values[field_key] = text.strip()
                self._on_layout_edited()

            row_widget.edit.textChanged.connect(on_text_changed)
        return row_widget

    def _add_field_item(
        self,
        list_widget: QListWidget,
        key: str,
        label: str,
        value: str,
    ) -> None:
        item = QListWidgetItem(list_widget)
        list_widget.addItem(item)
        self._attach_field_row(list_widget, item, key, label, value)

    def load_info(self, info: PostmapInfo) -> None:
        self._left.clear()
        self._right.clear()
        self._field_values.clear()
        self._custom_labels.clear()
        custom = get_custom_fields(info)
        self._custom_labels = {key: data.get("label", "Custom") for key, data in custom.items()}
        layout = get_layout(info)
        by_column: dict[int, list[dict]] = {0: [], 1: []}
        for entry in layout:
            by_column[entry["column"]].append(entry)
        for column in (0, 1):
            entries = sorted(by_column[column], key=lambda e: e["row"])
            list_widget = self._left if column == 0 else self._right
            for entry in entries:
                key = entry["key"]
                label = field_label(key, custom)
                value = field_value(info, key, custom)
                if key == "date" and not value.strip():
                    value = date.today().isoformat()
                self._field_values[key] = value
                self._add_field_item(list_widget, key, label, value)
        self.apply_fitted_geometry()

    def set_header_fields(self, edits: dict[str, QLineEdit]) -> None:
        self._header_edits = edits

    def selected_keys(self) -> list[str]:
        keys: list[str] = []
        for list_widget in (self._left, self._right):
            for item in list_widget.selectedItems():
                key = item.data(Qt.ItemDataRole.UserRole)
                if key:
                    keys.append(str(key))
        return keys

    def add_custom_field(self, label: str) -> None:
        key = new_custom_key()
        target = self._left if self._left.count() <= self._right.count() else self._right
        self._add_field_item(target, key, label.strip() or "Custom", "")
        self.apply_fitted_geometry()
        self._on_layout_edited()

    def delete_selected(self) -> bool:
        removed = False
        for list_widget in (self._left, self._right):
            for item in list(list_widget.selectedItems()):
                key = str(item.data(Qt.ItemDataRole.UserRole) or "")
                list_widget.takeItem(list_widget.row(item))
                self._field_values.pop(key, None)
                self._custom_labels.pop(key, None)
                removed = True
        if removed:
            self.apply_fitted_geometry()
            self._on_layout_edited()
        return removed

    def collect_layout(self) -> list[dict]:
        layout: list[dict] = []
        for column, list_widget in enumerate((self._left, self._right)):
            for row in range(list_widget.count()):
                item = list_widget.item(row)
                key = item.data(Qt.ItemDataRole.UserRole)
                if key:
                    layout.append({"key": str(key), "column": column, "row": row})
        return layout

    def collect_field_values(self) -> dict[str, str]:
        self._snapshot_values_from_widgets()
        return dict(self._field_values)

    def collect_custom_fields(self) -> dict[str, dict[str, str]]:
        self._snapshot_values_from_widgets()
        return {
            key: {
                "label": self._custom_labels.get(key, "Custom"),
                "value": self._field_values.get(key, ""),
            }
            for key in self._custom_labels
        }

    def collect_header(self) -> dict[str, str]:
        return {key: edit.text().strip() for key, edit in self._header_edits.items()}
