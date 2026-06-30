"""Survey spec definitions and pass/fail evaluation for 4D Stat plots.

A survey spec row states an acceptance limit for one 4D metric (Crossline,
Inline, Radial, Feather, Feather Diff) computed as a single statistic over the
plotted shotpoint values of a sequence. Each sequence is evaluated against every
spec row; a failed row with ``Error`` severity fails the whole
sequence/combined-sequence test, while ``Warning`` rows only annotate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from xpostmaps.core.postplot_4d_plot_data import (
    PLOT_KIND_LABELS,
    PlotKind,
    SequenceDiffSet,
    build_plot_series,
    combined_source_key,
    ordered_sequence_sets,
    primary_sequence_set,
    unique_sources_from_diff_rows,
)

# 4D metrics reuse the plot-kind identifiers exactly so a spec row maps straight
# onto the same values shown in the time-series plot for that metric.
METRIC_KINDS: tuple[PlotKind, ...] = (
    "crossline",
    "inline",
    "radial",
    "feather",
    "feather_diff",
)

METRIC_LABELS: dict[PlotKind, str] = dict(PLOT_KIND_LABELS)


class StatType(str, Enum):
    AVERAGE = "average"
    MAX_PCT_FAILURE = "max_pct_failure"
    MAX_CONSECUTIVE_FAILED = "max_consecutive_failed"
    MAX_VALUE = "max_value"


class Severity(str, Enum):
    WARNING = "warning"
    ERROR = "error"


STAT_TYPE_LABELS: dict[StatType, str] = {
    StatType.AVERAGE: "Average for Whole Line",
    StatType.MAX_PCT_FAILURE: "Max Percentage of Failure",
    StatType.MAX_CONSECUTIVE_FAILED: "Max Consecutive Failed Shotpoint",
    StatType.MAX_VALUE: "Absolute Max",
}

SEVERITY_LABELS: dict[Severity, str] = {
    Severity.WARNING: "Warning",
    Severity.ERROR: "Error",
}

# Statistics that compare per-shotpoint values against the Metric Limit to
# decide which shotpoints "fail"; only these use the Metric Limit column.
# Failure uses |value| > limit regardless of the Absolute column.
_REFERENCE_STATS = (StatType.MAX_PCT_FAILURE, StatType.MAX_CONSECUTIVE_FAILED)


def stat_uses_reference(statistic: StatType) -> bool:
    return statistic in _REFERENCE_STATS


def stat_uses_absolute(statistic: StatType) -> bool:
    """Only Average and Absolute Max use the Absolute column."""
    return statistic in (StatType.AVERAGE, StatType.MAX_VALUE)


def _shot_exceeds_metric_limit(value: float, limit: float) -> bool:
    """True when |value| exceeds the per-shot metric tolerance (Metric Limit)."""
    return abs(value) > abs(float(limit))


def stat_type_from_str(text: str) -> StatType:
    normalized = (text or "").strip().lower()
    for stat in StatType:
        if stat.value == normalized:
            return stat
    return StatType.MAX_VALUE


def severity_from_str(text: str) -> Severity:
    normalized = (text or "").strip().lower()
    for severity in Severity:
        if severity.value == normalized:
            return severity
    return Severity.ERROR


def metric_kind_from_str(text: str) -> PlotKind:
    normalized = (text or "").strip().lower()
    for kind in METRIC_KINDS:
        if kind == normalized:
            return kind
    return "crossline"


@dataclass
class SurveySpecRow:
    """One acceptance limit for a 4D metric statistic."""

    metric: PlotKind = "crossline"
    statistic: StatType = StatType.MAX_VALUE
    reference_value: float = 0.0
    stat_value: float = 0.0
    absolute: bool = True
    severity: Severity = Severity.ERROR


@dataclass
class SpecResult:
    """Outcome of one spec row evaluated against one sequence."""

    spec: SurveySpecRow
    sequence_no: str
    computed: float | None
    passed: bool
    applicable: bool
    sample_count: int = 0


@dataclass
class SequenceEvaluation:
    sequence_no: str
    results: list[SpecResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """Sequence fails only when an Error-severity, applicable spec fails."""
        return not any(
            (not result.passed)
            and result.applicable
            and result.spec.severity == Severity.ERROR
            for result in self.results
        )

    @property
    def has_warning(self) -> bool:
        return any(
            (not result.passed)
            and result.applicable
            and result.spec.severity == Severity.WARNING
            for result in self.results
        )


@dataclass
class SurveyEvaluation:
    sequences: list[SequenceEvaluation] = field(default_factory=list)
    spec_count: int = 0
    failed_details: list["FailedSpecDetail"] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        """PASS unless any combined Error-severity spec fails."""
        return not any(
            (not result.passed)
            and result.applicable
            and result.spec.severity == Severity.ERROR
            for result in self.combined_results
        )

    @property
    def has_warning(self) -> bool:
        return any(
            (not result.passed)
            and result.applicable
            and result.spec.severity == Severity.WARNING
            for result in self.combined_results
        )

    @property
    def combined_results(self) -> list[SpecResult]:
        if not self.sequences:
            return []
        return self.sequences[0].results


@dataclass
class FailedSpecDetail:
    """One failed survey-spec row with shotpoints attributed to a sequence."""

    sequence_no: str
    shotpoints_text: str
    statistic_text: str
    applies_to_all_sequences: bool = False
    severity: Severity = Severity.ERROR


def _apply_absolute(values: list[float], absolute: bool) -> list[float]:
    if not absolute:
        return list(values)
    return [abs(value) for value in values]


def _max_consecutive_failed_shotpoints(
    diff_set: SequenceDiffSet,
    kind: PlotKind,
    reference_value: float,
    excluded_shotpoints: set[int] | None = None,
) -> float | None:
    """Longest run of failed shotpoints along acquisition order, per source."""
    excluded = excluded_shotpoints or set()
    best = 0
    any_data = False
    for source_no in unique_sources_from_diff_rows(diff_set.diff_rows):
        built = build_plot_series(
            diff_set.diff_rows,
            diff_set.match_row,
            kind,
            source_no,
        )
        if not built.shotpoints:
            continue
        any_data = True
        run = 0
        for shotpoint, value in zip(built.shotpoints, built.values, strict=False):
            if shotpoint in excluded:
                run = 0
                continue
            if _shot_exceeds_metric_limit(value, reference_value):
                run += 1
                if run > best:
                    best = run
            else:
                run = 0
    return float(best) if any_data else None


def _ordered_series_for_sequence(
    diff_set: SequenceDiffSet,
    kind: PlotKind,
    excluded_shotpoints: set[int] | None = None,
) -> list[list[float]]:
    """Per-source shotpoint values ordered FSP -> LSP for *kind*."""
    excluded = excluded_shotpoints or set()
    series: list[list[float]] = []
    for source_no in unique_sources_from_diff_rows(diff_set.diff_rows):
        built = build_plot_series(
            diff_set.diff_rows,
            diff_set.match_row,
            kind,
            source_no,
        )
        if not built.shotpoints:
            continue
        values = [
            float(value)
            for shotpoint, value in zip(
                built.shotpoints, built.values, strict=False
            )
            if shotpoint not in excluded
        ]
        if values:
            series.append(values)
    return series


def _compute_statistic(
    per_source_values: list[list[float]],
    spec: SurveySpecRow,
) -> float | None:
    """Compute the spec's statistic; None when there is no data."""
    flat = [value for series in per_source_values for value in series]
    if not flat:
        return None
    adjusted_flat = _apply_absolute(flat, spec.absolute)

    if spec.statistic == StatType.AVERAGE:
        return sum(adjusted_flat) / len(adjusted_flat)
    if spec.statistic == StatType.MAX_VALUE:
        return max(adjusted_flat)
    if spec.statistic == StatType.MAX_PCT_FAILURE:
        fails = sum(
            1 for value in flat if _shot_exceeds_metric_limit(value, spec.reference_value)
        )
        return 100.0 * fails / len(flat)
    return None


def _compute_statistic_with_exclusions(
    diff_set: SequenceDiffSet,
    spec: SurveySpecRow,
    excluded_shotpoints: set[int] | None = None,
) -> float | None:
    if spec.statistic == StatType.MAX_CONSECUTIVE_FAILED:
        return _max_consecutive_failed_shotpoints(
            diff_set,
            spec.metric,
            spec.reference_value,
            excluded_shotpoints,
        )
    per_source = _ordered_series_for_sequence(
        diff_set,
        spec.metric,
        excluded_shotpoints=excluded_shotpoints,
    )
    return _compute_statistic(per_source, spec)


def evaluate_spec_for_sequence(
    diff_set: SequenceDiffSet,
    spec: SurveySpecRow,
    excluded_shotpoints: set[int] | None = None,
) -> SpecResult:
    per_source = _ordered_series_for_sequence(
        diff_set,
        spec.metric,
        excluded_shotpoints=excluded_shotpoints,
    )
    sample_count = sum(len(series) for series in per_source)
    computed = _compute_statistic_with_exclusions(
        diff_set,
        spec,
        excluded_shotpoints=excluded_shotpoints,
    )
    sequence_no = diff_set.match_row.sequence_no
    if computed is None:
        return SpecResult(
            spec=spec,
            sequence_no=sequence_no,
            computed=None,
            passed=True,
            applicable=False,
            sample_count=0,
        )
    passed = computed <= spec.stat_value
    return SpecResult(
        spec=spec,
        sequence_no=sequence_no,
        computed=computed,
        passed=passed,
        applicable=True,
        sample_count=sample_count,
    )


def evaluate_survey_specs(
    sets: list[SequenceDiffSet],
    specs: list[SurveySpecRow],
    excluded_by_sequence: dict[str, str] | None = None,
) -> SurveyEvaluation:
    """Evaluate every spec row against all sequences combined as one test."""
    excluded_map = excluded_by_sequence or {}
    if not sets or not specs:
        return SurveyEvaluation(spec_count=len(specs))

    ordered = ordered_sequence_sets(sets)
    sequence_label = _combined_sequence_label(ordered)
    results: list[SpecResult] = []
    failed_details: list[FailedSpecDetail] = []

    for spec in specs:
        result, details = evaluate_spec_combined(ordered, spec, excluded_map)
        results.append(result)
        if not result.passed and result.applicable:
            failed_details.extend(details)

    return SurveyEvaluation(
        sequences=[
            SequenceEvaluation(
                sequence_no=sequence_label,
                results=results,
            )
        ],
        spec_count=len(specs),
        failed_details=failed_details,
    )


def _combined_sequence_label(sets: list[SequenceDiffSet]) -> str:
    numbers = [item.match_row.sequence_no for item in sets if item.match_row.sequence_no]
    return ", ".join(numbers) if numbers else "—"


def _iter_source_series(
    sets: list[SequenceDiffSet],
    kind: PlotKind,
    excluded_map: dict[str, str],
) -> list[tuple[str, str, list[int], list[float]]]:
    """Per-source series: (sequence_no, source_no, shotpoints, values) FSP -> LSP."""
    if not sets:
        return []
    direction_row = primary_sequence_set(sets).match_row
    series: list[tuple[str, str, list[int], list[float]]] = []
    for diff_set in ordered_sequence_sets(sets):
        sequence_no = diff_set.match_row.sequence_no
        excluded = parse_excluded_shotpoints(excluded_map.get(sequence_no, ""))
        for source_no in unique_sources_from_diff_rows(diff_set.diff_rows):
            built = build_plot_series(
                diff_set.diff_rows,
                direction_row,
                kind,
                source_no,
            )
            shotpoints: list[int] = []
            values: list[float] = []
            for shotpoint, value in zip(built.shotpoints, built.values, strict=False):
                if shotpoint in excluded:
                    continue
                shotpoints.append(shotpoint)
                values.append(float(value))
            if shotpoints:
                series.append((sequence_no, source_no, shotpoints, values))
    return series


def _all_source_series(
    sets: list[SequenceDiffSet],
    kind: PlotKind,
    excluded_map: dict[str, str],
) -> list[tuple[str, list[int], list[float]]]:
    """Per-source shotpoint series: (sequence_no, shotpoints, values)."""
    return [
        (sequence_no, shotpoints, values)
        for sequence_no, _source_no, shotpoints, values in _iter_source_series(
            sets, kind, excluded_map
        )
    ]


def _flag_shot_exceeds_max_value(value: float, spec: SurveySpecRow) -> bool:
    """Per-shot test for Absolute Max: matches the combined statistic's absolute mode."""
    sample = abs(value) if spec.absolute else value
    return sample > float(spec.stat_value)


def _failing_run_shotpoints(
    shotpoints: list[int],
    values: list[float],
    metric_limit: float,
    max_allowed: float,
) -> list[int]:
    """Shotpoints belonging to consecutive runs longer than *max_allowed*.

    A run is a maximal sequence of shotpoints each exceeding *metric_limit*; only
    runs whose length exceeds the allowed consecutive count are returned (these
    are the shotpoints that fail the Max Consecutive Failed Shotpoint spec).
    """
    threshold = int(round(float(max_allowed)))
    flagged: list[int] = []
    current: list[int] = []
    for shotpoint, value in zip(shotpoints, values, strict=False):
        if _shot_exceeds_metric_limit(value, metric_limit):
            current.append(shotpoint)
            continue
        if len(current) > threshold:
            flagged.extend(current)
        current = []
    if len(current) > threshold:
        flagged.extend(current)
    return flagged


def _flagged_points_by_source(
    sets: list[SequenceDiffSet],
    spec: SurveySpecRow,
    excluded_map: dict[str, str],
) -> dict[tuple[str, str], list[int]]:
    """Map (sequence_no, source_no) -> flagged shotpoints for a failed spec.

    Average is a whole-line statistic with no individual offending shotpoints, so
    it yields nothing here (it is reported as a whole-line row instead).
    """
    result: dict[tuple[str, str], list[int]] = {}
    if spec.statistic == StatType.AVERAGE:
        return result
    for sequence_no, source_no, shotpoints, values in _iter_source_series(
        sets, spec.metric, excluded_map
    ):
        flagged: list[int] = []
        if spec.statistic == StatType.MAX_VALUE:
            flagged = [
                shotpoint
                for shotpoint, value in zip(shotpoints, values, strict=False)
                if _flag_shot_exceeds_max_value(value, spec)
            ]
        elif spec.statistic == StatType.MAX_PCT_FAILURE:
            flagged = [
                shotpoint
                for shotpoint, value in zip(shotpoints, values, strict=False)
                if _shot_exceeds_metric_limit(value, spec.reference_value)
            ]
        elif spec.statistic == StatType.MAX_CONSECUTIVE_FAILED:
            flagged = _failing_run_shotpoints(
                shotpoints, values, spec.reference_value, spec.stat_value
            )
        if flagged:
            result[(sequence_no, source_no)] = flagged
    return result


def flag_map_for_kind(
    sets: list[SequenceDiffSet],
    specs: list[SurveySpecRow],
    kind: PlotKind,
    excluded_by_sequence: dict[str, str] | None = None,
) -> dict[str, dict[int, Severity]]:
    """Per-series flagged shotpoints + severity for one metric *kind*.

    The returned mapping is keyed exactly like the plotted series
    (``combined_source_key`` when several sequences are combined, otherwise the
    plain source label) so the time-series plot can recolour flagged shotpoint
    markers (red for Error, orange for Warning). Only specs that *fail* (with
    Error or Warning severity) contribute; Error wins when both apply to the
    same shotpoint.
    """
    excluded_map = excluded_by_sequence or {}
    flags: dict[str, dict[int, Severity]] = {}
    if not sets or not specs:
        return flags
    multi = len(sets) > 1
    for spec in specs:
        if spec.metric != kind:
            continue
        result, _details = evaluate_spec_combined(sets, spec, excluded_map)
        if result.passed or not result.applicable:
            continue
        for (sequence_no, source_no), shotpoints in _flagged_points_by_source(
            sets, spec, excluded_map
        ).items():
            key = (
                combined_source_key(source_no, sequence_no) if multi else source_no
            )
            bucket = flags.setdefault(key, {})
            for shotpoint in shotpoints:
                if bucket.get(shotpoint) == Severity.ERROR:
                    continue
                if spec.severity == Severity.ERROR or shotpoint not in bucket:
                    bucket[shotpoint] = spec.severity
    return flags


def _pooled_values(
    sets: list[SequenceDiffSet],
    kind: PlotKind,
    excluded_map: dict[str, str],
) -> list[tuple[str, int, float]]:
    """Flat list of (sequence_no, shotpoint, value) across all sources."""
    pooled: list[tuple[str, int, float]] = []
    for sequence_no, shotpoints, values in _all_source_series(sets, kind, excluded_map):
        for shotpoint, value in zip(shotpoints, values, strict=False):
            pooled.append((sequence_no, shotpoint, value))
    return pooled


def _longest_failed_streak(
    shotpoints: list[int],
    values: list[float],
    metric_limit: float,
) -> list[int]:
    best: list[int] = []
    current: list[int] = []
    for shotpoint, value in zip(shotpoints, values, strict=False):
        if _shot_exceeds_metric_limit(value, metric_limit):
            current.append(shotpoint)
            if len(current) > len(best):
                best = list(current)
        else:
            current = []
    return best


def format_shotpoint_ranges(shotpoints: list[int]) -> str:
    """Format shotpoints as comma-separated values and ranges (e.g. 1001-1005).

    Consecutive integers collapse to a single range (1001, 1002, …, 1005 →
    ``1001-1005``). Shotpoints with a constant step along the line (e.g. every
    other SP: 1459, 1461, …, 1481) collapse the same way (``1459-1481``).
    """
    unique = sorted(set(shotpoints))
    if not unique:
        return "—"
    parts: list[str] = []
    run_start = unique[0]
    run_end = unique[0]
    run_step: int | None = None

    for shotpoint in unique[1:]:
        gap = shotpoint - run_end
        if gap <= 0:
            continue
        if run_step is None:
            run_step = gap
            run_end = shotpoint
            continue
        if gap == run_step:
            run_end = shotpoint
            continue
        parts.append(_format_shotpoint_run(run_start, run_end))
        run_start = run_end = shotpoint
        run_step = None

    parts.append(_format_shotpoint_run(run_start, run_end))
    return ", ".join(parts)


def _format_shotpoint_run(start: int, end: int) -> str:
    if start == end:
        return str(start)
    return f"{start}-{end}"


def format_limit_value(spec: SurveySpecRow) -> str:
    if spec.statistic == StatType.MAX_PCT_FAILURE:
        return f"{spec.stat_value:g}%"
    if spec.statistic == StatType.MAX_CONSECUTIVE_FAILED:
        return f"{int(round(spec.stat_value))}"
    return f"{spec.stat_value:g}"


def format_failure_reason(spec: SurveySpecRow, computed: float) -> str:
    stat_label = STAT_TYPE_LABELS[spec.statistic]
    metric_label = METRIC_LABELS[spec.metric]
    computed_text = format_statistic(spec.statistic, computed)
    limit_text = format_limit_value(spec)
    if spec.statistic == StatType.MAX_PCT_FAILURE:
        return (
            f"{computed_text} exceeded limit {limit_text}: "
            f"{stat_label} / {metric_label}"
        )
    if spec.statistic == StatType.MAX_CONSECUTIVE_FAILED:
        return (
            f"{computed_text} consecutive failed shotpoints (limit {limit_text}): "
            f"{stat_label} / {metric_label}"
        )
    if spec.statistic == StatType.AVERAGE:
        return (
            f"Average {computed_text} exceeded limit {limit_text}: "
            f"{stat_label} / {metric_label}"
        )
    return (
        f"Max {computed_text} exceeded limit {limit_text}: "
        f"{stat_label} / {metric_label}"
    )


def _details_for_failed_spec(
    sets: list[SequenceDiffSet],
    spec: SurveySpecRow,
    excluded_map: dict[str, str],
    computed: float,
) -> list[FailedSpecDetail]:
    reason = format_failure_reason(spec, computed)
    sequence_nos = [
        item.match_row.sequence_no
        for item in ordered_sequence_sets(sets)
        if item.match_row.sequence_no
    ]
    combined_label = _combined_sequence_label(sets)

    # Average is a whole-line statistic: there are no individual offending
    # shotpoints, so report it as a single combined row.
    if spec.statistic == StatType.AVERAGE:
        return [
            FailedSpecDetail(
                sequence_no=combined_label,
                shotpoints_text="—",
                statistic_text=reason,
                applies_to_all_sequences=True,
                severity=spec.severity,
            )
        ]

    # Absolute Max, Max Percentage of Failure and Max Consecutive Failed Shotpoint
    # all attribute the offending shotpoints; list them per sequence.
    by_sequence: dict[str, list[int]] = {}
    for (sequence_no, _source_no), shotpoints in _flagged_points_by_source(
        sets, spec, excluded_map
    ).items():
        by_sequence.setdefault(sequence_no, []).extend(shotpoints)

    details: list[FailedSpecDetail] = []
    for sequence_no in sequence_nos:
        shotpoints = by_sequence.get(sequence_no, [])
        if not shotpoints:
            continue
        details.append(
            FailedSpecDetail(
                sequence_no=sequence_no,
                shotpoints_text=format_shotpoint_ranges(shotpoints),
                statistic_text=reason,
                severity=spec.severity,
            )
        )

    if not details:
        details.append(
            FailedSpecDetail(
                sequence_no=combined_label,
                shotpoints_text="—",
                statistic_text=reason,
                applies_to_all_sequences=True,
                severity=spec.severity,
            )
        )
    return details


def evaluate_spec_combined(
    sets: list[SequenceDiffSet],
    spec: SurveySpecRow,
    excluded_map: dict[str, str],
) -> tuple[SpecResult, list[FailedSpecDetail]]:
    """Evaluate one spec against all sequences combined."""
    sequence_label = _combined_sequence_label(sets)
    pooled = _pooled_values(sets, spec.metric, excluded_map)
    sample_count = len(pooled)
    if not pooled:
        return (
            SpecResult(
                spec=spec,
                sequence_no=sequence_label,
                computed=None,
                passed=True,
                applicable=False,
                sample_count=0,
            ),
            [],
        )

    values = [value for _, _, value in pooled]
    computed: float | None
    if spec.statistic == StatType.AVERAGE:
        adjusted = _apply_absolute(values, spec.absolute)
        computed = sum(adjusted) / len(adjusted)
    elif spec.statistic == StatType.MAX_VALUE:
        adjusted = _apply_absolute(values, spec.absolute)
        computed = max(adjusted)
    elif spec.statistic == StatType.MAX_PCT_FAILURE:
        fails = sum(
            1 for value in values if _shot_exceeds_metric_limit(value, spec.reference_value)
        )
        computed = 100.0 * fails / len(values)
    elif spec.statistic == StatType.MAX_CONSECUTIVE_FAILED:
        best = 0
        for _, shotpoints, series_values in _all_source_series(
            sets, spec.metric, excluded_map
        ):
            streak = _longest_failed_streak(
                shotpoints, series_values, spec.reference_value
            )
            best = max(best, len(streak))
        computed = float(best)
    else:
        computed = None

    if computed is None:
        return (
            SpecResult(
                spec=spec,
                sequence_no=sequence_label,
                computed=None,
                passed=True,
                applicable=False,
                sample_count=sample_count,
            ),
            [],
        )

    passed = computed <= spec.stat_value
    details: list[FailedSpecDetail] = []
    if not passed:
        details = _details_for_failed_spec(sets, spec, excluded_map, computed)
    return (
        SpecResult(
            spec=spec,
            sequence_no=sequence_label,
            computed=computed,
            passed=passed,
            applicable=True,
            sample_count=sample_count,
        ),
        details,
    )


def failed_details_for_sequence(
    details: list[FailedSpecDetail],
    sequence_no: str,
) -> list[FailedSpecDetail]:
    """Return failure rows visible for one sequence in the results table."""
    return [
        detail
        for detail in details
        if detail.applies_to_all_sequences or detail.sequence_no == sequence_no
    ]


def format_statistic(statistic: StatType, value: float | None) -> str:
    if value is None:
        return "—"
    if statistic == StatType.MAX_PCT_FAILURE:
        return f"{value:.1f}%"
    if statistic == StatType.MAX_CONSECUTIVE_FAILED:
        return f"{int(round(value))}"
    return f"{value:.2f}"


def parse_excluded_shotpoints(text: str) -> set[int]:
    """Parse shotpoint exclusion text (e.g. ``1001, 1002, 1005-1010``)."""
    excluded: set[int] = set()
    for part in (text or "").split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            bounds = token.split("-", 1)
            if len(bounds) != 2:
                continue
            try:
                start = int(bounds[0].strip())
                end = int(bounds[1].strip())
            except ValueError:
                continue
            if start <= end:
                excluded.update(range(start, end + 1))
            else:
                excluded.update(range(end, start + 1))
            continue
        try:
            excluded.add(int(token))
        except ValueError:
            continue
    return excluded
