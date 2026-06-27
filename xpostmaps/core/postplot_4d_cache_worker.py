"""Background population of parse-derived Postplot 4D caches."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from xpostmaps.core.database import Database
from xpostmaps.core.models import MapData, ProjectSettings
from xpostmaps.core.postplot_4d_diff import warm_postplot_4d_parse_caches


class Postplot4DCacheWarmWorker(QThread):
    progress = Signal(int, int, str)
    finished_ok = Signal(int, int, float)
    failed = Signal(str)

    def __init__(
        self,
        db_path: Path,
        project_name: str,
        settings: ProjectSettings,
        map_data: MapData,
        *,
        include_receiver_feathers: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._db_path = db_path
        self._project_name = project_name
        self._settings = settings
        self._map_data = map_data
        self._include_receiver_feathers = include_receiver_feathers
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        self.requestInterruption()

    def _is_cancelled(self) -> bool:
        return self._cancelled or self.isInterruptionRequested()

    def run(self) -> None:
        started = time.perf_counter()
        db: Database | None = None
        try:
            db = Database(self._db_path)
            preplot_lines, feather_files = warm_postplot_4d_parse_caches(
                self._map_data,
                self._settings,
                db,
                self._project_name,
                include_receiver_feathers=self._include_receiver_feathers,
                db_path=self._db_path,
                progress_callback=self.progress.emit,
                cancelled=self._is_cancelled,
            )
            self.finished_ok.emit(
                preplot_lines,
                feather_files,
                time.perf_counter() - started,
            )
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        finally:
            if db is not None:
                db.close()
