"""Legend configuration popup with editable tables."""

from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
)

from xpostmaps.core.models import (
    AreaLegendEntry,
    LegendConfig,
    LineSequence,
    LineStyle,
    NavDataType,
    PostplotLegendEntry,
    sequence_id_matches,
)
from xpostmaps.ui.dialogs.base_dialog import SingleInstanceDialog
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


class LegendDialog:
    KEY = "legend"

    _STYLE_LABELS = ("Solid", "Dotted", "Dash")
    _DATA_TYPE_LABELS = ("Vessel", "Source")

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
        on_delete_sequences: Callable[[list[str]], None] | None = None,
        sequences_provider: Callable[[], list[LineSequence]] | None = None,
    ) -> None:
        seq_list: list[LineSequence] = list(sequences or [])
        row_sequence_ids: list[list[str]] = []

        def build(dialog: SingleInstanceDialog) -> None:
            layout = dialog.content_layout
            _clear_layout(layout)

            title = QLabel("Legend")
            title.setObjectName("sectionTitle")
            layout.addWidget(title)

            area_lbl = QLabel("Area")
            area_lbl.setStyleSheet("font-weight: 600;")
            layout.addWidget(area_lbl)

            area_table = QTableWidget(0, 2)
            area_table.setHorizontalHeaderLabels(["Area Name", "Border Color"])
            area_table.verticalHeader().setVisible(False)
            area_table.horizontalHeader().setSectionResizeMode(
                QHeaderView.ResizeMode.ResizeToContents
            )

            post_lbl = QLabel("PostPlot")
            post_lbl.setStyleSheet("font-weight: 600; margin-top: 8px;")

            post_table = QTableWidget(0, 5)
            post_table.setHorizontalHeaderLabels(
                ["Name", "Line Style", "Color", "P111/P190 Data", "Select Sequences"]
            )
            post_table.verticalHeader().setVisible(False)
            post_table.horizontalHeader().setSectionResizeMode(
                QHeaderView.ResizeMode.ResizeToContents
            )

            def _collect() -> LegendConfig:
                areas: list[AreaLegendEntry] = []
                for row in range(area_table.rowCount()):
                    name_w = area_table.cellWidget(row, 0)
                    color_w = area_table.cellWidget(row, 1)
                    if isinstance(name_w, QLineEdit) and isinstance(color_w, ColorButton):
                        name = name_w.text().strip()
                        if name:
                            areas.append(
                                AreaLegendEntry(
                                    name=name,
                                    color=color_w.color,
                                    opacity=color_w.opacity,
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

            def add_area_row(entry: AreaLegendEntry | None = None) -> None:
                row = area_table.rowCount()
                area_table.insertRow(row)
                area_table.setCellWidget(row, 0, QLineEdit(entry.name if entry else ""))
                area_table.setCellWidget(
                    row, 1, ColorButton(entry.color if entry else "#22c55e", entry.opacity if entry else 1.0)
                )

            def remove_area_row() -> None:
                row = area_table.currentRow()
                if row >= 0:
                    area_table.removeRow(row)

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

                def refresh_sequences() -> list[LineSequence]:
                    if sequences_provider:
                        seq_list.clear()
                        seq_list.extend(sequences_provider())
                    return list(seq_list)

                def delete_sequences(ids: list[str]) -> None:
                    if on_delete_sequences:
                        on_delete_sequences(ids)
                    for idx in range(len(row_sequence_ids)):
                        row_sequence_ids[idx] = [
                            seq_id
                            for seq_id in row_sequence_ids[idx]
                            if not sequence_id_matches(seq_id, ids)
                        ]
                        btn = post_table.cellWidget(idx, 4)
                        if isinstance(btn, QPushButton):
                            count = len(row_sequence_ids[idx])
                            btn.setText(
                                f"Select Sequences ({count})"
                                if count
                                else "Select Sequences"
                            )

                SequencesDialog.open(
                    parent=dialog,
                    legend_row_name=name,
                    sequences=seq_list,
                    selected_ids=row_sequence_ids[row] if row < len(row_sequence_ids) else [],
                    on_changed=on_changed,
                    on_delete=delete_sequences if on_delete_sequences else None,
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
                seq_btn = QPushButton(
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

            layout.addWidget(area_table)
            layout.addLayout(area_btns)
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

            layout.addWidget(post_table)
            layout.addLayout(post_btns)

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

        SingleInstanceDialog.show_dialog(cls.KEY, "Legend", build, parent, width=760)
