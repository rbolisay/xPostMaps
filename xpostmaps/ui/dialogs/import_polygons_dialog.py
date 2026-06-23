"""Manage imported polygon layers in a dedicated non-modal window."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from xpostmaps.core.crs_utils import epsg_label
from xpostmaps.core.models import AreaLegendEntry, LegendConfig
from xpostmaps.core.polygon_import_service import (
    import_polygon_paths,
    imported_polygon_entries,
    non_imported_polygon_entries,
    renumber_imported_polygons,
    sync_legend_imported_references,
)
from xpostmaps.parsers.polygon_import_parser import collect_polygon_paths
from xpostmaps.ui.dialogs.base_dialog import SingleInstanceDialog
from xpostmaps.ui.theme import themed_open_directory, themed_open_files

_IMPORT_FILTER = (
    "Polygon Files (*.kml *.csv *.shp);;"
    "KML (*.kml);;CSV (*.csv);;Shapefile (*.shp);;"
    "All Files (*)"
)


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


def _configure_table(table: QTableWidget) -> None:
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setMinimumSectionSize(34)
    table.verticalHeader().setDefaultSectionSize(34)
    table.horizontalHeader().setSectionResizeMode(
        QHeaderView.ResizeMode.ResizeToContents
    )
    table.setWordWrap(False)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
    table.setAlternatingRowColors(True)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)


def _fit_table(table: QTableWidget) -> None:
    table.resizeRowsToContents()
    for row in range(table.rowCount()):
        table.setRowHeight(row, max(table.rowHeight(row), 34))
    for col in range(table.columnCount()):
        table.resizeColumnToContents(col)


def _set_table_viewport_rows(table: QTableWidget, visible_rows: int = 8) -> None:
    table.resizeRowsToContents()
    header_h = table.horizontalHeader().sizeHint().height()
    row_h = table.verticalHeader().defaultSectionSize()
    if table.rowCount() > 0:
        row_h = max(row_h, max(table.rowHeight(r) for r in range(table.rowCount())))
    frame = table.frameWidth() * 2
    viewport_h = header_h + row_h * visible_rows + frame
    table.setMinimumHeight(viewport_h)
    table.setMaximumHeight(viewport_h)


class ImportPolygonsDialog:
    KEY = "import_polygons"

    @classmethod
    def open(
        cls,
        parent: QWidget,
        legend: LegendConfig,
        map_epsg: str,
        on_apply: Callable[[LegendConfig], None],
        on_map_epsg_changed: Callable[[str], None] | None = None,
        initial_dir: str = "",
    ) -> None:
        state = {
            "map_epsg": map_epsg,
            "folder": initial_dir,
            "entries": list(imported_polygon_entries(legend.areas)),
        }

        def apply_changes() -> None:
            renumber_imported_polygons(state["entries"])
            sync_legend_imported_references(legend.areas)
            legend.areas = non_imported_polygon_entries(legend.areas) + list(state["entries"])
            sync_legend_imported_references(legend.areas)
            on_apply(legend)

        def refresh_table(table: QTableWidget) -> None:
            renumber_imported_polygons(state["entries"])
            table.setRowCount(0)
            for entry in state["entries"]:
                row = table.rowCount()
                table.insertRow(row)
                table.setItem(
                    row,
                    0,
                    QTableWidgetItem(str(entry.import_polygon_number)),
                )
                label = entry.name or Path(entry.source_file).stem or "Polygon"
                if entry.source_file and Path(entry.source_file).name not in label:
                    label = f"{label} ({Path(entry.source_file).name})"
                table.setItem(row, 1, QTableWidgetItem(label))
                crs_text = epsg_label(entry.source_epsg) if entry.source_epsg else "Unknown"
                table.setItem(row, 2, QTableWidgetItem(crs_text))
            _fit_table(table)
            _set_table_viewport_rows(table, 8)
            summary.setText(f"{len(state['entries'])} imported polygon(s)")

        def import_paths(paths: list[Path]) -> None:
            if not paths:
                return
            entries, updated_epsg = import_polygon_paths(parent, paths, state["map_epsg"])
            if not entries:
                return
            if updated_epsg and updated_epsg != state["map_epsg"]:
                state["map_epsg"] = updated_epsg
                if on_map_epsg_changed:
                    on_map_epsg_changed(updated_epsg)
            state["entries"].extend(entries)
            refresh_table(table)
            apply_changes()

        def browse_folder() -> None:
            folder = themed_open_directory(
                parent,
                "Import Polygons — Select Folder",
            )
            if not folder:
                return
            state["folder"] = folder
            import_paths(collect_polygon_paths([Path(folder)]))

        def add_files() -> None:
            paths = themed_open_files(
                parent,
                "Import Polygons — Select Files",
                _IMPORT_FILTER,
            )
            if not paths:
                return
            state["folder"] = str(Path(paths[0]).parent)
            import_paths(collect_polygon_paths([Path(p) for p in paths]))

        def remove_selected() -> None:
            rows = sorted({index.row() for index in table.selectedIndexes()}, reverse=True)
            if not rows:
                return
            for row in rows:
                if 0 <= row < len(state["entries"]):
                    del state["entries"][row]
            refresh_table(table)
            apply_changes()

        def build(dialog: SingleInstanceDialog) -> None:
            state["entries"] = list(imported_polygon_entries(legend.areas))
            layout = dialog.content_layout
            _clear_layout(layout)

            hint = QLabel(
                "Import KML, CSV, or shapefile polygons. "
                "Coordinates are converted to the map CRS when needed."
            )
            hint.setWordWrap(True)
            layout.addWidget(hint)

            btn_row = QHBoxLayout()
            browse_btn = QPushButton("Browse Folder…")
            files_btn = QPushButton("Add Files…")
            remove_btn = QPushButton("Remove Selected")
            for btn in (browse_btn, files_btn, remove_btn):
                btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                btn.setAutoDefault(False)
            browse_btn.clicked.connect(browse_folder)
            files_btn.clicked.connect(add_files)
            remove_btn.clicked.connect(remove_selected)
            btn_row.addWidget(browse_btn)
            btn_row.addWidget(files_btn)
            btn_row.addWidget(remove_btn)
            btn_row.addStretch()
            layout.addLayout(btn_row)

            nonlocal summary
            summary = QLabel("")
            summary.setStyleSheet("color: #8b949e; font-size: 11px;")
            layout.addWidget(summary)

            nonlocal table
            table = QTableWidget(0, 3)
            table.setHorizontalHeaderLabels(
                ["Import Polygon No.", "Polygon", "CRS"]
            )
            _configure_table(table)
            layout.addWidget(table)

            refresh_table(table)

            close_row = QHBoxLayout()
            close_btn = QPushButton("Close")
            close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            close_btn.clicked.connect(dialog.close)
            close_row.addStretch()
            close_row.addWidget(close_btn)
            layout.addLayout(close_row)

        summary = QLabel("")
        table = QTableWidget()

        return SingleInstanceDialog.show_dialog(
            cls.KEY,
            "Import Polygons",
            build,
            parent,
            width=760,
            height=560,
        )
