"""Visual QA for packed-sequence aerial heatmaps (no empty sequence slots)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from xpostmaps.core.database import Database
from xpostmaps.core.postplot_4d_matching import build_postplot_4d_rows
from xpostmaps.core.postplot_4d_survey_plots_worker import SurveyPlotsLoadWorker
from xpostmaps.ui.postplot_4d_survey_plots.aerial_heatmap_canvas import AerialHeatmapCanvas

OUT = ROOT / "data" / "pdf_qa"
CASES = [
    ("4030", ROOT / "data" / "4030_4D.db", "4030_4D", "navplan", "radial"),
    ("7027", ROOT / "data" / "7027.db", "7027", "preplot", "radial"),
]


def _is_white(color: QColor, *, threshold: int = 248) -> bool:
    return (
        color.red() >= threshold
        and color.green() >= threshold
        and color.blue() >= threshold
    )


def _sample_region(image, x0: int, x1: int, y0: int, y1: int, step: int = 4) -> tuple[int, int]:
    colored = 0
    total = 0
    for y in range(y0, y1, step):
        for x in range(x0, x1, step):
            total += 1
            if not _is_white(image.pixelColor(x, y)):
                colored += 1
    return colored, total


def _load_result(db_path: Path, project: str, baseline: str):
    db = Database(db_path)
    settings, map_data = db.load_project(project, with_positions=False)
    matched = [
        row
        for row in build_postplot_4d_rows(map_data, settings, baseline)
        if row.has_match
    ]
    result_box: list = []
    worker = SurveyPlotsLoadWorker(db_path, project, baseline, matched)
    worker.finished_ok.connect(
        lambda result: result_box.append(result),
        Qt.ConnectionType.DirectConnection,
    )
    worker.start()
    worker.wait()
    return result_box[0]


def main() -> int:
    app = QApplication([])
    OUT.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []

    for label, db_path, project, baseline, preferred_kind in CASES:
        if not db_path.is_file():
            print(f"[{label}] SKIP — missing database")
            continue
        result = _load_result(db_path, project, baseline)
        kind = preferred_kind if preferred_kind in result.available_kinds else result.available_kinds[0]
        heatmap = result.heatmap_cache.get(kind)
        if heatmap is None:
            failures.append(f"{label}: no heatmap for {kind}")
            continue

        canvas = AerialHeatmapCanvas()
        n_cols = heatmap.image.shape[1]
        seq_span = heatmap.sequence_max - heatmap.sequence_min + 1
        if n_cols >= seq_span:
            failures.append(
                f"{label}: grid still uses sequence-number span ({n_cols} cols >= {seq_span})"
            )
        canvas.resize(max(1400, n_cols * 4), 900)
        canvas.show()
        canvas.render(heatmap)
        app.processEvents()

        image = canvas.capture_image(width=2400, height=900)
        path = OUT / f"aerial_{label}_{kind}_packed.png"
        image.save(str(path))

        width = image.width()
        height = image.height()
        plot_right = max(1, width - 100)
        plot_colored, plot_total = _sample_region(image, 40, plot_right, 80, height - 40)
        bar_colored, bar_total = _sample_region(image, plot_right, width - 4, 80, height - 40)
        plot_ratio = plot_colored / max(1, plot_total)
        bar_ratio = bar_colored / max(1, bar_total)

        ok_packed = n_cols < seq_span
        ok_plot = plot_colored > 20 and plot_ratio >= 0.25
        ok_bar = bar_colored > 5 and bar_ratio >= 0.15
        ok = ok_packed and ok_plot and ok_bar
        print(
            f"[{label}] {kind} cols={n_cols} seq_span={seq_span} "
            f"labels={heatmap.sequence_labels[0]}..{heatmap.sequence_labels[-1]} "
            f"plot={plot_ratio:.0%} bar={bar_ratio:.0%} "
            f"{'OK' if ok else 'FAIL'} -> {path.name}"
        )
        if not ok_packed:
            failures.append(f"{label}: not packed (cols={n_cols}, span={seq_span})")
        if not ok_plot:
            failures.append(f"{label}: plot area too sparse")
        if not ok_bar:
            failures.append(f"{label}: color legend missing")

    if failures:
        print("FAILURES:")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("All packed heatmap visual checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
