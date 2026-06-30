"""Survey-wide 4D plots view (aerials, histograms, survey spec pies)."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from xpostmaps.core.postplot_4d_plot_data import (
    PLOT_KIND_LABELS,
    PlotKind,
    SequenceDiffSet,
)
from xpostmaps.core.postplot_4d_survey_plot_data import (
    AerialHeatmapData,
    CumulativeHistogram,
    SurveyPlotsLoadResult,
    SurveySpecPieData,
    histogram_plot_title,
)
from xpostmaps.ui.postplot_4d_stat_plot.theme import STAT_PLOT_TAB_STYLE, STAT_PLOT_VIEW_STYLE
from xpostmaps.ui.postplot_4d_survey_plots.aerial_heatmap_canvas import AerialHeatmapCanvas
from xpostmaps.ui.postplot_4d_survey_plots.histogram_canvas import HistogramCanvas
from xpostmaps.ui.postplot_4d_survey_plots.survey_plot_title_edit import SurveyPlotTitleEdit
from xpostmaps.ui.postplot_4d_survey_plots.pie_panel import SurveySpecPiePanel

_PLOT_KINDS: tuple[PlotKind, ...] = (
    "crossline",
    "inline",
    "radial",
    "feather",
    "feather_diff",
)

_NESTED_SUB_TAB_STYLE = """
QTabWidget::pane {
    border: 1px solid #30363d;
    border-radius: 6px;
    background: #0d1117;
    top: -1px;
}
QTabBar::tab {
    background: #21262d;
    color: #8b949e;
    padding: 6px 14px;
    margin-right: 2px;
    border: 1px solid #30363d;
    border-bottom: none;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    min-width: 64px;
    font-size: 11px;
}
QTabBar::tab:selected {
    background: #30363d;
    color: #58a6ff;
    font-weight: 600;
    border-color: #58a6ff;
}
QTabBar::tab:hover:!selected {
    background: #262c36;
    color: #c9d1d9;
}
"""


class _AerialTabPage(QWidget):
    def __init__(self, kind: PlotKind, parent=None) -> None:
        super().__init__(parent)
        self.kind = kind
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._canvas = AerialHeatmapCanvas(parent=self)
        self._scroll.setWidget(self._canvas.scroll_widget())
        self._canvas.set_scroll_area(self._scroll)
        layout.addWidget(self._scroll, stretch=1)
        layout.addWidget(self._canvas.legend_widget(), alignment=Qt.AlignmentFlag.AlignTop)


class _HistogramTabPage(QWidget):
    def __init__(self, kind: PlotKind, parent=None) -> None:
        super().__init__(parent)
        self.kind = kind
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._title = SurveyPlotTitleEdit()
        self._title.textChanged.connect(self._sync_canvas_title)
        layout.addWidget(self._title)
        self._canvas = HistogramCanvas(parent=self)
        layout.addWidget(self._canvas, stretch=1)
        self._title_source_key: tuple[PlotKind, int] | None = None

    def clear_title_source(self) -> None:
        self._title_source_key = None

    def apply_default_title(self, text: str, source_key: tuple[PlotKind, int]) -> None:
        if self._title_source_key == source_key:
            return
        self._title_source_key = source_key
        self.set_title(text)

    def _sync_canvas_title(self) -> None:
        self._canvas.set_title(self._title.title_text())

    def set_title(self, text: str) -> None:
        self._title.reset_default(text)
        self._canvas.set_title(self._title.title_text())

    def title_text(self) -> str:
        return self._title.title_text()


class _MetricPlotPanel(QWidget):
    """Nested tabs: Aerial + Histogram for one metric kind."""

    def __init__(self, kind: PlotKind, parent=None) -> None:
        super().__init__(parent)
        self.kind = kind
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._sub_tabs = QTabWidget()
        self._sub_tabs.setDocumentMode(True)
        self._sub_tabs.setStyleSheet(_NESTED_SUB_TAB_STYLE)
        self._aerial_page = _AerialTabPage(kind, parent=self)
        self._histogram_page = _HistogramTabPage(kind, parent=self)
        self._sub_tabs.addTab(self._aerial_page, "Aerial")
        self._sub_tabs.addTab(self._histogram_page, "Histogram")
        layout.addWidget(self._sub_tabs)

    @property
    def sub_tabs(self) -> QTabWidget:
        return self._sub_tabs


class Postplot4DSurveyPlotsView(QWidget):
    """Whole-survey plots embedded in the Postplot 4D dialog."""

    back_requested = Signal()
    export_pdf_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("surveyPlotsRoot")
        self.setStyleSheet(STAT_PLOT_VIEW_STYLE)
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._sets: list[SequenceDiffSet] = []
        self._streamers_detected = False
        self._available_kinds: list[PlotKind] = []
        self._metric_cache: dict[PlotKind, list[float]] = {}
        self._heatmap_cache: dict[PlotKind, AerialHeatmapData] = {}
        self._histogram_cache: dict[PlotKind, CumulativeHistogram] = {}
        self._pie_charts: list[SurveySpecPieData] = []
        self._rendered_keys: set[str] = set()
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        toolbar = QHBoxLayout()
        self._export_btn = QPushButton("Export to PDF")
        self._export_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._export_btn.setMinimumSize(130, 32)
        self._export_btn.clicked.connect(self.export_pdf_requested.emit)
        back_btn = QPushButton("Back")
        back_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        back_btn.setMinimumSize(80, 32)
        back_btn.clicked.connect(self.back_requested.emit)
        plot_tips = QLabel(
            "Hold Right Click to Pan on Survey Plots\n"
            "Double Right Click on Survey Plots to Reset Zoom\n"
            "Use Mouse Scroll to Zoom In/Out"
        )
        plot_tips.setWordWrap(True)
        plot_tips.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop
        )
        plot_tips.setStyleSheet("color: #6e7681; font-size: 10px;")
        back_col = QWidget()
        back_col_layout = QVBoxLayout(back_col)
        back_col_layout.setContentsMargins(0, 0, 0, 0)
        back_col_layout.setSpacing(4)
        back_col_layout.addWidget(back_btn, alignment=Qt.AlignmentFlag.AlignRight)
        back_col_layout.addWidget(plot_tips, alignment=Qt.AlignmentFlag.AlignRight)
        toolbar.addWidget(self._export_btn, alignment=Qt.AlignmentFlag.AlignTop)
        toolbar.addStretch()
        toolbar.addWidget(back_col, alignment=Qt.AlignmentFlag.AlignTop)
        root.addLayout(toolbar)

        self._summary = QLabel("")
        self._summary.setStyleSheet("color: #8b949e; font-size: 11px;")
        root.addWidget(self._summary)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(STAT_PLOT_TAB_STYLE)
        self._metric_panels: dict[PlotKind, _MetricPlotPanel] = {}
        for kind in _PLOT_KINDS:
            panel = _MetricPlotPanel(kind, parent=self)
            self._metric_panels[kind] = panel
            self._tabs.addTab(panel, PLOT_KIND_LABELS[kind])
            panel.sub_tabs.currentChanged.connect(self._on_tab_changed)
        self._pie_panel = SurveySpecPiePanel(parent=self)
        self._tabs.addTab(self._pie_panel, "Survey Specs Pie")
        self._tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self._tabs, stretch=1)

    def set_loading(self, loading: bool, message: str = "") -> None:
        self._loading = loading
        self._export_btn.setEnabled(not loading and bool(self._sets))
        if loading:
            self._summary.setText(message or "Loading survey data from database…")
            self._summary.setStyleSheet("color: #58a6ff; font-size: 11px;")
            return
        self._summary.setStyleSheet("color: #8b949e; font-size: 11px;")

    def apply_load_result(
        self,
        result: SurveyPlotsLoadResult,
        *,
        from_cache: bool = False,
    ) -> None:
        self._sets = list(result.sets)
        self._streamers_detected = result.streamers_detected
        self._available_kinds = list(result.available_kinds)
        self._metric_cache = dict(result.metric_values)
        self._heatmap_cache = dict(result.heatmap_cache)
        self._histogram_cache = dict(result.histogram_cache)
        self._pie_charts = list(result.pie_charts)
        self._rendered_keys.clear()
        for panel in self._metric_panels.values():
            panel._histogram_page.clear_title_source()
        if not from_cache:
            self._loading = False
        self._export_btn.setEnabled(bool(result.sets))
        self._summary.setText(
            f"Survey plots · {result.sequence_count} sequence(s) · "
            f"{result.shotpoint_count:,} shotpoint row(s)"
            + (" · loaded from cache" if from_cache else "")
        )
        if from_cache:
            self._summary.setStyleSheet("color: #58a6ff; font-size: 11px;")
        else:
            self._summary.setStyleSheet("color: #8b949e; font-size: 11px;")
        self._update_tab_visibility()
        self.refresh_current_tab()

    def diff_sets(self) -> list[SequenceDiffSet]:
        return list(self._sets)

    def metric_cache(self) -> dict[PlotKind, list[float]]:
        return dict(self._metric_cache)

    def heatmap_cache(self) -> dict[PlotKind, AerialHeatmapData]:
        return dict(self._heatmap_cache)

    def histogram_cache(self) -> dict[PlotKind, CumulativeHistogram]:
        return dict(self._histogram_cache)

    def available_plot_kinds(self) -> list[PlotKind]:
        return list(self._available_kinds)

    def aerial_canvas(self, kind: PlotKind) -> AerialHeatmapCanvas | None:
        panel = self._metric_panels.get(kind)
        return panel._aerial_page._canvas if panel is not None else None

    def histogram_canvas(self, kind: PlotKind) -> HistogramCanvas | None:
        panel = self._metric_panels.get(kind)
        return panel._histogram_page._canvas if panel is not None else None

    def aerial_title(self, kind: PlotKind) -> str:
        panel = self._metric_panels.get(kind)
        if panel is None:
            return ""
        text = panel._aerial_page._canvas.title_text()
        if text:
            return text
        heatmap = self._heatmap_cache.get(kind)
        return heatmap.map_label if heatmap is not None else ""

    def histogram_title(self, kind: PlotKind) -> str:
        panel = self._metric_panels.get(kind)
        if panel is None:
            return ""
        text = panel._histogram_page.title_text()
        if text:
            return text
        if self._sets:
            return histogram_plot_title(self._sets, kind)
        return ""

    def pie_panel(self) -> SurveySpecPiePanel:
        return self._pie_panel

    def pie_charts(self) -> list[SurveySpecPieData]:
        return list(self._pie_charts)

    def current_tab_label(self) -> str:
        return self._tabs.tabText(self._tabs.currentIndex())

    def _tab_key(self, index: int) -> str | None:
        widget = self._tabs.widget(index)
        if widget is self._pie_panel:
            return "pie"
        for kind, panel in self._metric_panels.items():
            if widget is panel:
                current = panel.sub_tabs.currentWidget()
                if current is panel._aerial_page:
                    return f"aerial:{kind}"
                if current is panel._histogram_page:
                    return f"histogram:{kind}"
        return None

    def _current_tab_key(self) -> str | None:
        return self._tab_key(self._tabs.currentIndex())

    def _update_tab_visibility(self) -> None:
        for kind in _PLOT_KINDS:
            panel = self._metric_panels[kind]
            main_index = self._tabs.indexOf(panel)
            visible = kind in self._available_kinds
            if main_index >= 0:
                self._tabs.setTabVisible(main_index, visible)

            has_aerial = kind in self._heatmap_cache
            has_histogram = kind in self._histogram_cache
            aerial_index = panel.sub_tabs.indexOf(panel._aerial_page)
            hist_index = panel.sub_tabs.indexOf(panel._histogram_page)
            if aerial_index >= 0:
                panel.sub_tabs.setTabVisible(aerial_index, has_aerial)
            if hist_index >= 0:
                panel.sub_tabs.setTabVisible(hist_index, has_histogram)

            if visible:
                current = panel.sub_tabs.currentWidget()
                aerial_hidden = not has_aerial and current is panel._aerial_page
                hist_hidden = not has_histogram and current is panel._histogram_page
                if aerial_hidden and has_histogram:
                    panel.sub_tabs.setCurrentWidget(panel._histogram_page)
                elif hist_hidden and has_aerial:
                    panel.sub_tabs.setCurrentWidget(panel._aerial_page)

    def _on_tab_changed(self, _index: int) -> None:
        if not self._loading and self._sets:
            QTimer.singleShot(0, self.refresh_current_tab)

    def _render_aerial(self, kind: PlotKind) -> None:
        panel = self._metric_panels[kind]
        panel._aerial_page._canvas.render(self._heatmap_cache.get(kind))

    def _render_histogram(self, kind: PlotKind) -> None:
        panel = self._metric_panels[kind]
        histogram = self._histogram_cache.get(kind)
        if histogram is None:
            return
        panel._histogram_page.apply_default_title(
            histogram_plot_title(self._sets, kind),
            (kind, id(histogram)),
        )
        panel._histogram_page._canvas.render(histogram)

    def _render_pie(self) -> None:
        self._pie_panel.render(self._pie_charts)

    def refresh_current_tab(self) -> None:
        if self._loading or not self._sets:
            return
        key = self._current_tab_key()
        if key is None or key in self._rendered_keys:
            return
        if key == "pie":
            self._render_pie()
        elif key.startswith("aerial:"):
            kind = key.split(":", 1)[1]  # type: ignore[assignment]
            if kind in self._available_kinds and kind in self._heatmap_cache:
                self._render_aerial(kind)  # type: ignore[arg-type]
        elif key.startswith("histogram:"):
            kind = key.split(":", 1)[1]  # type: ignore[assignment]
            if kind in self._available_kinds and kind in self._histogram_cache:
                self._render_histogram(kind)  # type: ignore[arg-type]
        self._rendered_keys.add(key)

    def refresh_all(self) -> None:
        """Render every tab — used before PDF export."""
        if not self._sets:
            return
        for kind in self._available_kinds:
            if kind in self._heatmap_cache:
                self._render_aerial(kind)
                self._rendered_keys.add(f"aerial:{kind}")
            if kind in self._histogram_cache:
                self._render_histogram(kind)
                self._rendered_keys.add(f"histogram:{kind}")
        self._render_pie()
        self._rendered_keys.add("pie")

    def refresh(self) -> None:
        """Re-render the visible tab (keeps others cached)."""
        key = self._current_tab_key()
        if key is not None:
            self._rendered_keys.discard(key)
        self.refresh_current_tab()

    def restore_after_pdf_export(self) -> None:
        """Reset plot widgets after PDF capture mutates axis/layout state."""
        self._rendered_keys.clear()
        self.refresh_all()

    def prepare_for_pdf_capture(
        self,
        *,
        page_kind: str,
        metric_kind: str | None = None,
        pie_index: int | None = None,
    ) -> None:
        """Show the widget tree needed for off-screen PDF/preview capture."""
        if page_kind == "pie":
            if self._tabs.indexOf(self._pie_panel) >= 0:
                self._tabs.setCurrentWidget(self._pie_panel)
            if pie_index is not None:
                self._pie_panel.select_page(pie_index)
        elif metric_kind is not None:
            panel = self._metric_panels.get(metric_kind)  # type: ignore[arg-type]
            if panel is not None and self._tabs.indexOf(panel) >= 0:
                self._tabs.setCurrentWidget(panel)
                if page_kind == "aerial":
                    panel.sub_tabs.setCurrentWidget(panel._aerial_page)
                elif page_kind == "histogram":
                    panel.sub_tabs.setCurrentWidget(panel._histogram_page)
        QApplication.processEvents()
