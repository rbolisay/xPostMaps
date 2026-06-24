"""Postplot 4D matching window."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Callable, Literal

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from xpostmaps.core.coord_format import GeoDisplayFormatter, format_geo_display
from xpostmaps.core.database import Database
from xpostmaps.core.models import MapData, PositionRecord, ProjectSettings
from xpostmaps.core.postplot_4d_diff import (
    Postplot4DDiffRow,
    calculate_match_diff_rows,
    resolve_diff_map_epsg,
)
from xpostmaps.core.postplot_4d_matching import (
    BaselineKind,
    Postplot4DMatchRow,
    build_postplot_4d_rows,
)
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
        database: Database | None = None,
        on_diffs_saved: Callable[[], None] | None = None,
    ) -> SingleInstanceDialog:
        saved_baseline = settings.postplot_4d_baseline
        if saved_baseline not in ("navplan", "preplot"):
            saved_baseline = "navplan" if map_data and map_data.navplan_segments else "preplot"
        state: dict[str, BaselineKind | CoordMode | Postplot4DMatchRow | None | str] = {
            "baseline": saved_baseline,
            "coord_mode": "en",
            "active_match": None,
            "map_epsg": resolve_diff_map_epsg(map_data, settings),
        }
        row_cache: dict[BaselineKind, list[Postplot4DMatchRow]] = {}
        diff_rows: list[Postplot4DDiffRow] = []
        host_dialog: SingleInstanceDialog | None = None

        def rows_for(kind: BaselineKind) -> list[Postplot4DMatchRow]:
            if kind not in row_cache:
                row_cache[kind] = build_postplot_4d_rows(map_data, settings, kind)
            return row_cache[kind]

        def positions() -> list[PositionRecord]:
            if positions_provider is None:
                return list(map_data.positions) if map_data else []
            return list(positions_provider())

        def persist_diff_rows(match_row: Postplot4DMatchRow, rows: list[Postplot4DDiffRow]) -> None:
            if database is None or not project_name.strip():
                return
            database.save_postplot_4d_diffs(
                project_name.strip(),
                match_row.baseline_kind,
                match_row.baseline_name,
                match_row.sequence_id,
                rows,
            )
            if on_diffs_saved is not None:
                on_diffs_saved()

        def load_or_calculate_diffs(
            match_row: Postplot4DMatchRow,
        ) -> tuple[list[Postplot4DDiffRow], str]:
            if database is not None and project_name.strip():
                stored = database.load_postplot_4d_diffs(
                    project_name.strip(),
                    match_row.baseline_kind,
                    match_row.sequence_id,
                )
                if stored:
                    return stored, "loaded"
            rows = calculate_match_diff_rows(map_data, settings, positions(), match_row)
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
            header = diff_table.horizontalHeader()
            header.blockSignals(True)
            header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
            diff_table.setUpdatesEnabled(False)
            diff_table.setSortingEnabled(False)
            diff_table.setHorizontalHeaderLabels(
                [
                    "Shotpoint No.",
                    baseline_h1,
                    baseline_h2,
                    source_h1,
                    source_h2,
                    "Crossline (m)",
                    "Inline (m)",
                    "Radial (m)",
                ]
            )
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
                        source_a,
                        source_b,
                        _format_offset(diff_row.crossline_m),
                        _format_offset(diff_row.inline_m),
                        _format_offset(diff_row.radial_m),
                    ]
                    for col, value in enumerate(values):
                        _set_diff_table_item(diff_table, row_idx, col, value)
            finally:
                diff_table.setUpdatesEnabled(True)
                header.blockSignals(False)
            _finalize_diff_table_layout(diff_table)

        def show_diff_stat(match_row: Postplot4DMatchRow) -> None:
            nonlocal diff_rows
            state["active_match"] = match_row
            diff_rows, source = load_or_calculate_diffs(match_row)
            diff_title.setText(_diff_title(match_row))
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
            if host_dialog is not None:
                host_dialog.setWindowTitle("Postplot 4D")

        def _persist_note() -> str:
            if database is not None and project_name.strip():
                return "saved to project"
            return "not saved (no project database)"

        def recalculate_diffs() -> None:
            match_row = state["active_match"]
            if not isinstance(match_row, Postplot4DMatchRow):
                return
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
                    map_data,
                    settings,
                    positions(),
                    match_row,
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
                status = (
                    f"Diff stat recalculated: {len(diff_rows)} shotpoint(s) in {elapsed:.1f} s"
                )
                if parent is not None:
                    _show_host_status(parent, status)
                QTimer.singleShot(
                    5000,
                    lambda: _set_diff_summary(
                        diff_summary,
                        summary,
                        tone="normal",
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                _set_diff_summary(
                    diff_summary,
                    f"Recalculate failed: {exc}",
                    tone="busy",
                )
                if parent is not None:
                    _show_host_status(
                        parent,
                        f"Diff stat recalculate failed: {exc}",
                        8000,
                    )
            finally:
                recalc_btn.setEnabled(True)
                coord_toggle.setEnabled(True)
                recalc_btn.setText("Recalculate Diffs")
                QApplication.restoreOverrideCursor()

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
            name_header = (
                "Navplan Name" if state["baseline"] == "navplan" else "Preplot Name"
            )
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
            summary.setText(
                f"{len(rows)} row(s) from {state['baseline']} baseline, "
                f"{sum(1 for row in rows if row.has_match)} matched imported line(s)"
            )
            _fit_table(table)

        def set_baseline(kind: BaselineKind) -> None:
            if state["baseline"] == kind:
                return
            state["baseline"] = kind
            settings.postplot_4d_baseline = kind
            if on_baseline_changed is not None:
                on_baseline_changed()
            refresh_table()

        def build(dialog: SingleInstanceDialog) -> None:
            nonlocal summary, table, stack, diff_title, diff_table, diff_summary, coord_toggle, recalc_btn, host_dialog
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
            main_layout.addLayout(baseline_row)

            summary = QLabel("")
            summary.setStyleSheet("color: #8b949e; font-size: 11px;")
            main_layout.addWidget(summary)

            table = QTableWidget(0, 8)
            _configure_table(table)
            main_layout.addWidget(table, stretch=1)

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

            stack.addWidget(main_page)
            stack.addWidget(diff_page)
            layout.addWidget(stack, stretch=1)

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

        return SingleInstanceDialog.show_dialog(
            cls.KEY,
            "Postplot 4D",
            build,
            parent,
            width=1120,
            height=680,
        )
