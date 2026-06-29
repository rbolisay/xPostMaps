"""Export dialog for 4D Stat plot PDFs with live preview."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from xpostmaps.core.local_settings import load_pdf_output_directory, save_pdf_output_directory
from xpostmaps.core.pdf_export import (
    DPI_OPTIONS,
    MARGIN_PRESET_NAMES,
    MARGIN_PRESETS_MM,
    PAPER_SIZE_NAMES,
)
from xpostmaps.core.postplot_4d_plot_data import PLOT_KIND_LABELS, PlotKind
from xpostmaps.core.postplot_4d_plot_pdf import (
    DEFAULT_4D_STAT_PDF_REPORT_TITLE,
    STAT_PLOT_PDF_DEFAULT_DPI,
    Postplot4DStatPlotPdfOptions,
    default_4d_stat_pdf_filename,
    export_4d_stat_plot_pdf,
    iter_4d_stat_plot_page_specs,
    render_4d_stat_plot_preview_pages,
    resolve_4d_stat_output_path,
    resolved_plot_kinds,
)
from xpostmaps.ui.dialogs.base_dialog import SingleInstanceDialog
from xpostmaps.ui.postplot_4d_stat_plot.plot_view import Postplot4DStatPlotView


class Postplot4DStatPlotPdfDialog:
    KEY = "postplot_4d_stat_plot_pdf"

    @classmethod
    def open(
        cls,
        parent,
        *,
        plot_view: Postplot4DStatPlotView,
        logo_path: str = "",
        default_output_dir: Path | None = None,
    ) -> SingleInstanceDialog:
        match_row = plot_view.match_row()
        if match_row is None or not plot_view.diff_rows():
            QMessageBox.information(
                parent,
                "Export 4D Stat Plot PDF",
                "Load 4D Stat data before exporting.",
            )
            return None

        fallback_dir = default_output_dir or Path.cwd()
        default_dir = load_pdf_output_directory(fallback_dir)
        feather_available = "feather" in plot_view.available_plot_kinds()
        feather_diff_available = "feather_diff" in plot_view.available_plot_kinds()

        def build(dialog: SingleInstanceDialog) -> None:
            layout = dialog.content_layout
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
                child = item.layout()
                if child is not None:
                    while child.count():
                        nested = child.takeAt(0)
                        if nested.widget():
                            nested.widget().deleteLater()

            body = QHBoxLayout()
            body.setSpacing(16)

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

            filename_edit = QLineEdit(default_4d_stat_pdf_filename(match_row))
            left_form.addRow("PDF filename", filename_edit)

            report_title_edit = QLineEdit(DEFAULT_4D_STAT_PDF_REPORT_TITLE)
            left_form.addRow("Report title", report_title_edit)

            paper_combo = QComboBox()
            paper_combo.addItems(list(PAPER_SIZE_NAMES))
            paper_combo.setCurrentText("A4")
            left_form.addRow("Paper size", paper_combo)

            dpi_combo = QComboBox()
            for dpi in DPI_OPTIONS:
                dpi_combo.addItem(f"{dpi} DPI", dpi)
            default_dpi = (
                STAT_PLOT_PDF_DEFAULT_DPI
                if STAT_PLOT_PDF_DEFAULT_DPI in DPI_OPTIONS
                else DPI_OPTIONS[0]
            )
            dpi_index = DPI_OPTIONS.index(default_dpi) if default_dpi in DPI_OPTIONS else 0
            dpi_combo.setCurrentIndex(dpi_index)
            left_form.addRow("Resolution (DPI)", dpi_combo)

            orientation_combo = QComboBox()
            orientation_combo.addItems(["Portrait", "Landscape"])
            orientation_combo.setCurrentText("Landscape")
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

            plots_group = QGroupBox("Plots to include")
            plots_layout = QVBoxLayout(plots_group)
            plot_checks: dict[PlotKind, QCheckBox] = {}
            for kind in ("crossline", "inline", "radial", "feather", "feather_diff"):
                box = QCheckBox(PLOT_KIND_LABELS[kind])
                box.setChecked(True)
                if kind == "feather":
                    box.setEnabled(feather_available)
                    if not feather_available:
                        box.setChecked(False)
                        box.setToolTip("Feather is unavailable for this line.")
                if kind == "feather_diff":
                    box.setEnabled(feather_diff_available)
                    if not feather_diff_available:
                        box.setChecked(False)
                        box.setToolTip(
                            "Feather Diff requires a navplan baseline and detected streamers."
                        )
                plot_checks[kind] = box
                plots_layout.addWidget(box)
            left_form.addRow(plots_group)

            time_series_edit = QLineEdit()
            time_series_edit.setPlaceholderText(
                "G01, G02 Position Cross-line vs. Baseline (Up-line)"
            )
            left_form.addRow("Time series description", time_series_edit)

            open_after = QCheckBox("Open folder after export")
            open_after.setChecked(True)
            left_form.addRow("", open_after)

            hint = QLabel(
                "Use the preview arrows to step through every PDF page. "
                "Each selected plot type is written to its own page "
                "(one page per source when Combine Sources is off). "
                "The time series description applies to the current preview page."
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

            preview_title = QLabel("Preview")
            preview_title.setObjectName("sectionTitle")
            preview_label = QLabel()
            preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            preview_label.setMinimumSize(420, 360)
            preview_label.setStyleSheet(
                "background: #ffffff; border: 1px solid #30363d; color: #444;"
            )
            prev_page_btn = QPushButton("◀")
            prev_page_btn.setFixedWidth(36)
            prev_page_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            next_page_btn = QPushButton("▶")
            next_page_btn.setFixedWidth(36)
            next_page_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            page_counter = QLabel("Page 0 of 0")
            page_counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
            page_counter.setStyleSheet("color: #8b949e; font-size: 11px;")
            nav_row = QHBoxLayout()
            nav_row.addStretch()
            nav_row.addWidget(prev_page_btn)
            nav_row.addWidget(page_counter)
            nav_row.addWidget(next_page_btn)
            nav_row.addStretch()
            preview_host = QWidget()
            preview_layout = QVBoxLayout(preview_host)
            preview_layout.addWidget(preview_title)
            preview_layout.addWidget(preview_label, stretch=1)
            preview_layout.addLayout(nav_row)
            preview_scroll = QScrollArea()
            preview_scroll.setWidgetResizable(True)
            preview_scroll.setFrameShape(QScrollArea.Shape.StyledPanel)
            preview_scroll.setWidget(preview_host)
            body.addWidget(preview_scroll, stretch=1)

            layout.addLayout(body)

            preview_pages: list = []
            preview_index = 0
            page_specs = []
            description_overrides: dict[str, str] = {}
            syncing_description = False

            preview_timer = QTimer(dialog)
            preview_timer.setSingleShot(True)
            preview_timer.setInterval(250)

            def resolved_margin_mm() -> float:
                if margin_combo.currentText() == "Custom":
                    return float(margin_custom.value())
                return MARGIN_PRESETS_MM[margin_combo.currentText()]

            def current_options() -> Postplot4DStatPlotPdfOptions:
                out_dir = Path(output_edit.text().strip() or str(default_dir))
                return Postplot4DStatPlotPdfOptions(
                    output_dir=out_dir,
                    filename=filename_edit.text().strip(),
                    paper=paper_combo.currentText(),
                    dpi=int(dpi_combo.currentData()),
                    landscape=orientation_combo.currentText() == "Landscape",
                    margin_mm=resolved_margin_mm(),
                    report_title=report_title_edit.text().strip()
                    or DEFAULT_4D_STAT_PDF_REPORT_TITLE,
                    include_crossline=plot_checks["crossline"].isChecked(),
                    include_inline=plot_checks["inline"].isChecked(),
                    include_radial=plot_checks["radial"].isChecked(),
                    include_feather=plot_checks["feather"].isChecked(),
                    include_feather_diff=plot_checks["feather_diff"].isChecked(),
                    time_series_descriptions=dict(description_overrides),
                )

            def _current_page_spec():
                if not page_specs:
                    return None
                index = max(0, min(preview_index, len(page_specs) - 1))
                return page_specs[index]

            def _store_current_description() -> None:
                spec = _current_page_spec()
                if spec is None:
                    return
                text = time_series_edit.text().strip()
                if text:
                    description_overrides[spec.page_key] = text
                else:
                    description_overrides.pop(spec.page_key, None)

            def _load_description_for_current_page() -> None:
                nonlocal syncing_description
                spec = _current_page_spec()
                syncing_description = True
                if spec is None:
                    time_series_edit.clear()
                else:
                    text = description_overrides.get(
                        spec.page_key,
                        spec.default_time_series_description,
                    )
                    time_series_edit.setText(text)
                syncing_description = False

            def sync_margin_controls() -> None:
                margin_custom.setVisible(margin_combo.currentText() == "Custom")

            def _sync_page_nav() -> None:
                total = len(preview_pages)
                if total <= 0:
                    page_counter.setText("Page 0 of 0")
                    prev_page_btn.setEnabled(False)
                    next_page_btn.setEnabled(False)
                    return
                page_counter.setText(f"Page {preview_index + 1} of {total}")
                prev_page_btn.setEnabled(preview_index > 0)
                next_page_btn.setEnabled(preview_index < total - 1)

            def _show_preview_page() -> None:
                if not preview_pages:
                    preview_label.setText("Select at least one plot type")
                    preview_label.setPixmap(QPixmap())
                    _sync_page_nav()
                    return
                index = max(0, min(preview_index, len(preview_pages) - 1))
                image = preview_pages[index]
                if image.isNull():
                    preview_label.setText("Preview unavailable")
                    preview_label.setPixmap(QPixmap())
                    _sync_page_nav()
                    return
                pix = QPixmap.fromImage(image)
                scaled = pix.scaled(
                    preview_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                preview_label.setText("")
                preview_label.setPixmap(scaled)
                _sync_page_nav()

            def refresh_preview() -> None:
                nonlocal preview_pages, preview_index, page_specs
                _store_current_description()
                opts = current_options()
                page_specs = iter_4d_stat_plot_page_specs(plot_view, opts)
                if not page_specs:
                    preview_pages = []
                    preview_index = 0
                    _load_description_for_current_page()
                    _show_preview_page()
                    return
                preview_index = max(0, min(preview_index, len(page_specs) - 1))
                preview_pages = render_4d_stat_plot_preview_pages(
                    plot_view,
                    opts,
                    logo_path=logo_path,
                )
                _load_description_for_current_page()
                _show_preview_page()

            def show_previous_page() -> None:
                nonlocal preview_index
                if preview_index <= 0:
                    return
                _store_current_description()
                preview_index -= 1
                _load_description_for_current_page()
                _show_preview_page()

            def show_next_page() -> None:
                nonlocal preview_index
                if preview_index >= len(page_specs) - 1:
                    return
                _store_current_description()
                preview_index += 1
                _load_description_for_current_page()
                _show_preview_page()

            def schedule_preview() -> None:
                preview_timer.start()

            preview_timer.timeout.connect(refresh_preview)

            def browse_output() -> None:
                from PySide6.QtWidgets import QFileDialog

                path = QFileDialog.getExistingDirectory(
                    dialog,
                    "Select output directory",
                    output_edit.text().strip() or str(default_dir),
                )
                if path:
                    output_edit.setText(path)

            def on_description_changed() -> None:
                if syncing_description:
                    return
                _store_current_description()
                schedule_preview()

            def on_export() -> None:
                _store_current_description()
                opts = current_options()
                if not opts.filename.strip():
                    QMessageBox.warning(dialog, "Export PDF", "Enter a PDF filename.")
                    return
                if not resolved_plot_kinds(plot_view, opts):
                    QMessageBox.warning(
                        dialog,
                        "Export PDF",
                        "Select at least one plot type to include.",
                    )
                    return
                out_path = resolve_4d_stat_output_path(opts)
                save_pdf_output_directory(opts.output_dir)
                export_btn.setEnabled(False)
                preview_label.setText("Exporting…")
                QApplication.processEvents()
                try:
                    export_4d_stat_plot_pdf(
                        plot_view,
                        out_path,
                        opts,
                        logo_path=logo_path,
                    )
                except Exception as exc:  # noqa: BLE001
                    export_btn.setEnabled(True)
                    schedule_preview()
                    QMessageBox.warning(
                        dialog,
                        "Export 4D Stat Plot PDF",
                        f"Could not export PDF:\n{exc}",
                    )
                    return
                export_btn.setEnabled(True)
                schedule_preview()
                if open_after.isChecked():
                    folder = str(out_path.parent)
                    if sys.platform == "win32":
                        subprocess.Popen(["explorer", folder])  # noqa: S603
                    elif sys.platform == "darwin":
                        subprocess.Popen(["open", folder])  # noqa: S603
                    else:
                        subprocess.Popen(["xdg-open", folder])  # noqa: S603
                host = dialog.parent()
                if host is not None and hasattr(host, "statusBar"):
                    host.statusBar().showMessage(
                        f"4D Stat plot PDF exported: {out_path}",
                        6000,
                    )

            margin_combo.currentTextChanged.connect(lambda *_: sync_margin_controls())
            margin_combo.currentTextChanged.connect(schedule_preview)
            margin_custom.valueChanged.connect(schedule_preview)
            paper_combo.currentTextChanged.connect(schedule_preview)
            dpi_combo.currentIndexChanged.connect(schedule_preview)
            orientation_combo.currentTextChanged.connect(schedule_preview)
            output_edit.textChanged.connect(schedule_preview)
            filename_edit.textChanged.connect(schedule_preview)
            report_title_edit.textChanged.connect(schedule_preview)
            time_series_edit.textChanged.connect(on_description_changed)
            for box in plot_checks.values():
                box.toggled.connect(schedule_preview)

            browse_btn.clicked.connect(browse_output)
            export_btn.clicked.connect(on_export)
            close_btn.clicked.connect(dialog.close)
            prev_page_btn.clicked.connect(show_previous_page)
            next_page_btn.clicked.connect(show_next_page)

            sync_margin_controls()
            schedule_preview()

        return SingleInstanceDialog.show_dialog(
            cls.KEY,
            "Export 4D Stat Plot PDF",
            build,
            parent,
            width=980,
            height=720,
        )
