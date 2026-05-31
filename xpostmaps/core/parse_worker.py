"""Background parsing worker."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from xpostmaps.core.models import MapData, PostmapInfo, ProjectSettings
from xpostmaps.parsers.directory_parser import parse_navigation_directory


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
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._existing_postmap = existing_postmap
        self._existing_map_data = existing_map_data

    def run(self) -> None:
        try:
            has_nav = bool(self._settings.nav_files or self._settings.p111_p190_dir)
            has_preplot = bool(
                self._settings.preplot_files
                or self._settings.preplots_dir
                or self._settings.overlay_dir
            )
            if not has_nav and not has_preplot:
                self.failed.emit("Select P111/P190 or Preplot/Navplan files first.")
                return

            def callback(pct: int, msg: str) -> None:
                self.progress.emit(pct, msg)

            map_data: MapData = parse_navigation_directory(
                self._settings,
                progress_callback=callback,
                existing_postmap=self._existing_postmap,
                existing_map_data=self._existing_map_data,
            )
            if not map_data.segments and not map_data.preplot_segments:
                self.failed.emit("No navigation or preplot records found in selected files.")
                return
            self.finished_ok.emit(map_data)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
