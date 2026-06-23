"""Background parsing worker."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from xpostmaps.core.database import Database
from xpostmaps.core.models import MapData, PostmapInfo, ProjectSettings
from xpostmaps.core.navplan_catalog_utils import resolve_navplan_files
from xpostmaps.parsers.directory_parser import parse_navigation_directory, resolve_nav_files
from xpostmaps.parsers.preplot_parser import resolve_preplot_files


class ParseWorker(QThread):
    progress = Signal(int, str)
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        settings: ProjectSettings,
        parent=None,
        existing_postmap: PostmapInfo | None = None,
        existing_map_data: MapData | None = None,
        project_db_path: Path | None = None,
        project_name: str = "",
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._existing_postmap = existing_postmap
        self._existing_map_data = existing_map_data
        self._project_db_path = project_db_path
        self._project_name = project_name

    def _ensure_positions_loaded(self) -> None:
        """Load persisted positions inside the worker thread before incremental parse."""
        md = self._existing_map_data
        if md is None or md.positions or not md.positions_persisted:
            return
        if self._project_db_path is None or not self._project_name.strip():
            return

        db: Database | None = None
        try:
            db = Database(self._project_db_path)
            md.positions = db.load_positions(self._project_name)
        except Exception:  # noqa: BLE001
            md.positions = []
        finally:
            if db is not None:
                db.close()
        md.positions_persisted = False

    def run(self) -> None:
        try:
            worker_started = time.perf_counter()
            has_nav = bool(resolve_nav_files(self._settings))
            has_preplot = bool(resolve_preplot_files(self._settings))
            has_navplan = bool(resolve_navplan_files(self._settings))
            explicit = (
                self._settings.nav_files_explicit
                or self._settings.preplot_files_explicit
                or self._settings.navplan_files_explicit
            )
            if not has_nav and not has_preplot and not has_navplan and not explicit:
                self.failed.emit("Select P111/P190, preplot, or navplan files first.")
                return

            def callback(pct: int, msg: str) -> None:
                self.progress.emit(pct, msg)

            self.progress.emit(0, "Loading cached positions…")
            cache_started = time.perf_counter()
            self._ensure_positions_loaded()
            print(
                "[xPostMaps timing] Cached position load: "
                f"{(time.perf_counter() - cache_started) * 1000:.1f} ms"
            )

            parse_started = time.perf_counter()
            map_data: MapData = parse_navigation_directory(
                self._settings,
                progress_callback=callback,
                existing_postmap=self._existing_postmap,
                existing_map_data=self._existing_map_data,
            )
            print(
                "[xPostMaps timing] Parse worker parse_navigation_directory: "
                f"{(time.perf_counter() - parse_started) * 1000:.1f} ms"
            )
            if (
                not map_data.segments
                and not map_data.preplot_segments
                and not map_data.navplan_segments
                and not explicit
            ):
                self.failed.emit("No navigation, preplot, or navplan records found in selected files.")
                return
            print(
                "[xPostMaps timing] Parse worker total: "
                f"{(time.perf_counter() - worker_started) * 1000:.1f} ms"
            )
            self.finished_ok.emit(map_data)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
