"""Custom polygon coordinate editor for legend area rows."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from xpostmaps.core.models import PolygonPoint
from xpostmaps.ui.dialogs.base_dialog import SingleInstanceDialog


class CustomPolygonDialog:
    KEY_PREFIX = "custom_polygon_"

    @classmethod
    def open(
        cls,
        parent,
        area_name: str,
        points: list[PolygonPoint],
        on_changed,
        row_key: str = "",
    ) -> None:
        dialog_key = f"{cls.KEY_PREFIX}{row_key or area_name}"
        working_points = [PolygonPoint(p.x, p.y, p.latitude, p.longitude) for p in points]

        def build(dialog: SingleInstanceDialog) -> None:
            layout = dialog.content_layout
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
                else:
                    child = item.layout()
                    if child is not None:
                        while child.count():
                            sub = child.takeAt(0)
                            w = sub.widget()
                            if w is not None:
                                w.deleteLater()

            mode_row = QHBoxLayout()
            en_radio = QRadioButton("Northing / Easting")
            ll_radio = QRadioButton("Latitude / Longitude")
            en_radio.setChecked(True)
            mode_row.addWidget(en_radio)
            mode_row.addWidget(ll_radio)
            mode_row.addStretch()

            table = QTableWidget(0, 2)
            table.setHorizontalHeaderLabels(["Easting", "Northing"])
            table.verticalHeader().setVisible(False)
            table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
            table.horizontalHeader().setSectionResizeMode(
                QHeaderView.ResizeMode.ResizeToContents
            )

            def _apply_headers(use_en: bool) -> None:
                if use_en:
                    table.setHorizontalHeaderLabels(["Easting", "Northing"])
                else:
                    table.setHorizontalHeaderLabels(["Latitude", "Longitude"])

            def _populate() -> None:
                use_en = en_radio.isChecked()
                _apply_headers(use_en)
                table.setRowCount(len(working_points))
                for row, point in enumerate(working_points):
                    if use_en:
                        values = (
                            f"{point.x:.3f}" if point.x == point.x else "",
                            f"{point.y:.3f}" if point.y == point.y else "",
                        )
                    else:
                        values = (point.latitude, point.longitude)
                    for col, text in enumerate(values):
                        table.setItem(row, col, QTableWidgetItem(text))

            def _collect_from_table() -> None:
                use_en = en_radio.isChecked()
                rows = max(table.rowCount(), len(working_points))
                collected: list[PolygonPoint] = []
                for row in range(rows):
                    first = table.item(row, 0)
                    second = table.item(row, 1)
                    val1 = first.text().strip() if first else ""
                    val2 = second.text().strip() if second else ""
                    if not val1 and not val2:
                        continue
                    point = PolygonPoint()
                    if use_en:
                        try:
                            point.x = float(val1)
                            point.y = float(val2)
                        except ValueError:
                            continue
                    else:
                        point.latitude = val1
                        point.longitude = val2
                    collected.append(point)
                working_points.clear()
                working_points.extend(collected)

            def _sync_mode() -> None:
                _collect_from_table()
                _populate()

            en_radio.toggled.connect(lambda checked: _sync_mode() if checked else None)

            def add_point() -> None:
                _collect_from_table()
                working_points.append(PolygonPoint())
                _populate()

            def delete_selected() -> None:
                _collect_from_table()
                selected = sorted(
                    {index.row() for index in table.selectionModel().selectedRows()},
                    reverse=True,
                )
                for row in selected:
                    if 0 <= row < len(working_points):
                        del working_points[row]
                _populate()

            def commit_and_close() -> None:
                _collect_from_table()
                on_changed(
                    [PolygonPoint(p.x, p.y, p.latitude, p.longitude) for p in working_points]
                )
                dialog.close()

            btn_row = QHBoxLayout()
            add_btn = QPushButton("Add Point")
            delete_btn = QPushButton("Delete Selected")
            ok_btn = QPushButton("OK")
            ok_btn.setObjectName("primaryBtn")
            close_btn = QPushButton("Close")
            add_btn.clicked.connect(add_point)
            delete_btn.clicked.connect(delete_selected)
            ok_btn.clicked.connect(commit_and_close)
            close_btn.clicked.connect(dialog.close)
            btn_row.addWidget(add_btn)
            btn_row.addWidget(delete_btn)
            btn_row.addStretch()
            btn_row.addWidget(ok_btn)
            btn_row.addWidget(close_btn)

            layout.addLayout(mode_row)
            layout.addWidget(table)
            layout.addLayout(btn_row)
            _populate()

        SingleInstanceDialog.show_dialog(
            dialog_key,
            f"Custom Polygon — {area_name or 'Area'}",
            build,
            parent,
            width=520,
        )
