"""Visual check: combine several 7027 sequences on one preplot and capture plots.

Loads the real 7027 project database, finds a preplot line that was acquired as
multiple sequences (continuations), combines them on the 4D Stat Plot, and saves
PNG captures of each plot kind plus a single-sequence reference.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from xpostmaps.core.database import Database  # noqa: E402
from xpostmaps.core.postplot_4d_matching import (  # noqa: E402
    build_postplot_4d_rows,
    preplot_groups,
)
from xpostmaps.core.postplot_4d_plot_data import SequenceDiffSet  # noqa: E402
from xpostmaps.ui.postplot_4d_stat_plot.plot_view import (  # noqa: E402
    Postplot4DStatPlotView,
)

DB_PATH = ROOT / "data" / "7027.db"
OUT_DIR = ROOT / "data" / "combined_7027"
OUT_DIR.mkdir(parents=True, exist_ok=True)
KINDS = ("crossline", "inline", "radial")


def main() -> int:
    if not DB_PATH.is_file():
        print(f"DB not found: {DB_PATH}")
        return 1

    db = Database(DB_PATH)
    projects = db.list_projects()
    print("projects:", projects)
    if not projects:
        print("no projects in db")
        return 1
    project_name = projects[0]
    print("using project:", project_name)

    settings, map_data = db.load_project(project_name, with_positions=False)
    rows = build_postplot_4d_rows(map_data, settings, "preplot")

    # Keep only matched sequences that actually have saved 4D Stat diffs.
    plottable = [
        row
        for row in rows
        if row.has_match
        and db.has_postplot_4d_diffs(project_name, row.baseline_kind, row.sequence_id)
    ]
    print(f"matched+saved sequences: {len(plottable)} of {len(rows)} rows")

    groups = preplot_groups(plottable)
    multi = [(name, members) for name, members in groups if len(members) >= 2]
    print(f"preplots with >=2 saved sequences: {len(multi)}")
    for name, members in multi[:10]:
        print(f"  {name}: seqs {[m.sequence_no for m in members]}")
    if not multi:
        print("No preplot has multiple saved sequences; cannot test combine.")
        return 1

    # Pick the preplot with the most sequences, cap at 4 for a readable plot.
    multi.sort(key=lambda pair: len(pair[1]), reverse=True)
    preplot_name, members = multi[0]
    members = members[:4]
    print(f"\nCombining preplot {preplot_name!r} sequences {[m.sequence_no for m in members]}")

    sets: list[SequenceDiffSet] = []
    for match_row in members:
        diff_rows = db.load_postplot_4d_diffs(
            project_name, match_row.baseline_kind, match_row.sequence_id
        )
        print(
            f"  seq {match_row.sequence_no}: line={match_row.line_name} "
            f"FSP={match_row.first_sp} LSP={match_row.last_sp} "
            f"dir={match_row.line_direction!r} rows={len(diff_rows)}"
        )
        if diff_rows:
            sets.append(SequenceDiffSet(match_row=match_row, diff_rows=diff_rows))

    if len(sets) < 2:
        print("Fewer than 2 sequences had loadable diffs.")
        return 1

    app = QApplication.instance() or QApplication(sys.argv)
    view = Postplot4DStatPlotView()
    view.resize(1400, 950)
    view.set_combined_data(sets, streamers_detected=False)
    view.show()

    def _capture() -> None:
        print(f"\ntitle: {view._title.text()}")
        styles = view.source_styles_for_kind("crossline")
        print("crossline style keys:")
        for srow in styles:
            print(f"  {srow.source_no}  color={srow.color}")
        for kind in KINDS:
            canvas = view.canvas_for_kind(kind)
            if canvas is None or not canvas.has_data():
                print(f"{kind}: NO DATA")
                continue
            image = canvas.capture_image(width=1300, height=620)
            out = OUT_DIR / f"combined_{kind}.png"
            image.save(str(out))
            print(f"{kind}: saved {out}")

        # Single-sequence reference (lowest sequence only).
        view.set_combined_data(sets[:1], streamers_detected=False)
        app.processEvents()
        canvas = view.canvas_for_kind("crossline")
        if canvas is not None and canvas.has_data():
            image = canvas.capture_image(width=1300, height=620)
            out = OUT_DIR / "single_crossline.png"
            image.save(str(out))
            print(f"single crossline: saved {out}")

        app.quit()

    QTimer.singleShot(700, _capture)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
