"""Background parsing worker."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from xpostmaps.core.models import MapData, PostmapInfo, ProjectSettings
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
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._existing_postmap = existing_postmap
        self._existing_map_data = existing_map_data

    def run(self) -> None:
        try:
            has_nav = bool(resolve_nav_files(self._settings))
            has_preplot = bool(resolve_preplot_files(self._settings))
            explicit = (
                self._settings.nav_files_explicit
                or self._settings.preplot_files_explicit
            )
            if not has_nav and not has_preplot and not explicit:
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
            if (
                not map_data.segments
                and not map_data.preplot_segments
                and not explicit
            ):
                self.failed.emit("No navigation or preplot records found in selected files.")
                return
            self.finished_ok.emit(map_data)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
