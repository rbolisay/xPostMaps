"""Main application window."""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from xpostmaps.core.branding import APP_WINDOW_TITLE, DEVELOPER_CREDIT_HTML

from xpostmaps.core.autosave import AutosaveController
from xpostmaps.core.database import Database
from xpostmaps.core.legend_utils import legend_from_dict, legend_to_dict
from xpostmaps.core.local_settings import load_db_directory, save_db_directory
from xpostmaps.core.mediator import Mediator
from xpostmaps.core.project_db_utils import project_db_path
from xpostmaps.core.models import (
    ConditionalColorRule,
    DisplayMode,
    LegendConfig,
    LineSequence,
    MapData,
    PositionRecord,
    PostmapInfo,
    ProjectSettings,
)
from xpostmaps.core.parse_worker import ParseWorker
from xpostmaps.core.postplot_4d_diff import calculate_match_diff_rows
from xpostmaps.core.postplot_4d_matching import build_postplot_4d_rows
from xpostmaps.core.crs_utils import normalize_epsg
from xpostmaps.core.navplan_catalog_utils import (
    build_navplan_catalog_from_segments,
    resolve_navplan_file_order,
    resolve_navplan_files,
    sync_navplan_legend_entries,
)
from xpostmaps.core.preplot_catalog_utils import (
    build_preplot_catalog_from_segments,
    resolve_preplot_file_order,
    sync_preplot_legend_entries,
)
from xpostmaps.core.sequence_utils import sequence_id_matches
from xpostmaps.ui.dialogs.import_polygons_dialog import ImportPolygonsDialog
from xpostmaps.ui.dialogs.import_navplan_dialog import ImportNavplanDialog
from xpostmaps.ui.dialogs.legend_dialog import LayerStylesDialog
from xpostmaps.parsers.directory_parser import NAV_EXTENSIONS, resolve_nav_files
from xpostmaps.parsers.preplot_parser import resolve_preplot_files
from xpostmaps.core.polygon_import_service import imported_polygon_entries
from xpostmaps.ui.dialogs.nav_picker_dialog import NavFilePickerDialog
from xpostmaps.ui.dialogs.pdf_export_dialog import PdfExportDialog
from xpostmaps.ui.dialogs.postmap_info_dialog import PostmapInfoDialog
from xpostmaps.ui.dialogs.postplot_4d_dialog import Postplot4DDialog
from xpostmaps.ui.dialogs.preplot_navplan_dialog import PreplotNavplanDialog
from xpostmaps.ui.dialogs.project_browser_dialog import ProjectBrowserDialog
from xpostmaps.ui.left_panel import LeftPanel
from xpostmaps.ui.map_widget import PostplotMapWidget
from xpostmaps.ui.right_pane import RightPane
from xpostmaps.ui.theme import BG_DARK, app_stylesheet


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._mediator = Mediator.instance()
        default_db_dir = Path(__file__).resolve().parents[2] / "data"
        self._db_directory = load_db_directory(default_db_dir)
        self._db = Database(self._db_directory / "xpostmaps.db")
        self._settings = ProjectSettings()
        self._map_data: MapData | None = None
        # Cache of purely-geometric 4D diff rows per match row. These do not
        # depend on legend color/style/width, so we reuse them across legend
        # applies and only recompute when the underlying data changes.
        self._match_diff_cache: dict[tuple, list] = {}
        self._match_diff_cache_version: int = -1
        self._conditional_data_version: int = 0
        self._conditional_points_signature_cache: tuple | None = None
        self._preplot_file_signature: tuple | None = None
        self._navplan_file_signature: tuple | None = None
        self._worker: ParseWorker | None = None
        self._loading_project = False
        self._parsing = False
        self._closing_after_parse = False
        self._autosave = AutosaveController(self._autosave_project, self, delay_ms=2000)
        self._metadata_autosave = AutosaveController(
            self._autosave_project_metadata,
            self,
            delay_ms=500,
        )

        self.setWindowTitle(APP_WINDOW_TITLE)
        self.resize(1600, 900)
        self.setStyleSheet(app_stylesheet())

        central = QWidget()
        central.setStyleSheet(f"background: {BG_DARK};")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 6)
        root.setSpacing(4)

        content = QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(12)

        self._left = LeftPanel()
        self._left.setFixedWidth(320)

        self._map = PostplotMapWidget()
        self._right = RightPane()

        sheet = QHBoxLayout()
        sheet.setContentsMargins(0, 0, 0, 0)
        sheet.setSpacing(0)
        sheet.addWidget(self._map, stretch=1)
        sheet.addWidget(self._right, stretch=0)

        sheet_host = QWidget()
        sheet_host.setLayout(sheet)
        content.addWidget(self._left)
        content.addWidget(sheet_host, stretch=1)
        root.addLayout(content, stretch=1)

        credit = QLabel(DEVELOPER_CREDIT_HTML)
        credit.setTextFormat(Qt.TextFormat.RichText)
        credit.setOpenExternalLinks(True)
        credit.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        credit.setStyleSheet(
            "color: #6e7681; font-size: 10px; padding-left: 2px;"
            " a { color: #8b949e; text-decoration: none; }"
            " a:hover { text-decoration: underline; }"
        )
        root.addWidget(credit, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)

        status = QStatusBar()
        self.setStatusBar(status)
        status.showMessage("Ready")

        self._connect_signals()
        self._refresh_ui()

    def _connect_signals(self) -> None:
        self._left.project_name_changed.connect(self._on_project_name_changed)
        self._left.browse_load_project.connect(self._open_project_browser)
        self._left.save_project.connect(lambda: self._save_project(silent=False))
        self._left.select_preplot_navplan.connect(self._select_preplot_navplan)
        self._left.import_navplan.connect(self._open_import_navplan)
        self._left.select_p111_p190_dir.connect(self._select_p111_dir)
        self._left.open_import_polygons.connect(self._open_import_polygons)
        self._left.select_logo.connect(self._select_logo)
        self._left.open_postmap_info.connect(self._open_postmap_info)
        self._left.open_layer_styles.connect(self._open_layer_styles)
        self._left.open_pdf_export.connect(self._open_pdf_export)
        self._left.open_postplot_4d.connect(self._open_postplot_4d)
        self._right.minimap_view_changed.connect(self._on_minimap_view_changed)
        self._map.view_changed.connect(self._on_map_view_changed)

        self._mediator.map_data_updated.connect(self._on_map_data_updated)
        self._mediator.status_message.connect(self.statusBar().showMessage)

    def _schedule_autosave(self) -> None:
        if self._loading_project or self._parsing:
            return
        self._autosave.schedule()

    def _schedule_metadata_autosave(self) -> None:
        if self._loading_project or self._parsing:
            return
        self._metadata_autosave.schedule()

    def _ensure_project_name(self) -> bool:
        """Derive a project name from loaded file paths when none was entered."""
        if self._settings.name.strip():
            return True
        candidates: list[str] = []
        if self._settings.preplots_dir:
            candidates.append(self._settings.preplots_dir)
        if self._settings.navplans_dir:
            candidates.append(self._settings.navplans_dir)
        if self._settings.p111_p190_dir:
            candidates.append(self._settings.p111_p190_dir)
        candidates.extend(self._settings.preplot_files[:1])
        candidates.extend(self._settings.navplan_files[:1])
        candidates.extend(self._settings.nav_files[:1])
        for raw in candidates:
            if not raw:
                continue
            path = Path(raw)
            name = path.stem if path.is_file() else path.name
            if name:
                self._settings.name = name
                self._left.set_project_name(name)
                return True
        return False

    def _ensure_map_data(self) -> MapData:
        if self._map_data is None:
            self._map_data = MapData(postmap_info=PostmapInfo())
        return self._map_data

    def _sync_map_data_preplot_order(self) -> None:
        if not self._map_data:
            return
        order = resolve_preplot_file_order(self._map_data, self._settings)
        if order:
            self._map_data.preplot_file_order = order
        navplan_order = resolve_navplan_file_order(self._map_data, self._settings)
        if navplan_order:
            self._map_data.navplan_file_order = navplan_order

    def _apply_map_crs_from_preplot(self, map_data: MapData) -> None:
        info = map_data.postmap_info
        if info.epsg_code:
            info.epsg_code = normalize_epsg(info.epsg_code)
            return
        for entry in self._settings.preplot_catalog:
            if entry.crs_code:
                info.epsg_code = normalize_epsg(entry.crs_code)
                return
        for entry in self._settings.navplan_catalog:
            if entry.crs_code:
                info.epsg_code = normalize_epsg(entry.crs_code)
                return

    def _ensure_project_info_date(self, map_data: MapData | None = None) -> None:
        target = map_data or self._map_data
        if target and target.postmap_info and not target.postmap_info.date.strip():
            target.postmap_info.date = date.today().isoformat()

    def _current_map_epsg(self) -> str:
        map_data = self._ensure_map_data()
        self._apply_map_crs_from_preplot(map_data)
        return normalize_epsg(map_data.postmap_info.epsg_code)

    def _merge_preserved_postmap_info(
        self,
        parsed: PostmapInfo,
        preserved: PostmapInfo | None,
    ) -> PostmapInfo:
        """Keep in-memory / user-edited project info when re-parsing files.

        Parsed headers only fill fields that are still empty in the preserved
        copy. Non-empty preserved values always win so autosave and manual edits
        are not overwritten by file metadata.
        """
        if preserved is None:
            return parsed
        for field in PostmapInfo.__dataclass_fields__:
            if field == "extra":
                continue
            preserved_val = getattr(preserved, field)
            if isinstance(preserved_val, str) and preserved_val.strip():
                setattr(parsed, field, preserved_val.strip())
            elif preserved_val and not isinstance(preserved_val, str):
                setattr(parsed, field, preserved_val)
        if preserved.extra:
            parsed.extra = {**parsed.extra, **preserved.extra}
        if parsed.epsg_code:
            parsed.epsg_code = normalize_epsg(parsed.epsg_code)
        elif preserved.epsg_code:
            parsed.epsg_code = normalize_epsg(preserved.epsg_code)
        return parsed

    def _refresh_ui(self) -> None:
        if self._map_data:
            self._ensure_project_info_date(self._map_data)
            self._apply_map_crs_from_preplot(self._map_data)
        self._sync_map_data_preplot_order()
        self._map.set_legend(self._settings.legend_config)
        self._map.set_display_mode(self._settings.display_mode)
        self._refresh_conditional_postplot_points()
        self._map.render(self._map_data)
        self._right.update_from_project(self._settings, self._map_data)
        self._refresh_import_polygons_summary()
        self._refresh_preplot_summary()

    def _refresh_import_polygons_summary(self) -> None:
        imported = imported_polygon_entries(self._settings.legend_config.areas)
        if not imported:
            self._left.set_import_polygons("Not set")
            return
        if len(imported) == 1:
            self._left.set_import_polygons(imported[0].name or "1 polygon")
        else:
            self._left.set_import_polygons(f"{len(imported)} polygon(s)")

    def _refresh_preplot_summary(self) -> None:
        catalog = self._settings.preplot_catalog
        has_preplot = bool(catalog)
        self._left.set_preplot_dependent_controls_enabled(has_preplot)
        if not catalog:
            self._left.set_preplot_navplan("Not set")
            self._left.set_navplan("Not set")
            return
        if len(catalog) == 1:
            self._left.set_preplot_navplan(Path(catalog[0].file_path).name)
        else:
            self._left.set_preplot_navplan(f"{len(catalog)} preplot file(s)")
        nav_catalog = self._settings.navplan_catalog
        if not nav_catalog:
            self._left.set_navplan("Not set")
        elif len(nav_catalog) == 1:
            self._left.set_navplan(Path(nav_catalog[0].file_path).name)
        else:
            self._left.set_navplan(f"{len(nav_catalog)} navplan file(s)")

    def _on_project_name_changed(self, name: str) -> None:
        self._settings.name = name.strip()
        self._schedule_autosave()

    def _on_minimap_view_changed(self, view: dict) -> None:
        self._settings.minimap_view = dict(view)
        self._schedule_metadata_autosave()

    def _on_map_view_changed(self, view: dict) -> None:
        if self._loading_project:
            return
        self._settings.map_view = dict(view)
        self._schedule_metadata_autosave()

    def _set_left_button_active(self, key: str, active: bool) -> None:
        self._left.set_button_active(key, active)

    def _track_left_dialog(self, key: str, dialog) -> None:
        if dialog is None:
            self._set_left_button_active(key, False)
            return
        self._set_left_button_active(key, True)
        dialog.finished.connect(lambda _result=0, k=key: self._set_left_button_active(k, False))

    def _sync_current_views(self) -> None:
        """Capture the latest live views before any database write."""
        if self._loading_project:
            return
        if self._map_data is not None:
            self._settings.map_view = self._map.current_view()
        self._settings.minimap_view = self._right.current_minimap_view()

    def _on_logo_changed(self, path: str) -> None:
        self._settings.logo_path = path
        self._right.set_logo(path)
        self._persist_project()

    def _select_logo(self) -> None:
        self._set_left_button_active("logo", True)
        try:
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Select Logo",
                self._settings.logo_path or "",
                "Images (*.png *.jpg *.jpeg *.svg *.bmp);;All Files (*)",
            )
            if path:
                self._on_logo_changed(path)
        finally:
            self._set_left_button_active("logo", False)

    def _open_pdf_export(self) -> None:
        if not self._map_data:
            QMessageBox.information(
                self,
                "Export to PDF",
                "Load a project with map data before exporting.",
            )
            return
        self._right.update_from_project(self._settings, self._map_data)
        dialog = PdfExportDialog.open(
            self,
            map_widget=self._map,
            right_pane=self._right,
            settings=self._settings,
            map_data=self._map_data,
            project_name=self._settings.name,
            default_output_dir=self._db_directory,
        )
        self._track_left_dialog("pdf", dialog)

    def _open_postplot_4d(self) -> None:
        if not self._map_data:
            QMessageBox.information(
                self,
                "Postplot 4D",
                "Load imported P111/P190 and a Preplot or Navplan baseline first.",
            )
            return
        dialog = Postplot4DDialog.open(
            self,
            self._settings,
            self._map_data,
            on_baseline_changed=self._on_postplot_4d_baseline_changed,
            project_name=self._settings.name,
            positions_provider=self._current_positions,
            map_data_provider=lambda: self._map_data,
            database=self._db,
            on_diffs_saved=self._on_postplot_4d_diffs_saved,
        )
        self._track_left_dialog("postplot_4d", dialog)

    def _on_postplot_4d_baseline_changed(self) -> None:
        self._schedule_metadata_autosave()

    def _on_postplot_4d_diffs_saved(self) -> None:
        self._invalidate_conditional_diff_cache()
        self._refresh_conditional_postplot_points()
        self._map.render(self._map_data, force=True)

    def _open_layer_styles(self) -> None:
        perimeters = self._map_data.survey_perimeters if self._map_data else []
        dialog = LayerStylesDialog.open(
            self,
            self._settings.legend_config,
            on_apply=self._on_legend_apply,
            sequences=self._map_data.sequences if self._map_data else [],
            sequences_provider=self._current_sequences,
            survey_perimeters=perimeters,
            preplot_count=len(self._settings.preplot_catalog),
            navplan_catalog=self._settings.navplan_catalog,
            map_epsg=self._current_map_epsg(),
            on_map_epsg_changed=self._on_import_map_epsg_changed,
        )
        self._track_left_dialog("layer_styles", dialog)

    def _open_import_polygons(self) -> None:
        dialog = ImportPolygonsDialog.open(
            self,
            self._settings.legend_config,
            self._current_map_epsg(),
            on_apply=self._on_import_polygons_apply,
            on_map_epsg_changed=self._on_import_map_epsg_changed,
        )
        self._track_left_dialog("import_polygons", dialog)

    def _on_import_polygons_apply(self, legend: LegendConfig) -> None:
        self._on_legend_apply(legend)
        self._refresh_import_polygons_summary()

    def _on_import_map_epsg_changed(self, epsg_code: str) -> None:
        if not self._map_data:
            return
        self._map_data.postmap_info.epsg_code = normalize_epsg(epsg_code)
        self._right.update_from_project(self._settings, self._map_data)
        self._persist_project()

    def _current_sequences(self) -> list[LineSequence]:
        return list(self._map_data.sequences) if self._map_data else []

    def _current_positions(self) -> list[PositionRecord]:
        if self._map_data is None:
            return []
        if self._map_data.positions:
            return list(self._map_data.positions)
        name = self._settings.name.strip()
        if not name:
            return []
        positions = self._db.load_positions(name)
        self._map_data.positions = positions
        self._map_data.positions_persisted = bool(positions)
        return positions

    @staticmethod
    def _conditional_range_matches(value: float, range_text: str) -> bool:
        text = (range_text or "").strip().replace(" ", "")
        if not text or value != value:
            return False
        abs_value = abs(float(value))
        normalized = text.replace("–", "-").replace("—", "-")
        try:
            if normalized.startswith("<=") or normalized.startswith("=<"):
                return abs_value <= float(normalized[2:])
            if normalized.startswith(">=") or normalized.startswith("=>"):
                return abs_value >= float(normalized[2:])
            if normalized.startswith("<"):
                return abs_value < float(normalized[1:])
            if normalized.startswith(">"):
                return abs_value > float(normalized[1:])
            if "-" in normalized:
                left, right = normalized.split("-", 1)
                low = float(left) if left else 0.0
                high = float(right)
                if low > high:
                    low, high = high, low
                return low <= abs_value <= high
            return abs_value <= float(normalized)
        except ValueError:
            return False

    @staticmethod
    def _conditional_diff_value(rule: ConditionalColorRule, row) -> float:
        stat = (rule.diff_stat or "").strip().lower()
        if stat == "crossline":
            return float(row.crossline_m)
        if stat == "inline":
            return float(row.inline_m)
        return float(row.radial_m)

    def _conditional_rule_for_diff_row(
        self,
        rules: list[ConditionalColorRule],
        row,
    ) -> ConditionalColorRule | None:
        match: ConditionalColorRule | None = None
        for rule in rules:
            if rule.disabled:
                continue
            value = self._conditional_diff_value(rule, row)
            if self._conditional_range_matches(value, rule.range_value):
                match = rule
        return match

    @staticmethod
    def _conditional_points_signature(settings: ProjectSettings, data_version: int) -> tuple:
        """Inputs that affect conditional point selection and color."""
        return (
            data_version,
            tuple(
                (
                    tuple(entry.sequence_ids),
                    entry.sequence_filter_active,
                    entry.hidden,
                    tuple(
                        (
                            rule.diff_stat,
                            rule.range_value.strip(),
                            rule.color,
                            round(float(rule.opacity), 6),
                            rule.disabled,
                        )
                        for rule in entry.conditional_colors
                    ),
                )
                for entry in settings.legend_config.postplot_lines
            ),
        )

    def _refresh_conditional_postplot_points(self) -> None:
        if self._map_data is None:
            self._map.set_conditional_postplot_points([])
            self._conditional_points_signature_cache = None
            return
        active_entries = [
            entry
            for entry in self._settings.legend_config.postplot_lines
            if not entry.hidden
            and entry.sequence_filter_active
            and entry.sequence_ids
            and any(
                not rule.disabled and rule.range_value.strip()
                for rule in entry.conditional_colors
            )
        ]
        signature = self._conditional_points_signature(
            self._settings,
            self._conditional_data_version,
        )
        if signature == self._conditional_points_signature_cache:
            return
        if not active_entries:
            self._map.set_conditional_postplot_points([])
            self._conditional_points_signature_cache = signature
            return

        positions = self._current_positions()
        match_rows = [
            row
            for row in build_postplot_4d_rows(
                self._map_data,
                self._settings,
                self._settings.postplot_4d_baseline,
            )
            if row.has_match
        ]
        points: list[tuple[float, float, str, float, float]] = []
        for entry in active_entries:
            for match_row in match_rows:
                if not sequence_id_matches(match_row.sequence_id, entry.sequence_ids):
                    continue
                diff_rows = self._cached_match_diff_rows(match_row, positions)
                for diff_row in diff_rows:
                    rule = self._conditional_rule_for_diff_row(
                        entry.conditional_colors,
                        diff_row,
                    )
                    if rule is None:
                        continue
                    points.append(
                        (
                            diff_row.source_x,
                            diff_row.source_y,
                            rule.color,
                            rule.opacity,
                            entry.dot_radius if entry.dot_radius > 0 else 0.8,
                        )
                    )
        self._map.set_conditional_postplot_points(points)
        self._conditional_points_signature_cache = signature

    def _cached_match_diff_rows(
        self,
        match_row,
        positions: list[PositionRecord],
    ) -> list:
        """Return 4D diff rows for a match row, preferring saved DB data.

        Diff geometry depends only on parsed positions/baseline/CRS, never on
        legend color/style/width. Use persisted diff rows first, then calculate
        and save only when the DB has no rows for this match.
        """
        if self._match_diff_cache_version != self._conditional_data_version:
            self._match_diff_cache = {}
            self._match_diff_cache_version = self._conditional_data_version
        key = (
            match_row.sequence_id,
            match_row.baseline_kind,
            match_row.baseline_name,
            match_row.baseline_file_name,
            match_row.line_direction,
            self._settings.postplot_4d_baseline,
        )
        cached = self._match_diff_cache.get(key)
        if cached is None:
            cached = []
            project_name = self._settings.name.strip()
            if project_name:
                cached = self._db.load_postplot_4d_diffs(
                    project_name,
                    match_row.baseline_kind,
                    match_row.sequence_id,
                )
            if cached:
                self._match_diff_cache[key] = cached
                return cached
            cached = calculate_match_diff_rows(
                self._map_data,
                self._settings,
                positions,
                match_row,
                database=self._db,
                project_name=self._settings.name,
            )
            if project_name:
                self._db.save_postplot_4d_diffs(
                    project_name,
                    match_row.baseline_kind,
                    match_row.baseline_name,
                    match_row.sequence_id,
                    cached,
                )
            self._match_diff_cache[key] = cached
        return cached

    def _invalidate_conditional_diff_cache(self) -> None:
        """Drop cached 4D diff rows after the underlying data changes."""
        self._conditional_data_version += 1
        self._match_diff_cache = {}
        self._conditional_points_signature_cache = None

    def _delete_saved_postplot_4d_diffs_for_baseline(self, baseline_kind: str) -> None:
        name = self._settings.name.strip()
        if name:
            self._db.delete_postplot_4d_diffs_for_baseline(name, baseline_kind)
        self._invalidate_conditional_diff_cache()

    @staticmethod
    def _file_signature(paths: list[Path]) -> tuple:
        signature = []
        for path in sorted(paths, key=lambda p: str(p).lower()):
            try:
                stat = path.stat()
            except OSError:
                signature.append((str(path), None, None))
                continue
            signature.append((str(path), int(stat.st_mtime_ns), int(stat.st_size)))
        return tuple(signature)

    def _refresh_postplot_4d_input_signatures(self, *, invalidate: bool) -> None:
        preplot_sig = self._file_signature(resolve_preplot_files(self._settings))
        navplan_sig = self._file_signature(resolve_navplan_files(self._settings))
        if invalidate:
            if self._preplot_file_signature is not None and preplot_sig != self._preplot_file_signature:
                self._delete_saved_postplot_4d_diffs_for_baseline("preplot")
            if self._navplan_file_signature is not None and navplan_sig != self._navplan_file_signature:
                self._delete_saved_postplot_4d_diffs_for_baseline("navplan")
        self._preplot_file_signature = preplot_sig
        self._navplan_file_signature = navplan_sig

    def _invalidate_postplot_4d_diffs(self, map_data: MapData) -> None:
        self._invalidate_conditional_diff_cache()
        name = self._settings.name.strip()
        if not name:
            return
        parsed_names = map_data.stats.get("nav_files_parsed_names") or []
        if parsed_names:
            self._db.delete_postplot_4d_diffs_for_files(name, set(parsed_names))

    @staticmethod
    def _summary_value(values: set[str]) -> str:
        cleaned = {value.strip() for value in values if value.strip()}
        if not cleaned:
            return ""
        if len(cleaned) == 1:
            return next(iter(cleaned))
        return f"{len(cleaned)} values"

    def _nav_file_summaries(self) -> dict[str, tuple[str, str, str, str, str]]:
        """Summaries for the import table from already parsed project data."""
        if self._map_data is None:
            return {}

        grouped: dict[str, list[LineSequence]] = {}
        for seq in self._map_data.sequences:
            grouped.setdefault(seq.file_name, []).append(seq)

        summaries: dict[str, tuple[str, str, str, str, str]] = {}
        for file_name, sequences in grouped.items():
            first_sp = min(seq.first_sp for seq in sequences)
            last_sp = max(seq.last_sp for seq in sequences)
            summaries[file_name] = (
                self._summary_value({seq.line_name for seq in sequences}),
                self._summary_value({seq.subline for seq in sequences}),
                self._summary_value({seq.line_direction for seq in sequences}),
                str(first_sp),
                str(last_sp),
            )
        return summaries

    def _prune_legend_sequence_refs(self) -> None:
        if not self._map_data:
            return
        valid_ids = {seq.seq_id for seq in self._map_data.sequences}
        for entry in self._settings.legend_config.postplot_lines:
            entry.sequence_ids = [
                seq_id
                for seq_id in entry.sequence_ids
                if any(sequence_id_matches(valid_id, [seq_id]) for valid_id in valid_ids)
            ]

    def _on_legend_apply(self, legend: LegendConfig) -> None:
        self._settings.legend_config = legend_from_dict(legend_to_dict(legend))
        self._sync_map_data_preplot_order()
        self._map.set_legend(self._settings.legend_config)
        # Debounce the heavy map rebuild so repeated Apply/Ok clicks don't stack
        # multiple full renders while the legend dialog is still active.
        timer = getattr(self, "_legend_apply_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._complete_legend_apply)
            self._legend_apply_timer = timer
        timer.start(75)

    def _complete_legend_apply(self) -> None:
        self._refresh_conditional_postplot_points()
        self._map.render(self._map_data, force=True)
        self._right.update_from_project(self._settings, self._map_data)
        self._ensure_project_name()
        if self._settings.name.strip():
            self._schedule_metadata_autosave()
            self.statusBar().showMessage("Legend updated")
        else:
            self.statusBar().showMessage(
                "Legend updated — enter a project name to save to database",
                5000,
            )

    def _persist_project(self) -> None:
        """Save project immediately when possible."""
        self._ensure_project_name()
        self._autosave.save_now()

    def _open_postmap_info(self) -> None:
        if self._map_data:
            self._ensure_project_info_date(self._map_data)
        info = self._map_data.postmap_info if self._map_data else PostmapInfo()
        dialog = PostmapInfoDialog.open(self, info, on_changed=self._on_postmap_info_changed)
        self._track_left_dialog("info", dialog)

    def _on_postmap_info_changed(self, info: PostmapInfo) -> None:
        map_data = self._ensure_map_data()
        map_data.postmap_info = info
        self._ensure_project_info_date(map_data)
        self._right.refresh_postmap_info(map_data)
        self._schedule_metadata_autosave()

    def _select_preplot_navplan(self) -> None:
        dialog = PreplotNavplanDialog.open(
            self,
            self._settings,
            on_apply=self._on_preplot_settings_changed,
            initial_dir=self._settings.preplots_dir or self._settings.p111_p190_dir or "",
        )
        self._track_left_dialog("preplot", dialog)

    def _open_import_navplan(self) -> None:
        dialog = ImportNavplanDialog.open(
            self,
            self._settings,
            on_apply=self._on_navplan_settings_changed,
            initial_dir=self._settings.navplans_dir
            or self._settings.preplots_dir
            or self._settings.p111_p190_dir
            or "",
        )
        self._track_left_dialog("navplan", dialog)

    def _on_preplot_settings_changed(self, settings: ProjectSettings) -> None:
        old_files = set(self._settings.preplot_files)
        self._settings.preplot_files = settings.preplot_files
        self._settings.preplot_files_explicit = settings.preplot_files_explicit
        self._settings.preplots_dir = settings.preplots_dir
        self._settings.preplot_catalog = list(settings.preplot_catalog)
        if old_files != set(settings.preplot_files):
            self._delete_saved_postplot_4d_diffs_for_baseline("preplot")
        sync_preplot_legend_entries(
            self._settings.legend_config,
            self._settings.preplot_catalog,
        )
        self._refresh_preplot_summary()
        self._ensure_project_name()
        self._start_parse()

    def _on_navplan_settings_changed(self, settings: ProjectSettings) -> None:
        old_files = set(self._settings.navplan_files)
        self._settings.navplan_files = settings.navplan_files
        self._settings.navplan_files_explicit = settings.navplan_files_explicit
        self._settings.navplans_dir = settings.navplans_dir
        self._settings.navplan_catalog = list(settings.navplan_catalog)
        if old_files != set(settings.navplan_files):
            self._delete_saved_postplot_4d_diffs_for_baseline("navplan")
        sync_navplan_legend_entries(
            self._settings.legend_config,
            self._settings.navplan_catalog,
        )
        self._refresh_preplot_summary()
        self._ensure_project_name()
        self._start_parse()

    def _apply_nav_file_selection(self, files: list[str], folder: str) -> None:
        """Apply nav file list and re-parse so the map and database stay in sync."""
        if set(self._settings.nav_files) != set(files):
            self._delete_saved_postplot_4d_diffs_for_baseline("navplan")
            self._delete_saved_postplot_4d_diffs_for_baseline("preplot")
        self._settings.nav_files = files
        self._settings.nav_files_explicit = True
        self._settings.p111_p190_dir = folder
        if files:
            display = (
                f"{len(files)} file(s)"
                if len(files) != 1
                else files[0]
            )
        else:
            display = "(no nav files)"
        self._left.set_p111_p190_dir(display)
        self._ensure_project_name()
        self._start_parse()

    def _select_p111_dir(self) -> None:
        self._set_left_button_active("p111", True)
        try:
            result = NavFilePickerDialog.pick(
                self,
                title="Select P111/P190 Files",
                hint="Select a folder to scan for .p111/.p190 files, or add individual files.",
                extensions=NAV_EXTENSIONS,
                file_filter="Navigation Files (*.p111 *.p190 *.txt *.nav);;All Files (*)",
                initial_dir=self._settings.p111_p190_dir or "",
                initial_files=self._settings.nav_files or None,
                file_summaries=self._nav_file_summaries(),
            )
            if result is None:
                return
            files, folder = result
            QTimer.singleShot(0, lambda: self._apply_nav_file_selection(files, folder))
        finally:
            self._set_left_button_active("p111", False)

    def _start_parse(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        has_nav = bool(resolve_nav_files(self._settings))
        has_preplot = bool(resolve_preplot_files(self._settings))
        has_navplan = bool(resolve_navplan_files(self._settings))
        explicit_sources = (
            self._settings.nav_files_explicit
            or self._settings.preplot_files_explicit
            or self._settings.navplan_files_explicit
        )
        if not has_nav and not has_preplot and not has_navplan and not explicit_sources:
            return

        self._parsing = True
        self._autosave.set_enabled(False)
        self._metadata_autosave.set_enabled(False)
        self._left.set_progress(0, True)
        self._left.set_status("Parsing files…")
        QApplication.processEvents()
        existing = self._map_data.postmap_info if self._map_data else None
        project_name = self._settings.name.strip()
        project_db = project_db_path(self._db_directory, project_name) if project_name else None
        self._worker = ParseWorker(
            self._settings,
            self,
            existing_postmap=existing,
            existing_map_data=self._map_data,
            project_db_path=project_db,
            project_name=project_name,
        )
        self._worker.progress.connect(self._on_parse_progress)
        self._worker.finished_ok.connect(self._on_parse_finished)
        self._worker.failed.connect(self._on_parse_failed)
        self._worker.start()

    def _on_parse_progress(self, pct: int, msg: str) -> None:
        self._left.set_progress(pct)
        self._left.set_status(msg)

    def _on_parse_finished(self, map_data: MapData) -> None:
        if self._closing_after_parse:
            self._map_data = map_data
            self._parsing = False
            self._ensure_project_name()
            self._save_project(silent=True)
            self._db.close()
            QApplication.quit()
            return

        preserved = self._map_data.postmap_info if self._map_data else None
        map_data.postmap_info = self._merge_preserved_postmap_info(
            map_data.postmap_info,
            preserved,
        )

        self._map_data = map_data
        self._ensure_project_info_date(map_data)
        self._refresh_postplot_4d_input_signatures(invalidate=True)
        self._invalidate_postplot_4d_diffs(map_data)
        self._prune_legend_sequence_refs()
        if self._settings.preplot_files:
            self._settings.preplot_catalog = build_preplot_catalog_from_segments(
                self._settings.preplot_files,
                map_data.preplot_segments,
                map_data.postmap_info.epsg_code,
            )
        elif self._settings.preplot_files_explicit:
            self._settings.preplot_catalog = []
        sync_preplot_legend_entries(
            self._settings.legend_config,
            self._settings.preplot_catalog,
        )
        if self._settings.navplan_files:
            self._settings.navplan_catalog = build_navplan_catalog_from_segments(
                self._settings.navplan_files,
                map_data.navplan_segments,
                map_data.postmap_info.epsg_code,
            )
        elif self._settings.navplan_files_explicit:
            self._settings.navplan_catalog = []
        sync_navplan_legend_entries(
            self._settings.legend_config,
            self._settings.navplan_catalog,
        )
        self._apply_map_crs_from_preplot(map_data)
        self._sync_map_data_preplot_order()
        self._refresh_preplot_summary()
        self._left.set_progress(100, False)
        skipped = map_data.stats.get("nav_files_skipped", 0)
        parsed = map_data.stats.get("nav_files_parsed", 0)
        skip_note = f", {skipped} nav file(s) unchanged" if skipped else ""
        self._left.set_status(
            f"Loaded {map_data.stats.get('total_records', 0):,} nav records, "
            f"{map_data.stats.get('preplot_lines', 0)} preplot lines from "
            f"{parsed or map_data.stats.get('source_files', 0)} parsed nav + "
            f"{map_data.stats.get('preplot_files', 0)} preplot file(s), "
            f"{map_data.stats.get('navplan_files', 0)} navplan file(s){skip_note}"
        )
        self._left.set_status("Parse complete. Rendering map…")
        QTimer.singleShot(0, self._finish_parse_render)

    def _finish_parse_render(self) -> None:
        if self._map_data is None:
            return
        started = time.perf_counter()
        self._map.set_legend(self._settings.legend_config)
        self._map.set_display_mode(self._settings.display_mode)
        self._invalidate_conditional_diff_cache()
        self._refresh_conditional_postplot_points()
        self._map.render(self._map_data, force=True)
        print(f"[xPostMaps timing] Map render after parse: {(time.perf_counter() - started) * 1000:.1f} ms")
        self._left.set_status("Map rendered. Updating right pane…")
        QTimer.singleShot(0, self._finish_parse_right_pane)

    def _finish_parse_right_pane(self) -> None:
        if self._map_data is None:
            return
        started = time.perf_counter()
        self._right.update_from_project(self._settings, self._map_data)
        self._mediator.map_data_updated.emit(self._map_data)
        print(f"[xPostMaps timing] Right pane update after parse: {(time.perf_counter() - started) * 1000:.1f} ms")
        self._left.set_status("Saving parsed project…")
        QTimer.singleShot(0, self._finish_parse_save)

    def _finish_parse_save(self) -> None:
        started = time.perf_counter()
        self._parsing = False
        self._autosave.set_enabled(True)
        self._metadata_autosave.set_enabled(True)
        self._ensure_project_name()
        self._autosave.save_now()
        print(f"[xPostMaps timing] Parse-finish save dispatch: {(time.perf_counter() - started) * 1000:.1f} ms")

    def _on_parse_failed(self, message: str) -> None:
        self._parsing = False
        if self._closing_after_parse:
            self._save_close_metadata()
            self._db.close()
            QApplication.quit()
            return
        self._autosave.set_enabled(True)
        self._metadata_autosave.set_enabled(True)
        self._left.set_progress(0, False)
        self._left.set_status(message)
        QMessageBox.warning(self, "Parse Error", message)

    def _on_map_data_updated(self, map_data: MapData) -> None:
        self._map_data = map_data

    def _open_project_browser(self) -> None:
        dialog = ProjectBrowserDialog.open(
            self,
            str(self._db_directory),
            on_load=self._load_database_project,
            on_delete=self._delete_database_project,
            on_new_project=self._create_new_project,
            on_directory_changed=self._on_db_directory_changed,
        )
        self._track_left_dialog("browse_load", dialog)

    def _on_db_directory_changed(self, directory: str) -> None:
        self._db_directory = Path(directory)
        save_db_directory(self._db_directory)

    def _switch_database(self, db_path: Path) -> None:
        if self._db.db_path.resolve() == db_path.resolve():
            return
        self._db.close()
        self._db = Database(db_path)

    def _load_database_project(self, db_path: str, project_name: str) -> None:
        path = Path(db_path)
        if not path.is_file():
            QMessageBox.warning(self, "Load Project", f"Database not found:\n{db_path}")
            return
        self._switch_database(path)
        self._load_project_by_name(project_name)

    def _create_new_project(self, directory: str, project_name: str) -> bool:
        name = project_name.strip()
        if not name:
            return False
        db_dir = Path(directory)
        db_dir.mkdir(parents=True, exist_ok=True)
        target_db = project_db_path(db_dir, name)
        if target_db.exists():
            existing_db = Database(target_db)
            try:
                if name in existing_db.list_projects():
                    QMessageBox.warning(
                        self,
                        "New Project",
                        f"Project '{name}' already exists.",
                    )
                    return False
            finally:
                existing_db.close()

        settings = ProjectSettings(name=name)
        map_data = MapData(postmap_info=PostmapInfo())
        self._switch_database(target_db)
        try:
            self._db.save_project(settings, map_data)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self,
                "New Project",
                f"Could not create project database:\n{exc}",
            )
            return False

        self._db_directory = db_dir
        save_db_directory(self._db_directory)
        self._apply_loaded_project(settings, map_data)
        self.statusBar().showMessage(f"Created project: {name}", 3000)
        return True

    def _delete_database_project(self, db_path: str, project_name: str) -> None:
        path = Path(db_path)
        if not path.is_file():
            raise FileNotFoundError(path.name)

        owns_temp = self._db.db_path.resolve() != path.resolve()
        db = Database(path) if owns_temp else self._db
        try:
            if not db.delete_project(project_name):
                raise ValueError(f"Project '{project_name}' was not found.")
            remaining = db.list_projects()
        finally:
            if owns_temp:
                db.close()

        if self._settings.name.strip() == project_name.strip():
            self._settings = ProjectSettings()
            self._map_data = None
            self._left.set_project_name("")
            self._left.set_p111_p190_dir("")
            self._left.set_preplot_navplan("")
            self._left.set_navplan("")
            self._refresh_ui()

        if not remaining and path.is_file():
            path.unlink()

    def _load_database_file(self, db_path: str) -> None:
        path = Path(db_path)
        if not path.is_file():
            QMessageBox.warning(self, "Load Project", f"Database not found:\n{db_path}")
            return

        self._switch_database(path)
        projects = self._db.list_projects()
        if not projects:
            QMessageBox.information(
                self,
                "Load Project",
                f"No projects found in '{path.name}'.",
            )
            return

        if len(projects) == 1:
            self._load_project_by_name(projects[0])
            return

        name, ok = QInputDialog.getItem(
            self,
            "Load Project",
            f"Select project in {path.name}:",
            projects,
            0,
            False,
        )
        if ok and name:
            self._load_project_by_name(name)

    def _load_project_by_name(self, name: str) -> None:
        loaded = self._db.load_project(name)
        if loaded:
            self._apply_loaded_project(*loaded)
        else:
            QMessageBox.warning(self, "Load Project", f"Could not load '{name}'.")

    def _apply_loaded_project(self, settings: ProjectSettings, map_data: MapData) -> None:
        self._loading_project = True
        try:
            self._settings = settings
            self._map_data = map_data
            self._refresh_postplot_4d_input_signatures(invalidate=False)
            if settings.preplot_files and not settings.preplot_catalog:
                settings.preplot_catalog = build_preplot_catalog_from_segments(
                    settings.preplot_files,
                    map_data.preplot_segments,
                    map_data.postmap_info.epsg_code,
                )
            sync_preplot_legend_entries(
                settings.legend_config,
                settings.preplot_catalog,
            )
            if settings.navplan_files and not settings.navplan_catalog:
                settings.navplan_catalog = build_navplan_catalog_from_segments(
                    settings.navplan_files,
                    map_data.navplan_segments,
                    map_data.postmap_info.epsg_code,
                )
            sync_navplan_legend_entries(
                settings.legend_config,
                settings.navplan_catalog,
            )
            self._apply_map_crs_from_preplot(map_data)
            self._sync_map_data_preplot_order()
            self._left.set_project_name(settings.name)
            if settings.nav_files:
                nav_display = (
                    f"{len(settings.nav_files)} file(s)"
                    if len(settings.nav_files) != 1
                    else settings.nav_files[0]
                )
            else:
                nav_display = settings.p111_p190_dir
            self._left.set_p111_p190_dir(nav_display)
            self._refresh_preplot_summary()
            if settings.logo_path:
                self._right.set_logo(settings.logo_path)
            self._map.clear()
            self._map.set_legend(self._settings.legend_config)
            self._map.set_display_mode(self._settings.display_mode)
            self._invalidate_conditional_diff_cache()
            self._refresh_conditional_postplot_points()
            self._map.render(self._map_data, force=True)
            self._map.restore_view(settings.map_view)
            self._map.render(self._map_data, force=True)
            self._right.update_from_project(
                self._settings,
                self._map_data,
                apply_saved_minimap_view=True,
            )
            self._refresh_import_polygons_summary()
            total_records = int(map_data.stats.get("total_records", 0))
            self.statusBar().showMessage(
                f"Loaded project: {settings.name} "
                f"({len(map_data.segments)} nav segments, "
                f"{len(map_data.preplot_segments)} preplot segments, "
                f"{len(map_data.navplan_segments)} navplan segments, "
                f"{total_records:,} positions)"
            )
        finally:
            self._loading_project = False

    def _autosave_project(self) -> bool:
        return self._save_project(silent=True)

    def _autosave_project_metadata(self) -> bool:
        return self._save_project_metadata(silent=True)

    def _save_project_metadata(self, silent: bool = False) -> bool:
        if self._parsing:
            return False
        self._sync_current_views()
        self._settings.name = self._left.project_name() or self._settings.name.strip()
        name = self._settings.name.strip()
        if not name and not self._ensure_project_name():
            return False
        self._settings.name = self._settings.name.strip()
        target_db = project_db_path(self._db_directory, self._settings.name)
        self._db_directory.mkdir(parents=True, exist_ok=True)
        self._switch_database(target_db)
        try:
            self._db.save_project_metadata(self._settings, self._ensure_map_data())
        except Exception as exc:  # noqa: BLE001
            if not silent:
                QMessageBox.critical(self, "Save Project", f"Could not save project:\n{exc}")
            else:
                self.statusBar().showMessage(f"Auto-save failed: {exc}")
            return False
        if silent:
            self.statusBar().showMessage(f"Auto-saved: {self._settings.name}", 3000)
        return True

    def _save_project(self, silent: bool = False) -> bool:
        if self._parsing:
            if not silent:
                QMessageBox.warning(
                    self,
                    "Save Project",
                    "Cannot save while navigation files are still parsing.",
                )
            return False

        self._sync_current_views()
        self._settings.name = self._left.project_name() or self._settings.name.strip()
        name = self._settings.name.strip()
        if not name and not self._ensure_project_name():
            if not silent:
                QMessageBox.warning(self, "Save Project", "Enter a project name first.")
            return False

        name = self._settings.name.strip()
        self._settings.name = name
        target_db = project_db_path(self._db_directory, name)
        self._db_directory.mkdir(parents=True, exist_ok=True)
        self._switch_database(target_db)

        map_data = self._ensure_map_data()

        try:
            self._db.save_project(self._settings, map_data)
        except Exception as exc:  # noqa: BLE001
            if not silent:
                QMessageBox.critical(self, "Save Project", f"Could not save project:\n{exc}")
            else:
                self.statusBar().showMessage(f"Auto-save failed: {exc}")
            return False

        save_note = f"{name} → {target_db.name}"
        if silent:
            self.statusBar().showMessage(f"Auto-saved: {save_note}", 3000)
        else:
            self.statusBar().showMessage(f"Saved project: {save_note}")
            QMessageBox.information(
                self,
                "Save Project",
                f"Project '{name}' saved to:\n{target_db}",
            )
        self._mediator.project_saved.emit(name)
        return True

    def _save_close_metadata(self) -> bool:
        """Fast close-time save: latest UI metadata only, never full geometry."""
        if not (self._settings.name.strip() or self._ensure_project_name()):
            return False
        self._sync_current_views()
        self._settings.name = self._left.project_name() or self._settings.name.strip()
        name = self._settings.name.strip()
        if not name:
            return False
        target_db = project_db_path(self._db_directory, name)
        self._db_directory.mkdir(parents=True, exist_ok=True)
        self._switch_database(target_db)
        if self._db.get_project_id(name) is None:
            return False
        try:
            self._db.save_project_metadata(self._settings, self._ensure_map_data())
        except Exception:  # noqa: BLE001
            return False
        return True

    def closeEvent(self, event) -> None:  # noqa: N802
        self._autosave.set_enabled(False)
        self._metadata_autosave.set_enabled(False)
        if self._worker and self._worker.isRunning():
            self._closing_after_parse = True
            self._save_close_metadata()
            self.hide()
            event.ignore()
            return
        self._save_close_metadata()
        self._db.close()
        super().closeEvent(event)
