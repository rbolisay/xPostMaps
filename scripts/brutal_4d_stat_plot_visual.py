"""Brutal visual test for 4D Stat Plot rendering."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from xpostmaps.core.postplot_4d_diff import Postplot4DDiffRow  # noqa: E402
from xpostmaps.core.postplot_4d_matching import Postplot4DMatchRow  # noqa: E402
from xpostmaps.core.postplot_4d_plot_data import BoundaryRow  # noqa: E402
from xpostmaps.ui.postplot_4d_stat_plot.plot_view import Postplot4DStatPlotView  # noqa: E402

OUT_DIR = ROOT / "data" / "brutal_4d_stat_plot"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _make_rows() -> tuple[Postplot4DMatchRow, list[Postplot4DDiffRow]]:
    match = Postplot4DMatchRow(
        baseline_name="1065P1A",
        baseline_kind="navplan",
        line_name="1065P1A",
        subline="070",
        sequence_no="070",
        first_sp=1000,
        last_sp=1040,
        line_direction="Up-line",
        sequence_id="70.1065P1A-070.a070.p190|070|1065P1A",
    )
    rows: list[Postplot4DDiffRow] = []
    for sp in range(1000, 1041):
        for source_id, offset in (("001", -1.0), ("002", 1.5)):
            cross = float(np.sin((sp - 1000) / 4.0) * 8.0 + offset * 2.0)
            rows.append(
                Postplot4DDiffRow(
                    shotpoint=sp,
                    baseline_x=0.0,
                    baseline_y=0.0,
                    baseline_latitude="",
                    baseline_longitude="",
                    source_x=0.0,
                    source_y=0.0,
                    source_latitude="",
                    source_longitude="",
                    crossline_m=cross,
                    inline_m=cross * 0.3,
                    radial_m=abs(cross),
                    firing_source_id=source_id,
                )
            )
    return match, rows


def _non_white_fraction(image: QImage) -> float:
    width = image.width()
    height = image.height()
    if width <= 0 or height <= 0:
        return 0.0
    non_white = 0
    total = width * height
    for y in range(0, height, 2):
        for x in range(0, width, 2):
            color = image.pixelColor(x, y)
            if color.red() < 250 or color.green() < 250 or color.blue() < 250:
                non_white += 1
    sampled = ((width + 1) // 2) * ((height + 1) // 2)
    return non_white / max(sampled, 1)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    match, diff_rows = _make_rows()
    view = Postplot4DStatPlotView()
    view.resize(1200, 900)
    view.set_data(match, diff_rows, streamers_detected=False)
    view._tab_controls["crossline"].set_boundaries(
        [BoundaryRow(abs_boundary=5.0), BoundaryRow(abs_boundary=9.0)]
    )
    view.show()

    failures: list[str] = []

    def _verify() -> None:
        combined_h = 0
        canvas = view.canvas_for_kind("crossline")
        if canvas is None:
            failures.append("crossline canvas missing")
        elif not canvas.has_data():
            failures.append("crossline canvas has no curve items")
        else:
            image = canvas.capture_image(width=900, height=420)
            out_path = OUT_DIR / "crossline_combined.png"
            image.save(str(out_path))
            fraction = _non_white_fraction(image)
            print(f"crossline capture: {out_path} non-white fraction={fraction:.3f}")
            if fraction < 0.005:
                failures.append(f"crossline plot appears blank (non-white={fraction:.4f})")
            # Spot-check boundary rows near y=+5 / -5 in image space (center ~y=0).
            h = image.height()
            w = image.width()
            mid_x = w // 2
            # Sample a few rows; boundaries should appear as thin blue pixels, not fat bars.
            row_at_plus5 = int(h * 0.38)
            row_at_minus5 = int(h * 0.62)
            plus5 = image.pixelColor(mid_x, row_at_plus5)
            minus5 = image.pixelColor(mid_x, row_at_minus5)
            print(f"  sample +5 band blue={plus5.blue()}, -5 band blue={minus5.blue()}")
            if plus5.blue() < 80 and minus5.blue() < 80:
                failures.append("boundary lines at ±5 not visible in capture")
            combined_h = 0
            if canvas._combined_plot is not None:
                combined_h = canvas._combined_plot.height()

        view._combine_box.setChecked(False)
        view._on_combine_changed(False)
        canvas = view.canvas_for_kind("inline")
        if canvas is None or not canvas.has_data():
            failures.append("inline individual canvas missing data")
        else:
            source_tabs = canvas._source_tabs
            if source_tabs is not None:
                plot_count = len(source_tabs.all_plots())
                print(f"  source tab count={plot_count}")
                if plot_count < 2:
                    failures.append(f"expected 2 source tabs, got {plot_count}")
                if combined_h > 0 and source_tabs.all_plots():
                    ind_h = source_tabs.all_plots()[0].height()
                    print(f"  combined plot height={combined_h}, individual plot height={ind_h}")
                    if abs(ind_h - combined_h) > 80:
                        failures.append(
                            f"individual plot height {ind_h} != combined {combined_h}"
                        )
            image = canvas.capture_image(width=900, height=620)
            out_path = OUT_DIR / "inline_individual.png"
            image.save(str(out_path))
            fraction = _non_white_fraction(image)
            print(f"inline capture: {out_path} non-white fraction={fraction:.3f}")
            if fraction < 0.005:
                failures.append(f"inline plot appears blank (non-white={fraction:.4f})")

        if failures:
            print("BRUTAL 4D STAT PLOT VISUAL: FAIL")
            for item in failures:
                print(f"  - {item}")
            app.quit()
            sys.exit(1)

        print("BRUTAL 4D STAT PLOT VISUAL: PASS")
        app.quit()

    QTimer.singleShot(400, _verify)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
