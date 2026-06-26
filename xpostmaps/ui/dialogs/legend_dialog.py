"""Legend configuration popup with editable tables."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QVBoxLayout,
)

from xpostmaps.core.area_utils import (
    custom_source_index,
    polygon_source_dropdown_labels,
    polygon_source_from_index,
    polygon_source_index_from_selection,
)
from xpostmaps.core.models import (
    AreaCoordinateMode,
    AreaLegendEntry,
    ConditionalColorRule,
    LegendConfig,
    LineSequence,
    LineStyle,
    NavDataType,
    NavplanCatalogEntry,
    NavplanLegendEntry,
    PolygonPoint,
    PostplotLegendEntry,
    PreplotLegendEntry,
    SurveyPerimeter,
)
from xpostmaps.core.polygon_import_service import (
    imported_polygon_entries,
    non_imported_polygon_entries,
)
from xpostmaps.core.navplan_catalog_utils import (
    assignments_to_row_navplan_indices,
    row_navplan_indices_to_assignments,
)
from xpostmaps.core.preplot_catalog_utils import preplot_source_labels
from xpostmaps.core.sequence_utils import (
    assignments_to_row_sequence_ids,
    row_sequence_ids_to_assignments,
)
from xpostmaps.ui.dialogs.base_dialog import SingleInstanceDialog
from xpostmaps.ui.dialogs.custom_polygon_dialog import CustomPolygonDialog
from xpostmaps.ui.dialogs.navplans_dialog import NavplansDialog
from xpostmaps.ui.dialogs.sequences_dialog import SequencesDialog
from xpostmaps.ui.widgets.color_button import ColorButton


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
            continue
        child = item.layout()
        if child is not None:
            _clear_layout(child)


def _table_cell_button(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setObjectName("tableCellBtn")
    btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
    _apply_table_cell_button_width(btn, text)
    return btn


def _apply_table_cell_button_width(btn: QPushButton, text: str | None = None) -> None:
    label = text if text is not None else btn.text()
    pad = 24  # tableCellBtn horizontal padding + border
    btn.setMinimumWidth(btn.fontMetrics().horizontalAdvance(label) + pad)


_TABLE_CELL_HORIZONTAL_PAD = 16  # QTableWidget::item padding (8px each side)


def _widget_content_width(widget) -> int:
    """Best-effort width for a table cell widget including style chrome."""
    widget.ensurePolished()
    if isinstance(widget, QPushButton):
        _apply_table_cell_button_width(widget)
    elif isinstance(widget, QLineEdit):
        _apply_name_edit_width(widget)
    elif isinstance(widget, QComboBox):
        metrics = widget.fontMetrics()
        text_w = max(
            (metrics.horizontalAdvance(widget.itemText(i)) for i in range(widget.count())),
            default=0,
        )
        widget.setMinimumWidth(text_w + 36)  # arrow + padding + border
    else:
        widget.adjustSize()
    return max(
        widget.minimumWidth(),
        widget.minimumSizeHint().width(),
        widget.sizeHint().width(),
    )


_DIFF_STAT_LABELS = ("Crossline", "Inline", "Radial")
_DIFF_STAT_COMBO_VIEW_STYLE = """
QListView {
    background: #172235;
    color: #e6edf3;
    border: 1px solid #3b4a5f;
    selection-background-color: #3b82f6;
    selection-color: #ffffff;
    outline: 0;
}
QListView::item {
    min-height: 24px;
    padding: 4px 8px;
    color: #e6edf3;
}
QListView::item:selected {
    background: #3b82f6;
    color: #ffffff;
}
"""


class _DiffStatComboBox(QComboBox):
    """Combo whose popup is tall enough to show every diff-stat option."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.addItems(list(_DIFF_STAT_LABELS))
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.setMaxVisibleItems(self.count())
        view = self.view()
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setMinimumWidth(
            max(self.fontMetrics().horizontalAdvance(label) + 40 for label in _DIFF_STAT_LABELS)
        )
        view.setStyleSheet(_DIFF_STAT_COMBO_VIEW_STYLE)

    def showPopup(self) -> None:
        view = self.view()
        count = self.count()
        if count > 0:
            self.setMaxVisibleItems(count)
            row_h = max(max(view.sizeHintForRow(i), 28) for i in range(count))
            view.setFixedHeight(count * row_h + 2 * view.frameWidth())
        super().showPopup()


def _table_name_edit(text: str = "") -> QLineEdit:
    edit = QLineEdit(text)
    edit.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
    _apply_name_edit_width(edit, text)
    return edit


def _apply_name_edit_width(edit: QLineEdit, text: str | None = None) -> None:
    label = text if text is not None else edit.text()
    sample = label if label.strip() else " "
    pad = 28  # QTableWidget QLineEdit horizontal padding + border
    edit.setMinimumWidth(edit.fontMetrics().horizontalAdvance(sample) + pad)


def _connect_name_edit(table: QTableWidget, edit: QLineEdit, col: int = 0) -> None:
    def sync_name_width(_text: str = "") -> None:
        _apply_name_edit_width(edit)
        _fit_table_columns(table, [col])

    edit.textChanged.connect(sync_name_width)


def _column_content_width(table: QTableWidget, col: int) -> int:
    header = table.horizontalHeader()
    width = 0
    header_item = table.horizontalHeaderItem(col)
    if header_item is not None:
        width = header.fontMetrics().horizontalAdvance(header_item.text()) + 20
    for row in range(table.rowCount()):
        item = table.item(row, col)
        if item is not None:
            width = max(width, item.sizeHint().width())
        widget = table.cellWidget(row, col)
        if widget is not None:
            width = max(width, _widget_content_width(widget))
    return max(width + _TABLE_CELL_HORIZONTAL_PAD, 48)


def _fit_table_columns(table: QTableWidget, cols: list[int] | None = None) -> None:
    """Size columns to the widest row content and lock widths so widgets do not overlap."""
    if cols is None:
        cols = list(range(table.columnCount()))
    header = table.horizontalHeader()
    for col in cols:
        if col < 0 or col >= table.columnCount():
            continue
        header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(col, _column_content_width(table, col))


def _fit_table_column(table: QTableWidget, col: int) -> None:
    _fit_table_columns(table, [col])


def _fit_table_action_column(table: QTableWidget, col: int) -> None:
    _fit_table_columns(table, [col])


def _fit_table_name_column(table: QTableWidget, col: int = 0) -> None:
    _fit_table_columns(table, [col])


def _fit_table_row(table: QTableWidget, row: int) -> None:
    table.resizeRowToContents(row)
    table.setRowHeight(row, max(table.rowHeight(row), 34))


def _hide_checkbox(hidden: bool) -> QCheckBox:
    box = QCheckBox("")
    box.setChecked(hidden)
    box.setToolTip("Hide")
    return box


def _legend_section_toolbar_button(text: str, *, kind: str) -> QPushButton:
    """Toolbar buttons above legend tables share width within each button kind."""
    reference = "Add PostPlot Row" if kind == "add" else "Remove Selected"
    btn = QPushButton(text)
    btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    pad = 28
    btn.setMinimumWidth(btn.fontMetrics().horizontalAdvance(reference) + pad)
    return btn


def _configure_legend_table(table: QTableWidget) -> None:
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setMinimumSectionSize(34)
    table.verticalHeader().setDefaultSectionSize(34)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
    table.setWordWrap(False)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    table.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)


_LEGEND_MIN_DIALOG_WIDTH = 980
_LEGEND_MIN_DIALOG_HEIGHT = 280
_LEGEND_ROW_HEIGHT = 34
_LEGEND_MAX_VISIBLE_ROWS = 5  # header + body rows shown before vertical scroll
_LEGEND_MAX_BODY_ROWS = _LEGEND_MAX_VISIBLE_ROWS - 1


def _legend_table_body_cap(table: QTableWidget) -> int | None:
    """Return body-row cap before vertical scroll (header counts as one visible row)."""
    if table.rowCount() <= _LEGEND_MAX_BODY_ROWS:
        return None
    return _LEGEND_MAX_BODY_ROWS


def _table_viewport_height(table: QTableWidget, max_body_rows: int | None = None) -> int:
    """Return the viewport height needed for *table* rows (header + body + frame)."""
    table.resizeRowsToContents()
    header_h = table.horizontalHeader().sizeHint().height()
    default_row_h = max(table.verticalHeader().defaultSectionSize(), _LEGEND_ROW_HEIGHT)
    frame = table.frameWidth() * 2

    if table.rowCount() == 0:
        body_h = default_row_h
    else:
        row_heights = [max(table.rowHeight(r), default_row_h) for r in range(table.rowCount())]
        if max_body_rows is not None and len(row_heights) > max_body_rows:
            body_h = sum(row_heights[:max_body_rows])
        else:
            body_h = sum(row_heights)

    return header_h + body_h + frame


def _fit_table_height(table: QTableWidget, max_body_rows: int | None = None) -> None:
    """Apply viewport height to *table*; cap visible body rows when scrolling is required."""
    viewport_h = _table_viewport_height(table, max_body_rows)
    table.setMinimumHeight(viewport_h)
    table.setMaximumHeight(viewport_h)
    if max_body_rows is not None and table.rowCount() > max_body_rows:
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    else:
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)


def _layout_chrome_height(layout: QVBoxLayout, exclude: set) -> int:
    """Sum non-table widget heights inside *layout* (margins + spacing + chrome)."""
    margins = layout.contentsMargins()
    total = margins.top() + margins.bottom()
    count = layout.count()
    for i in range(count):
        item = layout.itemAt(i)
        if item is None:
            continue
        if i > 0:
            total += layout.spacing()
        widget = item.widget()
        if widget is not None:
            if widget not in exclude:
                total += widget.sizeHint().height()
            continue
        sub = item.layout()
        if sub is not None:
            total += _layout_chrome_height(sub, exclude)
    return total


def _cap_tables_to_viewport(tables: list[QTableWidget], viewport_budget: int) -> None:
    """Shrink visible table bodies proportionally so total table height fits *viewport_budget*."""
    if not tables:
        return
    total_rows = sum(max(t.rowCount(), 1) for t in tables)
    budget = max(viewport_budget, len(tables) * _LEGEND_ROW_HEIGHT)
    for table in tables:
        rows = max(table.rowCount(), 1)
        share = max(_LEGEND_ROW_HEIGHT, budget * rows // total_rows)
        max_visible = min(_LEGEND_MAX_BODY_ROWS, max(1, share // _LEGEND_ROW_HEIGHT))
        _fit_table_height(table, max_body_rows=max_visible if table.rowCount() > max_visible else None)


def _autosize_legend_dialog(
    dialog: SingleInstanceDialog,
    layout: QVBoxLayout,
    tables: list[QTableWidget],
) -> None:
    """Grow or shrink the legend dialog so tables never overlap, capping at the screen."""
    table_set = set(tables)
    for table in tables:
        _fit_table_columns(table)
        _fit_table_height(table, max_body_rows=_legend_table_body_cap(table))

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
    max_w = max(screen.width() - 48, _LEGEND_MIN_DIALOG_WIDTH)
    max_h = max(screen.height() - 48, _LEGEND_MIN_DIALOG_HEIGHT)

    chrome_h = _layout_chrome_height(layout, table_set)
    table_total = sum(t.minimumHeight() for t in tables)
    natural_h = chrome_h + table_total + pad_h

    if natural_h > max_h:
        available_for_tables = max_h - pad_h - chrome_h
        _cap_tables_to_viewport(tables, available_for_tables)
        table_total = sum(t.minimumHeight() for t in tables)
        target_h = min(chrome_h + table_total + pad_h, max_h)
    else:
        target_h = max(natural_h, _LEGEND_MIN_DIALOG_HEIGHT)

    target_w = min(max(_LEGEND_MIN_DIALOG_WIDTH, pad_w + layout.sizeHint().width()), max_w)

    dialog.setMinimumSize(_LEGEND_MIN_DIALOG_WIDTH, _LEGEND_MIN_DIALOG_HEIGHT)
    dialog.setMaximumSize(max_w, max_h)
    dialog.resize(target_w, target_h)
    layout.activate()
    QApplication.processEvents()

_COND_MIN_DIALOG_WIDTH = 480
_COND_MIN_DIALOG_HEIGHT = 120


def _conditional_table_width(table: QTableWidget) -> int:
    width = table.frameWidth() * 2
    if table.verticalHeader().isVisible():
        width += table.verticalHeader().width()
    for col in range(table.columnCount()):
        width += table.columnWidth(col)
    return width


def _autosize_conditional_colors_dialog(
    dialog: SingleInstanceDialog,
    layout: QVBoxLayout,
    table: QTableWidget,
) -> None:
    """Fit the conditional-colors popup to its table rows and column widths."""
    _fit_table_columns(table)
    body_cap = _legend_table_body_cap(table)
    _fit_table_height(table, max_body_rows=body_cap)

    table_w = _conditional_table_width(table)
    table.setMinimumWidth(table_w)
    table.setMaximumWidth(max(table_w, 1))
    table.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    if body_cap is not None and table.rowCount() > body_cap:
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    else:
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

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
    max_w = max(screen.width() - 48, _COND_MIN_DIALOG_WIDTH)
    max_h = max(screen.height() - 48, _COND_MIN_DIALOG_HEIGHT)

    chrome_h = _layout_chrome_height(layout, {table})
    table_h = table.minimumHeight()
    natural_h = chrome_h + table_h + pad_h

    if natural_h > max_h:
        available = max(max_h - pad_h - chrome_h, _LEGEND_ROW_HEIGHT)
        max_visible = max(1, available // _LEGEND_ROW_HEIGHT)
        _fit_table_height(
            table,
            max_body_rows=max_visible if table.rowCount() > max_visible else None,
        )
        table_h = table.minimumHeight()
        target_h = min(chrome_h + table_h + pad_h, max_h)
    else:
        target_h = natural_h

    target_w = min(
        max(_COND_MIN_DIALOG_WIDTH, pad_w + max(table_w, layout.sizeHint().width())),
        max_w,
    )
    target_h = min(target_h, max_h)

    dialog.setMinimumSize(target_w, target_h)
    dialog.setMaximumSize(target_w, target_h)
    dialog.resize(target_w, target_h)
    if outer is not None:
        outer.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
    layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    dialog._glass.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    layout.activate()
    QApplication.processEvents()


class LegendDialog:
    KEY = "legend"

    _STYLE_LABELS = ("Solid", "Dotted", "Dash")
    _AREA_STYLE_LABELS = ("Solid", "Dash")
    _DATA_TYPE_LABELS = ("Vessel", "Source")

    @staticmethod
    def _metric_config_for_style(style: LineStyle) -> tuple[str, int, int]:
        if style == LineStyle.DOTTED:
            return "Size (mm)", 2, 80
        return "Width (mm)", 1, 25

    @staticmethod
    def _secondary_metric_config_for_style(style: LineStyle) -> tuple[str, int, int] | None:
        if style == LineStyle.DASH:
            return "Dash length (mm)", 1, 200
        return None

    @staticmethod
    def _area_style_from_index(index: int) -> LineStyle:
        return LineStyle.SOLID if index == 0 else LineStyle.DASH

    @staticmethod
    def _index_from_area_style(style: LineStyle) -> int:
        return 0 if style == LineStyle.SOLID else 1

    @staticmethod
    def _data_type_from_index(index: int) -> NavDataType:
        types = (NavDataType.VESSEL, NavDataType.SOURCE)
        if 0 <= index < len(types):
            return types[index]
        return NavDataType.SOURCE

    @staticmethod
    def _index_from_data_type(data_type: NavDataType) -> int:
        mapping = {
            NavDataType.VESSEL: 0,
            NavDataType.SOURCE: 1,
        }
        return mapping.get(data_type, 1)

    @staticmethod
    def _style_from_index(index: int) -> LineStyle:
        styles = (LineStyle.SOLID, LineStyle.DOTTED, LineStyle.DASH)
        if 0 <= index < len(styles):
            return styles[index]
        return LineStyle.SOLID

    @staticmethod
    def _index_from_style(style: LineStyle) -> int:
        mapping = {
            LineStyle.SOLID: 0,
            LineStyle.DOTTED: 1,
            LineStyle.DASH: 2,
        }
        return mapping.get(style, 0)

    @classmethod
    def open(
        cls,
        parent,
        legend: LegendConfig,
        on_apply,
        sequences: list[LineSequence] | None = None,
        sequences_provider: Callable[[], list[LineSequence]] | None = None,
        survey_perimeters: list[SurveyPerimeter] | None = None,
        preplot_count: int = 0,
        navplan_catalog: list[NavplanCatalogEntry] | None = None,
        map_epsg: str = "",
        on_map_epsg_changed: Callable[[str], None] | None = None,
    ) -> None:
        seq_list: list[LineSequence] = list(sequences or [])
        navplan_list: list[NavplanCatalogEntry] = list(navplan_catalog or [])
        row_sequence_ids: list[list[str]] = []
        row_sequence_filter_active: list[bool] = []
        row_conditional_colors: list[list[ConditionalColorRule]] = []
        row_post_line_widths: list[float] = []
        row_post_dot_radii: list[float] = []
        row_post_dash_lengths: list[float] = []
        row_preplot_line_widths: list[float] = []
        row_preplot_dot_radii: list[float] = []
        row_preplot_dash_lengths: list[float] = []
        row_navplan_line_widths: list[float] = []
        row_navplan_dot_radii: list[float] = []
        row_navplan_dash_lengths: list[float] = []
        row_navplan_indices: list[list[int]] = []
        row_navplan_filter_active: list[bool] = []
        row_custom_points: list[list[PolygonPoint]] = []
        perimeter_count = len(survey_perimeters or [])
        imported_storage: list[AreaLegendEntry] = []

        # Live-apply guard: suppressed while the dialog is (re)built so that
        # programmatic widget changes don't fire apply mid-construction.
        live = {"on": False}

        def build(dialog: SingleInstanceDialog) -> None:
            live["on"] = False
            layout = dialog.content_layout
            _clear_layout(layout)
            row_custom_points.clear()
            row_sequence_ids.clear()
            row_sequence_filter_active.clear()
            row_conditional_colors.clear()
            row_post_line_widths.clear()
            row_post_dot_radii.clear()
            row_post_dash_lengths.clear()
            row_preplot_line_widths.clear()
            row_preplot_dot_radii.clear()
            row_preplot_dash_lengths.clear()
            row_navplan_line_widths.clear()
            row_navplan_dot_radii.clear()
            row_navplan_dash_lengths.clear()
            row_navplan_indices.clear()
            row_navplan_filter_active.clear()
            imported_storage.clear()
            imported_storage.extend(imported_polygon_entries(legend.areas))
            imported_count = len(imported_storage)
            active_map_epsg = map_epsg
            live_apply_timer = QTimer(dialog)
            live_apply_timer.setSingleShot(True)
            live_apply_timer.setInterval(120)

            title = QLabel("Legend")
            title.setObjectName("sectionTitle")
            layout.addWidget(title)

            area_lbl = QLabel("Area")
            area_lbl.setStyleSheet("font-weight: 600;")
            layout.addWidget(area_lbl)

            area_table = QTableWidget(0, 6)
            area_table.setHorizontalHeaderLabels(
                [
                    "Polygon Name",
                    "Polygon Source",
                    "Border Style",
                    "Border Color",
                    "Custom Points",
                    "Hide",
                ]
            )
            _configure_legend_table(area_table)

            post_lbl = QLabel("PostPlot")
            post_lbl.setStyleSheet("font-weight: 600; margin-top: 8px;")

            post_table = QTableWidget(0, 7)
            post_table.setHorizontalHeaderLabels(
                [
                    "Postplot Name",
                    "Line Style",
                    "Color",
                    "P111/P190 Data",
                    "Select Sequences",
                    "Conditional Colors",
                    "Hide",
                ]
            )
            _configure_legend_table(post_table)

            legend_tables: list[QTableWidget] = [area_table, post_table]

            def refit_legend_geometry() -> None:
                _autosize_legend_dialog(dialog, layout, legend_tables)

            def schedule_refit() -> None:
                QTimer.singleShot(0, refit_legend_geometry)

            def _collect() -> LegendConfig:
                areas: list[AreaLegendEntry] = []
                for row in range(area_table.rowCount()):
                    name_w = area_table.cellWidget(row, 0)
                    source_w = area_table.cellWidget(row, 1)
                    style_w = area_table.cellWidget(row, 2)
                    color_w = area_table.cellWidget(row, 3)
                    hide_w = area_table.cellWidget(row, 5)
                    if (
                        isinstance(name_w, QLineEdit)
                        and isinstance(source_w, QComboBox)
                        and isinstance(style_w, QComboBox)
                        and isinstance(color_w, ColorButton)
                        and isinstance(hide_w, QCheckBox)
                    ):
                        name = name_w.text().strip()
                        if name:
                            custom_points = (
                                row_custom_points[row]
                                if row < len(row_custom_points)
                                else []
                            )
                            coord_mode, perimeter_index, imported_index = (
                                polygon_source_from_index(
                                    source_w.currentIndex(),
                                    perimeter_count,
                                    imported_count,
                                )
                            )
                            areas.append(
                                AreaLegendEntry(
                                    name=name,
                                    border_style=cls._area_style_from_index(
                                        style_w.currentIndex()
                                    ),
                                    color=color_w.color,
                                    opacity=color_w.opacity,
                                    border_width=color_w.metric_value,
                                    hidden=hide_w.isChecked(),
                                    coordinate_mode=coord_mode,
                                    survey_perimeter_index=perimeter_index,
                                    imported_polygon_index=imported_index,
                                    custom_points=custom_points,
                                )
                            )

                return LegendConfig(
                    areas=areas + list(imported_storage),
                    preplot_lines=_collect_preplot_lines(),
                    navplan_lines=_collect_navplan_lines(),
                    postplot_lines=_collect_postplot_lines(),
                )

            def _ensure_symbology_row(
                widths: list[float],
                dots: list[float],
                dashes: list[float],
                row: int,
                entry=None,
            ) -> None:
                while len(widths) <= row:
                    widths.append(entry.line_width if entry is not None else 0.35)
                    dots.append(entry.dot_radius if entry is not None else 0.8)
                    dashes.append(
                        entry.dash_length_mm if entry is not None else 3.0
                    )

            def _symbology_metric_value(
                widths: list[float],
                dots: list[float],
                dashes: list[float],
                row: int,
                style: LineStyle,
            ) -> float:
                _ensure_symbology_row(widths, dots, dashes, row)
                if style == LineStyle.DOTTED:
                    return dots[row]
                return widths[row]

            def _symbology_secondary_metric_value(
                dashes: list[float],
                row: int,
                style: LineStyle,
            ) -> float:
                while len(dashes) <= row:
                    dashes.append(3.0)
                if style == LineStyle.DASH:
                    return dashes[row]
                return 3.0

            def _sync_symbology_metric(
                row: int,
                style_w,
                color_w,
                *,
                widths: list[float],
                dots: list[float],
                dashes: list[float],
            ) -> None:
                if not isinstance(style_w, QComboBox) or not isinstance(color_w, ColorButton):
                    return
                _ensure_symbology_row(widths, dots, dashes, row)
                style = cls._style_from_index(style_w.currentIndex())
                metric = color_w.metric_value
                if style == LineStyle.DOTTED:
                    dots[row] = metric
                else:
                    widths[row] = metric
                if style == LineStyle.DASH:
                    dashes[row] = color_w.secondary_metric_value

            def _bind_style_metric_switch(
                row: int,
                style_combo: QComboBox,
                color_btn: ColorButton,
                *,
                widths: list[float],
                dots: list[float],
                dashes: list[float],
            ) -> None:
                def on_style_changed() -> None:
                    _sync_symbology_metric(
                        row,
                        style_combo,
                        color_btn,
                        widths=widths,
                        dots=dots,
                        dashes=dashes,
                    )
                    style = cls._style_from_index(style_combo.currentIndex())
                    color_btn.set_color(
                        color_btn.color,
                        color_btn.opacity,
                        metric_value=_symbology_metric_value(
                            widths,
                            dots,
                            dashes,
                            row,
                            style,
                        ),
                        secondary_metric_value=_symbology_secondary_metric_value(
                            dashes,
                            row,
                            style,
                        ),
                    )
                    schedule_refit()

                style_combo.currentIndexChanged.connect(on_style_changed)
                color_btn.metric_changed.connect(
                    lambda _value: _sync_symbology_metric(
                        row,
                        style_combo,
                        color_btn,
                        widths=widths,
                        dots=dots,
                        dashes=dashes,
                    )
                )
                color_btn.secondary_metric_changed.connect(
                    lambda _value: _sync_symbology_metric(
                        row,
                        style_combo,
                        color_btn,
                        widths=widths,
                        dots=dots,
                        dashes=dashes,
                    )
                )

            def _collect_preplot_lines() -> list[PreplotLegendEntry]:
                lines: list[PreplotLegendEntry] = []
                for row in range(preplot_table.rowCount()):
                    name_w = preplot_table.cellWidget(row, 0)
                    source_w = preplot_table.cellWidget(row, 1)
                    style_w = preplot_table.cellWidget(row, 2)
                    color_w = preplot_table.cellWidget(row, 3)
                    hide_w = preplot_table.cellWidget(row, 4)
                    if (
                        isinstance(name_w, QLineEdit)
                        and isinstance(source_w, QComboBox)
                        and isinstance(style_w, QComboBox)
                        and isinstance(color_w, ColorButton)
                        and isinstance(hide_w, QCheckBox)
                    ):
                        name = name_w.text().strip()
                        if name:
                            _ensure_symbology_row(
                                row_preplot_line_widths,
                                row_preplot_dot_radii,
                                row_preplot_dash_lengths,
                                row,
                            )
                            _sync_symbology_metric(
                                row,
                                style_w,
                                color_w,
                                widths=row_preplot_line_widths,
                                dots=row_preplot_dot_radii,
                                dashes=row_preplot_dash_lengths,
                            )
                            lines.append(
                                PreplotLegendEntry(
                                    name=name,
                                    preplot_source_index=source_w.currentIndex(),
                                    line_style=cls._style_from_index(
                                        style_w.currentIndex()
                                    ),
                                    color=color_w.color,
                                    opacity=color_w.opacity,
                                    line_width=row_preplot_line_widths[row],
                                    dot_radius=row_preplot_dot_radii[row],
                                    dash_length_mm=row_preplot_dash_lengths[row],
                                    hidden=hide_w.isChecked(),
                                )
                            )
                return lines

            def _collect_navplan_lines() -> list[NavplanLegendEntry]:
                lines: list[NavplanLegendEntry] = []
                for row in range(navplan_table.rowCount()):
                    name_w = navplan_table.cellWidget(row, 0)
                    style_w = navplan_table.cellWidget(row, 1)
                    color_w = navplan_table.cellWidget(row, 2)
                    hide_w = navplan_table.cellWidget(row, 4)
                    if (
                        isinstance(name_w, QLineEdit)
                        and isinstance(style_w, QComboBox)
                        and isinstance(color_w, ColorButton)
                        and isinstance(hide_w, QCheckBox)
                    ):
                        name = name_w.text().strip()
                        if name:
                            style = cls._style_from_index(style_w.currentIndex())
                            selected = (
                                row_navplan_indices[row]
                                if row < len(row_navplan_indices)
                                else []
                            )
                            filter_active = (
                                row_navplan_filter_active[row]
                                if row < len(row_navplan_filter_active)
                                else False
                            )
                            _ensure_symbology_row(
                                row_navplan_line_widths,
                                row_navplan_dot_radii,
                                row_navplan_dash_lengths,
                                row,
                            )
                            _sync_symbology_metric(
                                row,
                                style_w,
                                color_w,
                                widths=row_navplan_line_widths,
                                dots=row_navplan_dot_radii,
                                dashes=row_navplan_dash_lengths,
                            )
                            lines.append(
                                NavplanLegendEntry(
                                    name=name,
                                    line_style=style,
                                    color=color_w.color,
                                    opacity=color_w.opacity,
                                    line_width=row_navplan_line_widths[row],
                                    dot_radius=row_navplan_dot_radii[row],
                                    dash_length_mm=row_navplan_dash_lengths[row],
                                    hidden=hide_w.isChecked(),
                                    navplan_source_indices=selected,
                                    navplan_filter_active=filter_active,
                                )
                            )
                return lines

            def _collect_postplot_lines() -> list[PostplotLegendEntry]:
                lines: list[PostplotLegendEntry] = []
                for row in range(post_table.rowCount()):
                    name_w = post_table.cellWidget(row, 0)
                    style_w = post_table.cellWidget(row, 1)
                    color_w = post_table.cellWidget(row, 2)
                    data_w = post_table.cellWidget(row, 3)
                    hide_w = post_table.cellWidget(row, 6)
                    if (
                        isinstance(name_w, QLineEdit)
                        and isinstance(style_w, QComboBox)
                        and isinstance(color_w, ColorButton)
                        and isinstance(data_w, QComboBox)
                        and isinstance(hide_w, QCheckBox)
                    ):
                        name = name_w.text().strip()
                        if name:
                            style = cls._style_from_index(style_w.currentIndex())
                            data_type = cls._data_type_from_index(data_w.currentIndex())
                            seq_ids = row_sequence_ids[row] if row < len(row_sequence_ids) else []
                            filter_active = (
                                row_sequence_filter_active[row]
                                if row < len(row_sequence_filter_active)
                                else False
                            )
                            _ensure_symbology_row(
                                row_post_line_widths,
                                row_post_dot_radii,
                                row_post_dash_lengths,
                                row,
                            )
                            _sync_symbology_metric(
                                row,
                                style_w,
                                color_w,
                                widths=row_post_line_widths,
                                dots=row_post_dot_radii,
                                dashes=row_post_dash_lengths,
                            )
                            lines.append(
                                PostplotLegendEntry(
                                    name=name,
                                    line_style=style,
                                    color=color_w.color,
                                    opacity=color_w.opacity,
                                    line_width=row_post_line_widths[row],
                                    dot_radius=row_post_dot_radii[row],
                                    dash_length_mm=row_post_dash_lengths[row],
                                    hidden=hide_w.isChecked(),
                                    data_type=data_type,
                                    sequence_ids=seq_ids,
                                    sequence_filter_active=filter_active,
                                    conditional_colors=(
                                        list(row_conditional_colors[row])
                                        if row < len(row_conditional_colors)
                                        else []
                                    ),
                                )
                            )
                return lines

            def _update_custom_button(row: int) -> None:
                source_w = area_table.cellWidget(row, 1)
                custom_btn = area_table.cellWidget(row, 4)
                if not isinstance(source_w, QComboBox) or not isinstance(custom_btn, QPushButton):
                    return
                is_custom = source_w.currentIndex() == custom_source_index(
                    perimeter_count,
                    imported_count,
                )
                count = len(row_custom_points[row]) if row < len(row_custom_points) else 0
                custom_btn.setEnabled(is_custom)
                custom_btn.setText(
                    f"Edit Points ({count})" if count else "Edit Points"
                )
                _apply_table_cell_button_width(custom_btn, custom_btn.text())
                _fit_table_columns(area_table, [4])
                schedule_refit()

            def apply_legend() -> None:
                live_apply_timer.stop()
                on_apply(_collect())

            def live_apply(*_args) -> None:
                # Live preview is intentionally disabled: applying a legend edit
                # triggers a full map re-render plus a minimap/right-pane rebuild,
                # which froze the dialog when fired on every keystroke/edit. The
                # legend now applies only when the user clicks Apply or Close.
                return

            def _open_custom_polygon(row: int) -> None:
                name_w = area_table.cellWidget(row, 0)
                area_name = name_w.text().strip() if isinstance(name_w, QLineEdit) else ""

                def on_changed(points: list[PolygonPoint]) -> None:
                    if row < len(row_custom_points):
                        row_custom_points[row] = points
                    else:
                        while len(row_custom_points) <= row:
                            row_custom_points.append([])
                        row_custom_points[row] = points
                    _update_custom_button(row)
                    apply_legend()

                existing = row_custom_points[row] if row < len(row_custom_points) else []
                CustomPolygonDialog.open(
                    parent=dialog,
                    area_name=area_name,
                    points=existing,
                    on_changed=on_changed,
                    row_key=str(row),
                )

            def add_area_row(entry: AreaLegendEntry | None = None) -> None:
                if entry is not None and not isinstance(entry, AreaLegendEntry):
                    entry = None
                row = area_table.rowCount()
                area_table.insertRow(row)
                name_edit = _table_name_edit(entry.name if entry else "")
                name_edit.editingFinished.connect(live_apply)
                _connect_name_edit(area_table, name_edit, 0)
                area_table.setCellWidget(row, 0, name_edit)

                source_combo = QComboBox()
                source_combo.addItems(
                    polygon_source_dropdown_labels(perimeter_count, imported_count)
                )
                if entry:
                    source_combo.setCurrentIndex(
                        polygon_source_index_from_selection(
                            entry.coordinate_mode,
                            entry.survey_perimeter_index,
                            entry.imported_polygon_index,
                            perimeter_count,
                            imported_count,
                        )
                    )
                source_combo.currentIndexChanged.connect(
                    lambda _idx, r=row: _update_custom_button(r)
                )
                source_combo.currentIndexChanged.connect(live_apply)
                area_table.setCellWidget(row, 1, source_combo)

                style_combo = QComboBox()
                style_combo.addItems(list(cls._AREA_STYLE_LABELS))
                if entry:
                    style_combo.setCurrentIndex(cls._index_from_area_style(entry.border_style))
                style_combo.currentIndexChanged.connect(live_apply)
                area_table.setCellWidget(row, 2, style_combo)

                color_btn = ColorButton(
                    entry.color if entry else "#22c55e",
                    entry.opacity if entry else 1.0,
                    entry.border_width if entry else 2.0,
                    lambda: ("Line thickness", 1, 12),
                )
                color_btn.color_changed.connect(live_apply)
                color_btn.opacity_changed.connect(live_apply)
                color_btn.metric_changed.connect(live_apply)
                area_table.setCellWidget(row, 3, color_btn)

                row_custom_points.append(
                    list(entry.custom_points) if entry else []
                )
                custom_btn = _table_cell_button("Edit Points")
                custom_btn.clicked.connect(
                    lambda _checked=False, r=row: _open_custom_polygon(r)
                )
                area_table.setCellWidget(row, 4, custom_btn)

                hide_box = _hide_checkbox(entry.hidden if entry else False)
                hide_box.toggled.connect(live_apply)
                area_table.setCellWidget(row, 5, hide_box)
                _update_custom_button(row)
                _fit_table_row(area_table, row)
                _fit_table_columns(area_table)
                schedule_refit()

            def remove_area_row() -> None:
                row = area_table.currentRow()
                if row >= 0:
                    area_table.removeRow(row)
                    if row < len(row_custom_points):
                        del row_custom_points[row]
                    schedule_refit()

            def _postplot_names() -> list[str]:
                names: list[str] = []
                for row in range(post_table.rowCount()):
                    name_w = post_table.cellWidget(row, 0)
                    if isinstance(name_w, QLineEdit):
                        name = name_w.text().strip()
                        if name:
                            names.append(name)
                return names

            def _refresh_postplot_sequence_buttons() -> None:
                for row in range(post_table.rowCount()):
                    btn = post_table.cellWidget(row, 4)
                    if not isinstance(btn, QPushButton):
                        continue
                    count = len(row_sequence_ids[row]) if row < len(row_sequence_ids) else 0
                    label = f"Select Sequences ({count})" if count else "Select Sequences"
                    btn.setText(label)
                    _apply_table_cell_button_width(btn, label)
                _fit_table_columns(post_table)
                schedule_refit()

            def _refresh_conditional_button(row: int) -> None:
                btn = post_table.cellWidget(row, 5)
                if not isinstance(btn, QPushButton):
                    return
                rules = row_conditional_colors[row] if row < len(row_conditional_colors) else []
                enabled = [rule for rule in rules if not rule.disabled]
                label = (
                    f"Conditional Colors ({len(enabled)})"
                    if enabled
                    else "Conditional Colors"
                )
                btn.setText(label)
                _apply_table_cell_button_width(btn, label)
                _fit_table_columns(post_table, [5])
                schedule_refit()

            def _open_conditional_colors(row: int) -> None:
                while len(row_conditional_colors) <= row:
                    row_conditional_colors.append([])
                saved_rules = [
                    ConditionalColorRule(
                        diff_stat=rule.diff_stat,
                        range_value=rule.range_value,
                        color=rule.color,
                        opacity=rule.opacity,
                        disabled=rule.disabled,
                    )
                    for rule in row_conditional_colors[row]
                ]
                name_w = post_table.cellWidget(row, 0)
                row_name = (
                    name_w.text().strip()
                    if isinstance(name_w, QLineEdit) and name_w.text().strip()
                    else f"Postplot Row {row + 1}"
                )
                style_w = post_table.cellWidget(row, 1)
                color_w = post_table.cellWidget(row, 2)

                def postplot_metric_config() -> tuple[str, int, int]:
                    return "Size (mm)", 2, 80

                def postplot_metric_value() -> float:
                    if row < len(row_post_dot_radii):
                        return row_post_dot_radii[row]
                    if isinstance(color_w, ColorButton):
                        return color_w.metric_value
                    return 0.8

                def build_conditional_dialog(cond_dialog: SingleInstanceDialog) -> None:
                    cond_layout = cond_dialog.content_layout
                    _clear_layout(cond_layout)
                    cond_layout.setContentsMargins(6, 0, 6, 6)
                    cond_layout.setSpacing(2)
                    cond_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

                    outer = cond_dialog.layout()
                    if outer is not None:
                        outer.setContentsMargins(6, 2, 6, 6)
                        outer.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)

                    title = QLabel(f"Conditional Colors - {row_name}")
                    title.setStyleSheet("font-weight: 600; margin: 0; padding: 0;")
                    title.setContentsMargins(0, 0, 0, 0)
                    title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                    title.setSizePolicy(
                        QSizePolicy.Policy.Preferred,
                        QSizePolicy.Policy.Fixed,
                    )
                    title.setFixedHeight(title.fontMetrics().height())

                    cond_table = QTableWidget(0, 4)
                    cond_table.setHorizontalHeaderLabels(
                        ["Diff Stat", "Range Value (Abs)", "Color", "Disable"]
                    )
                    _configure_legend_table(cond_table)

                    def refit_conditional_dialog() -> None:
                        _autosize_conditional_colors_dialog(
                            cond_dialog,
                            cond_layout,
                            cond_table,
                        )

                    def collect_rules() -> list[ConditionalColorRule]:
                        collected: list[ConditionalColorRule] = []
                        for rule_row in range(cond_table.rowCount()):
                            stat_w = cond_table.cellWidget(rule_row, 0)
                            range_w = cond_table.cellWidget(rule_row, 1)
                            color_w = cond_table.cellWidget(rule_row, 2)
                            disable_w = cond_table.cellWidget(rule_row, 3)
                            if (
                                isinstance(stat_w, QComboBox)
                                and isinstance(range_w, QLineEdit)
                                and isinstance(color_w, ColorButton)
                                and isinstance(disable_w, QCheckBox)
                            ):
                                collected.append(
                                    ConditionalColorRule(
                                        diff_stat=stat_w.currentText().strip().lower(),
                                        range_value=range_w.text().strip(),
                                        color=color_w.color,
                                        opacity=color_w.opacity,
                                        disabled=disable_w.isChecked(),
                                    )
                                )
                        return collected

                    def refresh_cond_table_layout() -> None:
                        refit_conditional_dialog()

                    def apply_conditional_rules() -> None:
                        row_conditional_colors[row] = collect_rules()
                        _refresh_conditional_button(row)
                        apply_legend()

                    def add_condition(rule: ConditionalColorRule | None = None) -> None:
                        rule_row = cond_table.rowCount()
                        cond_table.insertRow(rule_row)

                        stat_combo = _DiffStatComboBox()
                        current = (rule.diff_stat if rule else "radial").lower()
                        stat_combo.setCurrentIndex(
                            {"crossline": 0, "inline": 1, "radial": 2}.get(current, 2)
                        )
                        cond_table.setCellWidget(rule_row, 0, stat_combo)

                        range_edit = QLineEdit(rule.range_value if rule else "")
                        range_edit.setPlaceholderText("e.g. <3, 0-3, =>3")
                        cond_table.setCellWidget(rule_row, 1, range_edit)

                        color_btn = ColorButton(
                            rule.color if rule else "#22c55e",
                            rule.opacity if rule else 1.0,
                            postplot_metric_value(),
                            postplot_metric_config,
                        )
                        cond_table.setCellWidget(rule_row, 2, color_btn)

                        disable_box = QCheckBox("")
                        disable_box.setChecked(rule.disabled if rule else False)
                        cond_table.setCellWidget(rule_row, 3, disable_box)

                        _fit_table_row(cond_table, rule_row)
                        refresh_cond_table_layout()

                    def remove_selected() -> None:
                        selected = sorted(
                            {idx.row() for idx in cond_table.selectedIndexes()},
                            reverse=True,
                        )
                        if not selected and cond_table.currentRow() >= 0:
                            selected = [cond_table.currentRow()]
                        for rule_row in selected:
                            cond_table.removeRow(rule_row)
                        refresh_cond_table_layout()

                    toolbar = QHBoxLayout()
                    toolbar.setContentsMargins(0, 0, 0, 0)
                    toolbar.setSpacing(6)
                    add_btn = _legend_section_toolbar_button("Add Condition Row", kind="add")
                    remove_btn = _legend_section_toolbar_button("Remove Selected", kind="remove")
                    add_btn.clicked.connect(lambda: add_condition())
                    remove_btn.clicked.connect(remove_selected)
                    toolbar.addWidget(add_btn)
                    toolbar.addWidget(remove_btn)
                    toolbar.addStretch()

                    header = QVBoxLayout()
                    header.setContentsMargins(0, 0, 0, 0)
                    header.setSpacing(8)
                    header.addWidget(title)
                    header.addLayout(toolbar)
                    cond_layout.addLayout(header)
                    cond_layout.addWidget(cond_table)

                    action_row = QHBoxLayout()
                    action_row.setContentsMargins(0, 0, 0, 0)
                    apply_btn = QPushButton("Apply")
                    apply_btn.setObjectName("primaryBtn")
                    ok_btn = QPushButton("Ok")
                    close_btn = QPushButton("Close")

                    def close_without_apply() -> None:
                        row_conditional_colors[row] = saved_rules
                        _refresh_conditional_button(row)
                        cond_dialog.close()

                    apply_btn.clicked.connect(apply_conditional_rules)
                    ok_btn.clicked.connect(
                        lambda: (apply_conditional_rules(), cond_dialog.close())
                    )
                    close_btn.clicked.connect(close_without_apply)
                    action_row.addStretch()
                    action_row.addWidget(apply_btn)
                    action_row.addWidget(ok_btn)
                    action_row.addWidget(close_btn)
                    cond_layout.addLayout(action_row)

                    if saved_rules:
                        for rule in saved_rules:
                            add_condition(rule)
                    else:
                        refresh_cond_table_layout()

                    refit_conditional_dialog()
                    QTimer.singleShot(0, refit_conditional_dialog)

                SingleInstanceDialog.show_dialog(
                    f"legend_conditional_colors_{row}",
                    "Conditional Colors",
                    build_conditional_dialog,
                    dialog,
                    width=_COND_MIN_DIALOG_WIDTH,
                    height=_COND_MIN_DIALOG_HEIGHT,
                )

            def _open_sequences(row: int, name: str) -> None:
                if not seq_list:
                    return
                postplot_names = _postplot_names()
                current_assignments = row_sequence_ids_to_assignments(
                    postplot_names,
                    row_sequence_ids,
                )

                def on_assignments_changed(updated: dict[str, str]) -> None:
                    names = _postplot_names()
                    new_row_ids = assignments_to_row_sequence_ids(names, updated)
                    row_sequence_ids.clear()
                    row_sequence_ids.extend(new_row_ids)
                    while len(row_sequence_ids) < post_table.rowCount():
                        row_sequence_ids.append([])
                    while len(row_sequence_filter_active) < post_table.rowCount():
                        row_sequence_filter_active.append(False)
                    for idx in range(post_table.rowCount()):
                        active = bool(
                            row_sequence_ids[idx] if idx < len(row_sequence_ids) else []
                        )
                        if idx < len(row_sequence_filter_active):
                            row_sequence_filter_active[idx] = active
                        else:
                            row_sequence_filter_active.append(active)
                    _refresh_postplot_sequence_buttons()
                    apply_legend()

                def refresh_sequences() -> list[LineSequence]:
                    if sequences_provider:
                        seq_list.clear()
                        seq_list.extend(sequences_provider())
                    return list(seq_list)

                SequencesDialog.open(
                    parent=dialog,
                    sequences=seq_list,
                    postplot_names=postplot_names,
                    assignments=current_assignments,
                    on_assignments_changed=on_assignments_changed,
                    on_refresh=refresh_sequences,
                    row_key=str(row),
                )

            def add_post_row(entry: PostplotLegendEntry | None = None) -> None:
                if entry is not None and not isinstance(entry, PostplotLegendEntry):
                    entry = None
                row = post_table.rowCount()
                post_table.insertRow(row)
                name = entry.name if entry else ""
                post_name = _table_name_edit(name)
                post_name.editingFinished.connect(live_apply)
                _connect_name_edit(post_table, post_name, 0)
                post_table.setCellWidget(row, 0, post_name)

                style_combo = QComboBox()
                style_combo.addItems(list(cls._STYLE_LABELS))
                if entry:
                    style_combo.setCurrentIndex(cls._index_from_style(entry.line_style))
                style_combo.currentIndexChanged.connect(live_apply)
                post_table.setCellWidget(row, 1, style_combo)

                def post_metric_config(combo=style_combo) -> tuple[str, int, int]:
                    return cls._metric_config_for_style(
                        cls._style_from_index(combo.currentIndex())
                    )

                def post_secondary_metric_config(
                    combo=style_combo,
                ) -> tuple[str, int, int] | None:
                    return cls._secondary_metric_config_for_style(
                        cls._style_from_index(combo.currentIndex())
                    )

                _ensure_symbology_row(
                    row_post_line_widths,
                    row_post_dot_radii,
                    row_post_dash_lengths,
                    row,
                    entry,
                )
                post_style = (
                    entry.line_style
                    if entry
                    else cls._style_from_index(style_combo.currentIndex())
                )
                post_color = ColorButton(
                    entry.color if entry else "#ef4444",
                    entry.opacity if entry else 1.0,
                    _symbology_metric_value(
                        row_post_line_widths,
                        row_post_dot_radii,
                        row_post_dash_lengths,
                        row,
                        post_style,
                    ),
                    post_metric_config,
                    secondary_metric_value=_symbology_secondary_metric_value(
                        row_post_dash_lengths,
                        row,
                        post_style,
                    ),
                    secondary_metric_provider=post_secondary_metric_config,
                )
                _bind_style_metric_switch(
                    row,
                    style_combo,
                    post_color,
                    widths=row_post_line_widths,
                    dots=row_post_dot_radii,
                    dashes=row_post_dash_lengths,
                )
                post_table.setCellWidget(row, 2, post_color)
                post_color.color_changed.connect(live_apply)
                post_color.opacity_changed.connect(live_apply)

                data_combo = QComboBox()
                data_combo.addItems(list(cls._DATA_TYPE_LABELS))
                if entry:
                    data_combo.setCurrentIndex(cls._index_from_data_type(entry.data_type))
                data_combo.currentIndexChanged.connect(live_apply)
                post_table.setCellWidget(row, 3, data_combo)

                seq_ids = list(entry.sequence_ids) if entry else []
                row_sequence_ids.append(seq_ids)
                row_sequence_filter_active.append(
                    entry.sequence_filter_active if entry else False
                )
                row_conditional_colors.append(
                    list(entry.conditional_colors) if entry else []
                )
                seq_btn = _table_cell_button(
                    f"Select Sequences ({len(seq_ids)})" if seq_ids else "Select Sequences"
                )
                seq_btn.setEnabled(bool(seq_list))
                seq_btn.clicked.connect(lambda _checked=False, r=row, n=name: _open_sequences(
                    r,
                    post_table.cellWidget(r, 0).text().strip() if isinstance(
                        post_table.cellWidget(r, 0), QLineEdit
                    ) else n,
                ))
                post_table.setCellWidget(row, 4, seq_btn)

                conditional_btn = _table_cell_button("Conditional Colors")
                conditional_btn.clicked.connect(
                    lambda _checked=False, r=row: _open_conditional_colors(r)
                )
                post_table.setCellWidget(row, 5, conditional_btn)
                _refresh_conditional_button(row)

                hide_box = _hide_checkbox(entry.hidden if entry else False)
                hide_box.toggled.connect(live_apply)
                post_table.setCellWidget(row, 6, hide_box)
                _fit_table_row(post_table, row)
                _fit_table_columns(post_table)
                schedule_refit()

            def remove_post_row() -> None:
                row = post_table.currentRow()
                if row >= 0:
                    post_table.removeRow(row)
                    if row < len(row_sequence_ids):
                        del row_sequence_ids[row]
                    if row < len(row_sequence_filter_active):
                        del row_sequence_filter_active[row]
                    if row < len(row_conditional_colors):
                        del row_conditional_colors[row]
                    if row < len(row_post_line_widths):
                        del row_post_line_widths[row]
                    if row < len(row_post_dot_radii):
                        del row_post_dot_radii[row]
                    if row < len(row_post_dash_lengths):
                        del row_post_dash_lengths[row]
                    schedule_refit()

            # Only show area rows the user has explicitly added. Imported
            # polygons, preplots and survey perimeters are NOT auto-added.
            for entry in non_imported_polygon_entries(legend.areas):
                add_area_row(entry)
            _fit_table_columns(area_table)

            area_btns = QHBoxLayout()
            add_area_btn = _legend_section_toolbar_button("Add Area Row", kind="add")
            rem_area_btn = _legend_section_toolbar_button("Remove Selected", kind="remove")
            add_area_btn.clicked.connect(lambda _checked=False: add_area_row())
            rem_area_btn.clicked.connect(remove_area_row)
            area_btns.addWidget(add_area_btn)
            area_btns.addWidget(rem_area_btn)
            area_btns.addStretch()

            layout.addLayout(area_btns)
            layout.addWidget(area_table)

            preplot_lbl = QLabel("Preplot")
            preplot_lbl.setStyleSheet("font-weight: 600; margin-top: 8px;")
            layout.addWidget(preplot_lbl)

            preplot_table = QTableWidget(0, 5)
            preplot_table.setHorizontalHeaderLabels(
                [
                    "Preplot Name",
                    "Preplot Source",
                    "Line Style",
                    "Line Color",
                    "Hide",
                ]
            )
            _configure_legend_table(preplot_table)
            legend_tables.append(preplot_table)

            def add_preplot_row(entry: PreplotLegendEntry | None = None) -> None:
                if entry is not None and not isinstance(entry, PreplotLegendEntry):
                    entry = None
                row = preplot_table.rowCount()
                preplot_table.insertRow(row)
                pp_name = _table_name_edit(entry.name if entry else "")
                pp_name.editingFinished.connect(live_apply)
                _connect_name_edit(preplot_table, pp_name, 0)
                preplot_table.setCellWidget(row, 0, pp_name)

                source_combo = QComboBox()
                source_combo.addItems(preplot_source_labels(preplot_count))
                if entry and 0 <= entry.preplot_source_index < preplot_count:
                    source_combo.setCurrentIndex(entry.preplot_source_index)
                source_combo.currentIndexChanged.connect(live_apply)
                preplot_table.setCellWidget(row, 1, source_combo)

                style_combo = QComboBox()
                style_combo.addItems(list(cls._STYLE_LABELS))
                if entry:
                    style_combo.setCurrentIndex(cls._index_from_style(entry.line_style))
                style_combo.currentIndexChanged.connect(live_apply)
                preplot_table.setCellWidget(row, 2, style_combo)

                def preplot_metric_config(combo=style_combo) -> tuple[str, int, int]:
                    return cls._metric_config_for_style(
                        cls._style_from_index(combo.currentIndex())
                    )

                def preplot_secondary_metric_config(
                    combo=style_combo,
                ) -> tuple[str, int, int] | None:
                    return cls._secondary_metric_config_for_style(
                        cls._style_from_index(combo.currentIndex())
                    )

                _ensure_symbology_row(
                    row_preplot_line_widths,
                    row_preplot_dot_radii,
                    row_preplot_dash_lengths,
                    row,
                    entry,
                )
                preplot_style = (
                    entry.line_style
                    if entry
                    else cls._style_from_index(style_combo.currentIndex())
                )
                color_btn = ColorButton(
                    entry.color if entry else "#f59e0b",
                    entry.opacity if entry else 1.0,
                    _symbology_metric_value(
                        row_preplot_line_widths,
                        row_preplot_dot_radii,
                        row_preplot_dash_lengths,
                        row,
                        preplot_style,
                    ),
                    preplot_metric_config,
                    secondary_metric_value=_symbology_secondary_metric_value(
                        row_preplot_dash_lengths,
                        row,
                        preplot_style,
                    ),
                    secondary_metric_provider=preplot_secondary_metric_config,
                )
                _bind_style_metric_switch(
                    row,
                    style_combo,
                    color_btn,
                    widths=row_preplot_line_widths,
                    dots=row_preplot_dot_radii,
                    dashes=row_preplot_dash_lengths,
                )
                color_btn.color_changed.connect(live_apply)
                color_btn.opacity_changed.connect(live_apply)
                preplot_table.setCellWidget(row, 3, color_btn)

                hide_box = _hide_checkbox(entry.hidden if entry else False)
                hide_box.toggled.connect(live_apply)
                preplot_table.setCellWidget(row, 4, hide_box)
                _fit_table_row(preplot_table, row)
                _fit_table_columns(preplot_table)
                schedule_refit()

            def remove_preplot_row() -> None:
                row = preplot_table.currentRow()
                if row >= 0:
                    preplot_table.removeRow(row)
                    if row < len(row_preplot_line_widths):
                        del row_preplot_line_widths[row]
                    if row < len(row_preplot_dot_radii):
                        del row_preplot_dot_radii[row]
                    if row < len(row_preplot_dash_lengths):
                        del row_preplot_dash_lengths[row]
                    schedule_refit()

            navplan_lbl = QLabel("Navplan")
            navplan_lbl.setStyleSheet("font-weight: 600; margin-top: 8px;")

            navplan_table = QTableWidget(0, 5)
            navplan_table.setHorizontalHeaderLabels(
                [
                    "Navplan Name",
                    "Line Style",
                    "Navplan Color",
                    "Select Navplans",
                    "Hide",
                ]
            )
            _configure_legend_table(navplan_table)
            legend_tables.append(navplan_table)

            def _navplan_legend_names() -> list[str]:
                names: list[str] = []
                for row in range(navplan_table.rowCount()):
                    name_w = navplan_table.cellWidget(row, 0)
                    if isinstance(name_w, QLineEdit):
                        name = name_w.text().strip()
                        if name:
                            names.append(name)
                return names

            def _refresh_navplan_select_buttons() -> None:
                for row in range(navplan_table.rowCount()):
                    btn = navplan_table.cellWidget(row, 3)
                    if not isinstance(btn, QPushButton):
                        continue
                    count = len(row_navplan_indices[row]) if row < len(row_navplan_indices) else 0
                    label = f"Select Navplans ({count})" if count else "Select Navplans"
                    btn.setText(label)
                    _apply_table_cell_button_width(btn, label)
                _fit_table_columns(navplan_table)
                schedule_refit()

            def _open_navplans(row: int, name: str) -> None:
                if not navplan_list:
                    return
                legend_names = _navplan_legend_names()
                current_assignments = row_navplan_indices_to_assignments(
                    legend_names,
                    row_navplan_indices,
                )

                def on_assignments_changed(updated: dict[int, str]) -> None:
                    names = _navplan_legend_names()
                    new_row_indices = assignments_to_row_navplan_indices(names, updated)
                    row_navplan_indices.clear()
                    row_navplan_indices.extend(new_row_indices)
                    while len(row_navplan_indices) < navplan_table.rowCount():
                        row_navplan_indices.append([])
                    while len(row_navplan_filter_active) < navplan_table.rowCount():
                        row_navplan_filter_active.append(False)
                    for idx in range(navplan_table.rowCount()):
                        active = bool(
                            row_navplan_indices[idx] if idx < len(row_navplan_indices) else []
                        )
                        if idx < len(row_navplan_filter_active):
                            row_navplan_filter_active[idx] = active
                        else:
                            row_navplan_filter_active.append(active)
                    _refresh_navplan_select_buttons()
                    schedule_refit()
                    apply_legend()

                NavplansDialog.open(
                    parent=dialog,
                    catalog=navplan_list,
                    navplan_legend_names=legend_names,
                    assignments=current_assignments,
                    on_assignments_changed=on_assignments_changed,
                    row_key=str(row),
                )

            def add_navplan_row(entry: NavplanLegendEntry | None = None) -> None:
                if entry is not None and not isinstance(entry, NavplanLegendEntry):
                    entry = None
                row = navplan_table.rowCount()
                navplan_table.insertRow(row)
                name = entry.name if entry else ""
                nav_name = _table_name_edit(name)
                nav_name.editingFinished.connect(live_apply)
                _connect_name_edit(navplan_table, nav_name, 0)
                navplan_table.setCellWidget(row, 0, nav_name)

                style_combo = QComboBox()
                style_combo.addItems(list(cls._STYLE_LABELS))
                if entry:
                    style_combo.setCurrentIndex(cls._index_from_style(entry.line_style))
                style_combo.currentIndexChanged.connect(live_apply)
                navplan_table.setCellWidget(row, 1, style_combo)

                def navplan_metric_config(combo=style_combo) -> tuple[str, int, int]:
                    return cls._metric_config_for_style(
                        cls._style_from_index(combo.currentIndex())
                    )

                def navplan_secondary_metric_config(
                    combo=style_combo,
                ) -> tuple[str, int, int] | None:
                    return cls._secondary_metric_config_for_style(
                        cls._style_from_index(combo.currentIndex())
                    )

                _ensure_symbology_row(
                    row_navplan_line_widths,
                    row_navplan_dot_radii,
                    row_navplan_dash_lengths,
                    row,
                    entry,
                )
                navplan_style = (
                    entry.line_style
                    if entry
                    else cls._style_from_index(style_combo.currentIndex())
                )
                color_btn = ColorButton(
                    entry.color if entry else "#22c55e",
                    entry.opacity if entry else 1.0,
                    _symbology_metric_value(
                        row_navplan_line_widths,
                        row_navplan_dot_radii,
                        row_navplan_dash_lengths,
                        row,
                        navplan_style,
                    ),
                    navplan_metric_config,
                    secondary_metric_value=_symbology_secondary_metric_value(
                        row_navplan_dash_lengths,
                        row,
                        navplan_style,
                    ),
                    secondary_metric_provider=navplan_secondary_metric_config,
                )
                _bind_style_metric_switch(
                    row,
                    style_combo,
                    color_btn,
                    widths=row_navplan_line_widths,
                    dots=row_navplan_dot_radii,
                    dashes=row_navplan_dash_lengths,
                )
                color_btn.color_changed.connect(live_apply)
                color_btn.opacity_changed.connect(live_apply)
                navplan_table.setCellWidget(row, 2, color_btn)

                selected = list(entry.navplan_source_indices) if entry else []
                row_navplan_indices.append(selected)
                row_navplan_filter_active.append(
                    entry.navplan_filter_active if entry else False
                )
                nav_btn = _table_cell_button(
                    f"Select Navplans ({len(selected)})"
                    if selected
                    else "Select Navplans"
                )
                nav_btn.setEnabled(bool(navplan_list))
                nav_btn.clicked.connect(lambda _checked=False, r=row, n=name: _open_navplans(
                    r,
                    navplan_table.cellWidget(r, 0).text().strip() if isinstance(
                        navplan_table.cellWidget(r, 0), QLineEdit
                    ) else n,
                ))
                navplan_table.setCellWidget(row, 3, nav_btn)

                hide_box = _hide_checkbox(entry.hidden if entry else False)
                hide_box.toggled.connect(live_apply)
                navplan_table.setCellWidget(row, 4, hide_box)
                _fit_table_row(navplan_table, row)
                _fit_table_columns(navplan_table)
                schedule_refit()

            def remove_navplan_row() -> None:
                row = navplan_table.currentRow()
                if row >= 0:
                    navplan_table.removeRow(row)
                    if row < len(row_navplan_indices):
                        del row_navplan_indices[row]
                    if row < len(row_navplan_filter_active):
                        del row_navplan_filter_active[row]
                    if row < len(row_navplan_line_widths):
                        del row_navplan_line_widths[row]
                    if row < len(row_navplan_dot_radii):
                        del row_navplan_dot_radii[row]
                    if row < len(row_navplan_dash_lengths):
                        del row_navplan_dash_lengths[row]
                    schedule_refit()

            for entry in legend.preplot_lines:
                add_preplot_row(entry)
            _fit_table_columns(preplot_table)

            preplot_btns = QHBoxLayout()
            add_preplot_btn = _legend_section_toolbar_button("Add Preplot Row", kind="add")
            rem_preplot_btn = _legend_section_toolbar_button("Remove Selected", kind="remove")
            add_preplot_btn.clicked.connect(lambda _checked=False: add_preplot_row())
            rem_preplot_btn.clicked.connect(remove_preplot_row)
            preplot_btns.addWidget(add_preplot_btn)
            preplot_btns.addWidget(rem_preplot_btn)
            preplot_btns.addStretch()
            layout.addLayout(preplot_btns)
            layout.addWidget(preplot_table)
            if preplot_count == 0:
                preplot_note = QLabel(
                    "Load preplot files from the left pane to enable Preplot Source options."
                )
                preplot_note.setStyleSheet("color: #94a3b8; font-size: 11px;")
                layout.addWidget(preplot_note)

            layout.addWidget(navplan_lbl)

            for entry in legend.navplan_lines:
                add_navplan_row(entry)
            _fit_table_columns(navplan_table)

            navplan_btns = QHBoxLayout()
            add_navplan_btn = _legend_section_toolbar_button("Add Navplan Row", kind="add")
            rem_navplan_btn = _legend_section_toolbar_button("Remove Selected", kind="remove")
            add_navplan_btn.clicked.connect(lambda _checked=False: add_navplan_row())
            rem_navplan_btn.clicked.connect(remove_navplan_row)
            navplan_btns.addWidget(add_navplan_btn)
            navplan_btns.addWidget(rem_navplan_btn)
            navplan_btns.addStretch()
            layout.addLayout(navplan_btns)
            layout.addWidget(navplan_table)
            if not navplan_list:
                navplan_note = QLabel(
                    "Import navplan files from the left pane to enable Select Navplans."
                )
                navplan_note.setStyleSheet("color: #94a3b8; font-size: 11px;")
                layout.addWidget(navplan_note)

            layout.addWidget(post_lbl)

            for entry in legend.postplot_lines:
                add_post_row(entry)
            if not legend.postplot_lines:
                add_post_row(PostplotLegendEntry(name="Up Line", color="#ef4444"))
                add_post_row(PostplotLegendEntry(name="Down Line", color="#3b82f6"))
            _fit_table_columns(post_table)

            post_btns = QHBoxLayout()
            add_post_btn = _legend_section_toolbar_button("Add PostPlot Row", kind="add")
            rem_post_btn = _legend_section_toolbar_button("Remove Selected", kind="remove")
            add_post_btn.clicked.connect(lambda _checked=False: add_post_row())
            rem_post_btn.clicked.connect(remove_post_row)
            post_btns.addWidget(add_post_btn)
            post_btns.addWidget(rem_post_btn)
            post_btns.addStretch()

            layout.addLayout(post_btns)
            layout.addWidget(post_table)

            if not seq_list:
                note = QLabel("Load P111/P190 files to enable sequence selection.")
                note.setStyleSheet("color: #94a3b8; font-size: 11px;")
                layout.addWidget(note)

            action_row = QHBoxLayout()
            apply_btn = QPushButton("Apply")
            apply_btn.setObjectName("primaryBtn")
            ok_btn = QPushButton("Ok")
            close_btn = QPushButton("Close")

            def apply_changes() -> None:
                apply_legend()

            def ok_dialog() -> None:
                apply_legend()
                dialog.close()

            def close_dialog() -> None:
                dialog.close()

            apply_btn.clicked.connect(apply_changes)
            ok_btn.clicked.connect(ok_dialog)
            close_btn.clicked.connect(close_dialog)
            action_row.addStretch()
            action_row.addWidget(apply_btn)
            action_row.addWidget(ok_btn)
            action_row.addWidget(close_btn)
            layout.addLayout(action_row)

            # All rows built: enable live updates for subsequent user edits.
            live["on"] = True

            refit_legend_geometry()
            schedule_refit()

        return SingleInstanceDialog.show_dialog(
            cls.KEY,
            "Legend",
            build,
            parent,
            width=_LEGEND_MIN_DIALOG_WIDTH,
            height=_LEGEND_MIN_DIALOG_HEIGHT,
        )
