"""Visual QA: excluded shotpoints on 10221 / 1065P1A-070 navplan radial plot."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from xpostmaps.core.database import Database
from xpostmaps.core.postplot_4d_diff import calculate_match_diff_rows
from xpostmaps.core.postplot_4d_matching import build_postplot_4d_rows
from xpostmaps.core.postplot_4d_plot_data import SequenceDiffSet
from xpostmaps.core.postplot_4d_survey_spec import (
    Severity,
    StatType,
    SurveySpecRow,
    flag_map_for_kind,
)
from xpostmaps.ui.postplot_4d_stat_plot.plot_view import Postplot4DStatPlotView

OUT_DIR = ROOT / "data" / "brutal_10221_exclude_070"
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


def _grab(view: Postplot4DStatPlotView, path: Path) -> None:
    view.resize(1280, 820)
    view.show()
    app = QApplication.instance()
    assert app is not None
    for _ in range(3):
        app.processEvents()
    image = view.grab().toImage()
    image.save(str(path))


def main() -> int:
    app = QApplication(sys.argv)
    diff_set = _load_sequence()
    view = Postplot4DStatPlotView()
    view.set_combined_data([diff_set], streamers_detected=True)
    view._survey_panel.set_rows(SPECS)
    view._tabs.setCurrentWidget(view._tab_pages["radial"])
    view._evaluate_survey()
    view._refresh_all_tabs()
    _grab(view, OUT_DIR / "070_radial_no_exclusion.png")

    summary = view._survey_panel._summary
    edit = summary._table.cellWidget(0, summary._COL_EXCLUDED)
    if edit is not None:
        edit.setText("1481-1461")
    view._on_survey_specs_changed()
    _grab(view, OUT_DIR / "070_radial_excluded_1481-1461.png")

    flags = flag_map_for_kind(
        [diff_set], SPECS, "radial", excluded_by_sequence={"070": "1481-1461"}
    )
    print("Flagged after exclusion:")
    for source, bucket in sorted(flags.items()):
        print(f"  {source}: {dict(sorted(bucket.items()))}")

    print(f"Wrote {OUT_DIR}")
    QTimer.singleShot(0, app.quit)
    app.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
