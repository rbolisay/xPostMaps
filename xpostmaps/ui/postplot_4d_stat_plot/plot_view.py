"""Main 4D Stat Plot view with tabs and controls."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from xpostmaps.core.postplot_4d_diff import Postplot4DDiffRow
from xpostmaps.core.postplot_4d_matching import Postplot4DMatchRow
from xpostmaps.core.postplot_4d_plot_data import (
    BoundaryRow,
    PlotKind,
    PLOT_KIND_LABELS,
    build_plot_series,
    default_source_styles,
    feather_tab_available,
    unique_sources_from_diff_rows,
)
from xpostmaps.ui.postplot_4d_stat_plot.controls import PlotTabControls, YAxisControls
from xpostmaps.ui.postplot_4d_stat_plot.plot_widget import PlotCanvas
from xpostmaps.ui.postplot_4d_stat_plot.theme import STAT_PLOT_TAB_STYLE, STAT_PLOT_VIEW_STYLE

_PLOT_KINDS: tuple[PlotKind, ...] = ("crossline", "inline", "radial", "feather")
_DEFAULT_BOUNDARIES = [BoundaryRow(abs_boundary=6.0), BoundaryRow(abs_boundary=9.0)]


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

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("statPlotRoot")
        self.setStyleSheet(STAT_PLOT_VIEW_STYLE)
        self._match_row: Postplot4DMatchRow | None = None
        self._diff_rows: list[Postplot4DDiffRow] = []
        self._streamers_detected = False
        self._sources: list[str] = []

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
        toolbar.addWidget(export_btn)
        toolbar.addStretch()
        toolbar.addWidget(back_btn)
        root.addLayout(toolbar)

        self._title = QLabel("")
        self._title.setStyleSheet("font-weight: 600; color: #e6edf3;")
        root.addWidget(self._title)

        self._combine_box = QCheckBox("Combine Sources")
        self._combine_box.setChecked(True)
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
            controls.changed.connect(lambda k=kind: self._render_tab(k))
            self._tab_controls[kind] = controls
            self._controls_stack.addWidget(controls)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self._tabs, stretch=1)

        controls_host = QWidget()
        controls_layout = QVBoxLayout(controls_host)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(8)
        controls_layout.addWidget(self._controls_stack)
        self._y_axis = YAxisControls(parent=controls_host)
        self._y_axis.changed.connect(self._refresh_all_tabs)
        controls_layout.addWidget(self._y_axis)
        root.addWidget(controls_host)

    def set_data(
        self,
        match_row: Postplot4DMatchRow,
        diff_rows: list[Postplot4DDiffRow],
        *,
        streamers_detected: bool,
    ) -> None:
        self._match_row = match_row
        self._diff_rows = list(diff_rows)
        self._streamers_detected = streamers_detected
        self._sources = unique_sources_from_diff_rows(diff_rows)
        default_styles = default_source_styles(self._sources)
        for controls in self._tab_controls.values():
            controls.set_sources(default_styles)
            controls.set_boundaries(list(_DEFAULT_BOUNDARIES))
        if match_row.subline:
            self._title.setText(f"{match_row.line_name}.{match_row.subline} 4D Stat Plot")
        else:
            self._title.setText(f"{match_row.line_name} 4D Stat Plot")

        show_feather = feather_tab_available(
            diff_rows,
            streamers_detected=streamers_detected,
        )
        feather_index = self._tabs.indexOf(self._tab_pages["feather"])
        if feather_index >= 0:
            self._tabs.setTabVisible(feather_index, show_feather)
        self._sync_controls_stack()
        self._refresh_all_tabs()
        QTimer.singleShot(0, self._refresh_all_tabs)

    def match_row(self) -> Postplot4DMatchRow | None:
        return self._match_row

    def diff_rows(self) -> list[Postplot4DDiffRow]:
        return list(self._diff_rows)

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

    def available_plot_kinds(self) -> list[PlotKind]:
        kinds: list[PlotKind] = ["crossline", "inline", "radial"]
        if feather_tab_available(
            self._diff_rows,
            streamers_detected=self._streamers_detected,
        ):
            kinds.append("feather")
        return kinds

    def _sync_controls_stack(self) -> None:
        index = self._tabs.currentIndex()
        if 0 <= index < self._controls_stack.count():
            self._controls_stack.setCurrentIndex(index)

    def _on_tab_changed(self, _index: int) -> None:
        self._sync_controls_stack()
        self._refresh_current_tab()

    def _on_combine_changed(self, checked: bool) -> None:
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
        series_list = [
            build_plot_series(self._diff_rows, self._match_row, kind, source_no)
            for source_no in self._sources
        ]
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
        if "feather" not in self.available_plot_kinds():
            self._render_tab("feather")

    def refresh(self) -> None:
        self._refresh_all_tabs()
        QTimer.singleShot(50, self._refresh_all_tabs)
