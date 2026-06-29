"""Export a combined multi-sequence 4D Stat PDF from real 7027 data.

Verifies the PDF export works for a preplot split across several sequences in
both Combine Sources on/off modes, and that the output PDF has pages with real
plot content (not blank).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from xpostmaps.core.database import Database  # noqa: E402
from xpostmaps.core.postplot_4d_matching import (  # noqa: E402
    build_postplot_4d_rows,
    preplot_groups,
)
from xpostmaps.core.postplot_4d_plot_data import SequenceDiffSet  # noqa: E402
from xpostmaps.core.postplot_4d_plot_pdf import (  # noqa: E402
    Postplot4DStatPlotPdfOptions,
    compose_4d_stat_plot_pages,
    export_4d_stat_plot_pdf,
    iter_4d_stat_plot_page_specs,
)
from xpostmaps.ui.postplot_4d_stat_plot.plot_view import (  # noqa: E402
    Postplot4DStatPlotView,
)

DB_PATH = ROOT / "data" / "7027.db"
OUT_DIR = ROOT / "data" / "combined_7027_pdf"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _non_white(image) -> float:
    w, h = image.width(), image.height()
    non = 0
    for y in range(0, h, 7):
        for x in range(0, w, 7):
            c = image.pixelColor(x, y)
            if c.red() < 250 or c.green() < 250 or c.blue() < 250:
                non += 1
    sampled = ((w + 6) // 7) * ((h + 6) // 7)
    return non / max(sampled, 1)


def main() -> int:
    db = Database(DB_PATH)
    project_name = db.list_projects()[0]
    settings, map_data = db.load_project(project_name, with_positions=False)
    rows = build_postplot_4d_rows(map_data, settings, "preplot")
    plottable = [
        r
        for r in rows
        if r.has_match
        and db.has_postplot_4d_diffs(project_name, r.baseline_kind, r.sequence_id)
    ]
    groups = [g for g in preplot_groups(plottable) if len(g[1]) >= 3]
    groups.sort(key=lambda pair: len(pair[1]), reverse=True)
    preplot_name, members = groups[0]
    members = members[:4]
    print(f"preplot {preplot_name} seqs {[m.sequence_no for m in members]}")

    sets = []
    for m in members:
        diffs = db.load_postplot_4d_diffs(project_name, m.baseline_kind, m.sequence_id)
        if diffs:
            sets.append(SequenceDiffSet(match_row=m, diff_rows=diffs))

    app = QApplication.instance() or QApplication(sys.argv)
    view = Postplot4DStatPlotView()
    view.resize(1400, 950)
    view.set_combined_data(sets, streamers_detected=False)
    app.processEvents()

    failures: list[str] = []
    for combine in (True, False):
        view._combine_box.setChecked(combine)
        view._on_combine_changed(combine)
        app.processEvents()
        tag = "combine" if combine else "uncombined"
        options = Postplot4DStatPlotPdfOptions(
            output_dir=OUT_DIR,
            filename=f"combined_7027_{tag}.pdf",
            include_feather=False,
            include_feather_diff=False,
        )
        specs = iter_4d_stat_plot_page_specs(view, options)
        print(f"[{tag}] page_specs={len(specs)}")

        pages = compose_4d_stat_plot_pages(view, options, dpi=120)
        print(f"[{tag}] composed pages={len(pages)}")
        if not pages:
            failures.append(f"{tag}: no pages composed")
        for i, pg in enumerate(pages):
            frac = _non_white(pg)
            pg.save(str(OUT_DIR / f"{tag}_page{i}.png"))
            if frac < 0.01:
                failures.append(f"{tag} page {i} blank ({frac:.4f})")
        print(f"[{tag}] page non-white fractions sampled; saved previews")

        out_pdf = OUT_DIR / f"combined_7027_{tag}.pdf"
        export_4d_stat_plot_pdf(view, out_pdf, options)
        size = out_pdf.stat().st_size if out_pdf.is_file() else 0
        print(f"[{tag}] PDF written {out_pdf.name} size={size}")
        if size < 5000:
            failures.append(f"{tag}: PDF too small ({size} bytes)")

    if failures:
        print("FAIL:")
        for f in failures:
            print("  -", f)
        return 1
    print("PASS: combined PDF export works in both modes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
