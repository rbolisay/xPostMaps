"""Legend configuration popup with editable tables."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
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
    LegendConfig,
    LineSequence,
    LineStyle,
    NavDataType,
    PolygonPoint,
    PostplotLegendEntry,
    PreplotLegendEntry,
    SurveyPerimeter,
)
from xpostmaps.core.polygon_import_service import (
    imported_polygon_entries,
    non_imported_polygon_entries,
)
from xpostmaps.core.preplot_catalog_utils import preplot_source_labels
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


def _hide_checkbox(hidden: bool) -> QCheckBox:
    box = QCheckBox("")
    box.setChecked(hidden)
    box.setToolTip("Hide")
    return box


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
    def _metric_config_for_style(style: LineStyle) -> tuple[str, int, int]:
        if style == LineStyle.DOTTED:
            return "Dot Radius", 1, 20
        return "Line thickness", 1, 12

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
        map_epsg: str = "",
        on_map_epsg_changed: Callable[[str], None] | None = None,
    ) -> None:
        seq_list: list[LineSequence] = list(sequences or [])
        row_sequence_ids: list[list[str]] = []
        row_sequence_filter_active: list[bool] = []
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
            imported_storage.clear()
            imported_storage.extend(imported_polygon_entries(legend.areas))
            imported_count = len(imported_storage)
            active_map_epsg = map_epsg

            title = QLabel("Legend")
            title.setObjectName("sectionTitle")
            layout.addWidget(title)

            area_lbl = QLabel("Area")
            area_lbl.setStyleSheet("font-weight: 600;")
            layout.addWidget(area_lbl)

            area_table = QTableWidget(0, 6)
            area_table.setHorizontalHeaderLabels(
                [
                    "Area Polygon Names",
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

            post_table = QTableWidget(0, 6)
            post_table.setHorizontalHeaderLabels(
                ["Name", "Line Style", "Color", "P111/P190 Data", "Select Sequences", "Hide"]
            )
            _configure_legend_table(post_table)

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
                    postplot_lines=_collect_postplot_lines(),
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
                            lines.append(
                                PreplotLegendEntry(
                                    name=name,
                                    preplot_source_index=source_w.currentIndex(),
                                    line_style=cls._style_from_index(
                                        style_w.currentIndex()
                                    ),
                                    color=color_w.color,
                                    opacity=color_w.opacity,
                                    line_width=color_w.metric_value,
                                    dot_radius=color_w.metric_value,
                                    hidden=hide_w.isChecked(),
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
                    hide_w = post_table.cellWidget(row, 5)
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
                            lines.append(
                                PostplotLegendEntry(
                                    name=name,
                                    line_style=style,
                                    color=color_w.color,
                                    opacity=color_w.opacity,
                                    line_width=color_w.metric_value,
                                    dot_radius=color_w.metric_value,
                                    hidden=hide_w.isChecked(),
                                    data_type=data_type,
                                    sequence_ids=seq_ids,
                                    sequence_filter_active=filter_active,
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
                _fit_table_row(area_table, row)

            def apply_legend() -> None:
                on_apply(_collect())

            def live_apply(*_args) -> None:
                if live["on"]:
                    apply_legend()

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
                row = area_table.rowCount()
                area_table.insertRow(row)
                name_edit = QLineEdit(entry.name if entry else "")
                name_edit.editingFinished.connect(live_apply)
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

            def remove_area_row() -> None:
                row = area_table.currentRow()
                if row >= 0:
                    area_table.removeRow(row)
                    if row < len(row_custom_points):
                        del row_custom_points[row]
                    apply_legend()

            def _open_sequences(row: int, name: str) -> None:
                if not seq_list:
                    return

                def on_changed(ids: list[str]) -> None:
                    if row < len(row_sequence_ids):
                        row_sequence_ids[row] = ids
                    else:
                        while len(row_sequence_ids) <= row:
                            row_sequence_ids.append([])
                        row_sequence_ids[row] = ids
                    if row < len(row_sequence_filter_active):
                        row_sequence_filter_active[row] = True
                    else:
                        while len(row_sequence_filter_active) <= row:
                            row_sequence_filter_active.append(False)
                        row_sequence_filter_active[row] = True
                    btn = post_table.cellWidget(row, 4)
                    if isinstance(btn, QPushButton):
                        btn.setText(
                            f"Select Sequences ({len(ids)})"
                            if ids
                            else "Select Sequences"
                        )
                        _fit_table_row(post_table, row)
                    apply_legend()

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
                post_name = QLineEdit(name)
                post_name.editingFinished.connect(live_apply)
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

                post_metric = (
                    entry.dot_radius
                    if entry and entry.line_style == LineStyle.DOTTED
                    else entry.line_width if entry else 1.2
                )
                post_color = ColorButton(
                    entry.color if entry else "#ef4444",
                    entry.opacity if entry else 1.0,
                    post_metric,
                    post_metric_config,
                )
                post_color.color_changed.connect(live_apply)
                post_color.opacity_changed.connect(live_apply)
                post_color.metric_changed.connect(live_apply)
                post_table.setCellWidget(row, 2, post_color)

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

                hide_box = _hide_checkbox(entry.hidden if entry else False)
                hide_box.toggled.connect(live_apply)
                post_table.setCellWidget(row, 5, hide_box)
                _fit_table_row(post_table, row)

            def remove_post_row() -> None:
                row = post_table.currentRow()
                if row >= 0:
                    post_table.removeRow(row)
                    if row < len(row_sequence_ids):
                        del row_sequence_ids[row]
                    if row < len(row_sequence_filter_active):
                        del row_sequence_filter_active[row]
                    apply_legend()

            # Only show area rows the user has explicitly added. Imported
            # polygons, preplots and survey perimeters are NOT auto-added.
            for entry in non_imported_polygon_entries(legend.areas):
                add_area_row(entry)

            area_btns = QHBoxLayout()
            add_area_btn = QPushButton("Add Area Row")
            rem_area_btn = QPushButton("Remove Selected")
            add_area_btn.clicked.connect(add_area_row)
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

            def add_preplot_row(entry: PreplotLegendEntry | None = None) -> None:
                row = preplot_table.rowCount()
                preplot_table.insertRow(row)
                pp_name = QLineEdit(entry.name if entry else "")
                pp_name.editingFinished.connect(live_apply)
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

                preplot_metric = (
                    entry.dot_radius
                    if entry and entry.line_style == LineStyle.DOTTED
                    else entry.line_width if entry else 0.9
                )
                color_btn = ColorButton(
                    entry.color if entry else "#f59e0b",
                    entry.opacity if entry else 1.0,
                    preplot_metric,
                    preplot_metric_config,
                )
                color_btn.color_changed.connect(live_apply)
                color_btn.opacity_changed.connect(live_apply)
                color_btn.metric_changed.connect(live_apply)
                preplot_table.setCellWidget(row, 3, color_btn)

                hide_box = _hide_checkbox(entry.hidden if entry else False)
                hide_box.toggled.connect(live_apply)
                preplot_table.setCellWidget(row, 4, hide_box)
                _fit_table_row(preplot_table, row)

            def remove_preplot_row() -> None:
                row = preplot_table.currentRow()
                if row >= 0:
                    preplot_table.removeRow(row)
                    apply_legend()

            for entry in legend.preplot_lines:
                add_preplot_row(entry)

            preplot_btns = QHBoxLayout()
            add_preplot_btn = QPushButton("Add Preplot Row")
            rem_preplot_btn = QPushButton("Remove Selected")
            add_preplot_btn.clicked.connect(add_preplot_row)
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
            _set_table_viewport_rows(preplot_table, 4)
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
                apply_legend()

            def close_dialog() -> None:
                apply_legend()
                dialog.close()

            apply_btn.clicked.connect(apply_changes)
            close_btn.clicked.connect(close_dialog)
            action_row.addWidget(apply_btn)
            action_row.addWidget(close_btn)
            layout.addLayout(action_row)

            # All rows built: enable live updates for subsequent user edits.
            live["on"] = True

        SingleInstanceDialog.show_dialog(cls.KEY, "Legend", build, parent, width=980, height=900)
