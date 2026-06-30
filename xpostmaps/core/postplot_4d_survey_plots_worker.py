"""Background load of survey-wide 4D Stat diffs from the project database."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from xpostmaps.core.database import Database
from xpostmaps.core.postplot_4d_matching import Postplot4DMatchRow, sequence_sort_key
from xpostmaps.core.postplot_4d_plot_data import PlotKind, SequenceDiffSet
from xpostmaps.core.postplot_4d_survey_plot_cache import (
    compute_source_fingerprint,
    deserialize_survey_plot_cache,
    merge_cache_with_sets,
    serialize_survey_plot_cache,
)
from xpostmaps.core.postplot_4d_survey_plot_data import (
    SurveyPlotsLoadResult,
    available_survey_plot_kinds,
    build_survey_aerial_heatmap_cache,
    build_survey_histogram_cache,
    build_survey_metrics_cache,
    infer_streamers_detected,
    survey_spec_pie_charts,
)

__all__ = ["SurveyPlotsLoadResult", "SurveyPlotsLoadWorker"]


class SurveyPlotsLoadWorker(QThread):
    """Load survey plots, using a DB cache when available and refreshing when stale."""

    progress = Signal(str)
    cached_ready = Signal(object)
    finished_ok = Signal(object)
    finished_failed = Signal(str)

    def __init__(
        self,
        db_path: Path | str,
        project_name: str,
        baseline_kind: str,
        match_rows: list[Postplot4DMatchRow],
        *,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._db_path = Path(db_path)
        self._project_name = project_name.strip()
        self._baseline_kind = baseline_kind
        self._match_rows = list(match_rows)

    def _load_sets(
        self,
        database: Database,
    ) -> tuple[list[SequenceDiffSet], int] | None:
        match_by_id = {
            row.sequence_id: row
            for row in self._match_rows
            if row.has_match and row.sequence_id
        }
        grouped = database.load_all_postplot_4d_diffs_plot_lite(
            self._project_name,
            self._baseline_kind,
        )
        sets: list[SequenceDiffSet] = []
        shotpoint_count = 0
        for sequence_id, diff_rows in grouped.items():
            match_row = match_by_id.get(sequence_id)
            if match_row is None or not diff_rows:
                continue
            sets.append(SequenceDiffSet(match_row=match_row, diff_rows=diff_rows))
            shotpoint_count += len(diff_rows)
        if not sets:
            return None
        sets.sort(key=lambda item: sequence_sort_key(item.match_row))
        return sets, shotpoint_count

    def _compute_result(
        self,
        sets: list[SequenceDiffSet],
        shotpoint_count: int,
    ) -> SurveyPlotsLoadResult:
        streamers = infer_streamers_detected(sets)
        available = available_survey_plot_kinds(
            sets,
            streamers_detected=streamers,
        )
        metric_values = build_survey_metrics_cache(sets, available)
        self.progress.emit("Building aerial heatmaps…")
        heatmap_cache = build_survey_aerial_heatmap_cache(sets, available)
        histogram_cache = build_survey_histogram_cache(metric_values, available)
        self.progress.emit("Evaluating survey specs…")
        pie_charts = survey_spec_pie_charts(sets, metric_cache=metric_values)
        return SurveyPlotsLoadResult(
            sets=sets,
            streamers_detected=streamers,
            available_kinds=available,
            metric_values=metric_values,
            heatmap_cache=heatmap_cache,
            histogram_cache=histogram_cache,
            pie_charts=pie_charts,
            sequence_count=len(sets),
            shotpoint_count=shotpoint_count,
        )

    def run(self) -> None:
        try:
            if self.isInterruptionRequested():
                return
            database = Database(self._db_path)
            sequence_ids = sorted(
                row.sequence_id
                for row in self._match_rows
                if row.has_match and row.sequence_id
            )
            diff_signature = database.survey_plot_diff_signature(
                self._project_name,
                self._baseline_kind,
                sequence_ids,
            )
            fingerprint = compute_source_fingerprint(
                baseline_kind=self._baseline_kind,
                match_rows=self._match_rows,
                diff_signature=diff_signature,
            )

            cached_blob = database.load_survey_plot_cache(
                self._project_name,
                self._baseline_kind,
            )
            cached_record = (
                deserialize_survey_plot_cache(cached_blob)
                if cached_blob
                else None
            )

            self.progress.emit("Loading saved 4D Stat data from project database…")
            loaded = self._load_sets(database)
            if loaded is None:
                self.finished_failed.emit(
                    "No saved 4D Stat data found for the current baseline."
                )
                return
            sets, shotpoint_count = loaded

            if cached_record is not None and cached_record.heatmap_cache:
                cached_result = merge_cache_with_sets(
                    cached_record,
                    SurveyPlotsLoadResult(
                        sets=sets,
                        streamers_detected=cached_record.streamers_detected,
                        available_kinds=list(cached_record.available_kinds),
                        metric_values=dict(cached_record.metric_values),
                        heatmap_cache=dict(cached_record.heatmap_cache),
                        histogram_cache=dict(cached_record.histogram_cache),
                        pie_charts=list(cached_record.pie_charts),
                        sequence_count=len(sets),
                        shotpoint_count=shotpoint_count,
                    ),
                )
                if cached_record.fingerprint != fingerprint:
                    self.cached_ready.emit(cached_result)
                    self.progress.emit(
                        "Updating survey plots for new or changed lines…"
                    )
                else:
                    self.finished_ok.emit(cached_result)
                    return

            if self.isInterruptionRequested():
                return
            self.progress.emit(
                f"Preparing survey metrics ({len(sets)} sequences)…"
            )
            result = self._compute_result(sets, shotpoint_count)
            database.save_survey_plot_cache(
                self._project_name,
                self._baseline_kind,
                fingerprint=fingerprint,
                payload=serialize_survey_plot_cache(result, fingerprint=fingerprint),
            )
            self.finished_ok.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.finished_failed.emit(str(exc))
