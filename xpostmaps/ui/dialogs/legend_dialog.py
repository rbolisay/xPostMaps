"""Legend configuration popup with editable tables."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QVBoxLayout,
)

from xpostmaps.core.area_utils import (
    coord_index_from_selection,
    coord_selection_from_index,
    coordinate_dropdown_labels,
    custom_coordinate_index,
)
from xpostmaps.core.models import (
    AreaLegendEntry,
    LegendConfig,
    LineSequence,
    LineStyle,
    NavDataType,
    PolygonPoint,
    PostplotLegendEntry,
    SurveyPerimeter,
)
from xpostmaps.ui.dialogs.base_dialog import SingleInstanceDialog
from xpostmaps.ui.dialogs.custom_polygon_dialog import CustomPolygonDialog
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
    return btn


def _fit_table_row(table: QTableWidget, row: int) -> None:
    table.resizeRowToContents(row)
    table.setRowHeight(row, max(table.rowHeight(row), 34))
    for col in range(table.columnCount()):
        table.resizeColumnToContents(col)


def _configure_legend_table(table: QTableWidget) -> None:
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setMinimumSectionSize(34)
    table.verticalHeader().setDefaultSectionSize(34)
    table.horizontalHeader().setSectionResizeMode(
        QHeaderView.ResizeMode.ResizeToContents
    )
    table.setWordWrap(False)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)


def _set_table_viewport_rows(table: QTableWidget, visible_rows: int = 5) -> None:
    """Size table to show *visible_rows* before vertical scrolling."""
    table.resizeRowsToContents()
    header_h = table.horizontalHeader().sizeHint().height()
    row_h = table.verticalHeader().defaultSectionSize()
    if table.rowCount() > 0:
        row_h = max(row_h, max(table.rowHeight(r) for r in range(table.rowCount())))
    frame = table.frameWidth() * 2
    viewport_h = header_h + row_h * visible_rows + frame
    table.setMinimumHeight(viewport_h)
    table.setMaximumHeight(viewport_h)


class LegendDialog:
    KEY = "legend"

    _STYLE_LABELS = ("Solid", "Dotted", "Dash")
    _AREA_STYLE_LABELS = ("Solid", "Dash")
    _DATA_TYPE_LABELS = ("Vessel", "Source")

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
    ) -> None:
        seq_list: list[LineSequence] = list(sequences or [])
        row_sequence_ids: list[list[str]] = []
        row_custom_points: list[list[PolygonPoint]] = []
        perimeter_count = len(survey_perimeters or [])

        def build(dialog: SingleInstanceDialog) -> None:
            layout = dialog.content_layout
            _clear_layout(layout)

            title = QLabel("Legend")
            title.setObjectName("sectionTitle")
            layout.addWidget(title)

            area_lbl = QLabel("Area")
            area_lbl.setStyleSheet("font-weight: 600;")
            layout.addWidget(area_lbl)

            area_table = QTableWidget(0, 5)
            area_table.setHorizontalHeaderLabels(
                ["Area Name", "Border Style", "Border Color", "Coordinates", "Custom Points"]
            )
            _configure_legend_table(area_table)

            post_lbl = QLabel("PostPlot")
            post_lbl.setStyleSheet("font-weight: 600; margin-top: 8px;")

            post_table = QTableWidget(0, 5)
            post_table.setHorizontalHeaderLabels(
                ["Name", "Line Style", "Color", "P111/P190 Data", "Select Sequences"]
            )
            _configure_legend_table(post_table)

            def _collect() -> LegendConfig:
                areas: list[AreaLegendEntry] = []
                for row in range(area_table.rowCount()):
                    name_w = area_table.cellWidget(row, 0)
                    style_w = area_table.cellWidget(row, 1)
                    color_w = area_table.cellWidget(row, 2)
                    coord_w = area_table.cellWidget(row, 3)
                    if (
                        isinstance(name_w, QLineEdit)
                        and isinstance(style_w, QComboBox)
                        and isinstance(color_w, ColorButton)
                        and isinstance(coord_w, QComboBox)
                    ):
                        name = name_w.text().strip()
                        if name:
                            custom_points = (
                                row_custom_points[row]
                                if row < len(row_custom_points)
                                else []
                            )
                            coord_mode, perimeter_index = coord_selection_from_index(
                                coord_w.currentIndex(), perimeter_count
                            )
                            areas.append(
                                AreaLegendEntry(
                                    name=name,
                                    border_style=cls._area_style_from_index(
                                        style_w.currentIndex()
                                    ),
                                    color=color_w.color,
                                    opacity=color_w.opacity,
                                    coordinate_mode=coord_mode,
                                    survey_perimeter_index=perimeter_index,
                                    custom_points=custom_points,
                                )
                            )

                lines: list[PostplotLegendEntry] = []
                for row in range(post_table.rowCount()):
                    name_w = post_table.cellWidget(row, 0)
                    style_w = post_table.cellWidget(row, 1)
                    color_w = post_table.cellWidget(row, 2)
                    data_w = post_table.cellWidget(row, 3)
                    if (
                        isinstance(name_w, QLineEdit)
                        and isinstance(style_w, QComboBox)
                        and isinstance(color_w, ColorButton)
                        and isinstance(data_w, QComboBox)
                    ):
                        name = name_w.text().strip()
                        if name:
                            style = cls._style_from_index(style_w.currentIndex())
                            data_type = cls._data_type_from_index(data_w.currentIndex())
                            seq_ids = row_sequence_ids[row] if row < len(row_sequence_ids) else []
                            lines.append(
                                PostplotLegendEntry(
                                    name=name,
                                    line_style=style,
                                    color=color_w.color,
                                    opacity=color_w.opacity,
                                    data_type=data_type,
                                    sequence_ids=seq_ids,
                                )
                            )
                return LegendConfig(areas=areas, postplot_lines=lines)

            def _update_custom_button(row: int) -> None:
                coord_w = area_table.cellWidget(row, 3)
                custom_btn = area_table.cellWidget(row, 4)
                if not isinstance(coord_w, QComboBox) or not isinstance(custom_btn, QPushButton):
                    return
                is_custom = coord_w.currentIndex() == custom_coordinate_index(perimeter_count)
                count = len(row_custom_points[row]) if row < len(row_custom_points) else 0
                custom_btn.setEnabled(is_custom)
                custom_btn.setText(
                    f"Edit Points ({count})" if count else "Edit Points"
                )
                _fit_table_row(area_table, row)

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

                existing = row_custom_points[row] if row < len(row_custom_points) else []
                CustomPolygonDialog.open(
                    parent=dialog,
                    area_name=area_name,
                    points=existing,
                    on_changed=on_changed,
                    row_key=str(row),
                )

            def add_area_row(entry: AreaLegendEntry | None = None) -> None:
                row = area_table.rowCount()
                area_table.insertRow(row)
                area_table.setCellWidget(row, 0, QLineEdit(entry.name if entry else ""))

                style_combo = QComboBox()
                style_combo.addItems(list(cls._AREA_STYLE_LABELS))
                if entry:
                    style_combo.setCurrentIndex(cls._index_from_area_style(entry.border_style))
                area_table.setCellWidget(row, 1, style_combo)

                area_table.setCellWidget(
                    row,
                    2,
                    ColorButton(
                        entry.color if entry else "#22c55e",
                        entry.opacity if entry else 1.0,
                    ),
                )

                coord_combo = QComboBox()
                coord_combo.addItems(coordinate_dropdown_labels(perimeter_count))
                if entry:
                    coord_combo.setCurrentIndex(
                        coord_index_from_selection(
                            entry.coordinate_mode,
                            entry.survey_perimeter_index,
                            perimeter_count,
                        )
                    )
                coord_combo.currentIndexChanged.connect(
                    lambda _idx, r=row: _update_custom_button(r)
                )
                area_table.setCellWidget(row, 3, coord_combo)

                row_custom_points.append(
                    list(entry.custom_points) if entry else []
                )
                custom_btn = _table_cell_button("Edit Points")
                custom_btn.clicked.connect(
                    lambda _checked=False, r=row: _open_custom_polygon(r)
                )
                area_table.setCellWidget(row, 4, custom_btn)
                _update_custom_button(row)
                _fit_table_row(area_table, row)

            def remove_area_row() -> None:
                row = area_table.currentRow()
                if row >= 0:
                    area_table.removeRow(row)
                    if row < len(row_custom_points):
                        del row_custom_points[row]

            def _open_sequences(row: int, name: str) -> None:
                if not seq_list:
                    return

                def on_changed(ids: list[str]) -> None:
                    if row < len(row_sequence_ids):
                        row_sequence_ids[row] = ids
                    btn = post_table.cellWidget(row, 4)
                    if isinstance(btn, QPushButton):
                        btn.setText(
                            f"Select Sequences ({len(ids)})"
                            if ids
                            else "Select Sequences"
                        )
                        _fit_table_row(post_table, row)

                def refresh_sequences() -> list[LineSequence]:
                    if sequences_provider:
                        seq_list.clear()
                        seq_list.extend(sequences_provider())
                    return list(seq_list)

                SequencesDialog.open(
                    parent=dialog,
                    legend_row_name=name,
                    sequences=seq_list,
                    selected_ids=row_sequence_ids[row] if row < len(row_sequence_ids) else [],
                    on_changed=on_changed,
                    on_refresh=refresh_sequences,
                    row_key=str(row),
                )

            def add_post_row(entry: PostplotLegendEntry | None = None) -> None:
                row = post_table.rowCount()
                post_table.insertRow(row)
                name = entry.name if entry else ""
                post_table.setCellWidget(row, 0, QLineEdit(name))

                style_combo = QComboBox()
                style_combo.addItems(list(cls._STYLE_LABELS))
                if entry:
                    style_combo.setCurrentIndex(cls._index_from_style(entry.line_style))
                post_table.setCellWidget(row, 1, style_combo)
                post_table.setCellWidget(
                    row,
                    2,
                    ColorButton(
                        entry.color if entry else "#ef4444",
                        entry.opacity if entry else 1.0,
                    ),
                )

                data_combo = QComboBox()
                data_combo.addItems(list(cls._DATA_TYPE_LABELS))
                if entry:
                    data_combo.setCurrentIndex(cls._index_from_data_type(entry.data_type))
                post_table.setCellWidget(row, 3, data_combo)

                seq_ids = list(entry.sequence_ids) if entry else []
                row_sequence_ids.append(seq_ids)
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
                _fit_table_row(post_table, row)

            def remove_post_row() -> None:
                row = post_table.currentRow()
                if row >= 0:
                    post_table.removeRow(row)
                    if row < len(row_sequence_ids):
                        del row_sequence_ids[row]

            for entry in legend.areas:
                add_area_row(entry)
            if not legend.areas:
                add_area_row()

            area_btns = QHBoxLayout()
            add_area_btn = QPushButton("Add Area Row")
            rem_area_btn = QPushButton("Remove Selected")
            add_area_btn.clicked.connect(add_area_row)
            rem_area_btn.clicked.connect(remove_area_row)
            area_btns.addWidget(add_area_btn)
            area_btns.addWidget(rem_area_btn)

            layout.addLayout(area_btns)
            layout.addWidget(area_table)
            layout.addWidget(post_lbl)

            for entry in legend.postplot_lines:
                add_post_row(entry)
            if not legend.postplot_lines:
                add_post_row(PostplotLegendEntry(name="Up Line", color="#ef4444"))
                add_post_row(PostplotLegendEntry(name="Down Line", color="#3b82f6"))

            post_btns = QHBoxLayout()
            add_post_btn = QPushButton("Add PostPlot Row")
            rem_post_btn = QPushButton("Remove Selected")
            add_post_btn.clicked.connect(add_post_row)
            rem_post_btn.clicked.connect(remove_post_row)
            post_btns.addWidget(add_post_btn)
            post_btns.addWidget(rem_post_btn)

            layout.addLayout(post_btns)
            layout.addWidget(post_table)

            _set_table_viewport_rows(area_table, 5)
            _set_table_viewport_rows(post_table, 5)

            if not seq_list:
                note = QLabel("Load P111/P190 files to enable sequence selection.")
                note.setStyleSheet("color: #94a3b8; font-size: 11px;")
                layout.addWidget(note)

            action_row = QHBoxLayout()
            apply_btn = QPushButton("Apply")
            apply_btn.setObjectName("primaryBtn")
            close_btn = QPushButton("Close")

            def apply_changes() -> None:
                on_apply(_collect())

            apply_btn.clicked.connect(apply_changes)
            close_btn.clicked.connect(dialog.close)
            action_row.addWidget(apply_btn)
            action_row.addWidget(close_btn)
            layout.addLayout(action_row)

        SingleInstanceDialog.show_dialog(cls.KEY, "Legend", build, parent, width=920, height=780)
