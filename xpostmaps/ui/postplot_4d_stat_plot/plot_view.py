"""Main 4D Stat Plot view with tabs and controls."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from xpostmaps.core.postplot_4d_diff import Postplot4DDiffRow
from xpostmaps.core.postplot_4d_matching import Postplot4DMatchRow
from xpostmaps.core.postplot_4d_plot_data import (
    PlotKind,
    PLOT_KIND_LABELS,
    SequenceDiffSet,
    build_combined_plot_series,
    combined_sequence_numbers,
    combined_source_key,
    combined_source_numbers,
    feather_diff_tab_available,
    feather_tab_available,
    primary_sequence_set,
)
from xpostmaps.core.postplot_4d_plot_settings import (
    PlotViewSettings,
    load_excluded_shotpoints,
    load_plot_view_settings,
    load_plot_view_settings_for_plot,
    load_survey_specs,
    plot_settings_key,
    resolve_boundaries_for_plot,
    resolve_source_styles_for_plot,
    save_excluded_shotpoints,
    save_plot_kind_settings,
    save_plot_view_settings_for_plot,
    save_survey_specs,
)
from xpostmaps.core.postplot_4d_survey_spec import (
    SurveyEvaluation,
    evaluate_survey_specs,
)
from xpostmaps.ui.postplot_4d_stat_plot.controls import PlotTabControls, YAxisControls
from xpostmaps.ui.postplot_4d_stat_plot.plot_widget import PlotCanvas
from xpostmaps.ui.postplot_4d_stat_plot.survey_specs import SurveySpecsPanel
from xpostmaps.ui.postplot_4d_stat_plot.theme import STAT_PLOT_TAB_STYLE, STAT_PLOT_VIEW_STYLE

_PLOT_KINDS: tuple[PlotKind, ...] = (
    "crossline",
    "inline",
    "radial",
    "feather",
    "feather_diff",
)
_OPTIONAL_PLOT_KINDS: tuple[PlotKind, ...] = ("feather", "feather_diff")

_NAV_CAPTION_STYLE = "color: #8b949e; font-size: 10px;"


class _SublineNavigator(QWidget):
    """Centre control: preplot/sequence step arrows plus load/combine boxes."""

    previous_requested = Signal()
    next_requested = Signal()
    load_requested = Signal(str)
    previous_preplot_requested = Signal()
    next_preplot_requested = Signal()
    load_preplot_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._prev_preplot_btn = self._arrow_button(
            "\u23ee", "Previous Preplot", self.previous_preplot_requested.emit
        )
        self._prev_btn = self._arrow_button(
            "\u25c0", "Previous Sequence", self.previous_requested.emit
        )

        self._load_btn = self._text_button("Load/Combine Sequence(s)", self._emit_load)

        self._sequence_edit = self._input_box(
            "Seq, e.g. 1-3 or 1, 5, 9", width=150
        )
        self._sequence_edit.returnPressed.connect(self._emit_load)

        self._load_preplot_btn = self._text_button(
            "Load Preplot Sequence(s)", self._emit_load_preplot
        )
        self._preplot_edit = self._input_box("Preplot", width=130)
        self._preplot_edit.returnPressed.connect(self._emit_load_preplot)

        self._next_btn = self._arrow_button(
            "\u25b6", "Next Sequence", self.next_requested.emit
        )
        self._next_preplot_btn = self._arrow_button(
            "\u23ed", "Next Preplot", self.next_preplot_requested.emit
        )

        controls_row = QHBoxLayout()
        controls_row.setContentsMargins(0, 0, 0, 0)
        controls_row.setSpacing(6)
        for widget in (
            self._prev_preplot_btn,
            self._prev_btn,
            self._load_btn,
            self._sequence_edit,
            self._load_preplot_btn,
            self._preplot_edit,
            self._next_btn,
            self._next_preplot_btn,
        ):
            controls_row.addWidget(widget)

        prev_caption = QLabel("\u23ee Preplot   \u25c0 Sequence")
        prev_caption.setStyleSheet(_NAV_CAPTION_STYLE)
        next_caption = QLabel("Sequence \u25b6   Preplot \u23ed")
        next_caption.setStyleSheet(_NAV_CAPTION_STYLE)
        captions_row = QHBoxLayout()
        captions_row.setContentsMargins(0, 0, 0, 0)
        captions_row.setSpacing(6)
        captions_row.addWidget(prev_caption, alignment=Qt.AlignmentFlag.AlignLeft)
        captions_row.addStretch()
        captions_row.addWidget(next_caption, alignment=Qt.AlignmentFlag.AlignRight)

        host = QVBoxLayout(self)
        host.setContentsMargins(0, 0, 0, 0)
        host.setSpacing(1)
        host.addLayout(controls_row)
        host.addLayout(captions_row)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def _arrow_button(self, glyph: str, tooltip: str, slot) -> QPushButton:
        btn = QPushButton(glyph)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setFixedSize(36, 32)
        btn.setToolTip(tooltip)
        btn.clicked.connect(slot)
        return btn

    def _text_button(self, label: str, slot) -> QPushButton:
        btn = QPushButton(label)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        btn.adjustSize()
        btn.setFixedSize(btn.sizeHint().width() + 12, 32)
        btn.clicked.connect(slot)
        return btn

    def _input_box(self, placeholder: str, *, width: int) -> QLineEdit:
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.setClearButtonEnabled(True)
        edit.setFixedHeight(32)
        edit.setFixedWidth(width)
        return edit

    def _emit_load(self) -> None:
        self.load_requested.emit(self._sequence_edit.text().strip())

    def _emit_load_preplot(self) -> None:
        self.load_preplot_requested.emit(self._preplot_edit.text().strip())

    def set_sequence(self, sequence_no: str) -> None:
        self._sequence_edit.blockSignals(True)
        self._sequence_edit.setText(sequence_no)
        self._sequence_edit.blockSignals(False)

    def set_preplot(self, preplot_name: str) -> None:
        self._preplot_edit.blockSignals(True)
        self._preplot_edit.setText(preplot_name)
        self._preplot_edit.blockSignals(False)

    def set_navigation_enabled(self, *, can_previous: bool, can_next: bool) -> None:
        self._prev_btn.setEnabled(can_previous)
        self._next_btn.setEnabled(can_next)

    def set_preplot_navigation_enabled(
        self, *, can_previous: bool, can_next: bool
    ) -> None:
        self._prev_preplot_btn.setEnabled(can_previous)
        self._next_preplot_btn.setEnabled(can_next)


class _PlotTabPage(QWidget):
    def __init__(self, kind: PlotKind, parent=None) -> None:
        super().__init__(parent)
        self.kind = kind
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._canvas = PlotCanvas(kind, parent=self)
        layout.addWidget(self._canvas, stretch=1)


class Postplot4DStatPlotView(QWidget):
    """Plot view embedded in the 4D Stat dialog."""

    back_requested = Signal()
    export_pdf_requested = Signal()
    previous_subline_requested = Signal()
    next_subline_requested = Signal()
    load_subline_requested = Signal(str)
    previous_preplot_requested = Signal()
    next_preplot_requested = Signal()
    load_preplot_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("statPlotRoot")
        self.setStyleSheet(STAT_PLOT_VIEW_STYLE)
        self._match_row: Postplot4DMatchRow | None = None
        self._diff_rows: list[Postplot4DDiffRow] = []
        self._streamers_detected = False
        self._sources: list[str] = []
        self._sets: list[SequenceDiffSet] = []
        self._plot_settings_key: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        toolbar = QHBoxLayout()
        export_btn = QPushButton("Export to PDF")
        export_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        export_btn.setMinimumSize(130, 32)
        export_btn.clicked.connect(self.export_pdf_requested.emit)
        back_btn = QPushButton("Back")
        back_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        back_btn.setMinimumSize(80, 32)
        back_btn.clicked.connect(self.back_requested.emit)
        self._subline_nav = _SublineNavigator(parent=self)
        self._subline_nav.previous_requested.connect(self.previous_subline_requested.emit)
        self._subline_nav.next_requested.connect(self.next_subline_requested.emit)
        self._subline_nav.load_requested.connect(self.load_subline_requested.emit)
        self._subline_nav.previous_preplot_requested.connect(
            self.previous_preplot_requested.emit
        )
        self._subline_nav.next_preplot_requested.connect(self.next_preplot_requested.emit)
        self._subline_nav.load_preplot_requested.connect(self.load_preplot_requested.emit)
        top = Qt.AlignmentFlag.AlignTop
        toolbar.addWidget(export_btn, alignment=top)
        toolbar.addStretch()
        toolbar.addWidget(self._subline_nav, alignment=top)
        toolbar.addStretch()
        back_col = QVBoxLayout()
        back_col.setContentsMargins(0, 0, 0, 0)
        back_col.setSpacing(2)
        back_col.addWidget(back_btn, alignment=Qt.AlignmentFlag.AlignRight)
        self._acceptance = QLabel("Acceptance: \u2014")
        self._acceptance.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        back_col.addWidget(self._acceptance, alignment=Qt.AlignmentFlag.AlignRight)
        toolbar.addLayout(back_col)
        root.addLayout(toolbar)
        self._update_acceptance(None)

        self._title = QLabel("")
        self._title.setStyleSheet("font-weight: 600; color: #e6edf3;")
        root.addWidget(self._title)

        self._combine_box = QCheckBox("Combine Sources")
        self._combine_box.setStyleSheet("color: #e6edf3;")
        self._combine_box.toggled.connect(self._on_combine_changed)
        root.addWidget(self._combine_box)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(STAT_PLOT_TAB_STYLE)
        self._tab_pages: dict[PlotKind, _PlotTabPage] = {}
        self._tab_controls: dict[PlotKind, PlotTabControls] = {}
        self._controls_stack = QStackedWidget()
        for kind in _PLOT_KINDS:
            page = _PlotTabPage(kind, parent=self)
            self._tab_pages[kind] = page
            self._tabs.addTab(page, PLOT_KIND_LABELS[kind])
            controls = PlotTabControls(parent=self)
            controls.changed.connect(lambda k=kind: self._on_kind_controls_changed(k))
            self._tab_controls[kind] = controls
            self._controls_stack.addWidget(controls)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self._tabs, stretch=1)

        self._bottom_tabs = QTabWidget()
        self._bottom_tabs.setStyleSheet(STAT_PLOT_TAB_STYLE)

        # Survey Specs tab (default): acceptance limits + per-sequence results.
        self._survey_panel = SurveySpecsPanel(parent=self)
        self._survey_panel.set_rows(load_survey_specs())
        self._survey_panel.changed.connect(self._on_survey_specs_changed)
        specs_page = QWidget()
        specs_layout = QVBoxLayout(specs_page)
        specs_layout.setContentsMargins(8, 4, 8, 8)
        specs_layout.setSpacing(0)
        specs_layout.addWidget(
            self._survey_panel,
            alignment=Qt.AlignmentFlag.AlignTop,
        )
        specs_layout.addStretch(1)
        self._bottom_tabs.addTab(specs_page, "Survey Specs")

        # Plot Settings tab: per-kind Source Style + Boundary Limits + Y axis.
        plot_settings_page = QWidget()
        plot_settings_layout = QVBoxLayout(plot_settings_page)
        plot_settings_layout.setContentsMargins(8, 8, 8, 8)
        plot_settings_layout.setSpacing(8)
        plot_settings_layout.addWidget(self._controls_stack)
        self._y_axis = YAxisControls(parent=plot_settings_page)
        self._y_axis.changed.connect(self._on_y_axis_changed)
        plot_settings_layout.addWidget(self._y_axis)
        self._bottom_tabs.addTab(plot_settings_page, "Plot Settings")

        self._bottom_tabs.setCurrentIndex(0)
        root.addWidget(self._bottom_tabs)

        self._apply_saved_plot_view_settings()

    def set_data(
        self,
        match_row: Postplot4DMatchRow,
        diff_rows: list[Postplot4DDiffRow],
        *,
        streamers_detected: bool,
    ) -> None:
        """Single-sequence entry point (delegates to the combined path)."""
        self.set_combined_data(
            [SequenceDiffSet(match_row=match_row, diff_rows=list(diff_rows))],
            streamers_detected=streamers_detected,
        )

    def set_combined_data(
        self,
        sets: list[SequenceDiffSet],
        *,
        streamers_detected: bool,
    ) -> None:
        if not sets:
            return
        self._sets = list(sets)
        primary = primary_sequence_set(self._sets)
        match_row = primary.match_row
        self._match_row = match_row
        self._diff_rows = [row for item in self._sets for row in item.diff_rows]
        self._streamers_detected = streamers_detected
        self._sources = combined_source_numbers(self._sets)
        sequence_nos = combined_sequence_numbers(self._sets)
        multi = len(self._sets) > 1
        self._plot_settings_key = plot_settings_key(match_row)
        self._apply_plot_view_settings()

        for kind, controls in self._tab_controls.items():
            if multi:
                keys = [
                    combined_source_key(source_no, sequence_no)
                    for source_no in self._sources
                    for sequence_no in sequence_nos
                ]
                resolved = resolve_source_styles_for_plot(
                    self._plot_settings_key, keys, kind
                )
                style_by_key = {row.source_no: row for row in resolved}
                controls.set_source_matrix(self._sources, sequence_nos, style_by_key)
            else:
                controls.set_sources(
                    resolve_source_styles_for_plot(
                        self._plot_settings_key,
                        self._sources,
                        kind,
                    )
                )
            controls.set_boundaries(
                resolve_boundaries_for_plot(self._plot_settings_key, kind)
            )

        line_label = (
            f"{match_row.line_name}.{match_row.subline}"
            if match_row.subline
            else match_row.line_name
        )
        if multi:
            seq_label = ", ".join(sequence_nos)
            baseline = match_row.baseline_name or line_label
            self._title.setText(
                f"{baseline} 4D Stat Plot \u2014 Combined Sequences {seq_label}"
            )
        else:
            self._title.setText(f"{line_label} 4D Stat Plot")
        self._subline_nav.set_sequence(", ".join(sequence_nos))
        self._subline_nav.set_preplot(match_row.baseline_name)

        self._survey_panel.set_sequences(
            sequence_nos,
            load_excluded_shotpoints(),
        )

        show_feather = feather_tab_available(
            self._diff_rows,
            streamers_detected=streamers_detected,
        )
        show_feather_diff = feather_diff_tab_available(
            match_row,
            streamers_detected=streamers_detected,
        )
        for kind, visible in (
            ("feather", show_feather),
            ("feather_diff", show_feather_diff),
        ):
            tab_index = self._tabs.indexOf(self._tab_pages[kind])
            if tab_index >= 0:
                self._tabs.setTabVisible(tab_index, visible)
        self._sync_controls_stack()
        self._refresh_all_tabs()
        self._evaluate_survey()
        QTimer.singleShot(0, self._refresh_all_tabs)

    def match_row(self) -> Postplot4DMatchRow | None:
        return self._match_row

    def set_subline_navigation(self, *, can_previous: bool, can_next: bool) -> None:
        self._subline_nav.set_navigation_enabled(
            can_previous=can_previous,
            can_next=can_next,
        )

    def set_preplot_navigation(self, *, can_previous: bool, can_next: bool) -> None:
        self._subline_nav.set_preplot_navigation_enabled(
            can_previous=can_previous,
            can_next=can_next,
        )

    def diff_rows(self) -> list[Postplot4DDiffRow]:
        return list(self._diff_rows)

    def build_series_for_kind(self, kind: PlotKind):
        """Combined plot series for *kind*, keyed exactly as the on-screen plot.

        In multi-sequence mode the series are keyed by composite
        ``"G01 · Seq <n>"`` labels (matching the Source Style columns and the
        PDF export), so PDF rendering reuses the same data the view shows.
        """
        return build_combined_plot_series(self._sets, kind)

    def combine_sources(self) -> bool:
        return self._combine_box.isChecked()

    def tab_controls_for_kind(self, kind: PlotKind) -> PlotTabControls | None:
        return self._tab_controls.get(kind)

    def source_styles(self) -> list:
        return self.source_styles_for_kind(self.current_kind())

    def source_styles_for_kind(self, kind: PlotKind) -> list:
        controls = self._tab_controls.get(kind)
        return controls.source_styles() if controls is not None else []

    def boundaries(self) -> list[BoundaryRow]:
        return self.boundaries_for_kind(self.current_kind())

    def boundaries_for_kind(self, kind: PlotKind) -> list[BoundaryRow]:
        controls = self._tab_controls.get(kind)
        return controls.boundaries() if controls is not None else []

    def y_axis_auto(self) -> bool:
        return self._y_axis.auto_y()

    def y_axis_range(self) -> tuple[float | None, float | None]:
        return self._y_axis.y_range()

    def current_kind(self) -> PlotKind:
        widget = self._tabs.currentWidget()
        if isinstance(widget, _PlotTabPage):
            return widget.kind
        return "crossline"

    def canvas_for_kind(self, kind: PlotKind) -> PlotCanvas | None:
        page = self._tab_pages.get(kind)
        return page._canvas if page is not None else None

    def onscreen_plot_width(self) -> float:
        """Live on-screen plot width of the visible canvas, for PDF marker scaling.

        Only the currently-shown tab's plot is laid out at full size, so this
        single reference is shared across every exported page (all tabs display
        at the same width). Returns 0.0 when nothing is laid out yet, in which
        case the export falls back to DPI-faithful marker sizing.
        """
        page = self._tabs.currentWidget()
        canvas = getattr(page, "_canvas", None)
        if canvas is None:
            return 0.0
        content = canvas.content_widget()
        target = content if content is not None else canvas
        return float(target.width())

    def available_plot_kinds(self) -> list[PlotKind]:
        kinds: list[PlotKind] = ["crossline", "inline", "radial"]
        if feather_tab_available(
            self._diff_rows,
            streamers_detected=self._streamers_detected,
        ):
            kinds.append("feather")
        if feather_diff_tab_available(
            self._match_row,
            streamers_detected=self._streamers_detected,
        ):
            kinds.append("feather_diff")
        return kinds

    def _sync_controls_stack(self) -> None:
        index = self._tabs.currentIndex()
        if 0 <= index < self._controls_stack.count():
            self._controls_stack.setCurrentIndex(index)

    def _on_tab_changed(self, _index: int) -> None:
        self._sync_controls_stack()
        self._refresh_current_tab()

    def _apply_saved_plot_view_settings(self) -> None:
        """Initial defaults before the first plot line is loaded."""
        saved = load_plot_view_settings()
        self._apply_plot_view_settings(saved)

    def _apply_plot_view_settings(
        self, settings: PlotViewSettings | None = None
    ) -> None:
        if settings is None:
            if self._plot_settings_key:
                settings = load_plot_view_settings_for_plot(self._plot_settings_key)
            else:
                settings = load_plot_view_settings()
        self._y_axis.apply_settings(
            auto_y=settings.auto_y,
            y_min=settings.y_min,
            y_max=settings.y_max,
        )
        self._combine_box.blockSignals(True)
        try:
            self._combine_box.setChecked(settings.combine_sources)
        finally:
            self._combine_box.blockSignals(False)

    def _current_plot_view_settings(self) -> PlotViewSettings:
        y_min, y_max = self._y_axis.manual_y_range()
        return PlotViewSettings(
            auto_y=self._y_axis.auto_y(),
            y_min=float(y_min),
            y_max=float(y_max),
            combine_sources=self._combine_box.isChecked(),
        )

    def _persist_plot_view_settings(self) -> None:
        if not self._plot_settings_key:
            return
        save_plot_view_settings_for_plot(
            self._plot_settings_key,
            self._current_plot_view_settings(),
        )

    def _on_y_axis_changed(self) -> None:
        self._persist_plot_view_settings()
        self._refresh_all_tabs()

    def _autosave_survey_specs(self) -> None:
        """Persist global survey specs immediately (shared across all sequences)."""
        save_survey_specs(self._survey_panel.rows())
        save_excluded_shotpoints(self._survey_panel.excluded_shotpoints())

    def _on_survey_specs_changed(self) -> None:
        self._autosave_survey_specs()
        self._evaluate_survey()

    def _evaluate_survey(self) -> None:
        sequence_nos = combined_sequence_numbers(self._sets) if self._sets else []
        if not self._sets:
            self._survey_panel.set_sequences(sequence_nos, self._survey_panel.excluded_shotpoints())
            self._survey_panel.set_evaluation(None, sequence_nos)
            self._update_acceptance(None)
            return
        excluded = self._survey_panel.excluded_shotpoints()
        evaluation = evaluate_survey_specs(
            self._sets,
            self._survey_panel.rows(),
            excluded_by_sequence=excluded,
        )
        self._survey_panel.set_evaluation(evaluation, sequence_nos)
        self._update_acceptance(evaluation)

    def _update_acceptance(self, evaluation: SurveyEvaluation | None) -> None:
        if evaluation is None or evaluation.spec_count == 0:
            self._acceptance.setText("Acceptance: \u2014")
            self._acceptance.setStyleSheet("color: #8b949e; font-size: 12px;")
            return
        if evaluation.accepted:
            self._acceptance.setText("Acceptance: PASS")
            self._acceptance.setStyleSheet(
                "color: #3fb950; font-size: 13px; font-weight: 700;"
            )
        else:
            self._acceptance.setText("Acceptance: FAIL")
            self._acceptance.setStyleSheet(
                "color: #f85149; font-size: 13px; font-weight: 700;"
            )

    def survey_evaluation(self) -> SurveyEvaluation | None:
        """Current survey acceptance evaluation (None when no data)."""
        if not self._sets:
            return None
        return evaluate_survey_specs(
            self._sets,
            self._survey_panel.rows(),
            excluded_by_sequence=self._survey_panel.excluded_shotpoints(),
        )

    def _on_kind_controls_changed(self, kind: PlotKind) -> None:
        controls = self._tab_controls.get(kind)
        if controls is not None and self._plot_settings_key:
            save_plot_kind_settings(
                self._plot_settings_key,
                kind,
                controls.source_styles(),
                controls.boundaries(),
            )
        self._render_tab(kind)

    def _on_combine_changed(self, checked: bool) -> None:
        self._persist_plot_view_settings()
        for page in self._tab_pages.values():
            page._canvas.set_combine_sources(checked)
        self._refresh_all_tabs()

    def _render_tab(self, kind: PlotKind) -> None:
        if self._match_row is None:
            return
        page = self._tab_pages.get(kind)
        controls = self._tab_controls.get(kind)
        if page is None or controls is None:
            return
        styles = controls.source_styles()
        boundaries = controls.boundaries()
        y_min, y_max = self._y_axis.y_range()
        series_list = build_combined_plot_series(self._sets, kind)
        page._canvas.set_combine_sources(self._combine_box.isChecked())
        page._canvas.render(
            series_list,
            styles,
            boundaries,
            y_min=y_min,
            y_max=y_max,
            auto_y=self._y_axis.auto_y(),
        )

    def _refresh_current_tab(self) -> None:
        self._render_tab(self.current_kind())

    def _refresh_all_tabs(self) -> None:
        if self._match_row is None:
            return
        for kind in self.available_plot_kinds():
            self._render_tab(kind)
        for kind in _OPTIONAL_PLOT_KINDS:
            if kind not in self.available_plot_kinds():
                self._render_tab(kind)

    def refresh(self) -> None:
        self._refresh_all_tabs()
        QTimer.singleShot(50, self._refresh_all_tabs)
