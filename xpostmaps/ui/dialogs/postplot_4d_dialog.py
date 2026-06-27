"""Postplot 4D matching window."""

from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from xpostmaps.core.coord_format import GeoDisplayFormatter, format_geo_display
from xpostmaps.core.crs_utils import normalize_epsg
from xpostmaps.core.database import Database
from xpostmaps.core.models import MapData, PositionRecord, ProjectSettings
from xpostmaps.core.postplot_4d_diff import (
    CrsMismatchError,
    Postplot4DDiffRow,
    calculate_match_diff_rows,
    resolve_diff_map_epsg,
    source_has_streamers,
)
from xpostmaps.core.postplot_4d_diff_worker import DiffStatRecalcWorker
from xpostmaps.core.postplot_4d_matching import (
    BaselineKind,
    Postplot4DMatchRow,
    build_postplot_4d_rows,
)
from xpostmaps.parsers.metadata_parser import parse_file_metadata
from xpostmaps.ui.dialogs.base_dialog import SingleInstanceDialog

CoordMode = Literal["en", "lat"]

_BASELINE_BUTTON_STYLE = """
QPushButton {
    background: #263244;
    color: #e6edf3;
    border: 1px solid #3b4a5f;
    border-radius: 6px;
    padding: 5px 16px;
}
QPushButton:checked {
    background: #000000;
    color: #ffffff;
    border: 2px solid #58a6ff;
    font-weight: 700;
}
"""


def _clear_layout(layout: QVBoxLayout) -> None:
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
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    table.setWordWrap(False)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    table.setAlternatingRowColors(True)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)


def _fit_table(table: QTableWidget) -> None:
    table.resizeRowsToContents()
    for row in range(table.rowCount()):
        table.setRowHeight(row, max(table.rowHeight(row), 34))
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.resizeSections(QHeaderView.ResizeMode.ResizeToContents)


def _coord_toggle_label(mode: CoordMode) -> str:
    return "Lat / Long" if mode == "en" else "Easting / Northing"


def _set_diff_table_item(
    table: QTableWidget,
    row_idx: int,
    col: int,
    value: str,
) -> None:
    item = table.item(row_idx, col)
    if item is None:
        item = QTableWidgetItem(value)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        if col >= 5:
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        table.setItem(row_idx, col, item)
    else:
        item.setText(value)


def _finalize_diff_table_layout(table: QTableWidget) -> None:
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.resizeSections(QHeaderView.ResizeMode.ResizeToContents)


def _table_content_width(table: QTableWidget) -> int:
    """Total pixel width needed to show every column without truncation."""
    width = 0
    v_header = table.verticalHeader()
    if v_header is not None and v_header.isVisible():
        width += v_header.width()
    for col in range(table.columnCount()):
        width += table.columnWidth(col)
    width += table.frameWidth() * 2
    scrollbar = table.verticalScrollBar()
    if scrollbar is not None and scrollbar.maximum() > 0:
        width += scrollbar.sizeHint().width()
    return width


def _autosize_dialog_width(
    dialog: QWidget | None,
    table: QTableWidget,
    *,
    min_width: int = 760,
    chrome: int = 90,
) -> None:
    """Resize the dialog width to fit the table contents, clamped to the screen."""
    if dialog is None:
        return
    target = _table_content_width(table) + chrome
    screen = QApplication.primaryScreen()
    if screen is not None:
        max_width = int(screen.availableGeometry().width() * 0.96)
        target = min(target, max_width)
    target = max(min_width, target)
    dialog.resize(target, dialog.height())


_BULK_RECALC_LABEL = "Recalculate Diff Stat"
_BULK_CANCEL_LABEL = "Cancel Recalc"

_DIFF_SUMMARY_STYLE = "color: #8b949e; font-size: 11px;"
_DIFF_SUMMARY_BUSY_STYLE = "color: #58a6ff; font-size: 11px;"
_DIFF_SUMMARY_DONE_STYLE = "color: #3fb950; font-size: 11px;"


def _set_diff_summary(label: QLabel, text: str, *, tone: str = "normal") -> None:
    label.setText(text)
    if tone == "busy":
        label.setStyleSheet(_DIFF_SUMMARY_BUSY_STYLE)
    elif tone == "done":
        label.setStyleSheet(_DIFF_SUMMARY_DONE_STYLE)
    else:
        label.setStyleSheet(_DIFF_SUMMARY_STYLE)


def _show_host_status(host: QWidget, message: str, timeout_ms: int = 6000) -> None:
    target: QWidget | None = host
    if not hasattr(target, "statusBar") and target.parent() is not None:
        target = target.parent()
    if target is not None and hasattr(target, "statusBar"):
        target.statusBar().showMessage(message, timeout_ms)


def _format_coord(value: float) -> str:
    return f"{value:.3f}"


def _format_offset(value: float) -> str:
    return f"{value:.3f}"


def _format_feather(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.1f}"


def _natural_sort_key(text: str) -> tuple:
    parts = re.split(r"(\d+)", (text or "").upper())
    key: list[int | str] = []
    for part in parts:
        if part.isdigit():
            key.append(int(part))
        else:
            key.append(part)
    return tuple(key)


def _sort_match_rows(
    rows: list[Postplot4DMatchRow],
    column: int,
    order: Qt.SortOrder,
) -> list[Postplot4DMatchRow]:
    reverse = order == Qt.SortOrder.DescendingOrder

    if column == 3:
        with_seq = [row for row in rows if row.has_match and row.sequence_no.strip()]
        without_seq = [row for row in rows if row not in with_seq]

        def seq_key(row: Postplot4DMatchRow) -> tuple[int | str, ...]:
            try:
                return (int(row.sequence_no), row.sequence_no.upper())
            except ValueError:
                return (-1, row.sequence_no.upper())

        return sorted(with_seq, key=seq_key, reverse=reverse) + without_seq

    return sorted(
        rows,
        key=lambda row: (_natural_sort_key(row.baseline_name), row.baseline_name.upper()),
        reverse=reverse,
    )


def _diff_title(match_row: Postplot4DMatchRow) -> str:
    if match_row.subline:
        return f"{match_row.line_name}.{match_row.subline} Diff Stat Table"
    return f"{match_row.line_name} Diff Stat Table"


def _baseline_coord_headers(baseline_kind: BaselineKind, coord_mode: CoordMode) -> tuple[str, str]:
    label = "Navplan" if baseline_kind == "navplan" else "Preplot"
    if coord_mode == "lat":
        return f"{label} Latitude", f"{label} Longitude"
    return f"{label} Easting", f"{label} Northing"


def _source_coord_headers(coord_mode: CoordMode) -> tuple[str, str]:
    if coord_mode == "lat":
        return "Firing Source Latitude", "Firing Source Longitude"
    return "Firing Source Easting", "Firing Source Northing"


class Postplot4DDialog:
    KEY = "postplot_4d"

    @classmethod
    def open(
        cls,
        parent: QWidget,
        settings: ProjectSettings,
        map_data: MapData | None,
        on_baseline_changed: Callable[[], None] | None = None,
        project_name: str = "",
        positions_provider: Callable[[], list[PositionRecord]] | None = None,
        map_data_provider: Callable[[], MapData | None] | None = None,
        database: Database | None = None,
        on_diffs_saved: Callable[[], None] | None = None,
    ) -> SingleInstanceDialog:
        saved_baseline = settings.postplot_4d_baseline
        if saved_baseline not in ("navplan", "preplot"):
            saved_baseline = (
                "navplan"
                if map_data and map_data.navplan_segments
                else "preplot"
            )
        state: dict[
            str,
            BaselineKind | CoordMode | Postplot4DMatchRow | Qt.SortOrder | None | str | int,
        ] = {
            "baseline": saved_baseline,
            "coord_mode": "en",
            "active_match": None,
            "map_epsg": resolve_diff_map_epsg(map_data, settings),
            "sort_column": 0,
            "sort_order": Qt.SortOrder.AscendingOrder,
        }
        row_cache: dict[BaselineKind, list[Postplot4DMatchRow]] = {}
        crs_cache: dict[str, str] = {}
        diff_rows: list[Postplot4DDiffRow] = []
        bulk_recalc_worker: DiffStatRecalcWorker | None = None
        single_recalc_worker: DiffStatRecalcWorker | None = None
        bulk_recalc_launch_pending = False
        host_dialog: SingleInstanceDialog | None = None
        crs_note: QLabel | None = None
        diff_crs_note: QLabel | None = None

        def current_map_data() -> MapData | None:
            if map_data_provider is not None:
                return map_data_provider()
            return map_data

        def rows_for(kind: BaselineKind) -> list[Postplot4DMatchRow]:
            if kind not in row_cache:
                row_cache[kind] = build_postplot_4d_rows(current_map_data(), settings, kind)
            return row_cache[kind]

        def invalidate_row_cache() -> None:
            row_cache.clear()
            state["map_epsg"] = resolve_diff_map_epsg(current_map_data(), settings)

        def positions() -> list[PositionRecord]:
            active_map_data = current_map_data()
            if positions_provider is None:
                return list(active_map_data.positions) if active_map_data else []
            return list(positions_provider())

        def _parse_saved_at(value: str) -> datetime | None:
            if not value:
                return None
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None

        def _dependency_candidates(file_ref: str) -> list[Path]:
            if not file_ref:
                return []
            active_map_data = current_map_data()
            raw = Path(file_ref)
            refs: list[str] = [
                file_ref,
                *(active_map_data.source_files if active_map_data else []),
                *settings.nav_files,
                *settings.preplot_files,
                *settings.navplan_files,
                *(entry.file_path for entry in settings.preplot_catalog),
                *(entry.file_path for entry in settings.navplan_catalog),
            ]
            folders = [
                settings.p111_p190_dir,
                settings.preplots_dir,
                settings.navplans_dir,
            ]
            candidates: list[Path] = [raw]
            candidates.extend(Path(folder) / raw.name for folder in folders if folder)
            target_name = raw.name
            for ref in refs:
                path = Path(ref)
                if path.name == target_name:
                    candidates.append(path)
            seen: set[str] = set()
            unique: list[Path] = []
            for path in candidates:
                key = str(path)
                if key in seen:
                    continue
                seen.add(key)
                unique.append(path)
            return unique

        def _resolve_existing_file(file_ref: str) -> Path | None:
            for path in _dependency_candidates(file_ref):
                if path.is_file():
                    return path
            return None

        def _file_crs(path: Path | None) -> str:
            if path is None:
                return ""
            key = str(path.resolve())
            if key not in crs_cache:
                try:
                    metadata = parse_file_metadata(path)
                except OSError:
                    crs_cache[key] = ""
                else:
                    crs_cache[key] = normalize_epsg(metadata.get("epsg code", ""))
            return crs_cache[key]

        def _crs_display(path: Path | None) -> str:
            if path is None:
                return "unknown file"
            code = _file_crs(path)
            return f"{path.name}: EPSG {code}" if code else f"{path.name}: CRS unknown"

        def _source_file_for_match(match_row: Postplot4DMatchRow) -> Path | None:
            source_file = match_row.sequence_id.split("|", 1)[0] if match_row.sequence_id else ""
            return _resolve_existing_file(source_file)

        def _baseline_file_for_match(match_row: Postplot4DMatchRow) -> Path | None:
            return _resolve_existing_file(match_row.baseline_file_name)

        def _crs_note_for_match(match_row: Postplot4DMatchRow | None) -> str:
            diff_crs = str(state.get("map_epsg", "") or "")
            diff_label = f"EPSG {diff_crs}" if diff_crs else "unknown CRS"
            if match_row is None:
                baseline_label = "select a Diff Stat row to see exact baseline file CRS"
                source_label = "select a Diff Stat row to see exact P111/P190 CRS"
            else:
                baseline_name = "Preplot" if match_row.baseline_kind == "preplot" else "Navplan"
                baseline_label = f"{baseline_name} {_crs_display(_baseline_file_for_match(match_row))}"
                source_label = f"P111/P190 {_crs_display(_source_file_for_match(match_row))}"
            return (
                f"CRS in use: Diff/map {diff_label}  |  "
                f"{baseline_label}  |  {source_label}"
            )

        def _cached_file_mtime(active_db: Database | None, file_ref: str) -> float | None:
            # Read the file mtime recorded in the DB at import time instead of
            # stat()-ing the live (often network) file. Network stat() costs
            # ~1s/call, so this keeps the "skip already-calculated" check fast.
            if active_db is None or not project_name.strip() or not file_ref:
                return None
            name = Path(file_ref).name
            try:
                cached = active_db.load_postplot_4d_file_cache_by_name(
                    project_name.strip(), name
                )
            except Exception:  # noqa: BLE001
                return None
            if cached and cached.get("file_mtime"):
                return float(cached["file_mtime"])
            return None

        def _cached_file_newer_than_saved(
            active_db: Database | None,
            file_ref: str,
            saved_at: datetime | None,
        ) -> bool:
            mtime = _cached_file_mtime(active_db, file_ref)
            if mtime is None or saved_at is None:
                return False
            modified_at = datetime.fromtimestamp(mtime, tz=saved_at.tzinfo)
            return modified_at > saved_at

        def diff_needs_recalculate(
            match_row: Postplot4DMatchRow,
            db: Database | None = None,
        ) -> bool:
            active_db = database if db is None else db
            if active_db is None or not project_name.strip():
                return True
            saved_at = _parse_saved_at(
                active_db.postplot_4d_diffs_updated_at(
                    project_name.strip(),
                    match_row.baseline_kind,
                    match_row.sequence_id,
                )
            )
            if saved_at is None:
                return True
            source_ref = (
                match_row.sequence_id.split("|", 1)[0] if match_row.sequence_id else ""
            )
            return (
                _cached_file_newer_than_saved(active_db, source_ref, saved_at)
                or _cached_file_newer_than_saved(
                    active_db, match_row.baseline_file_name, saved_at
                )
            )

        def persist_diff_rows(
            match_row: Postplot4DMatchRow,
            rows: list[Postplot4DDiffRow],
            *,
            notify: bool = True,
        ) -> None:
            if database is None or not project_name.strip():
                return
            database.save_postplot_4d_diffs(
                project_name.strip(),
                match_row.baseline_kind,
                match_row.baseline_name,
                match_row.sequence_id,
                rows,
            )
            if notify and on_diffs_saved is not None:
                on_diffs_saved()

        def _source_has_streamers_for_match(match_row: Postplot4DMatchRow) -> bool:
            return source_has_streamers(
                _source_file_for_match(match_row),
                database=database,
                project_name=project_name,
            )

        def load_or_calculate_diffs(
            match_row: Postplot4DMatchRow,
        ) -> tuple[list[Postplot4DDiffRow], str]:
            if (
                database is not None
                and project_name.strip()
            ):
                stored = database.load_postplot_4d_diffs(
                    project_name.strip(),
                    match_row.baseline_kind,
                    match_row.sequence_id,
                )
                if stored:
                    return stored, "loaded"
            rows = calculate_match_diff_rows(
                current_map_data(),
                settings,
                positions(),
                match_row,
                database=database,
                project_name=project_name,
            )
            persist_diff_rows(match_row, rows)
            return rows, "calculated"

        def refresh_diff_table() -> None:
            match_row = state["active_match"]
            if not isinstance(match_row, Postplot4DMatchRow):
                return
            coord_mode = state["coord_mode"]
            assert coord_mode in ("en", "lat")
            baseline_h1, baseline_h2 = _baseline_coord_headers(match_row.baseline_kind, coord_mode)
            source_h1, source_h2 = _source_coord_headers(coord_mode)
            # Navplan Feather is the baseline feather and only exists for a
            # navplan baseline. Line Feather is the firing-source streamer
            # feather: show it whenever streamers were detected in the P111/P190
            # (line feather values present), even for a preplot baseline.
            show_navplan_feather = match_row.baseline_kind == "navplan"
            show_line_feather = any(
                diff_row.line_feather_deg is not None for diff_row in diff_rows
            ) or _source_has_streamers_for_match(match_row)
            column_labels = [
                "Shotpoint No.",
                baseline_h1,
                baseline_h2,
            ]
            if show_navplan_feather:
                column_labels.append("Navplan Feather")
            column_labels.extend(
                [
                    source_h1,
                    source_h2,
                    "Crossline (m)",
                    "Inline (m)",
                    "Radial (m)",
                ]
            )
            if show_line_feather:
                column_labels.append("Line Feather")
            header = diff_table.horizontalHeader()
            header.blockSignals(True)
            header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
            diff_table.setUpdatesEnabled(False)
            diff_table.setSortingEnabled(False)
            diff_table.setColumnCount(len(column_labels))
            diff_table.setHorizontalHeaderLabels(column_labels)
            row_count = len(diff_rows)
            if diff_table.rowCount() != row_count:
                diff_table.setRowCount(row_count)
            try:
                map_epsg = str(state.get("map_epsg", "") or "")
                geo_formatter = (
                    GeoDisplayFormatter(map_epsg) if coord_mode == "lat" else None
                )
                for row_idx, diff_row in enumerate(diff_rows):
                    diff_table.setRowHeight(row_idx, 34)
                    if coord_mode == "lat":
                        baseline_a = format_geo_display(
                            diff_row.baseline_latitude,
                            diff_row.baseline_x,
                            is_latitude=True,
                            formatter=geo_formatter,
                            other_projected=diff_row.baseline_y,
                        )
                        baseline_b = format_geo_display(
                            diff_row.baseline_longitude,
                            diff_row.baseline_y,
                            is_latitude=False,
                            formatter=geo_formatter,
                            other_projected=diff_row.baseline_x,
                        )
                        source_a = format_geo_display(
                            diff_row.source_latitude,
                            diff_row.source_x,
                            is_latitude=True,
                            formatter=geo_formatter,
                            other_projected=diff_row.source_y,
                        )
                        source_b = format_geo_display(
                            diff_row.source_longitude,
                            diff_row.source_y,
                            is_latitude=False,
                            formatter=geo_formatter,
                            other_projected=diff_row.source_x,
                        )
                    else:
                        baseline_a = _format_coord(diff_row.baseline_x)
                        baseline_b = _format_coord(diff_row.baseline_y)
                        source_a = _format_coord(diff_row.source_x)
                        source_b = _format_coord(diff_row.source_y)
                    values = [
                        str(diff_row.shotpoint),
                        baseline_a,
                        baseline_b,
                    ]
                    if show_navplan_feather:
                        values.append(_format_feather(diff_row.navplan_feather_deg))
                    values.extend(
                        [
                            source_a,
                            source_b,
                            _format_offset(diff_row.crossline_m),
                            _format_offset(diff_row.inline_m),
                            _format_offset(diff_row.radial_m),
                        ]
                    )
                    if show_line_feather:
                        values.append(_format_feather(diff_row.line_feather_deg))
                    for col, value in enumerate(values):
                        _set_diff_table_item(diff_table, row_idx, col, value)
            finally:
                diff_table.setUpdatesEnabled(True)
                header.blockSignals(False)
            _finalize_diff_table_layout(diff_table)
            _autosize_dialog_width(host_dialog, diff_table)

        def show_diff_stat(match_row: Postplot4DMatchRow) -> None:
            nonlocal diff_rows
            state["active_match"] = match_row
            try:
                diff_rows, source = load_or_calculate_diffs(match_row)
            except CrsMismatchError as exc:
                diff_rows = []
                diff_title.setText(_diff_title(match_row))
                if diff_crs_note is not None:
                    diff_crs_note.setText(_crs_note_for_match(match_row))
                refresh_diff_table()
                _set_diff_summary(
                    diff_summary,
                    f"Diff Stat blocked — CRS not verified: {exc}",
                    tone="busy",
                )
                if host_dialog is not None:
                    host_dialog.setWindowTitle(_diff_title(match_row))
                stack.setCurrentIndex(1)
                return
            diff_title.setText(_diff_title(match_row))
            if diff_crs_note is not None:
                diff_crs_note.setText(_crs_note_for_match(match_row))
            refresh_diff_table()
            if source == "loaded":
                summary = (
                    f"{len(diff_rows)} shotpoint difference(s) · "
                    "Loaded from saved project data"
                )
            else:
                summary = (
                    f"{len(diff_rows)} shotpoint difference(s) · "
                    "Calculated on open"
                )
            _set_diff_summary(diff_summary, summary, tone="normal")
            if host_dialog is not None:
                host_dialog.setWindowTitle(_diff_title(match_row))
            stack.setCurrentIndex(1)

        def show_main_view() -> None:
            state["active_match"] = None
            stack.setCurrentIndex(0)
            _autosize_dialog_width(host_dialog, table)
            if host_dialog is not None:
                host_dialog.setWindowTitle("Postplot 4D")

        def _persist_note() -> str:
            if database is not None and project_name.strip():
                return "saved to project"
            return "not saved (no project database)"

        def recalculate_diffs() -> None:
            nonlocal single_recalc_worker
            match_row = state["active_match"]
            if not isinstance(match_row, Postplot4DMatchRow):
                return
            if single_recalc_worker is not None and single_recalc_worker.isRunning():
                return
            if database is None or not project_name.strip():
                # No DB project is available to hand work to a background worker;
                # keep the old direct path for unsaved/ad-hoc projects.
                nonlocal diff_rows
                recalc_btn.setEnabled(False)
                coord_toggle.setEnabled(False)
                _set_diff_summary(diff_summary, "Recalculating differences…", tone="busy")
                recalc_btn.setText("Recalculating…")
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                QApplication.processEvents()
                started = time.perf_counter()
                try:
                    diff_rows = calculate_match_diff_rows(
                        current_map_data(),
                        settings,
                        positions(),
                        match_row,
                        database=database,
                        project_name=project_name,
                    )
                    persist_diff_rows(match_row, diff_rows)
                    refresh_diff_table()
                    elapsed = time.perf_counter() - started
                    stamp = datetime.now().strftime("%H:%M:%S")
                    summary = (
                        f"{len(diff_rows)} shotpoint difference(s) · "
                        f"Recalculated at {stamp} ({elapsed:.1f} s, {_persist_note()})"
                    )
                    _set_diff_summary(diff_summary, summary, tone="done")
                    if parent is not None:
                        _show_host_status(
                            parent,
                            f"Diff stat recalculated: {len(diff_rows)} shotpoint(s) in {elapsed:.1f} s",
                        )
                except Exception as exc:  # noqa: BLE001
                    _set_diff_summary(diff_summary, f"Recalculate failed: {exc}", tone="busy")
                    if parent is not None:
                        _show_host_status(parent, f"Diff stat recalculate failed: {exc}", 8000)
                finally:
                    recalc_btn.setEnabled(True)
                    coord_toggle.setEnabled(True)
                    recalc_btn.setText("Recalculate Diffs")
                    QApplication.restoreOverrideCursor()
                return

            recalc_btn.setEnabled(False)
            coord_toggle.setEnabled(False)
            _set_diff_summary(diff_summary, "Recalculating differences…", tone="busy")
            recalc_btn.setText("Recalculating…")
            started = time.perf_counter()

            def _on_single_finished(
                recalculated: int,
                skipped: int,
                failed: int,
                elapsed: float,
                cancelled: bool,
            ) -> None:
                nonlocal diff_rows, single_recalc_worker
                single_recalc_worker = None
                recalc_btn.setEnabled(True)
                coord_toggle.setEnabled(True)
                recalc_btn.setText("Recalculate Diffs")
                if cancelled:
                    _set_diff_summary(diff_summary, "Recalculate cancelled.", tone="normal")
                    return
                if failed:
                    _set_diff_summary(diff_summary, "Recalculate failed.", tone="busy")
                    return
                stored = database.load_postplot_4d_diffs(
                    project_name.strip(),
                    match_row.baseline_kind,
                    match_row.sequence_id,
                )
                diff_rows = stored
                refresh_diff_table()
                elapsed = time.perf_counter() - started
                stamp = datetime.now().strftime("%H:%M:%S")
                summary = (
                    f"{len(diff_rows)} shotpoint difference(s) · "
                    f"Recalculated at {stamp} ({elapsed:.1f} s, {_persist_note()})"
                )
                _set_diff_summary(diff_summary, summary, tone="done")
                status = (
                    f"Diff stat recalculated: {len(diff_rows)} shotpoint(s) in {elapsed:.1f} s"
                )
                if parent is not None:
                    _show_host_status(parent, status)
                if not cancelled and on_diffs_saved is not None:
                    on_diffs_saved()
                QTimer.singleShot(
                    5000,
                    lambda: _set_diff_summary(
                        diff_summary,
                        summary,
                        tone="normal",
                    ),
                )

            single_recalc_worker = DiffStatRecalcWorker(
                current_map_data,
                settings,
                positions,
                match_rows=[match_row],
                load_source_positions_per_match=True,
                db_path=database.db_path,
                project_name=project_name.strip(),
                parent=host_dialog or parent,
            )
            single_recalc_worker.progress.connect(
                lambda completed, total, detail: _set_diff_summary(
                    diff_summary,
                    f"Recalculating differences… {completed}/{total}: {detail}",
                    tone="busy",
                )
            )
            single_recalc_worker.finished_batch.connect(_on_single_finished)
            single_recalc_worker.start()

        def _bulk_recalc_running() -> bool:
            return (
                bulk_recalc_launch_pending
                or bulk_recalc_worker is not None
                and bulk_recalc_worker.isRunning()
            )

        def _reset_bulk_recalc_button() -> None:
            bulk_recalc_btn.setText(_BULK_RECALC_LABEL)
            bulk_recalc_btn.setEnabled(True)

        def _cancel_bulk_recalc_if_running() -> None:
            if bulk_recalc_worker is not None and bulk_recalc_worker.isRunning():
                bulk_recalc_worker.cancel()

        def _format_bulk_recalc_message(
            recalculated: int,
            skipped: int,
            failed: int,
            elapsed: float,
            *,
            cancelled: bool,
        ) -> str:
            prefix = "Diff Stat update cancelled" if cancelled else "Diff Stat update complete"
            message = (
                f"{prefix}: {recalculated} recalculated, {skipped} unchanged"
                + (f", {failed} failed" if failed else "")
                + f" ({elapsed:.1f} s)"
            )
            return message

        def _on_bulk_recalc_progress(completed: int, total: int, detail: str) -> None:
            if total <= 0:
                summary.setText(detail)
                return
            summary.setText(
                f"Recalculating Diff Stat {completed}/{total}: {detail}"
            )

        def _on_bulk_recalc_finished(
            recalculated: int,
            skipped: int,
            failed: int,
            elapsed: float,
            cancelled: bool,
        ) -> None:
            nonlocal bulk_recalc_worker, diff_rows
            bulk_recalc_worker = None
            _reset_bulk_recalc_button()
            if recalculated == 0 and failed == 0 and not cancelled:
                if skipped:
                    message = f"All {skipped} Diff Stat row(s) are up to date."
                else:
                    message = "No matched rows available for Diff Stat recalculation."
            else:
                message = _format_bulk_recalc_message(
                    recalculated,
                    skipped,
                    failed,
                    elapsed,
                    cancelled=cancelled,
                )
            summary.setText(message)
            active_match = state["active_match"]
            if (
                isinstance(active_match, Postplot4DMatchRow)
                and stack.currentIndex() == 1
                and database is not None
                and project_name.strip()
            ):
                stored = database.load_postplot_4d_diffs(
                    project_name.strip(),
                    active_match.baseline_kind,
                    active_match.sequence_id,
                )
                if stored:
                    diff_rows = stored
                refresh_diff_table()
                _set_diff_summary(diff_summary, message, tone="done")
            if not cancelled and on_diffs_saved is not None:
                on_diffs_saved()
            if parent is not None:
                _show_host_status(parent, message)
            QTimer.singleShot(6000, refresh_table)

        def _prepare_bulk_recalc_tasks(
            cancelled: Callable[[], bool],
        ) -> tuple[list[Postplot4DMatchRow], int]:
            active_baseline = state["baseline"]
            assert active_baseline in ("navplan", "preplot")
            matched_rows = [row for row in rows_for(active_baseline) if row.has_match]
            work_db = Database(database.db_path) if database is not None else None
            try:
                rows_to_recalc: list[Postplot4DMatchRow] = []
                skipped = 0
                for match_row in matched_rows:
                    if cancelled():
                        break
                    if diff_needs_recalculate(match_row, work_db):
                        rows_to_recalc.append(match_row)
                    else:
                        skipped += 1
                return rows_to_recalc, skipped
            finally:
                if work_db is not None:
                    work_db.close()

        def _launch_bulk_recalc_worker() -> None:
            nonlocal bulk_recalc_launch_pending, bulk_recalc_worker
            if not bulk_recalc_launch_pending:
                return
            bulk_recalc_launch_pending = False
            db_path = database.db_path if database is not None else None
            bulk_recalc_worker = DiffStatRecalcWorker(
                current_map_data,
                settings,
                positions,
                prepare_tasks=_prepare_bulk_recalc_tasks,
                load_source_positions_per_match=database is not None
                and bool(project_name.strip()),
                db_path=db_path,
                project_name=project_name,
                parent=host_dialog or parent,
            )
            bulk_recalc_worker.progress.connect(_on_bulk_recalc_progress)
            bulk_recalc_worker.finished_batch.connect(_on_bulk_recalc_finished)
            bulk_recalc_worker.start()

        def _on_bulk_recalc_clicked() -> None:
            nonlocal bulk_recalc_launch_pending
            if _bulk_recalc_running():
                if bulk_recalc_worker is not None:
                    bulk_recalc_worker.cancel()
                bulk_recalc_launch_pending = False
                summary.setText("Cancelling Diff Stat recalculation…")
                if bulk_recalc_worker is None:
                    _reset_bulk_recalc_button()
                    summary.setText("Diff Stat recalculation cancelled.")
                return

            bulk_recalc_launch_pending = True
            bulk_recalc_btn.setText(_BULK_CANCEL_LABEL)
            _set_diff_summary(diff_summary, "Recalculating Diff Stat…", tone="busy")
            summary.setText("Checking for stale Diff Stat rows…")
            QTimer.singleShot(0, _launch_bulk_recalc_worker)

        def clear_saved_diffs() -> None:
            nonlocal diff_rows
            active_baseline = state["baseline"]
            assert active_baseline in ("navplan", "preplot")
            if database is None or not project_name.strip():
                summary.setText("No project database available to clear Diff Stat rows.")
                return
            size_before_mb = database.file_size_bytes() / (1024 * 1024)
            reply = QMessageBox.warning(
                host_dialog or parent,
                "Clear Diff Stat",
                (
                    f"This will permanently delete only saved Diff Stat calculation rows "
                    f"for the {active_baseline} baseline.\n\n"
                    "Parsed/imported preplot, navplan, P111/P190 positions and feather "
                    "cache rows will be kept so recalculation stays fast.\n"
                    f"Current project file size: {size_before_mb:.0f} MB.\n"
                    "The database will be compacted afterward to reclaim disk space "
                    "(this may take a minute on large projects).\n\nContinue?"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            diff_rows_deleted = database.delete_postplot_4d_diffs_for_baseline(
                project_name.strip(),
                active_baseline,
            )
            if isinstance(state["active_match"], Postplot4DMatchRow):
                diff_rows = []
                if stack.currentIndex() == 1:
                    refresh_diff_table()
                    _set_diff_summary(diff_summary, "Saved Diff Stat rows cleared.", tone="done")
            if diff_rows_deleted == 0:
                compact_reply = QMessageBox.question(
                    host_dialog or parent,
                    "Compact Database",
                    (
                        "No saved Diff Stat rows were found to delete.\n\n"
                        f"The project file is still {size_before_mb:.0f} MB. "
                        "Compact it now to reclaim space left by earlier deletes?"
                    ),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if compact_reply != QMessageBox.StandardButton.Yes:
                    summary.setText(
                        f"No saved Diff Stat rows found for project "
                        f"{project_name.strip()!r}."
                    )
                    return
            summary.setText(
                "Compacting project database to reclaim disk space "
                "(this may take a minute)…"
            )
            QApplication.processEvents()
            wait_cursor = QApplication.overrideCursor()
            if wait_cursor is None:
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                size_after_bytes = database.vacuum()
            finally:
                if wait_cursor is None:
                    QApplication.restoreOverrideCursor()
            size_after_mb = size_after_bytes / (1024 * 1024)
            summary.setText(
                f"Cleared {diff_rows_deleted:,} Diff Stat row(s) for "
                f"{active_baseline} baseline. Kept imported parse caches. "
                f"Database compacted from {size_before_mb:.0f} MB to {size_after_mb:.0f} MB."
            )
            if on_diffs_saved is not None:
                on_diffs_saved()
            if parent is not None:
                _show_host_status(
                    parent,
                    f"Diff Stat cleared; database compacted to {size_after_mb:.0f} MB",
                )
            QTimer.singleShot(6000, refresh_table)

        def toggle_coord_mode() -> None:
            state["coord_mode"] = "lat" if state["coord_mode"] == "en" else "en"
            coord_toggle.setText(_coord_toggle_label(state["coord_mode"]))  # type: ignore[arg-type]
            refresh_diff_table()
            if "Recalculated at" not in diff_summary.text():
                _set_diff_summary(
                    diff_summary,
                    f"{len(diff_rows)} shotpoint difference(s)",
                    tone="normal",
                )

        def refresh_table() -> None:
            rows = rows_for(state["baseline"])  # type: ignore[arg-type]
            sort_column = int(state.get("sort_column", 0))
            sort_order = state.get("sort_order", Qt.SortOrder.AscendingOrder)
            if not isinstance(sort_order, Qt.SortOrder):
                sort_order = Qt.SortOrder.AscendingOrder
            if sort_column in (0, 3):
                rows = _sort_match_rows(rows, sort_column, sort_order)
            name_header = (
                "Navplan Name" if state["baseline"] == "navplan" else "Preplot Name"
            )
            header = table.horizontalHeader()
            header.blockSignals(True)
            table.setUpdatesEnabled(False)
            table.setSortingEnabled(False)
            table.setHorizontalHeaderLabels(
                [
                    name_header,
                    "Line Name",
                    "Subline",
                    "Sequence No.",
                    "Line FSP",
                    "Line LSP",
                    "Line Direction",
                    "Diff Stat",
                ]
            )
            header.setSortIndicatorShown(True)
            if sort_column in (0, 3):
                header.setSortIndicator(sort_column, sort_order)
            table.setRowCount(len(rows))
            try:
                for row_idx, match_row in enumerate(rows):
                    table.setRowHeight(row_idx, 34)
                    values = [
                        match_row.baseline_name,
                        match_row.line_name,
                        match_row.subline,
                        match_row.sequence_no,
                        str(match_row.first_sp) if match_row.has_match else "",
                        str(match_row.last_sp) if match_row.has_match else "",
                        match_row.line_direction,
                    ]
                    for col, value in enumerate(values):
                        item = QTableWidgetItem(value)
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        table.setItem(row_idx, col, item)
                    diff_btn = QPushButton("Diff Stat")
                    diff_btn.setObjectName("tableCellBtn")
                    diff_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                    diff_btn.setMinimumSize(82, 28)
                    diff_btn.setEnabled(match_row.has_match)
                    diff_btn.clicked.connect(
                        lambda _checked=False, row=match_row: show_diff_stat(row)
                    )
                    table.setCellWidget(row_idx, 7, diff_btn)
            finally:
                table.setUpdatesEnabled(True)
                header.blockSignals(False)
            summary.setText(
                f"{len(rows)} row(s) from {state['baseline']} baseline, "
                f"{sum(1 for row in rows if row.has_match)} matched imported line(s)"
            )
            _fit_table(table)
            _autosize_dialog_width(host_dialog, table)
            if crs_note is not None:
                crs_note.setText(_crs_note_for_match(None))

        def on_main_header_clicked(section: int) -> None:
            if section not in (0, 3):
                return
            current_column = int(state.get("sort_column", 0))
            current_order = state.get("sort_order", Qt.SortOrder.AscendingOrder)
            if not isinstance(current_order, Qt.SortOrder):
                current_order = Qt.SortOrder.AscendingOrder
            if current_column == section:
                state["sort_order"] = (
                    Qt.SortOrder.DescendingOrder
                    if current_order == Qt.SortOrder.AscendingOrder
                    else Qt.SortOrder.AscendingOrder
                )
            else:
                state["sort_column"] = section
                state["sort_order"] = Qt.SortOrder.AscendingOrder
            refresh_table()

        def set_baseline(kind: BaselineKind) -> None:
            if state["baseline"] == kind:
                return
            state["baseline"] = kind
            state["sort_column"] = 0
            state["sort_order"] = Qt.SortOrder.AscendingOrder
            settings.postplot_4d_baseline = kind
            if on_baseline_changed is not None:
                on_baseline_changed()
            refresh_table()

        def build(dialog: SingleInstanceDialog) -> None:
            nonlocal summary, table, stack, diff_title, diff_table, diff_summary, coord_toggle, recalc_btn, bulk_recalc_btn, host_dialog, crs_note, diff_crs_note
            host_dialog = dialog
            layout = dialog.content_layout
            _clear_layout(layout)

            stack = QStackedWidget()

            main_page = QWidget()
            main_layout = QVBoxLayout(main_page)
            main_layout.setContentsMargins(0, 0, 0, 0)

            title = QLabel(
                "Match imported P111/P190 line sequences against a Navplan or Preplot baseline."
            )
            title.setWordWrap(True)
            main_layout.addWidget(title)

            baseline_row = QHBoxLayout()
            baseline_row.addWidget(QLabel("Baseline:"))
            navplan_radio = QPushButton("Navplan")
            preplot_radio = QPushButton("Preplot")
            for button in (navplan_radio, preplot_radio):
                button.setCheckable(True)
                button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                button.setStyleSheet(_BASELINE_BUTTON_STYLE)
                button.setMinimumSize(92, 32)
            navplan_radio.setChecked(state["baseline"] == "navplan")
            preplot_radio.setChecked(state["baseline"] == "preplot")
            group = QButtonGroup(dialog)
            group.setExclusive(True)
            group.addButton(navplan_radio)
            group.addButton(preplot_radio)
            navplan_radio.toggled.connect(lambda checked: checked and set_baseline("navplan"))
            preplot_radio.toggled.connect(lambda checked: checked and set_baseline("preplot"))
            baseline_row.addWidget(navplan_radio)
            baseline_row.addWidget(preplot_radio)
            baseline_row.addStretch()
            bulk_recalc_btn = QPushButton(_BULK_RECALC_LABEL)
            bulk_recalc_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            bulk_recalc_btn.setMinimumSize(170, 32)
            bulk_recalc_btn.clicked.connect(_on_bulk_recalc_clicked)
            baseline_row.addWidget(bulk_recalc_btn)
            clear_diff_btn = QPushButton("Clear Diff Stat")
            clear_diff_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            clear_diff_btn.setMinimumSize(130, 32)
            clear_diff_btn.clicked.connect(clear_saved_diffs)
            baseline_row.addWidget(clear_diff_btn)
            main_layout.addLayout(baseline_row)

            summary = QLabel("")
            summary.setStyleSheet("color: #8b949e; font-size: 11px;")
            main_layout.addWidget(summary)

            table = QTableWidget(0, 8)
            _configure_table(table)
            table.horizontalHeader().sectionClicked.connect(on_main_header_clicked)
            main_layout.addWidget(table, stretch=1)
            crs_note = QLabel("")
            crs_note.setStyleSheet(_DIFF_SUMMARY_STYLE)
            crs_note.setWordWrap(True)
            main_layout.addWidget(crs_note)

            close_row = QHBoxLayout()
            close_btn = QPushButton("Close")
            close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            close_btn.clicked.connect(dialog.close)
            close_row.addStretch()
            close_row.addWidget(close_btn)
            main_layout.addLayout(close_row)

            diff_page = QWidget()
            diff_layout = QVBoxLayout(diff_page)
            diff_layout.setContentsMargins(0, 0, 0, 0)

            diff_toolbar = QHBoxLayout()
            coord_toggle = QPushButton(_coord_toggle_label(state["coord_mode"]))  # type: ignore[arg-type]
            coord_toggle.setCheckable(False)
            coord_toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            coord_toggle.setMinimumSize(140, 32)
            coord_toggle.clicked.connect(toggle_coord_mode)
            recalc_btn = QPushButton("Recalculate Diffs")
            recalc_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            recalc_btn.setMinimumSize(140, 32)
            recalc_btn.clicked.connect(recalculate_diffs)
            back_btn = QPushButton("Back")
            back_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            back_btn.setMinimumSize(80, 32)
            back_btn.clicked.connect(show_main_view)
            diff_toolbar.addWidget(coord_toggle)
            diff_toolbar.addWidget(recalc_btn)
            diff_toolbar.addStretch()
            diff_toolbar.addWidget(back_btn)
            diff_layout.addLayout(diff_toolbar)

            diff_title = QLabel("")
            diff_title.setStyleSheet("font-weight: 600;")
            diff_layout.addWidget(diff_title)

            diff_summary = QLabel("")
            diff_summary.setStyleSheet("color: #8b949e; font-size: 11px;")
            diff_layout.addWidget(diff_summary)

            diff_table = QTableWidget(0, 8)
            _configure_table(diff_table)
            diff_layout.addWidget(diff_table, stretch=1)
            diff_crs_note = QLabel("")
            diff_crs_note.setStyleSheet(_DIFF_SUMMARY_STYLE)
            diff_crs_note.setWordWrap(True)
            diff_layout.addWidget(diff_crs_note)

            stack.addWidget(main_page)
            stack.addWidget(diff_page)
            layout.addWidget(stack, stretch=1)

            if not hasattr(dialog, "_xpost_bulk_recalc_hook"):
                dialog.finished.connect(_cancel_bulk_recalc_if_running)
                dialog._xpost_bulk_recalc_hook = True

            invalidate_row_cache()
            if isinstance(state["active_match"], Postplot4DMatchRow):
                show_diff_stat(state["active_match"])
            else:
                refresh_table()

        summary = QLabel("")
        table = QTableWidget()
        stack = QStackedWidget()
        diff_title = QLabel("")
        diff_table = QTableWidget()
        diff_summary = QLabel("")
        coord_toggle = QPushButton()
        recalc_btn = QPushButton()
        bulk_recalc_btn = QPushButton()

        return SingleInstanceDialog.show_dialog(
            cls.KEY,
            "Postplot 4D",
            build,
            parent,
            width=1120,
            height=884,
        )
