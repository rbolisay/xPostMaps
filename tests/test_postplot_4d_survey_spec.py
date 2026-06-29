"""Survey spec evaluation and Survey Specs table wiring."""

from __future__ import annotations

import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QDoubleSpinBox

from xpostmaps.core.postplot_4d_diff import Postplot4DDiffRow
from xpostmaps.core.postplot_4d_matching import Postplot4DMatchRow
from xpostmaps.core.postplot_4d_plot_data import SequenceDiffSet
from xpostmaps.core.postplot_4d_survey_spec import (
    Severity,
    StatType,
    SurveySpecRow,
    evaluate_spec_for_sequence,
    evaluate_survey_specs,
    stat_uses_absolute,
    stat_uses_reference,
)
from xpostmaps.ui.postplot_4d_stat_plot.survey_specs import SurveySpecsPanel

ROOT = Path(__file__).resolve().parents[1]
DB_7027 = ROOT / "data" / "7027.db"


def _ensure_qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _match_row(*, first_sp: int = 14700, last_sp: int = 14740) -> Postplot4DMatchRow:
    return Postplot4DMatchRow(
        baseline_name="Base",
        baseline_kind="preplot",
        line_name="51892113001",
        subline="",
        sequence_no="3001",
        first_sp=first_sp,
        last_sp=last_sp,
        line_direction="Up-line",
        sequence_id="file|3001|51892113001",
    )


def _diff_row(shotpoint: int, crossline: float, source_id: str = "001") -> Postplot4DDiffRow:
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
        inline_m=0.0,
        radial_m=0.0,
        navplan_feather_deg=None,
        line_feather_deg=None,
        firing_source_id=source_id,
    )


def _consecutive_failed_spec(
    *,
    stat_value: float = 5.0,
    reference_value: float = 9.0,
    absolute: bool = False,
) -> SurveySpecRow:
    return SurveySpecRow(
        metric="crossline",
        statistic=StatType.MAX_CONSECUTIVE_FAILED,
        reference_value=reference_value,
        stat_value=stat_value,
        absolute=absolute,
        severity=Severity.ERROR,
    )


class TestSurveySpecFailureDetection(unittest.TestCase):
    def test_negative_crossline_exceeding_metric_limit_counts_as_failed(self) -> None:
        """Reproduces user report: -9.559 m with Metric Limit 9 must fail a shot."""
        rows = [
            _diff_row(14730, -5.0),
            _diff_row(14731, -9.2),
            _diff_row(14732, -9.559),
            _diff_row(14733, -9.8),
            _diff_row(14734, -10.0),
            _diff_row(14735, -9.7),
            _diff_row(14736, -9.6),
        ]
        diff_set = SequenceDiffSet(match_row=_match_row(), diff_rows=rows)
        spec = _consecutive_failed_spec(absolute=False)

        result = evaluate_spec_for_sequence(diff_set, spec)

        self.assertIsNotNone(result.computed)
        assert result.computed is not None
        self.assertGreaterEqual(result.computed, 6.0)
        self.assertFalse(result.passed)

    def test_absolute_off_does_not_skip_negative_exceedances(self) -> None:
        rows = [_diff_row(100, -10.0)]
        diff_set = SequenceDiffSet(match_row=_match_row(first_sp=100, last_sp=100), diff_rows=rows)
        spec = _consecutive_failed_spec(stat_value=0.0, absolute=False)

        result = evaluate_spec_for_sequence(diff_set, spec)

        self.assertEqual(result.computed, 1.0)
        self.assertFalse(result.passed)

    def test_positive_crossline_exceeding_metric_limit_still_fails(self) -> None:
        rows = [_diff_row(100, 10.5)]
        diff_set = SequenceDiffSet(match_row=_match_row(first_sp=100, last_sp=100), diff_rows=rows)
        spec = _consecutive_failed_spec(stat_value=0.0)

        result = evaluate_spec_for_sequence(diff_set, spec)

        self.assertEqual(result.computed, 1.0)
        self.assertFalse(result.passed)

    def test_within_metric_limit_passes(self) -> None:
        rows = [_diff_row(100, -8.0), _diff_row(101, 8.0)]
        diff_set = SequenceDiffSet(
            match_row=_match_row(first_sp=100, last_sp=101), diff_rows=rows
        )
        spec = _consecutive_failed_spec(stat_value=5.0)

        result = evaluate_spec_for_sequence(diff_set, spec)

        self.assertEqual(result.computed, 0.0)
        self.assertTrue(result.passed)

    def test_max_pct_failure_uses_magnitude(self) -> None:
        rows = [_diff_row(100, -12.0), _diff_row(101, 1.0)]
        diff_set = SequenceDiffSet(
            match_row=_match_row(first_sp=100, last_sp=101), diff_rows=rows
        )
        spec = SurveySpecRow(
            metric="crossline",
            statistic=StatType.MAX_PCT_FAILURE,
            reference_value=9.0,
            stat_value=40.0,
            absolute=False,
        )

        result = evaluate_spec_for_sequence(diff_set, spec)

        self.assertEqual(result.computed, 50.0)
        self.assertFalse(result.passed)

    def test_average_respects_absolute_off(self) -> None:
        rows = [_diff_row(100, -4.0), _diff_row(101, 4.0)]
        diff_set = SequenceDiffSet(
            match_row=_match_row(first_sp=100, last_sp=101), diff_rows=rows
        )
        spec = SurveySpecRow(
            metric="crossline",
            statistic=StatType.AVERAGE,
            stat_value=1.0,
            absolute=False,
        )

        result = evaluate_spec_for_sequence(diff_set, spec)

        self.assertEqual(result.computed, 0.0)
        self.assertTrue(result.passed)

    def test_absolute_max_respects_absolute_on(self) -> None:
        rows = [_diff_row(100, -8.0), _diff_row(101, 3.0)]
        diff_set = SequenceDiffSet(
            match_row=_match_row(first_sp=100, last_sp=101), diff_rows=rows
        )
        spec = SurveySpecRow(
            metric="crossline",
            statistic=StatType.MAX_VALUE,
            stat_value=7.5,
            absolute=True,
            severity=Severity.WARNING,
        )

        result = evaluate_spec_for_sequence(diff_set, spec)

        self.assertEqual(result.computed, 8.0)
        self.assertFalse(result.passed)

    def test_excluded_shotpoints_break_consecutive_run(self) -> None:
        rows = [
            _diff_row(100, -10.0),
            _diff_row(101, -10.0),
            _diff_row(102, -10.0),
            _diff_row(103, -10.0),
            _diff_row(104, -10.0),
            _diff_row(105, -10.0),
        ]
        diff_set = SequenceDiffSet(
            match_row=_match_row(first_sp=100, last_sp=105), diff_rows=rows
        )
        spec = _consecutive_failed_spec(stat_value=4.0)

        result = evaluate_spec_for_sequence(
            diff_set, spec, excluded_shotpoints={102, 103}
        )

        self.assertEqual(result.computed, 2.0)
        self.assertTrue(result.passed)

    def test_error_severity_fails_sequence_evaluation(self) -> None:
        rows = [_diff_row(100 + i, -10.0) for i in range(6)]
        diff_set = SequenceDiffSet(
            match_row=_match_row(first_sp=100, last_sp=105), diff_rows=rows
        )
        spec = _consecutive_failed_spec(stat_value=4.0)
        evaluation = evaluate_survey_specs([diff_set], [spec])

        self.assertFalse(evaluation.accepted)

    def test_warning_severity_does_not_fail_sequence(self) -> None:
        rows = [_diff_row(100 + i, -10.0) for i in range(6)]
        diff_set = SequenceDiffSet(
            match_row=_match_row(first_sp=100, last_sp=105), diff_rows=rows
        )
        spec = _consecutive_failed_spec(stat_value=4.0)
        spec.severity = Severity.WARNING
        evaluation = evaluate_survey_specs([diff_set], [spec])

        self.assertTrue(evaluation.accepted)
        self.assertTrue(evaluation.has_warning)


class TestSurveySpecsPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = _ensure_qapp()

    def test_column_wiring_statistic_vs_metric_limit(self) -> None:
        panel = SurveySpecsPanel()
        panel.set_rows(
            [
                SurveySpecRow(
                    statistic=StatType.MAX_CONSECUTIVE_FAILED,
                    metric="crossline",
                    reference_value=9.0,
                    stat_value=5.0,
                )
            ]
        )
        stat_spin = panel._table.cellWidget(0, 1)
        reference_spin = panel._table.cellWidget(0, 3)
        assert isinstance(stat_spin, QDoubleSpinBox)
        assert isinstance(reference_spin, QDoubleSpinBox)
        self.assertEqual(stat_spin.value(), 5.0)
        self.assertEqual(reference_spin.value(), 9.0)

    def test_metric_limit_disabled_for_average(self) -> None:
        panel = SurveySpecsPanel()
        panel.set_rows([SurveySpecRow(statistic=StatType.AVERAGE)])
        reference_spin = panel._table.cellWidget(0, 3)
        assert isinstance(reference_spin, QDoubleSpinBox)
        self.assertFalse(reference_spin.isEnabled())

    def test_absolute_disabled_for_consecutive_failed(self) -> None:
        panel = SurveySpecsPanel()
        panel.set_rows([SurveySpecRow(statistic=StatType.MAX_CONSECUTIVE_FAILED)])
        abs_container = panel._table.cellWidget(0, 4)
        assert abs_container is not None
        abs_box = abs_container.findChild(QCheckBox)
        assert abs_box is not None
        self.assertFalse(abs_box.isEnabled())

    def test_absolute_enabled_for_absolute_max(self) -> None:
        panel = SurveySpecsPanel()
        panel.set_rows([SurveySpecRow(statistic=StatType.MAX_VALUE)])
        abs_container = panel._table.cellWidget(0, 4)
        assert abs_container is not None
        abs_box = abs_container.findChild(QCheckBox)
        assert abs_box is not None
        self.assertTrue(abs_box.isEnabled())

    def test_changing_statistic_updates_disabled_columns(self) -> None:
        panel = SurveySpecsPanel()
        panel.set_rows([SurveySpecRow(statistic=StatType.AVERAGE)])
        stat_combo = panel._table.cellWidget(0, 0)
        assert isinstance(stat_combo, QComboBox)
        index = stat_combo.findData(StatType.MAX_CONSECUTIVE_FAILED)
        self.assertGreaterEqual(index, 0)
        stat_combo.setCurrentIndex(index)

        reference_spin = panel._table.cellWidget(0, 3)
        abs_box = panel._table.cellWidget(0, 4).findChild(QCheckBox)
        assert isinstance(reference_spin, QDoubleSpinBox)
        assert abs_box is not None
        self.assertTrue(reference_spin.isEnabled())
        self.assertFalse(abs_box.isEnabled())

    def test_stat_helper_flags(self) -> None:
        self.assertTrue(stat_uses_reference(StatType.MAX_CONSECUTIVE_FAILED))
        self.assertFalse(stat_uses_reference(StatType.AVERAGE))
        self.assertTrue(stat_uses_absolute(StatType.MAX_VALUE))
        self.assertFalse(stat_uses_absolute(StatType.MAX_PCT_FAILURE))


@unittest.skipUnless(DB_7027.is_file(), f"database not found: {DB_7027}")
class TestSurveySpecReal7027(unittest.TestCase):
    def test_real_saved_sequence_evaluates_all_statistics(self) -> None:
        from xpostmaps.core.database import Database
        from xpostmaps.core.postplot_4d_matching import build_postplot_4d_rows

        db = Database(DB_7027)
        project_name = db.list_projects()[0]
        settings, map_data = db.load_project(project_name, with_positions=False)
        rows = build_postplot_4d_rows(map_data, settings, "preplot")
        saved = [
            row
            for row in rows
            if row.has_match
            and db.has_postplot_4d_diffs(project_name, row.baseline_kind, row.sequence_id)
        ]
        self.assertTrue(saved)

        match_row = saved[0]
        diff_rows = db.load_postplot_4d_diffs(
            project_name, match_row.baseline_kind, match_row.sequence_id
        )
        self.assertTrue(diff_rows)
        diff_set = SequenceDiffSet(match_row=match_row, diff_rows=diff_rows)

        for statistic in StatType:
            spec = SurveySpecRow(
                metric="crossline",
                statistic=statistic,
                reference_value=9.0,
                stat_value=5.0,
                absolute=True,
            )
            result = evaluate_spec_for_sequence(diff_set, spec)
            self.assertTrue(result.applicable)
            self.assertIsNotNone(result.computed)
            self.assertGreater(result.sample_count, 0)


if __name__ == "__main__":
    unittest.main()
