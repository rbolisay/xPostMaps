"""Brutal + visual QA: shotpoint drag/Ctrl selection and Add to Excluded."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtGui import QBrush, QColor, QImage, QPen
from PySide6.QtWidgets import QApplication

import pyqtgraph as pg

from xpostmaps.core.database import Database
from xpostmaps.core.postplot_4d_diff import calculate_match_diff_rows
from xpostmaps.core.postplot_4d_matching import build_postplot_4d_rows
from xpostmaps.core.postplot_4d_plot_data import SequenceDiffSet
from xpostmaps.core.postplot_4d_survey_spec import (
    Severity,
    StatType,
    SurveySpecRow,
    flag_map_for_kind,
    parse_excluded_shotpoints,
)
from xpostmaps.ui.postplot_4d_stat_plot.plot_view import Postplot4DStatPlotView
from xpostmaps.ui.postplot_4d_stat_plot.plot_widget import (
    _SELECTION_RING_COLOR,
    _SELECTION_RING_SIZE_PX,
)
from xpostmaps.ui.postplot_4d_stat_plot.shotpoint_selection import pick_points_in_rect

OUT_DIR = ROOT / "data" / "brutal_4d_stat_plot_selection"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SPECS = [
    SurveySpecRow(
        statistic=StatType.MAX_VALUE,
        metric="radial",
        stat_value=12.0,
        absolute=True,
        severity=Severity.WARNING,
    ),
    SurveySpecRow(
        statistic=StatType.MAX_CONSECUTIVE_FAILED,
        metric="radial",
        reference_value=10.0,
        stat_value=8.0,
        severity=Severity.ERROR,
    ),
    SurveySpecRow(
        statistic=StatType.MAX_PCT_FAILURE,
        metric="radial",
        reference_value=7.5,
        stat_value=10.0,
        severity=Severity.ERROR,
    ),
]


def _selection_ring_style_ok(plot) -> bool:
    scatter = plot._selection_marker
    brush = scatter.opts.get("brush")
    pen = scatter.opts.get("pen")
    if not isinstance(brush, QBrush) or brush.color().alpha() != 0:
        return False
    if not isinstance(pen, QPen):
        return False
    ring = QColor(_SELECTION_RING_COLOR)
    pen_color = QColor(pen.color())
    return (
        abs(pen_color.red() - ring.red()) <= 8
        and abs(pen_color.green() - ring.green()) <= 8
        and abs(pen_color.blue() - ring.blue()) <= 8
        and float(scatter.opts.get("size", 0)) == float(_SELECTION_RING_SIZE_PX)
    )


def _load_sequence() -> SequenceDiffSet:
    db = Database(ROOT / "data" / "10221.db")
    settings, map_data = db.load_project("10221", with_positions=True)
    settings.postplot_4d_baseline = "navplan"
    positions = db.load_positions("10221")
    rows = build_postplot_4d_rows(map_data, settings, "navplan")
    match = next(
        r for r in rows if r.sequence_id.startswith("70.1065P1A-070.a070.p190")
    )
    diff_rows = db.load_postplot_4d_diffs(
        "10221", match.baseline_kind, match.sequence_id
    )
    if not diff_rows:
        diff_rows = calculate_match_diff_rows(
            map_data,
            settings,
            positions,
            match,
            database=db,
            project_name="10221",
        )
    return SequenceDiffSet(match_row=match, diff_rows=diff_rows)


def _grab(view: Postplot4DStatPlotView, path: Path) -> QImage:
    view.resize(1280, 820)
    if not view.isVisible():
        view.show()
    app = QApplication.instance()
    assert app is not None
    for _ in range(3):
        app.processEvents()
    canvas = view.canvas_for_kind("radial")
    if canvas is not None:
        image = canvas.capture_image(width=view.width(), height=max(480, view.height() - 280))
    else:
        image = view.grab().toImage()
    image.save(str(path))
    return image


def _plot(view: Postplot4DStatPlotView):
    canvas = view.canvas_for_kind("radial")
    if canvas is None:
        return None
    return canvas._combined_plot


def _pixel_at_data(plot, shotpoint: float, value: float) -> tuple[int, int]:
    vb = plot.getViewBox()
    scene_pt = vb.mapViewToScene(pg.Point(shotpoint, value))
    widget_pt = plot.mapFromScene(scene_pt)
    return int(round(widget_pt.x())), int(round(widget_pt.y()))


def _sample_ring_near(plot, shotpoint: float, value: float, image: QImage) -> QColor:
    x, y = _pixel_at_data(plot, shotpoint, value)
    x = max(0, min(image.width() - 1, x))
    y = max(0, min(image.height() - 1, y))
    best = image.pixelColor(x, y)
    best_score = best.red() + best.blue() - best.green()
    for dx in range(-6, 7):
        for dy in range(-6, 7):
            if dx * dx + dy * dy > 36:
                continue
            sx = max(0, min(image.width() - 1, x + dx))
            sy = max(0, min(image.height() - 1, y + dy))
            color = image.pixelColor(sx, sy)
            score = color.red() + color.blue() - color.green()
            if score > best_score:
                best_score = score
                best = color
    return best


def _is_fuchsia_ring_pixel(color: QColor) -> bool:
    return color.red() >= 180 and color.blue() >= 180 and color.green() <= 120


def _source_pixel_near(plot, shotpoint: float, value: float, image: QImage) -> QColor:
    """Sample the underlying source marker (inside the fuchsia ring)."""
    x, y = _pixel_at_data(plot, shotpoint, value)
    x = max(0, min(image.width() - 1, x))
    y = max(0, min(image.height() - 1, y))
    return image.pixelColor(x, y)


def _excluded_edit_text(view: Postplot4DStatPlotView) -> str:
    summary = view._survey_panel._summary
    edit = summary._table.cellWidget(0, summary._COL_EXCLUDED)
    return edit.text().strip() if edit is not None else ""


def _report(failures: list[str]) -> int:
    if failures:
        print("\nBRUTAL SELECTION QA: FAIL")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("\nBRUTAL SELECTION QA: PASS")
    print(f"Artifacts: {OUT_DIR}")
    return 0


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    failures: list[str] = []
    diff_set = _load_sequence()

    view = Postplot4DStatPlotView()
    view.set_combined_data([diff_set], streamers_detected=True)
    view._survey_panel.set_rows(SPECS)
    view._survey_panel.set_sequences(["070"], {"070": ""})
    view._tabs.setCurrentWidget(view._tab_pages["radial"])
    view._evaluate_survey()
    view._refresh_all_tabs()
    view.show()
    app.processEvents()

    plot = _plot(view)
    if plot is None:
        return _report(["radial canvas missing"])

    if plot._on_add_to_excluded is None:
        failures.append("plot exclusion handler not configured")

    ev_before = view.survey_evaluation()
    if ev_before is None or ev_before.accepted:
        failures.append("expected FAIL before any exclusion")

    # --- drag rectangle preview ---
    plot._on_selection_drag_move(1458, 7, 1484, 22)
    drag_visible = plot._drag_rect.isVisible()
    img_drag = _grab(view, OUT_DIR / "01_drag_rectangle.png")
    plot = _plot(view)
    if plot is None or not drag_visible:
        failures.append("drag rectangle not visible during selection drag")

    # --- drag select peak (1461-1481 region) ---
    plot._on_selection_drag_finish(1458, 7, 1484, 22)
    grouped = plot.selected_shotpoints_by_sequence()
    selected_sps = grouped.get("070", set())
    expected_peak = set(range(1461, 1482))
    missing_peak = expected_peak - selected_sps
    print(f"drag selected SPs ({len(selected_sps)}): {sorted(selected_sps)[:12]}...")
    if len(missing_peak) > 4:
        failures.append(
            f"drag missed too many peak SPs: missing {sorted(missing_peak)[:8]}"
        )
    if not selected_sps:
        failures.append("drag selection empty")

    img_selected = _grab(view, OUT_DIR / "02_after_drag_select.png")
    plot = _plot(view)
    if plot is None:
        failures.append("plot missing after drag select")
    else:
        xs, ys = plot._selection_marker.getData()
        marker_count = len(xs) if xs is not None else 0
        if marker_count < 20:
            failures.append(
                f"expected >=20 selection markers, got {marker_count}"
            )
        if not plot._selection_marker.isVisible():
            failures.append("selection markers not visible after drag")
        if not _selection_ring_style_ok(plot):
            failures.append("selection marker is not a transparent fuchsia ring")

        ring_sample = _sample_ring_near(plot, 1471.0, 21.0, img_selected)
        source_sample = _source_pixel_near(plot, 1471.0, 21.0, img_selected)
        print(
            "  SP1471 ring RGB="
            f"({ring_sample.red()}, {ring_sample.green()}, {ring_sample.blue()}) "
            f"center RGB=({source_sample.red()}, {source_sample.green()}, {source_sample.blue()})"
        )
        if not _is_fuchsia_ring_pixel(ring_sample):
            failures.append(
                f"SP1471 ring not fuchsia, got ({ring_sample.red()}, "
                f"{ring_sample.green()}, {ring_sample.blue()})"
            )
        if (
            source_sample.red() == 255
            and source_sample.green() == 0
            and source_sample.blue() == 255
        ):
            failures.append("SP1471 appears fuchsia-filled instead of ring-only")

        overlay = plot._selection_edit.text()
        if "Selected:" not in overlay:
            failures.append(f"selection overlay missing: {overlay!r}")

    # --- add to excluded via plot handler (peak selection) ---
    plot = _plot(view)
    if plot is None:
        return _report(failures + ["plot missing before add to excluded"])
    plot._add_selection_to_excluded()
    excluded_text = _excluded_edit_text(view)
    print(f"excluded field: {excluded_text!r}")
    excluded_set = parse_excluded_shotpoints(excluded_text)
    if not excluded_set:
        failures.append("excluded field empty after Add to Excluded")
    overlap_peak = excluded_set & expected_peak
    if len(overlap_peak) < 15:
        failures.append(
            f"too few peak SPs in excluded field: {len(overlap_peak)} of 21"
        )

    view._evaluate_survey()
    view._refresh_all_tabs()
    plot = _plot(view)
    ev_after = view.survey_evaluation()
    _grab(view, OUT_DIR / "04_after_add_to_excluded.png")

    if ev_after is None or not ev_after.accepted:
        failures.append("expected PASS after excluding peak via selection")

    flags = flag_map_for_kind([diff_set], SPECS, "radial", {"070": excluded_text})
    flagged = {sp for bucket in flags.values() for sp in bucket}
    flagged_in_excluded = flagged & excluded_set
    if flagged_in_excluded:
        failures.append(
            f"flags on excluded SPs after menu action: {sorted(flagged_in_excluded)[:8]}"
        )

    # --- ctrl toggle on fresh selection ---
    plot = _plot(view)
    if plot is None:
        failures.append("plot missing for ctrl toggle test")
    else:
        plot.clear_shotpoint_selection()
        plot._set_selected_keys([(1459, "G01")], replace=True)
        plot._toggle_selected_key((1459, "G01"), 1459.0, 12.1)
        if (1459, "G01") in plot._selected:
            failures.append("ctrl toggle failed to deselect SP1459")
        plot._toggle_selected_key((1459, "G01"), 1459.0, 12.1)
        if (1459, "G01") not in plot._selected:
            failures.append("ctrl toggle failed to re-add SP1459")
        _grab(view, OUT_DIR / "05_after_ctrl_toggle.png")

    # --- oracle: pick_points_in_rect ---
    plot = _plot(view)
    if plot is not None:
        oracle_keys = pick_points_in_rect(plot._pick_points, 1458, 7, 1484, 22)
        if len({sp for sp, _src in oracle_keys}) < 20:
            failures.append(f"oracle rect pick too small: {len(oracle_keys)}")

    if pg.getConfigOption("useOpenGL"):
        failures.append("plot must use CPU raster (useOpenGL=False)")

    return _report(failures)


if __name__ == "__main__":
    raise SystemExit(main())
