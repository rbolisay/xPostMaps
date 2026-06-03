"""Background PDF composition (widget capture must run on the UI thread)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from xpostmaps.core.pdf_export import PdfExportOptions, compose_pdf_to_path


@dataclass(frozen=True)
class PdfExportCapture:
    map_image: QImage
    pane_image: QImage


class PdfExportWorker(QThread):
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        output_path: Path,
        capture: PdfExportCapture,
        options: PdfExportOptions,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._output_path = output_path
        self._capture = capture
        self._options = options

    def run(self) -> None:
        try:
            compose_pdf_to_path(
                self._output_path,
                self._capture.map_image,
                self._capture.pane_image,
                self._options,
            )
            self.finished_ok.emit(str(self._output_path))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
