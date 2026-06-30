"""Visual QA for survey-wide 4D plot PDF export."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from xpostmaps.core.postplot_4d_diff import Postplot4DDiffRow  # noqa: E402
from xpostmaps.core.postplot_4d_matching import Postplot4DMatchRow  # noqa: E402
from xpostmaps.core.postplot_4d_plot_data import SequenceDiffSet  # noqa: E402
from xpostmaps.core.postplot_4d_survey_plot_data import (  # noqa: E402
    available_survey_plot_kinds,
    build_survey_aerial_heatmap_cache,
    build_survey_histogram_cache,
    build_survey_metrics_cache,
    infer_streamers_detected,
    survey_spec_pie_charts,
)
from xpostmaps.core.postplot_4d_survey_plots_worker import SurveyPlotsLoadResult  # noqa: E402
from xpostmaps.core.postplot_4d_survey_plot_pdf import (  # noqa: E402
    Postplot4DSurveyPlotPdfOptions,
    compose_survey_plot_pages,
    export_survey_plot_pdf,
)
from xpostmaps.ui.postplot_4d_survey_plots.survey_plots_view import (  # noqa: E402
    Postplot4DSurveyPlotsView,
)

OUT_DIR = ROOT / "data" / "brutal_survey_plot_pdf"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _make_rows(sequence_no: str, base_sp: int, count: int) -> SequenceDiffSet:
    match = Postplot4DMatchRow(
        baseline_name=f"Line{sequence_no}",
        baseline_kind="navplan",
        line_name=f"Line{sequence_no}",
        subline=sequence_no,
        sequence_no=sequence_no,
        first_sp=base_sp,
        last_sp=base_sp + count - 1,
        line_direction="Up-line",
        sequence_id=f"seq-{sequence_no}",
    )
    rows: list[Postplot4DDiffRow] = []
    for index in range(count):
        sp = base_sp + index
        cross = float(np.sin(index / 5.0) * 6.0 + index * 0.05)
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
                inline_m=cross * 0.35,
                radial_m=abs(cross),
                line_feather_deg=float(index % 7),
                navplan_feather_deg=float((index + 1) % 7),
                vessel_id="G001",
                firing_source_id="001" if index % 2 == 0 else "002",
            )
        )
    return SequenceDiffSet(match_row=match, diff_rows=rows)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    sets = [_make_rows("001", 1000, 80), _make_rows("002", 2000, 60)]
    kinds = available_survey_plot_kinds(sets, streamers_detected=True)
    metric_values = build_survey_metrics_cache(sets, kinds)
    result = SurveyPlotsLoadResult(
        sets=sets,
        streamers_detected=infer_streamers_detected(sets),
        available_kinds=kinds,
        metric_values=metric_values,
        heatmap_cache=build_survey_aerial_heatmap_cache(sets, kinds),
        histogram_cache=build_survey_histogram_cache(metric_values, kinds),
        pie_charts=survey_spec_pie_charts(sets, metric_cache=metric_values),
        sequence_count=len(sets),
        shotpoint_count=sum(len(s.diff_rows) for s in sets),
    )
    view = Postplot4DSurveyPlotsView()
    view.apply_load_result(result)
    view.refresh_all()
    app.processEvents()

    options = Postplot4DSurveyPlotPdfOptions(
        output_dir=OUT_DIR,
        filename="survey_plots_brutal.pdf",
        dpi=150,
        landscape=True,
    )
    pages = compose_survey_plot_pages(view, options, dpi=150)
    for index, page in enumerate(pages):
        out_png = OUT_DIR / f"page_{index + 1:02d}_{page.spec.page_key.replace(':', '_')}.png"
        page.image.save(str(out_png))
        print(f"Wrote {out_png}")

    pdf_path = OUT_DIR / options.filename
    export_survey_plot_pdf(view, pdf_path, options)
    print(f"Wrote {pdf_path}")
    print(f"Survey view visible with {len(view.available_plot_kinds())} metric kinds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
