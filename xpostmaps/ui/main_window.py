"""Main application window."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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

from xpostmaps.core.branding import APP_WINDOW_TITLE, DEVELOPER_CREDIT

from xpostmaps.core.autosave import AutosaveController
from xpostmaps.core.database import Database
from xpostmaps.core.legend_utils import legend_from_dict, legend_to_dict
from xpostmaps.core.local_settings import load_db_directory, save_db_directory
from xpostmaps.core.mediator import Mediator
from xpostmaps.core.project_db_utils import project_db_path
from xpostmaps.core.models import (
    DisplayMode,
    LegendConfig,
    LineSequence,
    MapData,
    PostmapInfo,
    ProjectSettings,
)
from xpostmaps.core.parse_worker import ParseWorker
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
from xpostmaps.ui.dialogs.legend_dialog import LegendDialog
from xpostmaps.parsers.directory_parser import NAV_EXTENSIONS, resolve_nav_files
from xpostmaps.parsers.preplot_parser import resolve_preplot_files
from xpostmaps.core.polygon_import_service import imported_polygon_entries
from xpostmaps.ui.dialogs.nav_picker_dialog import NavFilePickerDialog
from xpostmaps.ui.dialogs.pdf_export_dialog import PdfExportDialog
from xpostmaps.ui.dialogs.postmap_info_dialog import PostmapInfoDialog
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
        self._worker: ParseWorker | None = None
        self._loading_project = False
        self._parsing = False
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

        credit = QLabel(DEVELOPER_CREDIT)
        credit.setStyleSheet("color: #6e7681; font-size: 10px; padding-left: 2px;")
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
        self._left.open_legend.connect(self._open_legend)
        self._left.open_pdf_export.connect(self._open_pdf_export)
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

    def _on_logo_changed(self, path: str) -> None:
        self._settings.logo_path = path
        self._right.set_logo(path)
        self._persist_project()

    def _select_logo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Logo",
            self._settings.logo_path or "",
            "Images (*.png *.jpg *.jpeg *.svg *.bmp);;All Files (*)",
        )
        if path:
            self._on_logo_changed(path)

    def _open_pdf_export(self) -> None:
        if not self._map_data:
            QMessageBox.information(
                self,
                "Export to PDF",
                "Load a project with map data before exporting.",
            )
            return
        self._right.update_from_project(self._settings, self._map_data)
        PdfExportDialog.open(
            self,
            map_widget=self._map,
            right_pane=self._right,
            settings=self._settings,
            map_data=self._map_data,
            project_name=self._settings.name,
            default_output_dir=self._db_directory,
        )

    def _open_legend(self) -> None:
        perimeters = self._map_data.survey_perimeters if self._map_data else []
        LegendDialog.open(
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

    def _open_import_polygons(self) -> None:
        ImportPolygonsDialog.open(
            self,
            self._settings.legend_config,
            self._current_map_epsg(),
            on_apply=self._on_import_polygons_apply,
            on_map_epsg_changed=self._on_import_map_epsg_changed,
        )

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
        self._map.render(self._map_data)
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
        PostmapInfoDialog.open(self, info, on_changed=self._on_postmap_info_changed)

    def _on_postmap_info_changed(self, info: PostmapInfo) -> None:
        map_data = self._ensure_map_data()
        map_data.postmap_info = info
        self._ensure_project_info_date(map_data)
        self._right.refresh_postmap_info(map_data)
        self._schedule_metadata_autosave()

    def _select_preplot_navplan(self) -> None:
        PreplotNavplanDialog.open(
            self,
            self._settings,
            on_apply=self._on_preplot_settings_changed,
            initial_dir=self._settings.preplots_dir or self._settings.p111_p190_dir or "",
        )

    def _open_import_navplan(self) -> None:
        ImportNavplanDialog.open(
            self,
            self._settings,
            on_apply=self._on_navplan_settings_changed,
            initial_dir=self._settings.navplans_dir
            or self._settings.preplots_dir
            or self._settings.p111_p190_dir
            or "",
        )

    def _on_preplot_settings_changed(self, settings: ProjectSettings) -> None:
        self._settings.preplot_files = settings.preplot_files
        self._settings.preplot_files_explicit = settings.preplot_files_explicit
        self._settings.preplots_dir = settings.preplots_dir
        self._settings.preplot_catalog = list(settings.preplot_catalog)
        sync_preplot_legend_entries(
            self._settings.legend_config,
            self._settings.preplot_catalog,
        )
        self._refresh_preplot_summary()
        self._ensure_project_name()
        self._start_parse()

    def _on_navplan_settings_changed(self, settings: ProjectSettings) -> None:
        self._settings.navplan_files = settings.navplan_files
        self._settings.navplan_files_explicit = settings.navplan_files_explicit
        self._settings.navplans_dir = settings.navplans_dir
        self._settings.navplan_catalog = list(settings.navplan_catalog)
        sync_navplan_legend_entries(
            self._settings.legend_config,
            self._settings.navplan_catalog,
        )
        self._refresh_preplot_summary()
        self._ensure_project_name()
        self._start_parse()

    def _apply_nav_file_selection(self, files: list[str], folder: str) -> None:
        """Apply nav file list and re-parse so the map and database stay in sync."""
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
        result = NavFilePickerDialog.pick(
            self,
            title="Select P111/P190 Files",
            hint="Select a folder to scan for .p111/.p190 files, or add individual files.",
            extensions=NAV_EXTENSIONS,
            file_filter="Navigation Files (*.p111 *.p190 *.txt *.nav);;All Files (*)",
            initial_dir=self._settings.p111_p190_dir or "",
            initial_files=self._settings.nav_files or None,
            on_rescan=self._apply_nav_file_selection,
        )
        if result is None:
            return
        self._apply_nav_file_selection(*result)

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
        self._ensure_positions_loaded()
        existing = self._map_data.postmap_info if self._map_data else None
        self._worker = ParseWorker(
            self._settings,
            self,
            existing_postmap=existing,
            existing_map_data=self._map_data,
        )
        self._worker.progress.connect(self._on_parse_progress)
        self._worker.finished_ok.connect(self._on_parse_finished)
        self._worker.failed.connect(self._on_parse_failed)
        self._worker.start()

    def _ensure_positions_loaded(self) -> None:
        """Load persisted positions into memory before a re-parse.

        Positions are skipped on project open for speed; incremental re-parsing
        needs them to carry over records from unchanged nav files.
        """
        md = self._map_data
        if md is None or md.positions or not md.positions_persisted:
            return
        name = self._settings.name.strip()
        if not name:
            return
        try:
            md.positions = self._db.load_positions(name)
        except Exception:  # noqa: BLE001
            md.positions = []
        md.positions_persisted = False

    def _on_parse_progress(self, pct: int, msg: str) -> None:
        self._left.set_progress(pct)
        self._left.set_status(msg)

    def _on_parse_finished(self, map_data: MapData) -> None:
        preserved = self._map_data.postmap_info if self._map_data else None
        map_data.postmap_info = self._merge_preserved_postmap_info(
            map_data.postmap_info,
            preserved,
        )

        self._map_data = map_data
        self._ensure_project_info_date(map_data)
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
        self._map.set_legend(self._settings.legend_config)
        self._map.set_display_mode(self._settings.display_mode)
        self._map.render(self._map_data, force=True)
        self._right.update_from_project(self._settings, self._map_data)
        self._mediator.map_data_updated.emit(map_data)
        self._parsing = False
        self._autosave.set_enabled(True)
        self._metadata_autosave.set_enabled(True)
        self._ensure_project_name()
        self._autosave.save_now()

    def _on_parse_failed(self, message: str) -> None:
        self._parsing = False
        self._autosave.set_enabled(True)
        self._metadata_autosave.set_enabled(True)
        self._left.set_progress(0, False)
        self._left.set_status(message)
        QMessageBox.warning(self, "Parse Error", message)

    def _on_map_data_updated(self, map_data: MapData) -> None:
        self._map_data = map_data

    def _open_project_browser(self) -> None:
        ProjectBrowserDialog.open(
            self,
            str(self._db_directory),
            on_load=self._load_database_project,
            on_delete=self._delete_database_project,
            on_new_project=self._create_new_project,
            on_directory_changed=self._on_db_directory_changed,
        )

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
            self._refresh_ui()
            self._map.restore_view(settings.map_view)
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

    def closeEvent(self, event) -> None:  # noqa: N802
        self._autosave.set_enabled(False)
        self._metadata_autosave.set_enabled(False)
        if self._worker and self._worker.isRunning():
            self._worker.wait(120_000)
            self._parsing = False
        if self._settings.name.strip() or self._ensure_project_name():
            self._save_project(silent=True)
        self._db.close()
        super().closeEvent(event)
