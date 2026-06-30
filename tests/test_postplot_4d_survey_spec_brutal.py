"""Brutal audit: every 4D Statistic type vs an independent oracle + real 7027 data."""

from __future__ import annotations

import math
import unittest
from pathlib import Path

from xpostmaps.core.postplot_4d_diff import Postplot4DDiffRow
from xpostmaps.core.postplot_4d_matching import Postplot4DMatchRow
from xpostmaps.core.postplot_4d_plot_data import (
    PlotKind,
    build_plot_series,
    metric_values_for_kind,
    unique_sources_from_diff_rows,
)
from xpostmaps.core.postplot_4d_survey_spec import (
    Severity,
    StatType,
    SurveySpecRow,
    evaluate_spec_combined,
    evaluate_spec_for_sequence,
    evaluate_survey_specs,
    flag_map_for_kind,
    format_shotpoint_ranges,
    parse_excluded_shotpoints,
    excluded_shotpoints_for_sequence,
    excluded_text_for_sequence,
)

ROOT = Path(__file__).resolve().parents[1]
DB_7027 = ROOT / "data" / "7027.db"
DB_10221 = ROOT / "data" / "10221.db"


def _match(
    *,
    sequence_no: str = "3001",
    first_sp: int = 100,
    last_sp: int = 110,
    direction: str = "Up-line",
) -> Postplot4DMatchRow:
    return Postplot4DMatchRow(
        baseline_name="Base",
        baseline_kind="preplot",
        line_name="51892113001",
        subline="",
        sequence_no=sequence_no,
        first_sp=first_sp,
        last_sp=last_sp,
        line_direction=direction,
        sequence_id=f"file|{sequence_no}|51892113001",
    )


def _row(
    shotpoint: int,
    *,
    crossline: float = 0.0,
    inline: float = 0.0,
    radial: float = 0.0,
    feather: float | None = None,
    navplan_feather: float | None = None,
    source_id: str = "001",
) -> Postplot4DDiffRow:
    return Postplot4DDiffRow(
        shotpoint=shotpoint,
        baseline_x=0.0,
        baseline_y=0.0,
        baseline_latitude="",
        baseline_longitude="",
        source_x=0.0,
        source_y=0.0,
        source_latitude="",
        source_longitude="",
        crossline_m=crossline,
        inline_m=inline,
        radial_m=radial,
        navplan_feather_deg=navplan_feather,
        line_feather_deg=feather,
        firing_source_id=source_id,
    )


def _diff_set(
    rows: list[Postplot4DDiffRow],
    match: Postplot4DMatchRow | None = None,
):
    from xpostmaps.core.postplot_4d_plot_data import SequenceDiffSet

    return SequenceDiffSet(match_row=match or _match(), diff_rows=rows)


def _values_for_spec(
    diff_set,
    metric: PlotKind,
    excluded: set[int] | None = None,
) -> list[float]:
    excluded = excluded or set()
    values: list[float] = []
    for source in unique_sources_from_diff_rows(diff_set.diff_rows):
        built = build_plot_series(
            diff_set.diff_rows, diff_set.match_row, metric, source
        )
        for shotpoint, value in zip(built.shotpoints, built.values, strict=False):
            if shotpoint in excluded:
                continue
            values.append(float(value))
    return values


def _oracle_average(values: list[float], *, absolute: bool) -> float | None:
    if not values:
        return None
    adjusted = [abs(v) for v in values] if absolute else values
    return sum(adjusted) / len(adjusted)


def _oracle_absolute_max(values: list[float], *, absolute: bool) -> float | None:
    if not values:
        return None
    adjusted = [abs(v) for v in values] if absolute else values
    return max(adjusted)


def _oracle_pct_failure(values: list[float], metric_limit: float) -> float | None:
    if not values:
        return None
    limit = abs(metric_limit)
    fails = sum(1 for v in values if abs(v) > limit)
    return 100.0 * fails / len(values)


def _oracle_max_consecutive(
    diff_set,
    metric: PlotKind,
    metric_limit: float,
    excluded: set[int] | None = None,
) -> float | None:
    excluded = excluded or set()
    limit = abs(metric_limit)
    best = 0
    any_data = False
    for source in unique_sources_from_diff_rows(diff_set.diff_rows):
        built = build_plot_series(
            diff_set.diff_rows, diff_set.match_row, metric, source
        )
        if not built.shotpoints:
            continue
        any_data = True
        run = 0
        for shotpoint, value in zip(built.shotpoints, built.values, strict=False):
            if shotpoint in excluded:
                run = 0
                continue
            if abs(value) > limit:
                run += 1
                best = max(best, run)
            else:
                run = 0
    return float(best) if any_data else None


def _oracle(
    diff_set,
    spec: SurveySpecRow,
    excluded: set[int] | None = None,
) -> tuple[float | None, bool]:
    values = _values_for_spec(diff_set, spec.metric, excluded)
    computed: float | None
    if spec.statistic == StatType.AVERAGE:
        computed = _oracle_average(values, absolute=spec.absolute)
    elif spec.statistic == StatType.MAX_VALUE:
        computed = _oracle_absolute_max(values, absolute=spec.absolute)
    elif spec.statistic == StatType.MAX_PCT_FAILURE:
        computed = _oracle_pct_failure(values, spec.reference_value)
    elif spec.statistic == StatType.MAX_CONSECUTIVE_FAILED:
        computed = _oracle_max_consecutive(
            diff_set, spec.metric, spec.reference_value, excluded
        )
    else:
        raise AssertionError(f"unknown statistic {spec.statistic}")
    if computed is None:
        return None, True
    return computed, computed <= spec.stat_value


def _assert_spec(
    case: str,
    diff_set,
    spec: SurveySpecRow,
    *,
    excluded: set[int] | None = None,
    expect_computed: float | None = None,
    expect_passed: bool | None = None,
) -> None:
    result = evaluate_spec_for_sequence(diff_set, spec, excluded_shotpoints=excluded)
    oracle_computed, oracle_passed = _oracle(diff_set, spec, excluded)

    if oracle_computed is None:
        assert result.computed is None, f"{case}: expected no data"
        assert not result.applicable, f"{case}: should not be applicable"
    else:
        assert result.computed is not None, f"{case}: expected computed value"
        assert math.isclose(result.computed, oracle_computed, rel_tol=0, abs_tol=1e-9), (
            f"{case}: engine={result.computed} oracle={oracle_computed}"
        )
        assert result.passed == oracle_passed, (
            f"{case}: pass engine={result.passed} oracle={oracle_passed}"
        )

    if expect_computed is not None:
        assert result.computed is not None
        assert math.isclose(result.computed, expect_computed, rel_tol=0, abs_tol=1e-9), case
    if expect_passed is not None:
        assert result.passed == expect_passed, case


class TestAverageForWholeLine(unittest.TestCase):
    def test_signed_average(self) -> None:
        ds = _diff_set([_row(100, crossline=-4.0), _row(101, crossline=4.0)])
        spec = SurveySpecRow(
            statistic=StatType.AVERAGE,
            metric="crossline",
            stat_value=1.0,
            absolute=False,
        )
        _assert_spec("signed avg zero", ds, spec, expect_computed=0.0, expect_passed=True)

    def test_absolute_average(self) -> None:
        ds = _diff_set([_row(100, crossline=-4.0), _row(101, crossline=4.0)])
        spec = SurveySpecRow(
            statistic=StatType.AVERAGE,
            metric="crossline",
            stat_value=3.0,
            absolute=True,
        )
        _assert_spec("abs avg fail", ds, spec, expect_computed=4.0, expect_passed=False)

        spec_pass = SurveySpecRow(
            statistic=StatType.AVERAGE,
            metric="crossline",
            stat_value=5.0,
            absolute=True,
        )
        _assert_spec("abs avg pass", ds, spec_pass, expect_computed=4.0, expect_passed=True)

    def test_average_uses_inline_metric(self) -> None:
        ds = _diff_set([_row(100, inline=2.0), _row(101, inline=6.0)])
        spec = SurveySpecRow(
            statistic=StatType.AVERAGE,
            metric="inline",
            stat_value=5.0,
            absolute=True,
        )
        _assert_spec("inline avg", ds, spec, expect_computed=4.0, expect_passed=True)

    def test_excluded_shotpoints_omitted_from_average(self) -> None:
        ds = _diff_set(
            [
                _row(100, crossline=0.0),
                _row(101, crossline=100.0),
                _row(102, crossline=0.0),
            ]
        )
        spec = SurveySpecRow(
            statistic=StatType.AVERAGE,
            metric="crossline",
            stat_value=1.0,
            absolute=True,
        )
        _assert_spec(
            "exclude outlier",
            ds,
            spec,
            excluded={101},
            expect_computed=0.0,
            expect_passed=True,
        )


class TestAbsoluteMax(unittest.TestCase):
    def test_absolute_on_uses_magnitude(self) -> None:
        ds = _diff_set([_row(100, crossline=-8.0), _row(101, crossline=3.0)])
        spec = SurveySpecRow(
            statistic=StatType.MAX_VALUE,
            metric="crossline",
            stat_value=7.5,
            absolute=True,
        )
        _assert_spec("abs max on", ds, spec, expect_computed=8.0, expect_passed=False)

    def test_absolute_off_uses_signed_max(self) -> None:
        ds = _diff_set([_row(100, crossline=-8.0), _row(101, crossline=3.0)])
        spec = SurveySpecRow(
            statistic=StatType.MAX_VALUE,
            metric="crossline",
            stat_value=7.5,
            absolute=False,
        )
        _assert_spec("abs max off", ds, spec, expect_computed=3.0, expect_passed=True)

    def test_radial_metric(self) -> None:
        ds = _diff_set([_row(100, radial=12.0), _row(101, radial=4.0)])
        spec = SurveySpecRow(
            statistic=StatType.MAX_VALUE,
            metric="radial",
            stat_value=10.0,
            absolute=True,
        )
        _assert_spec("radial max", ds, spec, expect_computed=12.0, expect_passed=False)


class TestMaxPercentageOfFailure(unittest.TestCase):
    def test_magnitude_counts_negative_exceedance(self) -> None:
        ds = _diff_set([_row(100, crossline=-12.0), _row(101, crossline=1.0)])
        spec = SurveySpecRow(
            statistic=StatType.MAX_PCT_FAILURE,
            metric="crossline",
            reference_value=9.0,
            stat_value=40.0,
        )
        _assert_spec("pct neg fail", ds, spec, expect_computed=50.0, expect_passed=False)

    def test_exactly_at_limit_is_not_a_failure(self) -> None:
        ds = _diff_set([_row(100, crossline=9.0), _row(101, crossline=-9.0)])
        spec = SurveySpecRow(
            statistic=StatType.MAX_PCT_FAILURE,
            metric="crossline",
            reference_value=9.0,
            stat_value=0.0,
        )
        _assert_spec("at limit ok", ds, spec, expect_computed=0.0, expect_passed=True)

    def test_three_of_four_fail(self) -> None:
        ds = _diff_set(
            [
                _row(100, crossline=10.0),
                _row(101, crossline=-10.0),
                _row(102, crossline=0.0),
                _row(103, crossline=9.5),
            ]
        )
        spec = SurveySpecRow(
            statistic=StatType.MAX_PCT_FAILURE,
            metric="crossline",
            reference_value=9.0,
            stat_value=70.0,
        )
        _assert_spec("75 pct fail", ds, spec, expect_computed=75.0, expect_passed=False)

    def test_excluded_shots_removed_from_pct(self) -> None:
        ds = _diff_set(
            [
                _row(100, crossline=20.0),
                _row(101, crossline=0.0),
                _row(102, crossline=0.0),
            ]
        )
        spec = SurveySpecRow(
            statistic=StatType.MAX_PCT_FAILURE,
            metric="crossline",
            reference_value=9.0,
            stat_value=50.0,
        )
        _assert_spec(
            "exclude fail shot",
            ds,
            spec,
            excluded={100},
            expect_computed=0.0,
            expect_passed=True,
        )


class TestMaxConsecutiveFailedShotpoint(unittest.TestCase):
    def test_negative_streak_user_report(self) -> None:
        ds = _diff_set(
            [
                _row(14730, crossline=-5.0),
                _row(14731, crossline=-9.2),
                _row(14732, crossline=-9.559),
                _row(14733, crossline=-9.8),
                _row(14734, crossline=-10.0),
                _row(14735, crossline=-9.7),
                _row(14736, crossline=-9.6),
            ],
            _match(first_sp=14730, last_sp=14736),
        )
        spec = SurveySpecRow(
            statistic=StatType.MAX_CONSECUTIVE_FAILED,
            metric="crossline",
            reference_value=9.0,
            stat_value=5.0,
        )
        _assert_spec(
            "user negative streak",
            ds,
            spec,
            expect_computed=6.0,
            expect_passed=False,
        )

    def test_exactly_at_limit_does_not_break_streak(self) -> None:
        ds = _diff_set(
            [
                _row(100, crossline=-9.0),
                _row(101, crossline=-10.0),
                _row(102, crossline=-10.0),
            ]
        )
        spec = SurveySpecRow(
            statistic=StatType.MAX_CONSECUTIVE_FAILED,
            metric="crossline",
            reference_value=9.0,
            stat_value=1.0,
        )
        _assert_spec("at limit breaks", ds, spec, expect_computed=2.0, expect_passed=False)

    def test_broken_run(self) -> None:
        ds = _diff_set(
            [
                _row(100, crossline=10.0),
                _row(101, crossline=10.0),
                _row(102, crossline=0.0),
                _row(103, crossline=10.0),
                _row(104, crossline=10.0),
            ]
        )
        spec = SurveySpecRow(
            statistic=StatType.MAX_CONSECUTIVE_FAILED,
            metric="crossline",
            reference_value=9.0,
            stat_value=2.0,
        )
        _assert_spec("broken run", ds, spec, expect_computed=2.0, expect_passed=True)

    def test_down_line_order(self) -> None:
        ds = _diff_set(
            [
                _row(200, crossline=10.0),
                _row(199, crossline=10.0),
                _row(198, crossline=10.0),
                _row(197, crossline=0.0),
            ],
            _match(first_sp=200, last_sp=197, direction="Down-line"),
        )
        spec = SurveySpecRow(
            statistic=StatType.MAX_CONSECUTIVE_FAILED,
            metric="crossline",
            reference_value=9.0,
            stat_value=2.0,
        )
        _assert_spec("down line", ds, spec, expect_computed=3.0, expect_passed=False)

    def test_multi_source_takes_worst_source(self) -> None:
        ds = _diff_set(
            [
                _row(100, crossline=10.0, source_id="001"),
                _row(101, crossline=10.0, source_id="001"),
                _row(100, crossline=0.0, source_id="002"),
                _row(101, crossline=10.0, source_id="002"),
                _row(102, crossline=10.0, source_id="002"),
                _row(103, crossline=10.0, source_id="002"),
                _row(104, crossline=10.0, source_id="002"),
            ],
            _match(first_sp=100, last_sp=104),
        )
        spec = SurveySpecRow(
            statistic=StatType.MAX_CONSECUTIVE_FAILED,
            metric="crossline",
            reference_value=9.0,
            stat_value=3.0,
        )
        _assert_spec("multi source", ds, spec, expect_computed=4.0, expect_passed=False)

    def test_excluded_shotpoint_breaks_streak(self) -> None:
        ds = _diff_set([_row(100 + i, crossline=-10.0) for i in range(6)])
        spec = SurveySpecRow(
            statistic=StatType.MAX_CONSECUTIVE_FAILED,
            metric="crossline",
            reference_value=9.0,
            stat_value=4.0,
        )
        _assert_spec(
            "exclude breaks streak",
            ds,
            spec,
            excluded={102, 103},
            expect_computed=2.0,
            expect_passed=True,
        )


class TestCombinedEvaluation(unittest.TestCase):
    def test_warning_and_error_together(self) -> None:
        rows = [_row(100 + i, crossline=-10.0) for i in range(6)]
        ds = _diff_set(rows)
        specs = [
            SurveySpecRow(
                statistic=StatType.MAX_VALUE,
                metric="crossline",
                stat_value=5.0,
                absolute=True,
                severity=Severity.WARNING,
            ),
            SurveySpecRow(
                statistic=StatType.MAX_CONSECUTIVE_FAILED,
                metric="crossline",
                reference_value=9.0,
                stat_value=10.0,
                severity=Severity.ERROR,
            ),
        ]
        evaluation = evaluate_survey_specs([ds], specs)
        self.assertTrue(evaluation.accepted)
        self.assertTrue(evaluation.has_warning)

    def test_error_fails_overall(self) -> None:
        rows = [_row(100 + i, crossline=-10.0) for i in range(6)]
        ds = _diff_set(rows)
        specs = [
            SurveySpecRow(
                statistic=StatType.MAX_CONSECUTIVE_FAILED,
                metric="crossline",
                reference_value=9.0,
                stat_value=4.0,
                severity=Severity.ERROR,
            )
        ]
        evaluation = evaluate_survey_specs([ds], specs)
        self.assertFalse(evaluation.accepted)

    def test_multi_sequence_combined_not_per_sequence(self) -> None:
        ds1 = _diff_set(
            [_row(100, crossline=0.0), _row(101, crossline=0.0)],
            _match(sequence_no="3001", first_sp=100, last_sp=101),
        )
        ds2 = _diff_set(
            [_row(200, crossline=-10.0), _row(201, crossline=-10.0)],
            _match(sequence_no="3002", first_sp=200, last_sp=201),
        )
        spec = SurveySpecRow(
            statistic=StatType.MAX_CONSECUTIVE_FAILED,
            metric="crossline",
            reference_value=9.0,
            stat_value=1.0,
            severity=Severity.ERROR,
        )
        per_seq_2 = evaluate_spec_for_sequence(ds2, spec)
        self.assertFalse(per_seq_2.passed)

        combined = evaluate_survey_specs([ds1, ds2], [spec])
        self.assertFalse(combined.accepted)
        self.assertEqual(len(combined.sequences), 1)
        self.assertTrue(combined.failed_details)

    def test_failed_details_include_shotpoint_ranges(self) -> None:
        rows = [_row(100 + i, crossline=-10.0) for i in range(6)]
        ds = _diff_set(rows)
        spec = SurveySpecRow(
            statistic=StatType.MAX_CONSECUTIVE_FAILED,
            metric="crossline",
            reference_value=9.0,
            stat_value=4.0,
        )
        evaluation = evaluate_survey_specs([ds], [spec])
        self.assertFalse(evaluation.accepted)
        self.assertTrue(evaluation.failed_details)
        detail = evaluation.failed_details[0]
        self.assertEqual(detail.shotpoints_text, "100-105")
        self.assertIn("consecutive", detail.statistic_text.lower())

    def test_absolute_max_lists_each_exceeding_shotpoint(self) -> None:
        rows = [
            _row(100, crossline=5.0),
            _row(101, crossline=15.0),
            _row(102, crossline=8.0),
            _row(103, crossline=13.0),
        ]
        ds = _diff_set(rows)
        spec = SurveySpecRow(
            statistic=StatType.MAX_VALUE,
            metric="crossline",
            stat_value=12.0,
            absolute=True,
            severity=Severity.WARNING,
        )
        evaluation = evaluate_survey_specs([ds], [spec])
        self.assertTrue(evaluation.accepted)
        self.assertTrue(evaluation.has_warning)
        self.assertEqual(len(evaluation.failed_details), 1)
        detail = evaluation.failed_details[0]
        self.assertEqual(detail.shotpoints_text, "101, 103")
        self.assertEqual(detail.severity, Severity.WARNING)

    def test_separate_rows_for_each_failed_spec(self) -> None:
        rows = [_row(100 + i, crossline=13.0) for i in range(5)]
        ds = _diff_set(rows)
        specs = [
            SurveySpecRow(
                statistic=StatType.MAX_VALUE,
                metric="crossline",
                stat_value=12.0,
                absolute=True,
                severity=Severity.WARNING,
            ),
            SurveySpecRow(
                statistic=StatType.MAX_CONSECUTIVE_FAILED,
                metric="crossline",
                reference_value=10.0,
                stat_value=3.0,
                severity=Severity.ERROR,
            ),
        ]
        evaluation = evaluate_survey_specs([ds], specs)
        self.assertFalse(evaluation.accepted)
        self.assertEqual(len(evaluation.failed_details), 2)
        self.assertEqual(
            {detail.severity for detail in evaluation.failed_details},
            {Severity.WARNING, Severity.ERROR},
        )


class TestFlagMapForKind(unittest.TestCase):
    def test_error_overrides_warning_on_same_shotpoint(self) -> None:
        rows = [_row(100 + i, crossline=13.0) for i in range(5)]
        ds = _diff_set(rows)
        specs = [
            SurveySpecRow(
                statistic=StatType.MAX_VALUE,
                metric="crossline",
                stat_value=12.0,
                absolute=True,
                severity=Severity.WARNING,
            ),
            SurveySpecRow(
                statistic=StatType.MAX_CONSECUTIVE_FAILED,
                metric="crossline",
                reference_value=10.0,
                stat_value=3.0,
                severity=Severity.ERROR,
            ),
        ]
        flags = flag_map_for_kind([ds], specs, "crossline")
        self.assertEqual(flags["G01"][100], Severity.ERROR)
        self.assertEqual(len(flags["G01"]), 5)


class TestFormatShotpointRanges(unittest.TestCase):
    def test_single_range_and_gaps(self) -> None:
        self.assertEqual(
            format_shotpoint_ranges([1001, 1003, 1010, 1011, 1012]),
            "1001-1003, 1010-1012",
        )
        self.assertEqual(format_shotpoint_ranges([]), "—")

    def test_consecutive_integers_collapse(self) -> None:
        self.assertEqual(
            format_shotpoint_ranges([1001, 1002, 1003, 1004, 1005]),
            "1001-1005",
        )

    def test_constant_step_along_line(self) -> None:
        self.assertEqual(
            format_shotpoint_ranges([1459, 1461, 1463, 1465, 1467, 1469]),
            "1459-1469",
        )


class TestCombinedSpecEvaluation(unittest.TestCase):
    def test_combined_average_pools_all_sequences(self) -> None:
        ds1 = _diff_set(
            [_row(100, crossline=2.0)],
            _match(sequence_no="3001", first_sp=100, last_sp=100),
        )
        ds2 = _diff_set(
            [_row(200, crossline=6.0)],
            _match(sequence_no="3002", first_sp=200, last_sp=200),
        )
        spec = SurveySpecRow(
            statistic=StatType.AVERAGE,
            metric="crossline",
            stat_value=5.0,
            absolute=True,
        )
        result, _details = evaluate_spec_combined([ds1, ds2], spec, {})
        assert result.computed is not None
        self.assertAlmostEqual(result.computed, 4.0)
        self.assertTrue(result.passed)


class TestParseExcludedShotpoints(unittest.TestCase):
    def test_range_and_list(self) -> None:
        self.assertEqual(parse_excluded_shotpoints("1001, 1005-1007"), {1001, 1005, 1006, 1007})
        self.assertEqual(parse_excluded_shotpoints("1007-1005"), {1005, 1006, 1007})

    def test_ascending_and_descending_ranges_equivalent(self) -> None:
        self.assertEqual(
            parse_excluded_shotpoints("1001-1010"),
            set(range(1001, 1011)),
        )
        self.assertEqual(parse_excluded_shotpoints("1010-1001"), set(range(1001, 1011)))

    def test_spaced_and_unicode_dashes(self) -> None:
        self.assertEqual(parse_excluded_shotpoints("1001 - 1010"), set(range(1001, 1011)))
        self.assertEqual(parse_excluded_shotpoints("1010 \u2013 1001"), set(range(1001, 1011)))

    def test_sequence_alias_lookup(self) -> None:
        mapping = {"70": "1481-1461"}
        self.assertEqual(excluded_text_for_sequence(mapping, "070"), "1481-1461")
        self.assertEqual(
            excluded_shotpoints_for_sequence(mapping, "070"),
            set(range(1461, 1482)),
        )


@unittest.skipUnless(DB_10221.is_file(), f"database not found: {DB_10221}")
class TestSurveySpec10221Exclude070(unittest.TestCase):
    """Real 10221 / 1065P1A-070 navplan radial exclusion (user screenshot case)."""

    @classmethod
    def setUpClass(cls) -> None:
        from xpostmaps.core.database import Database
        from xpostmaps.core.postplot_4d_diff import calculate_match_diff_rows
        from xpostmaps.core.postplot_4d_matching import build_postplot_4d_rows
        from xpostmaps.core.postplot_4d_plot_data import SequenceDiffSet

        db = Database(DB_10221)
        settings, map_data = db.load_project("10221", with_positions=True)
        settings.postplot_4d_baseline = "navplan"
        positions = db.load_positions("10221")
        rows = build_postplot_4d_rows(map_data, settings, "navplan")
        match = next(
            r
            for r in rows
            if r.sequence_id.startswith("70.1065P1A-070.a070.p190")
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
        cls.diff_set = SequenceDiffSet(match_row=match, diff_rows=diff_rows)
        cls.excluded = parse_excluded_shotpoints("1481-1461")
        cls.specs = [
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

    def test_without_exclusion_matches_three_failures(self) -> None:
        evaluation = evaluate_survey_specs([self.diff_set], self.specs, {})
        self.assertFalse(evaluation.accepted)
        self.assertTrue(evaluation.has_warning)
        self.assertEqual(len(evaluation.failed_details), 3)

    def test_exclusion_accepts_with_one_warning(self) -> None:
        excluded_map = {"070": "1481-1461"}
        evaluation = evaluate_survey_specs(
            [self.diff_set], self.specs, excluded_by_sequence=excluded_map
        )
        self.assertTrue(evaluation.accepted)
        self.assertTrue(evaluation.has_warning)
        self.assertEqual(len(evaluation.failed_details), 1)

    def test_exclusion_alias_key_70_equivalent_to_070(self) -> None:
        flags_070 = flag_map_for_kind(
            [self.diff_set],
            self.specs,
            "radial",
            excluded_by_sequence={"070": "1481-1461"},
        )
        flags_70 = flag_map_for_kind(
            [self.diff_set],
            self.specs,
            "radial",
            excluded_by_sequence={"70": "1481-1461"},
        )
        self.assertEqual(flags_070, flags_70)

    def test_no_flagged_shotpoints_inside_excluded_range(self) -> None:
        flags = flag_map_for_kind(
            [self.diff_set],
            self.specs,
            "radial",
            excluded_by_sequence={"070": "1481-1461"},
        )
        flagged = {sp for bucket in flags.values() for sp in bucket}
        overlap = flagged & self.excluded
        self.assertEqual(overlap, set(), f"excluded SPs still flagged: {sorted(overlap)}")

    def test_only_sp_1459_warns_after_exclusion(self) -> None:
        flags = flag_map_for_kind(
            [self.diff_set],
            self.specs,
            "radial",
            excluded_by_sequence={"070": "1481-1461"},
        )
        g01 = flags.get("G01", {})
        self.assertEqual(set(g01.keys()), {1459})
        self.assertEqual(g01[1459], Severity.WARNING)
        self.assertEqual(flags.get("G02", {}), {})


@unittest.skipUnless(DB_7027.is_file(), f"database not found: {DB_7027}")
class TestSurveySpecReal7027Brutal(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from xpostmaps.core.database import Database
        from xpostmaps.core.postplot_4d_matching import build_postplot_4d_rows
        from xpostmaps.core.postplot_4d_plot_data import SequenceDiffSet

        db = Database(DB_7027)
        cls.project = db.list_projects()[0]
        settings, map_data = db.load_project(cls.project, with_positions=False)
        match_rows = build_postplot_4d_rows(map_data, settings, "preplot")
        cls.sets: list = []
        for match_row in match_rows:
            if not match_row.has_match:
                continue
            if not db.has_postplot_4d_diffs(
                cls.project, match_row.baseline_kind, match_row.sequence_id
            ):
                continue
            diff_rows = db.load_postplot_4d_diffs(
                cls.project, match_row.baseline_kind, match_row.sequence_id
            )
            if diff_rows:
                cls.sets.append(
                    SequenceDiffSet(match_row=match_row, diff_rows=diff_rows)
                )
        if not cls.sets:
            raise unittest.SkipTest("no saved diff sequences in 7027.db")

    def test_every_saved_sequence_matches_oracle_for_all_statistics(self) -> None:
        metrics: list[PlotKind] = ["crossline", "inline", "radial"]
        for diff_set in self.sets:
            for metric in metrics:
                if not metric_values_for_kind(diff_set.diff_rows, metric):
                    continue
                for statistic in StatType:
                    spec = SurveySpecRow(
                        metric=metric,
                        statistic=statistic,
                        reference_value=9.0,
                        stat_value=5.0,
                        absolute=True,
                    )
                    _assert_spec(
                        f"7027 seq {diff_set.match_row.sequence_no} {metric} {statistic.value}",
                        diff_set,
                        spec,
                    )

    def test_hand_verified_crossline_average_on_first_sequence(self) -> None:
        diff_set = self.sets[0]
        values = metric_values_for_kind(diff_set.diff_rows, "crossline")
        self.assertTrue(values)
        expected = sum(abs(v) for v in values) / len(values)
        spec = SurveySpecRow(
            statistic=StatType.AVERAGE,
            metric="crossline",
            stat_value=99999.0,
            absolute=True,
        )
        result = evaluate_spec_for_sequence(diff_set, spec)
        assert result.computed is not None
        self.assertAlmostEqual(result.computed, expected, places=6)


if __name__ == "__main__":
    unittest.main()
