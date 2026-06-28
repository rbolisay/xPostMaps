"""Background worker for Layer Styles shapefile/KML export.

The layer file export only reads plain data (legend config + map data) and
writes files to disk, so it is safe to run off the UI thread. This keeps the
Export dialog responsive while large surveys are written.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from xpostmaps.core.layer_file_export import export_layers
from xpostmaps.core.models import LegendConfig, MapData
from xpostmaps.core.pdf_export import PdfExportOptions


class LayerFileExportWorker(QThread):
    progress = Signal(int, int, str)
    finished_ok = Signal(list)
    failed = Signal(str)

    def __init__(
        self,
        options: PdfExportOptions,
        pdf_stem: str,
        legend: LegendConfig,
        map_data: MapData,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._options = options
        self._pdf_stem = pdf_stem
        self._legend = legend
        self._map_data = map_data

    def run(self) -> None:
        try:
            def emit_progress(index: int, total: int, label: str) -> None:
                self.progress.emit(index, total, label)

            written = export_layers(
                self._options.output_dir,
                self._pdf_stem,
                self._legend,
                self._map_data,
                shapefiles=self._options.export_shapefiles,
                kml=self._options.export_kml,
                dxf=self._options.export_dxf,
                progress_callback=emit_progress,
            )

            labels = {
                "shp": ("Shapefiles", self._options.export_shapefiles),
                "kml": ("KML", self._options.export_kml),
                "dxf": ("DXF", self._options.export_dxf),
            }
            notes: list[str] = []
            for key, (label, requested) in labels.items():
                if not requested:
                    continue
                paths = written.get(key, [])
                if paths:
                    notes.append(f"{label} ({len(paths)}): {paths[0].parent}")
                else:
                    notes.append(f"{label}: no layer geometry to write.")

            self.finished_ok.emit(notes)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
