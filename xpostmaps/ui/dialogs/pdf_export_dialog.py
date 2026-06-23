"""PDF export dialog with live sheet preview."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QDoubleSpinBox,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from xpostmaps.core.local_settings import load_pdf_output_directory, save_pdf_output_directory
from xpostmaps.core.models import MapData, PostmapInfo, ProjectSettings
from xpostmaps.core.pdf_export import (
    DPI_OPTIONS,
    MARGIN_PRESET_NAMES,
    MARGIN_PRESETS_MM,
    PAPER_SIZE_NAMES,
    SCALE_MODES,
    PdfExportOptions,
    capture_export_images,
    compose_pdf_hybrid,
    compose_pdf_vector_from_captures,
    default_pdf_filename,
    effective_raster_dpi,
    raster_dpi_clamped,
    render_sheet_hybrid_preview,
    render_sheet_preview,
    resolve_output_path,
)
from xpostmaps.core.pdf_export_worker import PdfExportCapture, PdfExportWorker
from xpostmaps.ui.dialogs.base_dialog import SingleInstanceDialog
from xpostmaps.ui.map_widget import PostplotMapWidget
from xpostmaps.ui.right_pane import RightPane


class PdfExportDialog:
    KEY = "pdf_export"

    @classmethod
    def open(
        cls,
        parent,
        *,
        map_widget: PostplotMapWidget,
        right_pane: RightPane,
        settings: ProjectSettings,
        map_data: MapData | None,
        project_name: str,
        default_output_dir: Path,
    ) -> None:
        info = map_data.postmap_info if map_data else PostmapInfo()
        default_dir = load_pdf_output_directory(default_output_dir)

        def build(dialog: SingleInstanceDialog) -> None:
            layout = dialog.content_layout
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            body = QHBoxLayout()
            body.setSpacing(16)

            # --- Left: settings ---
            left = QWidget()
            left_form = QFormLayout(left)
            left_form.setSpacing(10)
            left_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

            out_row = QHBoxLayout()
            output_edit = QLineEdit(str(default_dir))
            browse_btn = QPushButton("Browse…")
            out_row.addWidget(output_edit, stretch=1)
            out_row.addWidget(browse_btn)
            out_host = QWidget()
            out_host.setLayout(out_row)
            left_form.addRow("Output directory", out_host)

            filename_edit = QLineEdit(
                default_pdf_filename(project_name, info.file_name)
            )
            left_form.addRow("PDF filename", filename_edit)

            paper_combo = QComboBox()
            paper_combo.addItems(list(PAPER_SIZE_NAMES))
            paper_combo.setCurrentText("A3")
            left_form.addRow("Paper size", paper_combo)

            dpi_combo = QComboBox()
            for dpi in DPI_OPTIONS:
                dpi_combo.addItem(f"{dpi} DPI", dpi)
            dpi_combo.setCurrentIndex(DPI_OPTIONS.index(600))
            left_form.addRow("Resolution (DPI)", dpi_combo)

            orientation_combo = QComboBox()
            orientation_combo.addItems(["Landscape", "Portrait"])
            left_form.addRow("Orientation", orientation_combo)

            margin_combo = QComboBox()
            margin_combo.addItems(list(MARGIN_PRESET_NAMES))
            margin_combo.setCurrentText("Default")
            margin_custom = QDoubleSpinBox()
            margin_custom.setRange(0.0, 50.0)
            margin_custom.setSuffix(" mm")
            margin_custom.setDecimals(1)
            margin_custom.setValue(10.0)
            margin_custom.setVisible(False)
            margin_row = QHBoxLayout()
            margin_row.setContentsMargins(0, 0, 0, 0)
            margin_row.addWidget(margin_combo, stretch=1)
            margin_row.addWidget(margin_custom)
            margin_host = QWidget()
            margin_host.setLayout(margin_row)
            left_form.addRow("Margins", margin_host)

            scale_combo = QComboBox()
            scale_combo.addItems(list(SCALE_MODES))
            scale_combo.setCurrentText("Default")
            scale_custom = QSpinBox()
            scale_custom.setRange(25, 400)
            scale_custom.setSuffix(" %")
            scale_custom.setValue(100)
            scale_custom.setVisible(False)
            scale_row = QHBoxLayout()
            scale_row.setContentsMargins(0, 0, 0, 0)
            scale_row.addWidget(scale_combo, stretch=1)
            scale_row.addWidget(scale_custom)
            scale_host = QWidget()
            scale_host.setLayout(scale_row)
            left_form.addRow("Scale", scale_host)

            vector_mode = QCheckBox("High-quality PDF layout (recommended)")
            vector_mode.setChecked(True)
            left_form.addRow("", vector_mode)

            detail_slider = QSlider(Qt.Orientation.Horizontal)
            detail_slider.setRange(0, 100)
            detail_slider.setValue(100)
            detail_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
            detail_slider.setTickInterval(25)
            detail_value = QLabel("100")
            detail_value.setMinimumWidth(28)
            detail_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            detail_row = QHBoxLayout()
            detail_row.setContentsMargins(0, 0, 0, 0)
            detail_row.addWidget(detail_slider, stretch=1)
            detail_row.addWidget(detail_value)
            detail_host = QWidget()
            detail_host.setLayout(detail_row)
            left_form.addRow("Map detail", detail_host)

            open_after = QCheckBox("Open folder after export")
            open_after.setChecked(True)
            left_form.addRow("", open_after)

            hint = QLabel(
                "Postplot linework is written as true PDF vectors — zoom stays sharp, "
                "not pixelated. Set Map detail to 100 to keep full geometry (matches "
                "the map); lower values decimate for faster export. "
                "The right pane is re-rendered for crisp text. "
                "Turn off high-quality layout for a faster screen-capture PDF."
            )
            hint.setWordWrap(True)
            hint.setStyleSheet("color: #8b949e; font-size: 11px;")
            left_form.addRow(hint)

            export_btn = QPushButton("Export PDF")
            export_btn.setObjectName("primaryBtn")
            close_btn = QPushButton("Close")
            btn_row = QHBoxLayout()
            btn_row.addWidget(export_btn)
            btn_row.addWidget(close_btn)
            btn_row.addStretch()
            btn_host = QWidget()
            btn_host.setLayout(btn_row)
            left_form.addRow(btn_host)

            body.addWidget(left, stretch=0)

            # --- Right: preview ---
            preview_title = QLabel("Preview")
            preview_title.setObjectName("sectionTitle")
            preview_label = QLabel()
            preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            preview_label.setMinimumSize(420, 360)
            preview_label.setStyleSheet(
                "background: #ffffff; border: 1px solid #30363d; color: #444;"
            )
            preview_scroll = QScrollArea()
            preview_scroll.setWidgetResizable(True)
            preview_scroll.setFrameShape(QScrollArea.Shape.StyledPanel)
            preview_host = QWidget()
            preview_layout = QVBoxLayout(preview_host)
            preview_layout.addWidget(preview_title)
            preview_layout.addWidget(preview_label, stretch=1)
            preview_scroll.setWidget(preview_host)
            body.addWidget(preview_scroll, stretch=1)

            layout.addLayout(body)

            preview_timer = QTimer(dialog)
            preview_timer.setSingleShot(True)
            preview_timer.setInterval(200)

            export_worker: PdfExportWorker | None = None
            progress: QProgressDialog | None = None

            def resolved_margin_mm() -> float:
                if margin_combo.currentText() == "Custom":
                    return float(margin_custom.value())
                return MARGIN_PRESETS_MM[margin_combo.currentText()]

            def resolved_scale() -> tuple[str, int]:
                mode = scale_combo.currentText()
                percent = scale_custom.value() if mode == "Custom" else 100
                return mode, percent

            def sync_margin_controls() -> None:
                margin_custom.setVisible(margin_combo.currentText() == "Custom")

            def sync_scale_controls() -> None:
                scale_custom.setVisible(scale_combo.currentText() == "Custom")

            def sync_vector_controls() -> None:
                enabled = vector_mode.isChecked()
                detail_slider.setEnabled(enabled)
                detail_value.setEnabled(enabled)

            def sync_detail_label() -> None:
                detail_value.setText(str(detail_slider.value()))

            def current_options() -> PdfExportOptions:
                out_dir = Path(output_edit.text().strip() or str(default_dir))
                scale_mode, scale_percent = resolved_scale()
                return PdfExportOptions(
                    output_dir=out_dir,
                    filename=filename_edit.text().strip(),
                    paper=paper_combo.currentText(),
                    dpi=int(dpi_combo.currentData()),
                    landscape=orientation_combo.currentText() == "Landscape",
                    margin_mm=resolved_margin_mm(),
                    scale_mode=scale_mode,
                    scale_percent=scale_percent,
                    line_detail_percent=detail_slider.value(),
                )

            def _with_map_visible(action, *, hide_dialog: bool = True):
                """Prepare the main window for screen-grab capture (raster preview/export)."""
                host = dialog.parent()
                if hide_dialog:
                    dialog.hide()
                if host is not None:
                    host.raise_()
                    host.activateWindow()
                for _ in range(6):
                    QApplication.processEvents()
                try:
                    return action()
                finally:
                    if hide_dialog:
                        dialog.show()
                        dialog.raise_()
                        dialog.activateWindow()

            def refresh_preview() -> None:
                opts = current_options()
                if vector_mode.isChecked():
                    image = render_sheet_hybrid_preview(
                        map_widget,
                        right_pane,
                        opts,
                    )
                    pix = QPixmap.fromImage(image)
                else:
                    def build_preview():
                        return render_sheet_preview(
                            map_widget,
                            right_pane,
                            paper=opts.paper,
                            landscape=opts.landscape,
                            margin_mm=opts.margin_mm,
                            scale_mode=opts.scale_mode,
                            scale_percent=opts.scale_percent,
                        )

                    pix = _with_map_visible(build_preview)
                if pix.isNull():
                    preview_label.setText("Preview unavailable")
                    return
                scaled = pix.scaled(
                    preview_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                preview_label.setPixmap(scaled)

            def schedule_preview() -> None:
                preview_timer.start()

            preview_timer.timeout.connect(refresh_preview)

            def browse_output() -> None:
                path = QFileDialog.getExistingDirectory(
                    dialog,
                    "Select output directory",
                    output_edit.text().strip() or str(default_dir),
                )
                if path:
                    output_edit.setText(path)

            def _set_export_busy(busy: bool) -> None:
                export_btn.setEnabled(not busy)
                preview_timer.stop()
                if busy:
                    preview_label.setText("Exporting…")
                else:
                    schedule_preview()

            def _finish_export(
                out_path: Path,
                opts: PdfExportOptions,
                *,
                dpi_note: str,
            ) -> None:
                nonlocal export_worker, progress
                export_worker = None
                if progress is not None:
                    progress.close()
                    progress = None
                _set_export_busy(False)
                save_pdf_output_directory(opts.output_dir)
                msg = f"Saved:\n{out_path}"
                if dpi_note:
                    msg = f"{dpi_note}\n\n{msg}"
                QMessageBox.information(dialog, "Export to PDF", msg)
                if open_after.isChecked():
                    cls._reveal_in_folder(out_path)

            def _fail_export(message: str) -> None:
                nonlocal export_worker, progress
                export_worker = None
                if progress is not None:
                    progress.close()
                    progress = None
                _set_export_busy(False)
                QMessageBox.critical(
                    dialog,
                    "Export to PDF",
                    f"Could not write PDF:\n{message}",
                )

            def _capture_with_map_visible(
                export_options: PdfExportOptions,
            ) -> tuple[QImage, QImage]:
                return _with_map_visible(
                    lambda: capture_export_images(
                        map_widget,
                        right_pane,
                        export_options,
                        use_screen_grab=True,
                    )
                )

            def do_export() -> None:
                nonlocal export_worker, progress
                if export_worker is not None and export_worker.isRunning():
                    return
                opts = current_options()
                if not opts.output_dir.is_dir():
                    QMessageBox.warning(
                        dialog,
                        "Export to PDF",
                        "Choose a valid output directory.",
                    )
                    return
                out_path = resolve_output_path(opts)
                if out_path.exists():
                    answer = QMessageBox.question(
                        dialog,
                        "Overwrite file?",
                        f"{out_path.name} already exists. Replace it?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    )
                    if answer != QMessageBox.StandardButton.Yes:
                        return

                if vector_mode.isChecked():
                    _set_export_busy(True)
                    progress = QProgressDialog(
                        "Writing PDF…",
                        None,
                        0,
                        0,
                        dialog,
                    )
                    progress.setWindowTitle("Export to PDF")
                    progress.setWindowModality(Qt.WindowModality.WindowModal)
                    progress.setMinimumDuration(0)
                    progress.setCancelButton(None)
                    progress.show()
                    QApplication.processEvents()
                    try:
                        _with_map_visible(
                            lambda: compose_pdf_hybrid(
                                out_path,
                                map_widget,
                                right_pane,
                                opts,
                            ),
                            hide_dialog=False,
                        )
                    except Exception as exc:  # noqa: BLE001
                        _fail_export(str(exc))
                        return
                    _finish_export(out_path, opts, dpi_note="")
                    return

                dpi_note = ""
                if raster_dpi_clamped(opts.dpi):
                    effective = effective_raster_dpi(opts.dpi)
                    dpi_note = (
                        f"Requested {opts.dpi} DPI; raster compositing uses {effective} DPI "
                        f"so export stays responsive."
                    )

                _set_export_busy(True)
                try:
                    map_image, pane_image = _capture_with_map_visible(opts)
                except Exception as exc:  # noqa: BLE001
                    _fail_export(str(exc))
                    return

                if map_image.isNull() or pane_image.isNull():
                    _fail_export("Could not capture map or right pane.")
                    return

                progress = QProgressDialog(
                    "Writing PDF…",
                    None,
                    0,
                    0,
                    dialog,
                )
                progress.setWindowTitle("Export to PDF")
                progress.setWindowModality(Qt.WindowModality.WindowModal)
                progress.setMinimumDuration(0)
                progress.setCancelButton(None)
                progress.show()
                QApplication.processEvents()

                capture = PdfExportCapture(map_image=map_image, pane_image=pane_image)
                worker = PdfExportWorker(out_path, capture, opts, parent=dialog)
                export_worker = worker

                def on_ok(saved_path: str) -> None:
                    _finish_export(Path(saved_path), opts, dpi_note=dpi_note)

                def on_failed(message: str) -> None:
                    _fail_export(message)

                worker.finished_ok.connect(on_ok)
                worker.failed.connect(on_failed)
                worker.start()

            browse_btn.clicked.connect(browse_output)
            export_btn.clicked.connect(do_export)
            close_btn.clicked.connect(dialog.close)

            output_edit.textChanged.connect(schedule_preview)
            filename_edit.textChanged.connect(schedule_preview)
            paper_combo.currentIndexChanged.connect(schedule_preview)
            dpi_combo.currentIndexChanged.connect(schedule_preview)
            orientation_combo.currentIndexChanged.connect(schedule_preview)
            margin_combo.currentIndexChanged.connect(sync_margin_controls)
            margin_combo.currentIndexChanged.connect(schedule_preview)
            margin_custom.valueChanged.connect(schedule_preview)
            scale_combo.currentIndexChanged.connect(sync_scale_controls)
            scale_combo.currentIndexChanged.connect(schedule_preview)
            scale_custom.valueChanged.connect(schedule_preview)
            vector_mode.stateChanged.connect(sync_vector_controls)
            vector_mode.stateChanged.connect(schedule_preview)
            detail_slider.valueChanged.connect(sync_detail_label)
            detail_slider.valueChanged.connect(schedule_preview)
            sync_margin_controls()
            sync_scale_controls()
            sync_vector_controls()
            sync_detail_label()

            schedule_preview()

        SingleInstanceDialog.show_dialog(
            cls.KEY,
            "Export to PDF",
            build,
            parent,
            width=1040,
            height=720,
        )

    @staticmethod
    def _reveal_in_folder(file_path: Path) -> None:
        """Open a single file-explorer window with the exported PDF selected."""
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["explorer", f"/select,{file_path}"],
                    check=False,
                )
            elif sys.platform == "darwin":
                subprocess.run(["open", "-R", str(file_path)], check=False)
            else:
                subprocess.run(["xdg-open", str(file_path.parent)], check=False)
        except OSError:
            pass
