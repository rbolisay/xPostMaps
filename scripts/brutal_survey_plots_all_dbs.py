"""Brutal Survey Plots audit: axes, statistics, all plot visuals, PDF preview + export."""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from xpostmaps.core.database import Database  # noqa: E402
from xpostmaps.core.postplot_4d_matching import build_postplot_4d_rows  # noqa: E402
from xpostmaps.core.postplot_4d_survey_plot_pdf import (  # noqa: E402
    Postplot4DSurveyPlotPdfOptions,
    compose_survey_plot_pages,
    export_survey_plot_pdf,
    iter_survey_plot_page_specs,
    render_survey_plot_preview_pages,
)
from xpostmaps.core.postplot_4d_survey_plot_data import (  # noqa: E402
    combined_survey_extent,
    validate_aerial_heatmap_axes,
    validate_histogram_sample_count,
    validate_pie_chart_stats,
)
from xpostmaps.core.postplot_4d_survey_plots_worker import SurveyPlotsLoadWorker  # noqa: E402
from xpostmaps.ui.postplot_4d_survey_plots.survey_plots_view import (  # noqa: E402
    Postplot4DSurveyPlotsView,
)

OUT_ROOT = ROOT / "data" / "brutal_survey_plots_all"
OUT_ROOT.mkdir(parents=True, exist_ok=True)

PDF_DPI = 150
PREVIEW_DPI = 96
MIN_PAGE_BYTES = 8_000
MIN_COLORED_SAMPLES = 15
MIN_COLORBAR_SAMPLES = 5


@dataclass(frozen=True)
class DbCase:
    label: str
    db_path: Path
    project: str
    baseline: str


CASES = [
    DbCase("10221", ROOT / "data" / "10221.db", "10221", "navplan"),
    DbCase("4030", ROOT / "data" / "4030_4D.db", "4030_4D", "navplan"),
    DbCase("7027", ROOT / "data" / "7027.db", "7027", "preplot"),
]


def _save_png(image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(path))


def _is_white(color: QColor, *, threshold: int = 248) -> bool:
    return (
        color.red() >= threshold
        and color.green() >= threshold
        and color.blue() >= threshold
    )


def _sample_colored(image, x0: int, x1: int, y0: int, y1: int, step: int = 6) -> int:
    colored = 0
    for y in range(y0, y1, step):
        for x in range(x0, x1, step):
            if not _is_white(image.pixelColor(x, y)):
                colored += 1
    return colored


def _assert_visual_image(image, *, label: str, require_colorbar: bool = False) -> list[str]:
    errors: list[str] = []
    if image.isNull() or image.width() < 200 or image.height() < 120:
        errors.append(f"{label}: image too small or null")
        return errors
    width = image.width()
    height = image.height()
    plot_colored = _sample_colored(image, 40, max(41, width - 100), 40, height - 40)
    if plot_colored < MIN_COLORED_SAMPLES:
        errors.append(f"{label}: plot area appears blank ({plot_colored} colored samples)")
    if require_colorbar:
        bar_colored = _sample_colored(image, max(0, width - 80), width - 2, 40, height - 40)
        if bar_colored < MIN_COLORBAR_SAMPLES:
            errors.append(f"{label}: color legend appears missing ({bar_colored} samples)")
    return errors


def _validate_load_result(result, extent) -> list[str]:
    errors: list[str] = []
    if result.sequence_count != extent.sequence_count:
        errors.append(
            f"sequence_count {result.sequence_count} != {extent.sequence_count}"
        )
    if result.shotpoint_count != extent.shotpoint_row_count:
        errors.append(
            f"shotpoint_count {result.shotpoint_count:,} "
            f"!= {extent.shotpoint_row_count:,}"
        )
    for kind, heatmap in result.heatmap_cache.items():
        errors.extend(
            f"aerial:{kind}: {msg}"
            for msg in validate_aerial_heatmap_axes(heatmap, extent)
        )
    for kind, histogram in result.histogram_cache.items():
        values = result.metric_values.get(kind, [])
        errors.extend(
            f"histogram:{kind}: {msg}"
            for msg in validate_histogram_sample_count(histogram, values)
        )
    for index, chart in enumerate(result.pie_charts):
        errors.extend(
            f"pie:{index}: {msg}" for msg in validate_pie_chart_stats(chart)
        )
    return errors


def _capture_all_ui_plots(view: Postplot4DSurveyPlotsView, out_dir: Path) -> list[str]:
    saved: list[str] = []
    app = QApplication.instance()
    kinds = view.available_plot_kinds()

    for kind in kinds:
        panel = view._metric_panels[kind]
        if kind in view.heatmap_cache():
            view._tabs.setCurrentIndex(view._tabs.indexOf(panel))
            panel.sub_tabs.setCurrentWidget(panel._aerial_page)
            view._rendered_keys.discard(f"aerial:{kind}")
            view.refresh_current_tab()
            app.processEvents()
            aerial = view.aerial_canvas(kind)
            if aerial is not None:
                path = out_dir / f"ui_aerial_{kind}.png"
                _save_png(aerial.capture_image(width=1400, height=900), path)
                saved.append(path.name)

        if kind in view.histogram_cache():
            view._tabs.setCurrentIndex(view._tabs.indexOf(panel))
            panel.sub_tabs.setCurrentWidget(panel._histogram_page)
            view._rendered_keys.discard(f"histogram:{kind}")
            view.refresh_current_tab()
            app.processEvents()
            hist = view.histogram_canvas(kind)
            if hist is not None:
                path = out_dir / f"ui_histogram_{kind}.png"
                _save_png(
                    hist.capture_image(
                        width=1400,
                        height=700,
                        title=panel._histogram_page._title.text(),
                    ),
                    path,
                )
                saved.append(path.name)

    charts = view.pie_charts()
    if charts:
        view._tabs.setCurrentIndex(view._tabs.indexOf(view._pie_panel))
        view._rendered_keys.discard("pie")
        view.refresh_current_tab()
        app.processEvents()
        for index in range(len(charts)):
            view.pie_panel().select_page(index)
            app.processEvents()
            path = out_dir / f"ui_pie_{index:02d}.png"
            _save_png(
                view.pie_panel().capture_page_image(index, width=1200, height=800),
                path,
            )
            saved.append(path.name)

    return saved


def _validate_ui_pngs(out_dir: Path, kinds: list[str], pie_count: int) -> list[str]:
    errors: list[str] = []
    for kind in kinds:
        aerial_path = out_dir / f"ui_aerial_{kind}.png"
        if aerial_path.is_file():
            from PySide6.QtGui import QImage

            image = QImage(str(aerial_path))
            errors.extend(
                _assert_visual_image(
                    image,
                    label=f"ui_aerial_{kind}",
                    require_colorbar=True,
                )
            )
        hist_path = out_dir / f"ui_histogram_{kind}.png"
        if hist_path.is_file():
            from PySide6.QtGui import QImage

            image = QImage(str(hist_path))
            errors.extend(_assert_visual_image(image, label=f"ui_histogram_{kind}"))
    for index in range(pie_count):
        pie_path = out_dir / f"ui_pie_{index:02d}.png"
        if pie_path.is_file():
            from PySide6.QtGui import QImage

            image = QImage(str(pie_path))
            errors.extend(_assert_visual_image(image, label=f"ui_pie_{index:02d}"))
    return errors


def run_case(case: DbCase) -> dict[str, object]:
    out_dir = OUT_ROOT / case.label
    out_dir.mkdir(parents=True, exist_ok=True)
    result_info: dict[str, object] = {"label": case.label, "ok": False, "errors": []}

    if not case.db_path.is_file():
        result_info["error"] = f"Missing {case.db_path}"
        print(f"[{case.label}] SKIP — database not found")
        return result_info

    app = QApplication.instance() or QApplication(sys.argv)
    db = Database(case.db_path)
    settings, map_data = db.load_project(case.project, with_positions=False)
    matched = [
        row
        for row in build_postplot_4d_rows(map_data, settings, case.baseline)
        if row.has_match
    ]
    print(f"[{case.label}] matched rows: {len(matched)} baseline={case.baseline}")

    worker = SurveyPlotsLoadWorker(
        case.db_path,
        case.project,
        case.baseline,
        matched,
    )
    result_box: list = []
    errors: list[str] = []

    worker.finished_ok.connect(
        lambda result: result_box.append(result),
        Qt.ConnectionType.DirectConnection,
    )
    worker.finished_failed.connect(
        lambda message: errors.append(message),
        Qt.ConnectionType.DirectConnection,
    )

    t0 = time.perf_counter()
    worker.start()
    worker.wait()
    app.processEvents()
    load_s = time.perf_counter() - t0

    if errors:
        result_info["error"] = errors[0]
        print(f"[{case.label}] LOAD FAILED: {errors[0]}")
        return result_info
    if not result_box:
        result_info["error"] = "No load result"
        print(f"[{case.label}] LOAD FAILED: empty result")
        return result_info

    result = result_box[0]
    extent = combined_survey_extent(result.sets)
    print(
        f"[{case.label}] load {load_s:.1f}s — "
        f"{result.sequence_count} seq ({extent.sequence_min}..{extent.sequence_max}), "
        f"shots {extent.shot_min}-{extent.shot_max}, "
        f"{result.shotpoint_count:,} rows, kinds={result.available_kinds}, "
        f"pies={len(result.pie_charts)}"
    )

    data_errors = _validate_load_result(result, extent)
    if data_errors:
        print(f"[{case.label}] DATA VALIDATION ERRORS:")
        for item in data_errors[:20]:
            print(f"  - {item}")
        if len(data_errors) > 20:
            print(f"  ... and {len(data_errors) - 20} more")
        result_info["errors"] = data_errors
        result_info["error"] = data_errors[0]
        return result_info

    view = Postplot4DSurveyPlotsView()
    view.resize(1400, 900)
    view.show()
    view.apply_load_result(result)
    app.processEvents()

    t0 = time.perf_counter()
    view.refresh_all()
    app.processEvents()
    render_s = time.perf_counter() - t0
    print(f"[{case.label}] render all tabs: {render_s:.2f}s")

    ui_pngs = _capture_all_ui_plots(view, out_dir)
    print(f"[{case.label}] UI previews: {len(ui_pngs)} PNGs")

    visual_errors = _validate_ui_pngs(
        out_dir,
        list(result.available_kinds),
        len(result.pie_charts),
    )
    if visual_errors:
        print(f"[{case.label}] UI VISUAL ERRORS:")
        for item in visual_errors:
            print(f"  - {item}")
        result_info["errors"] = visual_errors
        result_info["error"] = visual_errors[0]
        return result_info

    options = Postplot4DSurveyPlotPdfOptions(
        output_dir=out_dir,
        filename=f"{case.label}_survey_plots.pdf",
        dpi=PDF_DPI,
        landscape=True,
    )
    page_specs = iter_survey_plot_page_specs(view, options)
    print(f"[{case.label}] PDF pages: {len(page_specs)}")

    t0 = time.perf_counter()
    preview_pages = render_survey_plot_preview_pages(view, options)
    preview_s = time.perf_counter() - t0
    print(f"[{case.label}] PDF preview compose: {preview_s:.2f}s ({len(preview_pages)} pages)")

    preview_errors: list[str] = []
    for index, page in enumerate(preview_pages):
        png_path = out_dir / f"pdf_preview_{index + 1:02d}_{page.spec.page_key.replace(':', '_')}.png"
        page.image.save(str(png_path))
        preview_errors.extend(
            _assert_visual_image(
                page.image,
                label=f"pdf_preview_{page.spec.page_key}",
                require_colorbar=page.spec.page_kind.value == "aerial",
            )
        )
    if preview_errors:
        print(f"[{case.label}] PDF PREVIEW VISUAL ERRORS:")
        for item in preview_errors:
            print(f"  - {item}")
        result_info["errors"] = preview_errors
        result_info["error"] = preview_errors[0]
        return result_info

    t0 = time.perf_counter()
    pages = compose_survey_plot_pages(view, options, dpi=PDF_DPI)
    compose_s = time.perf_counter() - t0
    print(f"[{case.label}] PDF compose (export dpi): {compose_s:.2f}s")

    for index, page in enumerate(pages):
        png_path = out_dir / f"pdf_page_{index + 1:02d}_{page.spec.page_key.replace(':', '_')}.png"
        page.image.save(str(png_path))

    pdf_path = out_dir / options.filename
    t0 = time.perf_counter()
    export_survey_plot_pdf(view, pdf_path, options)
    pdf_s = time.perf_counter() - t0
    pdf_kb = pdf_path.stat().st_size // 1024
    print(f"[{case.label}] PDF export: {pdf_s:.2f}s -> {pdf_path.name} ({pdf_kb} KB)")

    if not pdf_path.is_file() or pdf_path.stat().st_size <= MIN_PAGE_BYTES:
        result_info["error"] = "PDF export missing or too small"
        return result_info
    if len(pages) < 3:
        result_info["error"] = f"expected >=3 PDF pages, got {len(pages)}"
        return result_info
    if len(pages) != len(page_specs):
        result_info["error"] = f"composed pages {len(pages)} != specs {len(page_specs)}"
        return result_info
    pie_pages = [page for page in pages if page.spec.page_kind.value == "pie"]
    if len(pie_pages) != len(result.pie_charts):
        result_info["error"] = (
            f"pie PDF pages {len(pie_pages)} != charts {len(result.pie_charts)}"
        )
        return result_info
    if len(preview_pages) != len(pages):
        result_info["error"] = (
            f"preview pages {len(preview_pages)} != export pages {len(pages)}"
        )
        return result_info

    result_info.update(
        {
            "ok": True,
            "load_s": load_s,
            "render_s": render_s,
            "preview_s": preview_s,
            "compose_s": compose_s,
            "pdf_s": pdf_s,
            "pages": len(pages),
            "pie_pages": len(pie_pages),
            "ui_pngs": len(ui_pngs),
            "pdf_kb": pdf_kb,
            "extent": (
                f"seq {extent.sequence_count} "
                f"({extent.sequence_min}..{extent.sequence_max}), "
                f"shots {extent.shot_min}-{extent.shot_max}, "
                f"{extent.shotpoint_row_count:,} rows"
            ),
            "out_dir": str(out_dir),
        }
    )
    print(f"[{case.label}] PASS — extent: {result_info['extent']}")
    return result_info


def main() -> int:
    print("=" * 72)
    print("BRUTAL SURVEY PLOTS AUDIT — axes, stats, UI, PDF preview, PDF export")
    print("=" * 72)
    results = [run_case(case) for case in CASES]
    print("\nSUMMARY")
    print("-" * 72)
    failed = 0
    for item in results:
        label = item["label"]
        if item.get("ok"):
            print(
                f"  {label}: PASS — {item['ui_pngs']} UI PNGs, {item['pages']} PDF pages "
                f"({item['pie_pages']} pie), load {item['load_s']:.1f}s, pdf {item['pdf_kb']} KB"
            )
            print(f"         extent: {item['extent']}")
            print(f"         -> {item['out_dir']}")
        else:
            failed += 1
            err = item.get("error", "unknown")
            print(f"  {label}: FAIL — {err}")
            extra = item.get("errors") or []
            if isinstance(extra, list) and len(extra) > 1:
                print(f"         ({len(extra)} validation issues)")
    print("-" * 72)
    if failed:
        print(f"FAILED {failed}/{len(results)}")
        return 1
    print(f"ALL {len(results)} DATABASES PASSED")
    print(f"Visual outputs: {OUT_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
