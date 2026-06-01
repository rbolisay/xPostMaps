"""Main application window."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QWidget,
)

from xpostmaps.core.autosave import AutosaveController
from xpostmaps.core.database import Database
from xpostmaps.core.legend_utils import legend_from_dict, legend_to_dict
from xpostmaps.core.mediator import Mediator
from xpostmaps.core.models import (
    DisplayMode,
    LegendConfig,
    LineSequence,
    MapData,
    PostmapInfo,
    ProjectSettings,
)
from xpostmaps.core.parse_worker import ParseWorker
from xpostmaps.core.sequence_utils import sequence_id_matches
from xpostmaps.ui.dialogs.legend_dialog import LegendDialog
from xpostmaps.parsers.directory_parser import NAV_EXTENSIONS, resolve_nav_files
from xpostmaps.parsers.preplot_parser import PREPLOT_EXTENSIONS
from xpostmaps.ui.dialogs.nav_picker_dialog import NavFilePickerDialog
from xpostmaps.ui.dialogs.postmap_info_dialog import PostmapInfoDialog
from xpostmaps.ui.left_panel import LeftPanel
from xpostmaps.ui.map_widget import PostplotMapWidget
from xpostmaps.ui.right_pane import RightPane
from xpostmaps.ui.theme import BG_DARK, app_stylesheet


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._mediator = Mediator.instance()
        self._db = Database()
        self._settings = ProjectSettings()
        self._map_data: MapData | None = None
        self._worker: ParseWorker | None = None
        self._loading_project = False
        self._parsing = False
        self._autosave = AutosaveController(self._autosave_project, self, delay_ms=2000)

        self.setWindowTitle("xPostMaps — Postplot Viewer")
        self.resize(1600, 900)
        self.setStyleSheet(app_stylesheet())

        central = QWidget()
        central.setStyleSheet(f"background: {BG_DARK};")
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(12, 12, 0, 12)
        root.setSpacing(12)

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
        root.addWidget(self._left)
        root.addWidget(sheet_host, stretch=1)

        status = QStatusBar()
        self.setStatusBar(status)
        status.showMessage("Ready")

        self._connect_signals()
        self._refresh_ui()

    def _connect_signals(self) -> None:
        self._left.project_name_changed.connect(self._on_project_name_changed)
        self._left.browse_project.connect(self._load_project)
        self._left.load_project.connect(self._load_project)
        self._left.save_project.connect(lambda: self._save_project(silent=False))
        self._left.select_preplot_navplan.connect(self._select_preplot_navplan)
        self._left.select_p111_p190_dir.connect(self._select_p111_dir)
        self._left.select_logo.connect(self._select_logo)
        self._left.open_postmap_info.connect(self._open_postmap_info)
        self._left.open_legend.connect(self._open_legend)

        self._mediator.map_data_updated.connect(self._on_map_data_updated)
        self._mediator.status_message.connect(self.statusBar().showMessage)

    def _schedule_autosave(self) -> None:
        if self._loading_project or self._parsing:
            return
        self._autosave.schedule()

    def _ensure_project_name(self) -> bool:
        """Derive a project name from loaded file paths when none was entered."""
        if self._settings.name.strip():
            return True
        candidates: list[str] = []
        if self._settings.preplots_dir:
            candidates.append(self._settings.preplots_dir)
        if self._settings.p111_p190_dir:
            candidates.append(self._settings.p111_p190_dir)
        candidates.extend(self._settings.preplot_files[:1])
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

    def _refresh_ui(self) -> None:
        self._map.set_legend(self._settings.legend_config)
        self._map.set_display_mode(self._settings.display_mode)
        self._map.render(self._map_data)
        self._right.update_from_project(self._settings, self._map_data)

    def _on_project_name_changed(self, name: str) -> None:
        self._settings.name = name.strip()
        self._schedule_autosave()

    def _on_logo_changed(self, path: str) -> None:
        self._settings.logo_path = path
        self._right.set_logo(path)
        self._schedule_autosave()

    def _select_logo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Logo",
            self._settings.logo_path or "",
            "Images (*.png *.jpg *.jpeg *.svg *.bmp);;All Files (*)",
        )
        if path:
            self._on_logo_changed(path)

    def _open_legend(self) -> None:
        perimeters = self._map_data.survey_perimeters if self._map_data else []
        LegendDialog.open(
            self,
            self._settings.legend_config,
            on_apply=self._on_legend_apply,
            sequences=self._map_data.sequences if self._map_data else [],
            sequences_provider=self._current_sequences,
            survey_perimeters=perimeters,
        )

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
        self._map.set_legend(self._settings.legend_config)
        self._map.render(self._map_data)
        self._right.update_from_project(self._settings, self._map_data)
        self._autosave.save_now()
        self.statusBar().showMessage("Legend applied")

    def _open_postmap_info(self) -> None:
        info = self._map_data.postmap_info if self._map_data else PostmapInfo()
        PostmapInfoDialog.open(self, info, on_changed=self._on_postmap_info_changed)

    def _on_postmap_info_changed(self, info: PostmapInfo) -> None:
        map_data = self._ensure_map_data()
        map_data.postmap_info = info
        self._right.update_from_project(self._settings, map_data)
        self._schedule_autosave()

    def _select_preplot_navplan(self) -> None:
        result = NavFilePickerDialog.pick(
            self,
            title="Select Preplot / Navplan Files",
            hint=(
                "Select preplot (.p111/.p190 start/end lines, doglegs) or "
                "navplan files (shotpoints along each line)."
            ),
            extensions=PREPLOT_EXTENSIONS,
            file_filter=(
                "Preplot / Navplan (*.p111 *.p190 *.nav *.navplan *.plan *.txt);;"
                "All Files (*)"
            ),
            initial_dir=self._settings.preplots_dir or self._settings.p111_p190_dir or "",
            initial_files=self._settings.preplot_files or None,
        )
        if not result:
            return
        files, folder = result
        self._settings.preplot_files = files
        self._settings.preplots_dir = folder
        display = (
            f"{len(files)} file(s)"
            if len(files) != 1
            else files[0]
        )
        self._left.set_preplot_navplan(display)
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
        )
        if result is None:
            return
        files, folder = result
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

    def _start_parse(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        has_nav = bool(resolve_nav_files(self._settings))
        has_preplot = bool(
            self._settings.preplot_files
            or self._settings.preplots_dir
            or self._settings.overlay_dir
        )
        if not has_nav and not has_preplot:
            return

        self._parsing = True
        self._autosave.set_enabled(False)
        self._left.set_progress(0, True)
        self._left.set_status("Parsing files…")
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

    def _on_parse_progress(self, pct: int, msg: str) -> None:
        self._left.set_progress(pct)
        self._left.set_status(msg)

    def _on_parse_finished(self, map_data: MapData) -> None:
        if self._map_data and self._map_data.postmap_info:
            preserved = self._map_data.postmap_info
            for field in PostmapInfo.__dataclass_fields__:
                if field == "extra":
                    continue
                edited = getattr(preserved, field)
                if edited:
                    setattr(map_data.postmap_info, field, edited)

        self._map_data = map_data
        self._prune_legend_sequence_refs()
        self._left.set_progress(100, False)
        skipped = map_data.stats.get("nav_files_skipped", 0)
        parsed = map_data.stats.get("nav_files_parsed", 0)
        skip_note = f", {skipped} nav file(s) unchanged" if skipped else ""
        self._left.set_status(
            f"Loaded {map_data.stats.get('total_records', 0):,} nav records, "
            f"{map_data.stats.get('preplot_lines', 0)} preplot lines from "
            f"{parsed or map_data.stats.get('source_files', 0)} parsed nav + "
            f"{map_data.stats.get('preplot_files', 0)} preplot file(s){skip_note}"
        )
        self._refresh_ui()
        self._mediator.map_data_updated.emit(map_data)
        self._parsing = False
        self._autosave.set_enabled(True)
        self._ensure_project_name()
        self._autosave.save_now()

    def _on_parse_failed(self, message: str) -> None:
        self._parsing = False
        self._autosave.set_enabled(True)
        self._left.set_progress(0, False)
        self._left.set_status(message)
        QMessageBox.warning(self, "Parse Error", message)

    def _on_map_data_updated(self, map_data: MapData) -> None:
        self._map_data = map_data

    def _load_project(self) -> None:
        projects = self._db.list_projects()
        if not projects:
            QMessageBox.information(self, "Load Project", "No saved projects found.")
            return
        name, ok = QInputDialog.getItem(
            self, "Load Project", "Select project:", projects, 0, False
        )
        if ok and name:
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
            preplot_display = (
                f"{len(settings.preplot_files)} file(s)"
                if settings.preplot_files
                else settings.preplots_dir or settings.overlay_dir
            )
            self._left.set_preplot_navplan(preplot_display)
            if settings.logo_path:
                self._right.set_logo(settings.logo_path)
            self._refresh_ui()
            self.statusBar().showMessage(
                f"Loaded project: {settings.name} "
                f"({len(map_data.segments)} nav segments, "
                f"{len(map_data.preplot_segments)} preplot segments, "
                f"{len(map_data.positions):,} positions)"
            )
        finally:
            self._loading_project = False

    def _autosave_project(self) -> bool:
        return self._save_project(silent=True)

    def _save_project(self, silent: bool = False) -> bool:
        if self._parsing:
            return False
        name = self._settings.name.strip()
        if not name and not self._ensure_project_name():
            if not silent:
                QMessageBox.warning(self, "Save Project", "Enter a project name first.")
            return False

        name = self._settings.name.strip()

        self._settings.name = name
        map_data = self._ensure_map_data()

        try:
            self._db.save_project(self._settings, map_data)
        except Exception as exc:  # noqa: BLE001
            if not silent:
                QMessageBox.critical(self, "Save Project", f"Could not save project:\n{exc}")
            else:
                self.statusBar().showMessage(f"Auto-save failed: {exc}")
            return False

        if silent:
            self.statusBar().showMessage(f"Auto-saved: {name}", 3000)
        else:
            self.statusBar().showMessage(f"Saved project: {name}")
        self._mediator.project_saved.emit(name)
        return True

    def closeEvent(self, event) -> None:  # noqa: N802
        self._autosave.set_enabled(False)
        if self._worker and self._worker.isRunning():
            self._worker.wait(120_000)
            self._parsing = False
        if self._settings.name.strip() or self._ensure_project_name():
            self._save_project(silent=True)
        self._db.close()
        super().closeEvent(event)
