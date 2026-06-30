"""Survey-wide 4D plot data: aerial series, cumulative histograms, spec pies."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from xpostmaps.core.postplot_4d_plot_data import (
    PLOT_KIND_LABELS,
    PLOT_KIND_PDF_LABELS,
    PLOT_KIND_UNITS,
    PlotKind,
    SequenceDiffSet,
    feather_diff_tab_available,
    feather_tab_available,
    metric_values_for_kind,
    normalize_source_label,
    ordered_sequence_sets,
    primary_vessel_id,
    unique_sources_from_diff_rows,
)
from xpostmaps.core.postplot_4d_diff import feather_diff_deg, Postplot4DDiffRow
from xpostmaps.core.postplot_4d_plot_settings import load_survey_specs
from xpostmaps.core.postplot_4d_survey_spec import (
    Severity,
    StatType,
    SurveySpecRow,
    STAT_TYPE_LABELS,
    SEVERITY_LABELS,
    _iter_source_series,
    _shot_exceeds_metric_limit,
    evaluate_spec_combined,
    format_limit_value,
    format_statistic,
    stat_uses_reference,
)

HISTOGRAM_MAX_BUCKET = 15
AERIAL_HEATMAP_DEFAULT_LIMIT = 15.0
PIE_PASS_COLOR = "#22c55e"
PIE_FAIL_COLOR_ERROR = "#ef4444"
PIE_FAIL_COLOR_WARNING = "#f97316"
AERIAL_HEATMAP_METER_KINDS: frozenset[PlotKind] = frozenset(
    {"crossline", "inline", "radial"}
)
FEATHER_HISTOGRAM_KINDS: frozenset[PlotKind] = frozenset(
    {"feather", "feather_diff"}
)
HISTOGRAM_DEGREE_STEP = 1


@dataclass(frozen=True)
class SurveyPlotsLoadResult:
    """Fully prepared survey plot payload for the UI or PDF export."""

    sets: list[SequenceDiffSet]
    streamers_detected: bool
    available_kinds: list[PlotKind]
    metric_values: dict[PlotKind, list[float]]
    heatmap_cache: dict[PlotKind, AerialHeatmapData]
    histogram_cache: dict[PlotKind, CumulativeHistogram]
    pie_charts: list[SurveySpecPieData]
    sequence_count: int
    shotpoint_count: int


@dataclass
class AerialHeatmapData:
    """Sequence × shotpoint heatmap for one metric and primary source."""

    image: object  # np.ndarray float64, NaN = gap
    sequence_labels: list[str]
    sequence_min: int
    sequence_max: int
    shot_min: int
    shot_max: int
    value_limit: float
    source_no: str
    kind: PlotKind
    header_title: str = "Aerial View"
    survey_label: str = "Survey: Monitor"
    map_label: str = ""


@dataclass
class PieSlice:
    label: str
    value: float
    color: str


@dataclass
class SurveySpecPieStats:
    """Survey-wide shotpoint summary for one spec pie chart."""

    total_shotpoints: int
    pass_count: int
    fail_count: int
    pass_pct: float
    fail_pct: float
    average: float | None
    maximum: float | None
    minimum: float | None
    unit: str


@dataclass
class SurveySpecPieData:
    spec: SurveySpecRow
    headline: str
    title: str
    tab_label: str
    slices: list[PieSlice] = field(default_factory=list)
    subtitle: str = ""
    stats: SurveySpecPieStats | None = None
    spec_passed: bool = True
    fail_color: str = PIE_FAIL_COLOR_ERROR
    severity: Severity = Severity.ERROR


@dataclass
class CumulativeHistogram:
    """Cumulative percentage histogram for survey-wide metrics."""

    bucket_labels: list[str]
    cumulative_pct: list[float]
    sample_count: int
    x_axis_unit: str = "meter"
    x_positions: list[float] | None = None


@dataclass(frozen=True)
class CombinedSurveyExtent:
    """Combined x/y extent for survey-wide plots across all sequences."""

    sequence_labels: list[str]
    sequence_min: int
    sequence_max: int
    shot_min: int
    shot_max: int
    sequence_count: int
    shotpoint_row_count: int


def parse_sequence_number(label: str, *, fallback: int = 0) -> int:
    """Parse a sequence label to its numeric axis value."""
    text = (label or "").strip()
    if not text:
        return fallback
    try:
        return int(text)
    except ValueError:
        digits = "".join(character for character in text if character.isdigit())
        if digits:
            return int(digits)
        return fallback


def combined_survey_extent(sets: list[SequenceDiffSet]) -> CombinedSurveyExtent:
    """Shot and sequence bounds aggregated across every loaded sequence."""
    ordered = ordered_sequence_sets(sets)
    sequence_labels = [item.match_row.sequence_no for item in ordered]
    sequence_numbers = [
        parse_sequence_number(label, fallback=index)
        for index, label in enumerate(sequence_labels)
    ]
    shots: set[int] = set()
    row_count = 0
    for item in ordered:
        row_count += len(item.diff_rows)
        for row in item.diff_rows:
            if row.shotpoint > 0:
                shots.add(int(row.shotpoint))
    if not sequence_numbers:
        return CombinedSurveyExtent(
            sequence_labels=sequence_labels,
            sequence_min=0,
            sequence_max=0,
            shot_min=0,
            shot_max=0,
            sequence_count=0,
            shotpoint_row_count=row_count,
        )
    if not shots:
        return CombinedSurveyExtent(
            sequence_labels=sequence_labels,
            sequence_min=min(sequence_numbers),
            sequence_max=max(sequence_numbers),
            shot_min=0,
            shot_max=0,
            sequence_count=len(sequence_labels),
            shotpoint_row_count=row_count,
        )
    return CombinedSurveyExtent(
        sequence_labels=sequence_labels,
        sequence_min=min(sequence_numbers),
        sequence_max=max(sequence_numbers),
        shot_min=min(shots),
        shot_max=max(shots),
        sequence_count=len(sequence_labels),
        shotpoint_row_count=row_count,
    )


def validate_aerial_heatmap_axes(
    heatmap: AerialHeatmapData,
    extent: CombinedSurveyExtent,
) -> list[str]:
    """Return human-readable errors when heatmap axes do not match combined survey data."""
    errors: list[str] = []
    grid = np.asarray(heatmap.image)
    expected_rows = extent.shot_max - extent.shot_min + 1 if extent.shot_max >= extent.shot_min else 0
    expected_cols = extent.sequence_count
    if heatmap.sequence_labels != extent.sequence_labels:
        errors.append(
            "sequence_labels mismatch: "
            f"heatmap={len(heatmap.sequence_labels)} extent={len(extent.sequence_labels)}"
        )
    if heatmap.shot_min != extent.shot_min:
        errors.append(f"shot_min {heatmap.shot_min} != expected {extent.shot_min}")
    if heatmap.shot_max != extent.shot_max:
        errors.append(f"shot_max {heatmap.shot_max} != expected {extent.shot_max}")
    if grid.shape != (expected_rows, expected_cols):
        errors.append(
            f"grid shape {grid.shape} != expected ({expected_rows}, {expected_cols})"
        )
    return errors


def validate_histogram_sample_count(
    histogram: CumulativeHistogram,
    values: list[float],
) -> list[str]:
    errors: list[str] = []
    if histogram.x_axis_unit == "degrees":
        expected = sum(1 for value in values if math.isfinite(float(value)))
    else:
        expected = len(values)
    if histogram.sample_count != expected:
        errors.append(
            f"histogram sample_count {histogram.sample_count} != values {expected}"
        )
    if histogram.cumulative_pct and histogram.sample_count > 0:
        if abs(histogram.cumulative_pct[-1] - 100.0) > 0.05:
            errors.append(
                f"histogram cumulative_pct ends at {histogram.cumulative_pct[-1]}, not 100%"
            )
    return errors


def validate_pie_chart_stats(chart: SurveySpecPieData) -> list[str]:
    errors: list[str] = []
    if chart.stats is None:
        return ["pie chart missing stats"]
    stats = chart.stats
    if stats.pass_count + stats.fail_count != stats.total_shotpoints:
        errors.append(
            f"pie pass+fail {stats.pass_count}+{stats.fail_count} "
            f"!= total {stats.total_shotpoints}"
        )
    if stats.total_shotpoints and abs(stats.pass_pct + stats.fail_pct - 100.0) > 0.05:
        errors.append(
            f"pie percentages {stats.pass_pct}+{stats.fail_pct} != 100"
        )
    if chart.slices:
        slice_total = sum(slice_.value for slice_ in chart.slices)
        if abs(slice_total - 100.0) > 0.05:
            errors.append(f"pie slice values sum to {slice_total}, not 100")
    return errors


def infer_streamers_detected(sets: list[SequenceDiffSet]) -> bool:
    """Infer streamer survey from saved diff rows — no source-file probing."""
    if not sets:
        return False
    all_rows = [row for item in sets for row in item.diff_rows]
    if any(row.line_feather_deg is not None for row in all_rows):
        return True
    return any(row.navplan_feather_deg is not None for row in all_rows)


def _kind_has_plottable_values(sets: list[SequenceDiffSet], kind: PlotKind) -> bool:
    for item in sets:
        if metric_values_for_kind(item.diff_rows, kind):
            return True
    return False


def build_survey_metrics_cache(
    sets: list[SequenceDiffSet],
    kinds: list[PlotKind],
) -> dict[PlotKind, list[float]]:
    """Precompute flat metric value lists for histogram / spec evaluation."""
    cache: dict[PlotKind, list[float]] = {}
    for kind in kinds:
        values: list[float] = []
        for item in sets:
            values.extend(metric_values_for_kind(item.diff_rows, kind))
        cache[kind] = values
    return cache


def _metric_at_row(row: Postplot4DDiffRow, kind: PlotKind) -> float | None:
    if kind == "crossline":
        return float(row.crossline_m)
    if kind == "inline":
        return float(row.inline_m)
    if kind == "radial":
        return float(row.radial_m)
    if kind == "feather":
        return None if row.line_feather_deg is None else float(row.line_feather_deg)
    if kind == "feather_diff":
        return feather_diff_deg(
            line_feather_deg=row.line_feather_deg,
            navplan_feather_deg=row.navplan_feather_deg,
        )
    return None


def _primary_survey_source(sets: list[SequenceDiffSet]) -> str:
    for item in sets:
        for source_no in unique_sources_from_diff_rows(item.diff_rows):
            if source_no in ("G01", "G001"):
                return source_no
    for item in sets:
        sources = unique_sources_from_diff_rows(item.diff_rows)
        if sources:
            return sources[0]
    return "G01"


def _survey_source_label_list(sets: list[SequenceDiffSet]) -> str:
    """Comma-separated G01, G02, … labels present in the survey."""
    labels: list[str] = []
    for item in sets:
        for source_no in unique_sources_from_diff_rows(item.diff_rows):
            if source_no not in labels:
                labels.append(source_no)
    return ", ".join(labels) if labels else "G01"


def aerial_map_label(sets: list[SequenceDiffSet], kind: PlotKind) -> str:
    metric_name = PLOT_KIND_LABELS[kind]
    unit = PLOT_KIND_UNITS[kind]
    sources = _survey_source_label_list(sets)
    return (
        f"Areal Map: Position {metric_name} [{unit}] for {sources} "
        "vs. Baseline (absolute values)"
    )


def _heatmap_value_limit(values: np.ndarray, kind: PlotKind) -> float:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return AERIAL_HEATMAP_DEFAULT_LIMIT
    abs_vals = np.abs(finite)
    peak = float(np.percentile(abs_vals, 95))
    if kind in AERIAL_HEATMAP_METER_KINDS:
        return max(AERIAL_HEATMAP_DEFAULT_LIMIT, min(peak * 1.05, 30.0))
    return max(5.0, min(peak * 1.05, 30.0))


def _aerial_heatmap_column_fill_mask(grid: np.ndarray) -> np.ndarray:
    """True where vertical gap-fill is allowed (between shots with data in each column)."""
    work = np.asarray(grid)
    n_rows, n_cols = work.shape
    mask = np.zeros((n_rows, n_cols), dtype=bool)
    for col in range(n_cols):
        rows = np.flatnonzero(np.isfinite(work[:, col]))
        if rows.size >= 2:
            mask[rows[0] : rows[-1] + 1, col] = True
        elif rows.size == 1:
            mask[rows[0], col] = True
    return mask


def _fill_masked_gaps(
    grid: np.ndarray,
    *,
    fill_mask: np.ndarray,
    shifts: tuple[tuple[int, int], ...],
) -> np.ndarray:
    out = np.asarray(grid, dtype=np.float64).copy()
    if out.size == 0 or not fill_mask.any():
        return out
    invalid = fill_mask & ~np.isfinite(out)
    if not invalid.any():
        return out
    n_rows, n_cols = out.shape
    max_passes = n_rows + n_cols + 2
    for _ in range(max_passes):
        if not invalid.any():
            break
        updated = False
        for dy, dx in shifts:
            source = np.full_like(out, np.nan)
            y_src = slice(max(0, -dy), n_rows - max(0, dy))
            y_dst = slice(max(0, dy), n_rows - max(0, -dy))
            x_src = slice(max(0, -dx), n_cols - max(0, dx))
            x_dst = slice(max(0, dx), n_cols - max(0, -dx))
            source[y_dst, x_dst] = out[y_src, x_src]
            fill_cells = invalid & np.isfinite(source)
            if fill_cells.any():
                out[fill_cells] = source[fill_cells]
                invalid = fill_mask & ~np.isfinite(out)
                updated = True
        if not updated:
            break
    return out


def fill_aerial_heatmap_gaps(grid: np.ndarray) -> np.ndarray:
    """Fill vertical shot gaps within each sequence column only."""
    work = np.asarray(grid, dtype=np.float64)
    if work.size == 0 or np.isfinite(work).all():
        return work.copy()
    if not np.isfinite(work).any():
        return work.copy()
    col_mask = _aerial_heatmap_column_fill_mask(work)
    return _fill_masked_gaps(
        work,
        fill_mask=col_mask,
        shifts=((-1, 0), (1, 0)),
    )


def build_survey_aerial_heatmap(
    sets: list[SequenceDiffSet],
    kind: PlotKind,
    *,
    source_no: str | None = None,
) -> AerialHeatmapData | None:
    """Build sequence (x) × shotpoint (y) heatmap for the primary source."""
    ordered = ordered_sequence_sets(sets)
    if not ordered:
        return None
    source = source_no or _primary_survey_source(sets)
    shots: set[int] = set()
    for item in ordered:
        for row in item.diff_rows:
            if row.shotpoint > 0:
                shots.add(int(row.shotpoint))
    if not shots:
        return None
    shot_min = min(shots)
    shot_max = max(shots)
    n_rows = shot_max - shot_min + 1
    n_cols = len(ordered)
    grid = np.full((n_rows, n_cols), np.nan, dtype=np.float64)
    sequence_labels = [item.match_row.sequence_no for item in ordered]
    sequence_numbers = [
        parse_sequence_number(label, fallback=index)
        for index, label in enumerate(sequence_labels)
    ]
    seq_min = min(sequence_numbers)
    seq_max = max(sequence_numbers)

    for col, item in enumerate(ordered):
        for row in item.diff_rows:
            label = normalize_source_label(
                row.firing_source_id,
                fallback_index=1,
            )
            if label != source:
                continue
            value = _metric_at_row(row, kind)
            if value is None:
                continue
            row_index = shot_max - int(row.shotpoint)
            grid[row_index, col] = float(value)

    if not np.isfinite(grid).any():
        return None

    value_limit = _heatmap_value_limit(grid, kind)
    map_label = aerial_map_label(sets, kind)
    return AerialHeatmapData(
        image=grid,
        sequence_labels=sequence_labels,
        sequence_min=seq_min,
        sequence_max=seq_max,
        shot_min=shot_min,
        shot_max=shot_max,
        value_limit=value_limit,
        source_no=source,
        kind=kind,
        survey_label="",
        map_label=map_label,
    )


def build_survey_aerial_heatmap_cache(
    sets: list[SequenceDiffSet],
    kinds: list[PlotKind],
) -> dict[PlotKind, AerialHeatmapData]:
    cache: dict[PlotKind, AerialHeatmapData] = {}
    for kind in kinds:
        built = build_survey_aerial_heatmap(sets, kind)
        if built is not None:
            cache[kind] = built
    return cache


def build_survey_histogram_cache(
    metric_values: dict[PlotKind, list[float]],
    kinds: list[PlotKind],
) -> dict[PlotKind, CumulativeHistogram]:
    cache: dict[PlotKind, CumulativeHistogram] = {}
    for kind in kinds:
        if kind not in metric_values:
            continue
        values = metric_values[kind]
        if kind in FEATHER_HISTOGRAM_KINDS:
            cache[kind] = cumulative_histogram_degrees(values)
        else:
            cache[kind] = cumulative_histogram(values)
    return cache


def survey_metric_values(
    sets: list[SequenceDiffSet],
    kind: PlotKind,
    *,
    excluded_map: dict[str, str] | None = None,
    cache: dict[PlotKind, list[float]] | None = None,
) -> list[float]:
    """Flat metric values for all sources/lines (respecting exclusions)."""
    if excluded_map:
        values: list[float] = []
        for _sequence_no, _source_no, _shotpoints, series_values in _iter_source_series(
            sets, kind, excluded_map
        ):
            values.extend(float(value) for value in series_values)
        return values
    if cache is not None and kind in cache:
        return cache[kind]
    values: list[float] = []
    for item in sets:
        values.extend(metric_values_for_kind(item.diff_rows, kind))
    return values


def cumulative_histogram(
    values: list[float],
    *,
    max_bucket: int = HISTOGRAM_MAX_BUCKET,
) -> CumulativeHistogram:
    """Build cumulative % histogram for absolute metric values."""
    abs_vals = [abs(float(value)) for value in values]
    count = len(abs_vals)
    labels: list[str] = [str(index) for index in range(max_bucket + 1)]
    labels.append(f">{max_bucket}")
    if count == 0:
        return CumulativeHistogram(
            bucket_labels=labels,
            cumulative_pct=[0.0] * len(labels),
            sample_count=0,
        )
    cumulative: list[float] = []
    for upper in range(1, max_bucket + 2):
        hits = sum(1 for value in abs_vals if value <= float(upper))
        cumulative.append(100.0 * hits / count)
    cumulative.append(100.0)
    return CumulativeHistogram(
        bucket_labels=labels,
        cumulative_pct=cumulative,
        sample_count=count,
    )


def _degree_axis_bounds(
    min_value: float,
    max_value: float,
    *,
    step: int = HISTOGRAM_DEGREE_STEP,
) -> tuple[int, int]:
    """Round signed feather limits outward to whole-degree multiples."""
    axis_min = int(math.floor(min_value / step) * step)
    axis_max = int(math.ceil(max_value / step) * step)
    if axis_min >= axis_max:
        axis_max = axis_min + step
    return axis_min, axis_max


def cumulative_histogram_degrees(
    values: list[float],
    *,
    step: int = HISTOGRAM_DEGREE_STEP,
) -> CumulativeHistogram:
    """Cumulative % histogram with signed degree x-axis (negative to positive)."""
    signed = [float(value) for value in values if math.isfinite(float(value))]
    count = len(signed)
    if count == 0:
        axis_min, axis_max = -step, step
        ticks = list(range(axis_min, axis_max + 1, step))
        labels = [str(tick) for tick in ticks]
        return CumulativeHistogram(
            bucket_labels=labels,
            cumulative_pct=[0.0] * len(labels),
            sample_count=0,
            x_axis_unit="degrees",
            x_positions=[float(tick) for tick in ticks],
        )

    axis_min, axis_max = _degree_axis_bounds(min(signed), max(signed), step=step)
    ticks = list(range(axis_min, axis_max + 1, step))
    labels = [str(tick) for tick in ticks]
    cumulative: list[float] = []
    for upper in ticks:
        hits = sum(1 for value in signed if value <= float(upper))
        cumulative.append(100.0 * hits / count)
    return CumulativeHistogram(
        bucket_labels=labels,
        cumulative_pct=cumulative,
        sample_count=count,
        x_axis_unit="degrees",
        x_positions=[float(tick) for tick in ticks],
    )


def _fast_computed_statistic(
    spec: SurveySpecRow,
    values: list[float],
) -> float | None:
    """Cheap survey-wide statistic from precomputed metric values."""
    if not values:
        return None
    if spec.statistic == StatType.AVERAGE:
        adjusted = _apply_absolute(values, spec.absolute) if spec.absolute else values
        return sum(adjusted) / len(adjusted)
    if spec.statistic == StatType.MAX_VALUE:
        adjusted = [abs(float(value)) for value in values] if spec.absolute else values
        return max(float(value) for value in adjusted)
    if spec.statistic == StatType.MAX_PCT_FAILURE:
        fails = sum(
            1
            for value in values
            if _shot_exceeds_metric_limit(float(value), spec.reference_value)
        )
        return 100.0 * fails / len(values)
    return None


def _apply_absolute(values: list[float], absolute: bool) -> list[float]:
    if not absolute:
        return list(values)
    return [abs(float(value)) for value in values]


def _pie_stat_short_label(statistic: StatType) -> str:
    return {
        StatType.AVERAGE: "Average",
        StatType.MAX_VALUE: "Max Value",
        StatType.MAX_PCT_FAILURE: "Max Pct Failure",
        StatType.MAX_CONSECUTIVE_FAILED: "Max Consecutive Failed",
    }[statistic]


def _shot_fails_spec(value: float, spec: SurveySpecRow) -> bool:
    if spec.statistic == StatType.MAX_VALUE:
        sample = abs(float(value)) if spec.absolute else float(value)
        return sample > float(spec.stat_value)
    if stat_uses_reference(spec.statistic):
        return _shot_exceeds_metric_limit(float(value), spec.reference_value)
    return False


def _metric_samples(values: list[float], spec: SurveySpecRow) -> list[float]:
    if spec.absolute:
        return [abs(float(value)) for value in values]
    return [float(value) for value in values]


def _pass_fail_counts(
    sets: list[SequenceDiffSet],
    spec: SurveySpecRow,
    excluded_map: dict[str, str],
    *,
    metric_cache: dict[PlotKind, list[float]] | None = None,
) -> tuple[int, int]:
    if spec.statistic == StatType.MAX_CONSECUTIVE_FAILED:
        pass_count = 0
        fail_count = 0
        for _sequence_no, _source_no, _shotpoints, series_values in _iter_source_series(
            sets, spec.metric, excluded_map
        ):
            for value in series_values:
                if _shot_exceeds_metric_limit(float(value), spec.reference_value):
                    fail_count += 1
                else:
                    pass_count += 1
        return pass_count, fail_count

    values = survey_metric_values(
        sets,
        spec.metric,
        excluded_map=excluded_map,
        cache=metric_cache,
    )
    pass_count = 0
    fail_count = 0
    for value in values:
        if _shot_fails_spec(float(value), spec):
            fail_count += 1
        else:
            pass_count += 1
    return pass_count, fail_count


def _build_pie_stats(
    values: list[float],
    spec: SurveySpecRow,
    pass_count: int,
    fail_count: int,
) -> SurveySpecPieStats:
    total = pass_count + fail_count
    unit = PLOT_KIND_UNITS[spec.metric]
    if not values:
        return SurveySpecPieStats(
            total_shotpoints=0,
            pass_count=0,
            fail_count=0,
            pass_pct=0.0,
            fail_pct=0.0,
            average=None,
            maximum=None,
            minimum=None,
            unit=unit,
        )
    samples = _metric_samples(values, spec)
    return SurveySpecPieStats(
        total_shotpoints=total,
        pass_count=pass_count,
        fail_count=fail_count,
        pass_pct=100.0 * pass_count / total if total else 0.0,
        fail_pct=100.0 * fail_count / total if total else 0.0,
        average=sum(samples) / len(samples),
        maximum=max(samples),
        minimum=min(samples),
        unit=unit,
    )


def _pie_fail_color(spec: SurveySpecRow) -> str:
    if spec.severity == Severity.WARNING:
        return PIE_FAIL_COLOR_WARNING
    return PIE_FAIL_COLOR_ERROR


def _pie_slices_for_spec(
    sets: list[SequenceDiffSet],
    spec: SurveySpecRow,
    excluded_map: dict[str, str],
    *,
    metric_cache: dict[PlotKind, list[float]] | None = None,
) -> list[PieSlice]:
    """Pass vs fail shotpoint counts for one survey spec row."""
    fail_color = _pie_fail_color(spec)
    if spec.statistic == StatType.AVERAGE:
        values = survey_metric_values(
            sets,
            spec.metric,
            excluded_map=excluded_map,
            cache=metric_cache,
        )
        computed = _fast_computed_statistic(spec, values)
        if computed is None:
            result, _details = evaluate_spec_combined(sets, spec, excluded_map)
            if not result.applicable:
                return []
            passed = result.passed
        else:
            passed = computed <= spec.stat_value
        if passed:
            return [
                PieSlice("Pass", 100.0, PIE_PASS_COLOR),
                PieSlice("Fail", 0.0, fail_color),
            ]
        return [
            PieSlice("Pass", 0.0, PIE_PASS_COLOR),
            PieSlice("Fail", 100.0, fail_color),
        ]

    if spec.statistic == StatType.MAX_CONSECUTIVE_FAILED:
        pass_count = 0
        fail_count = 0
        for _sequence_no, _source_no, shotpoints, series_values in _iter_source_series(
            sets, spec.metric, excluded_map
        ):
            for value in series_values:
                if _shot_exceeds_metric_limit(float(value), spec.reference_value):
                    fail_count += 1
                else:
                    pass_count += 1
    else:
        values = survey_metric_values(
            sets,
            spec.metric,
            excluded_map=excluded_map,
            cache=metric_cache,
        )
        pass_count = 0
        fail_count = 0
        for value in values:
            failed = False
            if spec.statistic == StatType.MAX_VALUE:
                sample = abs(float(value)) if spec.absolute else float(value)
                failed = sample > float(spec.stat_value)
            elif stat_uses_reference(spec.statistic):
                failed = _shot_exceeds_metric_limit(float(value), spec.reference_value)
            if failed:
                fail_count += 1
            else:
                pass_count += 1

    total = pass_count + fail_count
    if total == 0:
        return []
    return [
        PieSlice("Pass", 100.0 * pass_count / total, PIE_PASS_COLOR),
        PieSlice("Fail", 100.0 * fail_count / total, fail_color),
    ]


def survey_spec_pie_charts(
    sets: list[SequenceDiffSet],
    specs: list[SurveySpecRow] | None = None,
    *,
    excluded_map: dict[str, str] | None = None,
    metric_cache: dict[PlotKind, list[float]] | None = None,
) -> list[SurveySpecPieData]:
    """One pie chart per configured survey spec row."""
    excluded_map = excluded_map or {}
    spec_rows = list(specs if specs is not None else load_survey_specs())
    charts: list[SurveySpecPieData] = []
    for spec in spec_rows:
        values = survey_metric_values(
            sets,
            spec.metric,
            excluded_map=excluded_map,
            cache=metric_cache,
        )
        slices = _pie_slices_for_spec(
            sets,
            spec,
            excluded_map,
            metric_cache=metric_cache,
        )
        if not slices:
            continue
        pass_count, fail_count = _pass_fail_counts(
            sets,
            spec,
            excluded_map,
            metric_cache=metric_cache,
        )
        stats = _build_pie_stats(values, spec, pass_count, fail_count)
        metric_label = PLOT_KIND_PDF_LABELS[spec.metric]
        stat_label = STAT_TYPE_LABELS[spec.statistic]
        short_stat = _pie_stat_short_label(spec.statistic)
        limit_text = format_limit_value(spec)
        computed = _fast_computed_statistic(spec, values)
        if computed is None:
            result, _details = evaluate_spec_combined(sets, spec, excluded_map)
            computed = result.computed
            spec_passed = result.passed
        else:
            if spec.statistic == StatType.AVERAGE:
                spec_passed = computed <= spec.stat_value
            elif spec.statistic == StatType.MAX_VALUE:
                spec_passed = computed <= float(spec.stat_value)
            elif spec.statistic == StatType.MAX_PCT_FAILURE:
                spec_passed = computed <= float(spec.stat_value)
            else:
                result, _details = evaluate_spec_combined(sets, spec, excluded_map)
                spec_passed = result.passed
        computed_text = format_statistic(spec.statistic, computed)
        status = "PASS" if spec_passed else SEVERITY_LABELS[spec.severity].upper()
        headline = "4D Survey Statistic"
        title = f"Position {metric_label} · {stat_label}"
        tab_label = f"{PLOT_KIND_LABELS[spec.metric]} · {short_stat}"
        subtitle = f"Limit: {limit_text} · Computed: {computed_text} · {status}"
        charts.append(
            SurveySpecPieData(
                spec=spec,
                headline=headline,
                title=title,
                tab_label=tab_label,
                slices=slices,
                subtitle=subtitle,
                stats=stats,
                spec_passed=spec_passed,
                fail_color=_pie_fail_color(spec),
                severity=spec.severity,
            )
        )
    return charts


def aerial_plot_title(
    sets: list[SequenceDiffSet],
    kind: PlotKind,
) -> str:
    """Title for a survey-wide aerial plot."""
    return aerial_map_label(sets, kind)


def histogram_plot_title(
    sets: list[SequenceDiffSet],
    kind: PlotKind,
) -> str:
    """Title for a survey-wide cumulative histogram."""
    metric_name = PLOT_KIND_LABELS[kind]
    return (
        f"Cumulative Histogram: Source Position {metric_name} vs Baseline "
        "(Absolute Values)"
    )


def metric_unit(kind: PlotKind) -> str:
    return PLOT_KIND_UNITS[kind]


def available_survey_plot_kinds(
    sets: list[SequenceDiffSet],
    *,
    streamers_detected: bool,
) -> list[PlotKind]:
    """Plot kinds that have data for the loaded survey."""
    if not sets:
        return []
    all_rows = [row for item in sets for row in item.diff_rows]
    primary_match = sets[0].match_row
    kinds: list[PlotKind] = ["crossline", "inline", "radial"]
    if feather_tab_available(all_rows, streamers_detected=streamers_detected) and _kind_has_plottable_values(
        sets, "feather"
    ):
        kinds.append("feather")
    if feather_diff_tab_available(
        primary_match,
        streamers_detected=streamers_detected,
    ) and _kind_has_plottable_values(sets, "feather_diff"):
        kinds.append("feather_diff")
    return kinds
