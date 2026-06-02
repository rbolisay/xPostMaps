"""Orchestrate polygon import with CRS detection and reprojection."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMenu,
    QMessageBox,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from xpostmaps.core.crs_utils import (
    WGS84_EPSG,
    crs_match,
    epsg_label,
    normalize_epsg,
    transform_coordinates,
)
from xpostmaps.core.models import (
    AreaCoordinateMode,
    AreaLegendEntry,
    LineStyle,
    PolygonPoint,
)
from xpostmaps.parsers.polygon_import_parser import (
    ImportedPolygon,
    collect_polygon_paths,
    parse_polygon_file,
)
from xpostmaps.ui.theme import (
    app_stylesheet,
    apply_menu_theme,
    themed_open_directory,
    themed_open_files,
)

_IMPORT_FILTER = (
    "Polygon Files (*.kml *.csv *.shp);;"
    "KML (*.kml);;"
    "CSV (*.csv);;"
    "Shapefile (*.shp);;"
    "All Files (*)"
)

_DEFAULT_COLORS = ("#22c55e", "#3b82f6", "#f59e0b", "#a855f7", "#ef4444", "#06b6d4")


class CsvCrsDialog(QDialog):
    """Ask whether CSV coordinates use the map CRS or WGS84 geographic."""

    def __init__(
        self,
        parent: QWidget | None,
        map_epsg: str,
        file_names: list[str],
    ) -> None:
        super().__init__(parent)
        self.setStyleSheet(app_stylesheet())
        self.setWindowTitle("CSV Coordinate System")
        self.setModal(True)
        self._choice = "map"

        layout = QVBoxLayout(self)
        files_text = ", ".join(file_names[:3])
        if len(file_names) > 3:
            files_text += f" (+{len(file_names) - 3} more)"
        layout.addWidget(
            QLabel(
                f"Select the coordinate system used by:\n{files_text}"
            )
        )

        map_label = f"Map CRS ({epsg_label(map_epsg) if map_epsg else 'not set — load preplot first'})"
        self._map_radio = QRadioButton(map_label)
        self._wgs_radio = QRadioButton("WGS84 (EPSG:4326 — latitude / longitude)")
        self._map_radio.setChecked(True)
        if not map_epsg:
            self._map_radio.setEnabled(False)
            self._wgs_radio.setChecked(True)
            self._choice = "wgs84"
        layout.addWidget(self._map_radio)
        layout.addWidget(self._wgs_radio)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def choice(self) -> str:
        if self._wgs_radio.isChecked():
            return "wgs84"
        return "map"


def _pick_import_paths(parent: QWidget, anchor: QWidget | None = None) -> list[Path]:
    menu = QMenu(parent)
    apply_menu_theme(menu)
    chosen: list[Path] = []

    def _files() -> None:
        paths = themed_open_files(
            parent,
            "Import Polygons — Select Files",
            _IMPORT_FILTER,
        )
        chosen.extend(Path(p) for p in paths)

    def _folder() -> None:
        directory = themed_open_directory(
            parent,
            "Import Polygons — Select Folder",
        )
        if directory:
            chosen.append(Path(directory))

    files_action = menu.addAction("Select Files…")
    folder_action = menu.addAction("Select Folder…")
    files_action.triggered.connect(_files)
    folder_action.triggered.connect(_folder)
    if anchor is not None:
        pos = anchor.mapToGlobal(anchor.rect().bottomLeft())
    else:
        pos = parent.mapToGlobal(parent.rect().center())
    menu.exec(pos)
    return chosen


def _assign_csv_epsg(
    parent: QWidget,
    csv_polygons: list[ImportedPolygon],
    map_epsg: str,
) -> bool:
    if not csv_polygons:
        return True
    file_names = sorted({poly.source_file for poly in csv_polygons})
    dialog = CsvCrsDialog(parent, map_epsg, file_names)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    if dialog.choice == "wgs84":
        for poly in csv_polygons:
            poly.source_epsg = WGS84_EPSG
            poly.is_geographic = True
        return True

    if not map_epsg:
        QMessageBox.warning(
            parent,
            "Import Polygons",
            "Map CRS is not set. Load a preplot file first or enter the EPSG code "
            "in Project Information, then import CSV coordinates in Map CRS.",
        )
        return False

    for poly in csv_polygons:
        poly.source_epsg = map_epsg
        poly.is_geographic = False
    return True


def _confirm_reproject(
    parent: QWidget,
    source_file: str,
    source_epsg: str,
    map_epsg: str,
    polygon_count: int,
) -> bool:
    reply = QMessageBox.question(
        parent,
        "Convert Coordinates",
        (
            f"{polygon_count} polygon(s) from '{source_file}' are in {epsg_label(source_epsg)}.\n"
            f"Map CRS is {epsg_label(map_epsg)}.\n\n"
            "Convert coordinates to Map CRS?"
        ),
        QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Ok,
    )
    return reply == QMessageBox.StandardButton.Ok


def _polygons_to_points(xs: list[float], ys: list[float]) -> list[PolygonPoint]:
    points: list[PolygonPoint] = []
    for x, y in zip(xs, ys):
        if x == x and y == y:
            points.append(PolygonPoint(x=x, y=y))
    return points


def _resolve_import_polygons(
    parent: QWidget,
    paths: list[Path],
    map_epsg: str,
) -> tuple[list[AreaLegendEntry], str]:
    """Parse, reproject, and build legend area entries. Returns entries and updated map EPSG."""
    resolved_map_epsg = normalize_epsg(map_epsg)
    file_paths = collect_polygon_paths(paths)
    if not file_paths:
        QMessageBox.information(parent, "Import Polygons", "No .kml, .csv, or .shp files found.")
        return [], resolved_map_epsg

    all_polygons: list[ImportedPolygon] = []
    for path in file_paths:
        parsed = parse_polygon_file(path)
        resolved = str(path.resolve())
        for poly in parsed:
            poly.source_file = resolved
        all_polygons.extend(parsed)

    if not all_polygons:
        QMessageBox.warning(
            parent,
            "Import Polygons",
            "No polygon geometry was found in the selected files.",
        )
        return [], resolved_map_epsg

    csv_polys = [p for p in all_polygons if p.source_file.lower().endswith(".csv")]
    if csv_polys and not _assign_csv_epsg(parent, csv_polys, resolved_map_epsg):
        return [], resolved_map_epsg

    for poly in all_polygons:
        if poly.source_epsg:
            continue
        if poly.is_geographic:
            poly.source_epsg = WGS84_EPSG
        elif resolved_map_epsg:
            poly.source_epsg = resolved_map_epsg

    by_file: dict[str, list[ImportedPolygon]] = defaultdict(list)
    for poly in all_polygons:
        by_file[poly.source_file].append(poly)

    entries: list[AreaLegendEntry] = []
    color_index = 0

    for source_file, file_polys in by_file.items():
        sample_epsg = next((p.source_epsg for p in file_polys if p.source_epsg), "")

        if not resolved_map_epsg and sample_epsg and not crs_match(sample_epsg, WGS84_EPSG):
            resolved_map_epsg = normalize_epsg(sample_epsg)

        needs_transform = (
            bool(resolved_map_epsg)
            and bool(sample_epsg)
            and not crs_match(sample_epsg, resolved_map_epsg)
        )

        if needs_transform:
            if not _confirm_reproject(
                parent,
                source_file,
                sample_epsg,
                resolved_map_epsg,
                len(file_polys),
            ):
                continue
        elif (
            sample_epsg
            and crs_match(sample_epsg, WGS84_EPSG)
            and not resolved_map_epsg
        ):
            QMessageBox.warning(
                parent,
                "Import Polygons",
                (
                    f"'{source_file}' is in WGS84 geographic coordinates, but Map CRS "
                    "is not set. Load a preplot or set EPSG in Project Information before importing."
                ),
            )
            continue

        for poly in file_polys:
            xs, ys = list(poly.xs), list(poly.ys)
            source_epsg = poly.source_epsg or sample_epsg

            if (
                resolved_map_epsg
                and source_epsg
                and not crs_match(source_epsg, resolved_map_epsg)
            ):
                xs, ys = transform_coordinates(xs, ys, source_epsg, resolved_map_epsg)
                if len(xs) < 3:
                    continue

            points = _polygons_to_points(xs, ys)
            if len(points) < 3:
                continue

            color = _DEFAULT_COLORS[color_index % len(_DEFAULT_COLORS)]
            color_index += 1
            entries.append(
                AreaLegendEntry(
                    name=poly.name,
                    border_style=LineStyle.SOLID,
                    color=color,
                    opacity=1.0,
                    custom_points=points,
                    source_file=source_file,
                    source_epsg=source_epsg or resolved_map_epsg or "",
                )
            )

    return entries, resolved_map_epsg


def renumber_imported_polygons(entries: list[AreaLegendEntry]) -> None:
    for index, entry in enumerate(entries, start=1):
        entry.import_polygon_number = index


def sync_legend_imported_references(legend_areas: list[AreaLegendEntry]) -> None:
    imported = imported_polygon_entries(legend_areas)
    renumber_imported_polygons(imported)
    for area in non_imported_polygon_entries(legend_areas):
        if area.coordinate_mode != AreaCoordinateMode.IMPORTED:
            continue
        if area.imported_polygon_index >= len(imported):
            area.coordinate_mode = AreaCoordinateMode.CUSTOM
            area.imported_polygon_index = 0


def is_imported_polygon(entry: AreaLegendEntry) -> bool:
    return entry.import_polygon_number > 0 and bool(entry.custom_points)


def imported_polygon_entries(legend_areas: list[AreaLegendEntry]) -> list[AreaLegendEntry]:
    return [entry for entry in legend_areas if is_imported_polygon(entry)]


def non_imported_polygon_entries(legend_areas: list[AreaLegendEntry]) -> list[AreaLegendEntry]:
    return [entry for entry in legend_areas if not is_imported_polygon(entry)]


def import_polygon_paths(
    parent: QWidget,
    paths: list[Path],
    map_epsg: str,
) -> tuple[list[AreaLegendEntry], str]:
    """Import polygon files and return legend entries plus updated map EPSG."""
    if not paths:
        return [], normalize_epsg(map_epsg)
    return _resolve_import_polygons(parent, paths, map_epsg)


def run_polygon_import(
    parent: QWidget,
    map_epsg: str,
    anchor: QWidget | None = None,
) -> tuple[list[AreaLegendEntry], str]:
    """Prompt for files/folder, import polygons, return legend entries and map EPSG."""
    paths = _pick_import_paths(parent, anchor)
    if not paths:
        return [], normalize_epsg(map_epsg)
    return import_polygon_paths(parent, paths, map_epsg)
