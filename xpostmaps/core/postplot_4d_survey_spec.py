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
    ordered_sequence_sets,
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
    StatType.AVERAGE: "Average",
    StatType.MAX_PCT_FAILURE: "Max Percentage of Failure",
    StatType.MAX_CONSECUTIVE_FAILED: "Max Consecutive Failed Shotpoint",
    StatType.MAX_VALUE: "Max Value",
}

SEVERITY_LABELS: dict[Severity, str] = {
    Severity.WARNING: "Warning",
    Severity.ERROR: "Error",
}

# Statistics that compare per-shotpoint values against the Reference Value to
# decide which shotpoints "fail"; only these use the Reference Value column.
_REFERENCE_STATS = (StatType.MAX_PCT_FAILURE, StatType.MAX_CONSECUTIVE_FAILED)


def stat_uses_reference(statistic: StatType) -> bool:
    return statistic in _REFERENCE_STATS


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

    @property
    def accepted(self) -> bool:
        """PASS unless any sequence fails an Error-severity spec."""
        return all(seq.passed for seq in self.sequences)

    @property
    def has_warning(self) -> bool:
        return any(seq.has_warning for seq in self.sequences)


def _apply_absolute(values: list[float], absolute: bool) -> list[float]:
    if not absolute:
        return list(values)
    return [abs(value) for value in values]


def _max_consecutive(flags: list[bool]) -> int:
    best = run = 0
    for flag in flags:
        run = run + 1 if flag else 0
        if run > best:
            best = run
    return best


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
        fails = sum(1 for value in adjusted_flat if value > spec.reference_value)
        return 100.0 * fails / len(adjusted_flat)
    if spec.statistic == StatType.MAX_CONSECUTIVE_FAILED:
        best = 0
        for series in per_source_values:
            adjusted = _apply_absolute(series, spec.absolute)
            flags = [value > spec.reference_value for value in adjusted]
            best = max(best, _max_consecutive(flags))
        return float(best)
    return None


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
    computed = _compute_statistic(per_source, spec)
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
    """Evaluate every spec row against every sequence in *sets*."""
    excluded_map = excluded_by_sequence or {}
    sequences: list[SequenceEvaluation] = []
    for diff_set in ordered_sequence_sets(sets):
        sequence_no = diff_set.match_row.sequence_no
        excluded = parse_excluded_shotpoints(excluded_map.get(sequence_no, ""))
        results = [
            evaluate_spec_for_sequence(diff_set, spec, excluded_shotpoints=excluded)
            for spec in specs
        ]
        sequences.append(
            SequenceEvaluation(
                sequence_no=sequence_no,
                results=results,
            )
        )
    return SurveyEvaluation(sequences=sequences, spec_count=len(specs))


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
