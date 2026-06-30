"""Export dialog for survey-wide 4D plot PDFs."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QSize
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
from xpostmaps.core.postplot_4d_survey_plot_pdf import (
    DEFAULT_SURVEY_PLOT_PDF_REPORT_TITLE,
    Postplot4DSurveyPlotPdfOptions,
    default_survey_plot_pdf_filename,
    export_survey_plot_pdf,
    iter_survey_plot_page_specs,
    render_survey_plot_preview_pages,
    resolve_survey_plot_output_path,
)
from xpostmaps.core.postplot_4d_plot_pdf import STAT_PLOT_PDF_DEFAULT_DPI
from xpostmaps.ui.dialogs.base_dialog import SingleInstanceDialog
from xpostmaps.ui.postplot_4d_survey_plots.survey_plots_view import Postplot4DSurveyPlotsView


class Postplot4DSurveyPlotPdfDialog:
    KEY = "postplot_4d_survey_plot_pdf"

    @classmethod
    def open(
        cls,
        parent,
        *,
        survey_view: Postplot4DSurveyPlotsView,
        logo_path: str = "",
        default_output_dir: Path | None = None,
        baseline_kind: str = "survey",
    ) -> SingleInstanceDialog | None:
        if not survey_view.diff_sets():
            QMessageBox.information(
                parent,
                "Export Survey Plots PDF",
                "Load survey 4D Stat data before exporting.",
            )
            return None

        fallback_dir = default_output_dir or Path.cwd()
        default_dir = load_pdf_output_directory(fallback_dir)
        available = set(survey_view.available_plot_kinds())

        def build(dialog: SingleInstanceDialog) -> None:
            layout = dialog.content_layout
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

            body = QHBoxLayout()
            body.setSpacing(16)

            left = QWidget()
            left_form = QFormLayout(left)
            left_form.setSpacing(10)

            out_row = QHBoxLayout()
            output_edit = QLineEdit(str(default_dir))
            browse_btn = QPushButton("Browse…")
            out_row.addWidget(output_edit, stretch=1)
            out_row.addWidget(browse_btn)
            out_host = QWidget()
            out_host.setLayout(out_row)
            left_form.addRow("Output directory", out_host)

            filename_edit = QLineEdit(default_survey_plot_pdf_filename(baseline_kind))
            left_form.addRow("PDF filename", filename_edit)

            paper_combo = QComboBox()
            paper_combo.addItems(list(PAPER_SIZE_NAMES))
            paper_combo.setCurrentText("A4")
            left_form.addRow("Paper size", paper_combo)

            dpi_combo = QComboBox()
            for dpi in DPI_OPTIONS:
                dpi_combo.addItem(f"{dpi} DPI", dpi)
            default_dpi = STAT_PLOT_PDF_DEFAULT_DPI if STAT_PLOT_PDF_DEFAULT_DPI in DPI_OPTIONS else DPI_OPTIONS[0]
            dpi_combo.setCurrentIndex(
                DPI_OPTIONS.index(default_dpi) if default_dpi in DPI_OPTIONS else 0
            )
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
            margin_row.addWidget(margin_combo, stretch=1)
            margin_row.addWidget(margin_custom)
            margin_host = QWidget()
            margin_host.setLayout(margin_row)
            left_form.addRow("Margins", margin_host)

            aerial_group = QGroupBox("Aerial plots")
            aerial_layout = QVBoxLayout(aerial_group)
            aerial_checks: dict[PlotKind, QCheckBox] = {}
            for kind in ("crossline", "inline", "radial", "feather", "feather_diff"):
                box = QCheckBox(PLOT_KIND_LABELS[kind])
                box.setChecked(kind in available)
                box.setEnabled(kind in available)
                aerial_checks[kind] = box
                aerial_layout.addWidget(box)

            hist_group = QGroupBox("Histogram plots")
            hist_layout = QVBoxLayout(hist_group)
            hist_checks: dict[PlotKind, QCheckBox] = {}
            for kind in ("crossline", "inline", "radial", "feather", "feather_diff"):
                box = QCheckBox(PLOT_KIND_LABELS[kind])
                box.setChecked(kind in available)
                box.setEnabled(kind in available)
                hist_checks[kind] = box
                hist_layout.addWidget(box)

            pie_check = QCheckBox("Survey Specs Pie")
            pie_check.setChecked(True)

            left_form.addRow(aerial_group)
            left_form.addRow(hist_group)
            left_form.addRow("", pie_check)

            report_title_edit = QLineEdit(DEFAULT_SURVEY_PLOT_PDF_REPORT_TITLE)
            left_form.addRow("Report title", report_title_edit)

            page_desc_edit = QLineEdit()
            page_desc_edit.setPlaceholderText("Description for current preview page")
            left_form.addRow("Page description", page_desc_edit)

            open_after = QCheckBox("Open folder after export")
            open_after.setChecked(True)
            left_form.addRow("", open_after)

            export_btn = QPushButton("Export PDF")
            export_btn.setObjectName("primaryBtn")
            close_btn = QPushButton("Close")
            btn_row = QHBoxLayout()
            btn_row.addWidget(export_btn)
            btn_row.addWidget(close_btn)
            btn_host = QWidget()
            btn_host.setLayout(btn_row)
            left_form.addRow(btn_host)

            preview_label = QLabel()
            preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            preview_label.setMinimumSize(420, 360)
            preview_label.setStyleSheet(
                "background: #ffffff; border: 1px solid #30363d; color: #444;"
            )
            prev_page_btn = QPushButton("◀")
            prev_page_btn.setFixedWidth(36)
            next_page_btn = QPushButton("▶")
            next_page_btn.setFixedWidth(36)
            page_counter = QLabel("Page 0 of 0")
            page_counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
            nav_row = QHBoxLayout()
            nav_row.addStretch()
            nav_row.addWidget(prev_page_btn)
            nav_row.addWidget(page_counter)
            nav_row.addWidget(next_page_btn)
            nav_row.addStretch()
            preview_host = QWidget()
            preview_layout = QVBoxLayout(preview_host)
            preview_layout.addWidget(QLabel("Preview"))
            preview_layout.addWidget(preview_label, stretch=1)
            preview_layout.addLayout(nav_row)
            preview_scroll = QScrollArea()
            preview_scroll.setWidgetResizable(True)
            preview_scroll.setFrameShape(QScrollArea.Shape.StyledPanel)
            preview_scroll.setWidget(preview_host)
            body.addWidget(left, stretch=0)
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

            def current_options() -> Postplot4DSurveyPlotPdfOptions:
                return Postplot4DSurveyPlotPdfOptions(
                    output_dir=Path(output_edit.text().strip() or str(default_dir)),
                    filename=filename_edit.text().strip(),
                    paper=paper_combo.currentText(),
                    dpi=int(dpi_combo.currentData()),
                    landscape=orientation_combo.currentText() == "Landscape",
                    margin_mm=resolved_margin_mm(),
                    report_title=report_title_edit.text().strip()
                    or DEFAULT_SURVEY_PLOT_PDF_REPORT_TITLE,
                    include_aerial_crossline=aerial_checks["crossline"].isChecked(),
                    include_aerial_inline=aerial_checks["inline"].isChecked(),
                    include_aerial_radial=aerial_checks["radial"].isChecked(),
                    include_aerial_feather=aerial_checks["feather"].isChecked(),
                    include_aerial_feather_diff=aerial_checks["feather_diff"].isChecked(),
                    include_histogram_crossline=hist_checks["crossline"].isChecked(),
                    include_histogram_inline=hist_checks["inline"].isChecked(),
                    include_histogram_radial=hist_checks["radial"].isChecked(),
                    include_histogram_feather=hist_checks["feather"].isChecked(),
                    include_histogram_feather_diff=hist_checks["feather_diff"].isChecked(),
                    include_survey_specs_pie=pie_check.isChecked(),
                    page_descriptions=dict(description_overrides),
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
                text = page_desc_edit.text().strip()
                if text:
                    description_overrides[spec.page_key] = text
                else:
                    description_overrides.pop(spec.page_key, None)

            def _load_description_for_current_page() -> None:
                nonlocal syncing_description
                spec = _current_page_spec()
                syncing_description = True
                if spec is None:
                    page_desc_edit.clear()
                else:
                    page_desc_edit.setText(
                        description_overrides.get(
                            spec.page_key,
                            spec.description,
                        )
                    )
                syncing_description = False

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

            def _preview_display_size() -> QSize:
                viewport = preview_scroll.viewport()
                return QSize(
                    max(320, viewport.width() - 16 if viewport else 420),
                    max(240, viewport.height() - 48 if viewport else 360),
                )

            def refresh_preview() -> None:
                nonlocal preview_pages, preview_index, page_specs
                _store_current_description()
                opts = current_options()
                try:
                    composed = render_survey_plot_preview_pages(
                        survey_view,
                        opts,
                        logo_path=logo_path,
                    )
                    preview_pages = composed
                    page_specs = [page.spec for page in composed]
                except ValueError as exc:
                    preview_pages = []
                    page_specs = []
                    preview_label.setText(str(exc))
                    preview_label.setPixmap(QPixmap())
                    _sync_page_nav()
                    return
                if not preview_pages:
                    preview_index = 0
                    preview_label.setText("No pages selected.")
                    preview_label.setPixmap(QPixmap())
                    _sync_page_nav()
                    return
                preview_index = max(0, min(preview_index, len(preview_pages) - 1))
                _load_description_for_current_page()
                _show_preview_page()
                _sync_page_nav()
                QTimer.singleShot(0, _show_preview_page)

            def _show_preview_page() -> None:
                if not preview_pages:
                    preview_label.setText("No pages selected.")
                    preview_label.setPixmap(QPixmap())
                    return
                index = max(0, min(preview_index, len(preview_pages) - 1))
                image = preview_pages[index].image
                if image.isNull():
                    preview_label.setText("Preview unavailable")
                    preview_label.setPixmap(QPixmap())
                    return
                pixmap = QPixmap.fromImage(image)
                target = _preview_display_size()
                scaled = pixmap.scaled(
                    target,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                preview_label.setPixmap(scaled)
                preview_label.setText("")

            def schedule_preview() -> None:
                preview_timer.start()

            def on_export() -> None:
                _store_current_description()
                opts = current_options()
                out_path = resolve_survey_plot_output_path(opts)
                try:
                    survey_view.refresh_all()
                    QApplication.processEvents()
                    export_survey_plot_pdf(
                        survey_view,
                        out_path,
                        opts,
                        logo_path=logo_path,
                    )
                except ValueError as exc:
                    QMessageBox.warning(dialog, "Export Survey Plots PDF", str(exc))
                    return
                save_pdf_output_directory(opts.output_dir)
                QMessageBox.information(
                    dialog,
                    "Export Survey Plots PDF",
                    f"Saved:\n{out_path}",
                )
                if open_after.isChecked():
                    folder = str(out_path.parent)
                    if sys.platform == "win32":
                        subprocess.run(["explorer", folder], check=False)
                    elif sys.platform == "darwin":
                        subprocess.run(["open", folder], check=False)
                    else:
                        subprocess.run(["xdg-open", folder], check=False)

            def on_browse() -> None:
                from PySide6.QtWidgets import QFileDialog

                path = QFileDialog.getExistingDirectory(
                    dialog,
                    "Select output directory",
                    output_edit.text().strip() or str(default_dir),
                )
                if path:
                    output_edit.setText(path)
                    schedule_preview()

            def on_prev_page() -> None:
                nonlocal preview_index
                if preview_index > 0:
                    preview_index -= 1
                    _load_description_for_current_page()
                    _show_preview_page()
                    _sync_page_nav()

            def on_next_page() -> None:
                nonlocal preview_index
                if preview_index < len(preview_pages) - 1:
                    preview_index += 1
                    _load_description_for_current_page()
                    _show_preview_page()
                    _sync_page_nav()

            margin_combo.currentTextChanged.connect(
                lambda _text: (
                    margin_custom.setVisible(margin_combo.currentText() == "Custom"),
                    schedule_preview(),
                )
            )
            for widget in (
                output_edit,
                filename_edit,
                paper_combo,
                dpi_combo,
                orientation_combo,
                margin_custom,
                report_title_edit,
                pie_check,
            ):
                if hasattr(widget, "textChanged"):
                    widget.textChanged.connect(lambda _t: schedule_preview())
                elif hasattr(widget, "currentIndexChanged"):
                    widget.currentIndexChanged.connect(lambda _i: schedule_preview())
                elif hasattr(widget, "valueChanged"):
                    widget.valueChanged.connect(lambda _v: schedule_preview())
                elif hasattr(widget, "toggled"):
                    widget.toggled.connect(lambda _c: schedule_preview())
            for box in list(aerial_checks.values()) + list(hist_checks.values()):
                box.toggled.connect(lambda _c: schedule_preview())
            page_desc_edit.textChanged.connect(
                lambda _t: (None if syncing_description else schedule_preview())
            )
            preview_timer.timeout.connect(refresh_preview)
            export_btn.clicked.connect(on_export)
            close_btn.clicked.connect(dialog.close)
            browse_btn.clicked.connect(on_browse)
            prev_page_btn.clicked.connect(on_prev_page)
            next_page_btn.clicked.connect(on_next_page)
            QTimer.singleShot(0, refresh_preview)

        return SingleInstanceDialog.show_dialog(
            cls.KEY,
            "Export Survey Plots PDF",
            build,
            parent,
            width=980,
            height=720,
        )
