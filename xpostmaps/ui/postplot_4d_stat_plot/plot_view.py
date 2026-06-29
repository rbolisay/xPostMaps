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
    build_plot_series,
    feather_diff_tab_available,
    feather_tab_available,
    unique_sources_from_diff_rows,
)
from xpostmaps.core.postplot_4d_plot_settings import (
    resolve_boundaries_for_kind,
    resolve_source_styles_for_line,
    save_kind_settings,
)
from xpostmaps.ui.postplot_4d_stat_plot.controls import PlotTabControls, YAxisControls
from xpostmaps.ui.postplot_4d_stat_plot.plot_widget import PlotCanvas
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
    """Compact centre control: prev/next arrows plus a sequence load box."""

    previous_requested = Signal()
    next_requested = Signal()
    load_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._prev_btn = QPushButton("\u25c0")
        self._prev_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._prev_btn.setFixedSize(36, 32)
        self._prev_btn.setToolTip("Previous Sequence")
        self._prev_btn.clicked.connect(self.previous_requested.emit)

        self._load_btn = QPushButton("Load Sequence")
        self._load_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._load_btn.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self._load_btn.adjustSize()
        load_w = self._load_btn.sizeHint().width() + 12
        self._load_btn.setFixedSize(load_w, 32)
        self._load_btn.clicked.connect(self._emit_load)

        self._sequence_edit = QLineEdit()
        self._sequence_edit.setPlaceholderText("Sequence")
        self._sequence_edit.setClearButtonEnabled(True)
        self._sequence_edit.setFixedHeight(32)
        self._sequence_edit.setFixedWidth(96)
        self._sequence_edit.returnPressed.connect(self._emit_load)

        self._next_btn = QPushButton("\u25b6")
        self._next_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._next_btn.setFixedSize(36, 32)
        self._next_btn.setToolTip("Next Sequence")
        self._next_btn.clicked.connect(self.next_requested.emit)

        controls_row = QHBoxLayout()
        controls_row.setContentsMargins(0, 0, 0, 0)
        controls_row.setSpacing(6)
        controls_row.addWidget(self._prev_btn)
        controls_row.addWidget(self._load_btn)
        controls_row.addWidget(self._sequence_edit)
        controls_row.addWidget(self._next_btn)

        prev_caption = QLabel("Previous Sequence")
        prev_caption.setStyleSheet(_NAV_CAPTION_STYLE)
        next_caption = QLabel("Next Sequence")
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

    def _emit_load(self) -> None:
        self.load_requested.emit(self._sequence_edit.text().strip())

    def set_sequence(self, sequence_no: str) -> None:
        self._sequence_edit.blockSignals(True)
        self._sequence_edit.setText(sequence_no)
        self._sequence_edit.blockSignals(False)

    def set_navigation_enabled(self, *, can_previous: bool, can_next: bool) -> None:
        self._prev_btn.setEnabled(can_previous)
        self._next_btn.setEnabled(can_next)


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
        self._subline_nav = _SublineNavigator(parent=self)
        self._subline_nav.previous_requested.connect(self.previous_subline_requested.emit)
        self._subline_nav.next_requested.connect(self.next_subline_requested.emit)
        self._subline_nav.load_requested.connect(self.load_subline_requested.emit)
        top = Qt.AlignmentFlag.AlignTop
        toolbar.addWidget(export_btn, alignment=top)
        toolbar.addStretch()
        toolbar.addWidget(self._subline_nav, alignment=top)
        toolbar.addStretch()
        toolbar.addWidget(back_btn, alignment=top)
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
            controls.changed.connect(lambda k=kind: self._on_kind_controls_changed(k))
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
        for kind, controls in self._tab_controls.items():
            controls.set_sources(resolve_source_styles_for_line(self._sources, kind))
            controls.set_boundaries(resolve_boundaries_for_kind(kind))
        if match_row.subline:
            self._title.setText(f"{match_row.line_name}.{match_row.subline} 4D Stat Plot")
        else:
            self._title.setText(f"{match_row.line_name} 4D Stat Plot")
        self._subline_nav.set_sequence(match_row.sequence_no)

        show_feather = feather_tab_available(
            diff_rows,
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
        QTimer.singleShot(0, self._refresh_all_tabs)

    def match_row(self) -> Postplot4DMatchRow | None:
        return self._match_row

    def set_subline_navigation(self, *, can_previous: bool, can_next: bool) -> None:
        self._subline_nav.set_navigation_enabled(
            can_previous=can_previous,
            can_next=can_next,
        )

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

    def _on_kind_controls_changed(self, kind: PlotKind) -> None:
        controls = self._tab_controls.get(kind)
        if controls is not None:
            save_kind_settings(
                kind,
                controls.source_styles(),
                controls.boundaries(),
            )
        self._render_tab(kind)

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
        for kind in _OPTIONAL_PLOT_KINDS:
            if kind not in self.available_plot_kinds():
                self._render_tab(kind)

    def refresh(self) -> None:
        self._refresh_all_tabs()
        QTimer.singleShot(50, self._refresh_all_tabs)
