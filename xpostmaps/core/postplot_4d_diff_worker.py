"""Background worker for parallel Postplot 4D Diff Stat recalculation."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from xpostmaps.core.database import Database
from xpostmaps.core.models import (
    MapData,
    PositionRecord,
    ProjectSettings,
    RecordType,
    make_sequence_group_id,
    sequence_group_id,
)
from xpostmaps.core.postplot_4d_diff import (
    Postplot4DDiffRow,
    calculate_match_diff_rows,
    reset_postplot_4d_path_caches,
)
from xpostmaps.core.postplot_4d_matching import Postplot4DMatchRow

_MAX_DIFF_STAT_WORKERS = 8
_MAX_DB_LOAD_DIFF_STAT_WORKERS = 2
_PROGRESS_INTERVAL_S = 0.2


def diff_stat_worker_count(task_count: int) -> int:
    if task_count <= 1:
        return 1
    cpu_count = os.cpu_count() or 2
    return max(1, min(task_count, cpu_count, _MAX_DIFF_STAT_WORKERS))


@dataclass(frozen=True)
class DiffStatRecalcTaskResult:
    match_row: Postplot4DMatchRow
    row_count: int = 0
    error: str = ""


class Single4DStatCalcWorker(QThread):
    """Calculate saved 4D Stat rows for one matched sequence."""

    progress = Signal(str)
    finished_ok = Signal(object, float)
    finished_failed = Signal(str)
    finished_cancelled = Signal()

    def __init__(
        self,
        map_data_provider: Callable[[], MapData | None],
        settings: ProjectSettings,
        positions_provider: Callable[[], list[PositionRecord]],
        match_row: Postplot4DMatchRow,
        *,
        load_source_positions_from_db: bool = False,
        db_path: Path | None = None,
        project_name: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._map_data_provider = map_data_provider
        self._settings = settings
        self._positions_provider = positions_provider
        self._match_row = match_row
        self._load_source_positions_from_db = load_source_positions_from_db
        self._db_path = db_path
        self._project_name = project_name.strip()
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()
        self.requestInterruption()

    def _cancelled(self) -> bool:
        return self._cancel_event.is_set() or self.isInterruptionRequested()

    def run(self) -> None:
        started = time.perf_counter()
        db: Database | None = None
        try:
            reset_postplot_4d_path_caches()
            map_data = self._map_data_provider()
            if self._cancelled():
                self.finished_cancelled.emit()
                return

            self.progress.emit("Loading source positions…")
            if self._db_path is not None:
                db = Database(self._db_path)
                try:
                    db._conn.execute("PRAGMA busy_timeout=30000")
                except Exception:  # noqa: BLE001
                    pass

            if self._load_source_positions_from_db and db is not None and self._project_name:
                source_positions = db.load_source_positions_for_sequence_ids(
                    self._project_name,
                    [self._match_row.sequence_id],
                )
            else:
                source_positions = list(self._positions_provider())

            if self._cancelled():
                self.finished_cancelled.emit()
                return

            label = f"{self._match_row.baseline_name} -> {self._match_row.line_name}"
            self.progress.emit(f"Calculating 4D Stat for {label}…")
            rows = calculate_match_diff_rows(
                map_data,
                self._settings,
                source_positions,
                self._match_row,
                database=db,
                project_name=self._project_name,
            )
            if self._cancelled():
                self.finished_cancelled.emit()
                return

            if db is not None and self._project_name:
                db.save_postplot_4d_diffs(
                    self._project_name,
                    self._match_row.baseline_kind,
                    self._match_row.baseline_name,
                    self._match_row.sequence_id,
                    rows,
                )

            self.finished_ok.emit(rows, time.perf_counter() - started)
        except Exception as exc:  # noqa: BLE001
            self.finished_failed.emit(str(exc))
        finally:
            if db is not None:
                db.close()


class DiffStatRecalcWorker(QThread):
    progress = Signal(int, int, str)
    finished_batch = Signal(int, int, int, float, bool)

    def __init__(
        self,
        map_data_provider: Callable[[], MapData | None],
        settings: ProjectSettings,
        positions_provider: Callable[[], list[PositionRecord]],
        match_rows: list[Postplot4DMatchRow] | None = None,
        *,
        prepare_tasks: Callable[[Callable[[], bool]], tuple[list[Postplot4DMatchRow], int]] | None = None,
        positions_provider_for_matches: Callable[
            [list[Postplot4DMatchRow]],
            list[PositionRecord],
        ]
        | None = None,
        load_source_positions_per_match: bool = False,
        db_path: Path | None = None,
        project_name: str = "",
        skipped_count: int = 0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._map_data_provider = map_data_provider
        self._settings = settings
        self._positions_provider = positions_provider
        self._positions_provider_for_matches = positions_provider_for_matches
        self._load_source_positions_per_match = load_source_positions_per_match
        self._match_rows = list(match_rows or [])
        self._prepare_tasks = prepare_tasks
        self._db_path = db_path
        self._project_name = project_name
        self._skipped_count = skipped_count
        self._cancel_event = threading.Event()
        self._write_lock = threading.Lock()
        self._thread_local = threading.local()
        self._db_connections: list[Database] = []
        self._db_connections_lock = threading.Lock()
        self._last_progress_emit = 0.0

    def cancel(self) -> None:
        self._cancel_event.set()
        self.requestInterruption()

    def _cancelled(self) -> bool:
        return self._cancel_event.is_set() or self.isInterruptionRequested()

    def _thread_db(self) -> Database | None:
        if self._db_path is None:
            return None
        db = getattr(self._thread_local, "db", None)
        if db is None:
            db = Database(self._db_path)
            self._thread_local.db = db
            with self._db_connections_lock:
                self._db_connections.append(db)
        return db

    def _close_all_dbs(self) -> None:
        with self._db_connections_lock:
            for db in self._db_connections:
                db.close()
            self._db_connections.clear()

    def _build_source_index(
        self,
        positions: list[PositionRecord],
    ) -> dict[str, list[PositionRecord]]:
        by_group: dict[str, list[PositionRecord]] = {}
        for record in positions:
            if record.record_type != RecordType.SOURCE or record.point_num <= 0:
                continue
            group = make_sequence_group_id(
                record.file_name,
                record.sequence_no,
                record.line_name,
            )
            by_group.setdefault(group, []).append(record)
        return by_group

    def _positions_for_match(self, match_row: Postplot4DMatchRow) -> list[PositionRecord]:
        if not match_row.sequence_id:
            return []
        return self._source_positions_by_group.get(
            sequence_group_id(match_row.sequence_id),
            [],
        )

    def _emit_progress(self, completed: int, total: int, detail: str) -> None:
        now = time.perf_counter()
        if completed < total and now - self._last_progress_emit < _PROGRESS_INTERVAL_S:
            return
        self._last_progress_emit = now
        self.progress.emit(completed, total, detail)

    def _compute_and_persist(self, match_row: Postplot4DMatchRow) -> DiffStatRecalcTaskResult:
        if self._cancelled():
            return DiffStatRecalcTaskResult(match_row=match_row, error="cancelled")
        db = self._thread_db()
        try:
            if self._load_source_positions_per_match and db is not None:
                source_positions = db.load_source_positions_for_sequence_ids(
                    self._project_name,
                    [match_row.sequence_id],
                )
            else:
                source_positions = self._positions_for_match(match_row)
            rows = calculate_match_diff_rows(
                self._map_data,
                self._settings,
                source_positions,
                match_row,
                database=db,
                project_name=self._project_name,
            )
            if self._cancelled():
                return DiffStatRecalcTaskResult(match_row=match_row, error="cancelled")
            if db is not None and self._project_name.strip():
                with self._write_lock:
                    db.save_postplot_4d_diffs(
                        self._project_name.strip(),
                        match_row.baseline_kind,
                        match_row.baseline_name,
                        match_row.sequence_id,
                        rows,
                    )
            return DiffStatRecalcTaskResult(match_row=match_row, row_count=len(rows))
        except Exception as exc:  # noqa: BLE001
            return DiffStatRecalcTaskResult(match_row=match_row, error=str(exc))

    def _next_pending(
        self,
        pending_iter,
        futures: dict[Future[DiffStatRecalcTaskResult], Postplot4DMatchRow],
        executor: ThreadPoolExecutor,
        worker_count: int,
    ) -> None:
        while not self._cancelled() and len(futures) < worker_count:
            try:
                match_row = next(pending_iter)
            except StopIteration:
                return
            futures[executor.submit(self._compute_and_persist, match_row)] = match_row

    def run(self) -> None:
        started = time.perf_counter()
        recalculated = 0
        failed = 0
        skipped = self._skipped_count

        try:
            # Start from a clean slate so a fresh import/file change is picked
            # up, then reuse memoised path lookups across all matches in this run.
            reset_postplot_4d_path_caches()
            self._map_data = self._map_data_provider()

            if self._prepare_tasks is not None:
                self.progress.emit(0, 0, "Checking for stale 4D Stat rows…")
                pending, skipped = self._prepare_tasks(self._cancelled)
            else:
                pending = self._match_rows
                skipped = self._skipped_count

            if self._cancelled():
                self.finished_batch.emit(0, skipped, 0, time.perf_counter() - started, True)
                return

            if not pending:
                self.finished_batch.emit(0, skipped, 0, 0.0, False)
                return

            if self._load_source_positions_per_match and self._db_path is not None:
                self.progress.emit(0, len(pending), "Starting 4D Stat workers…")
                self._positions = []
                self._source_positions_by_group = {}
            else:
                self.progress.emit(0, len(pending), "Loading source positions…")
                if self._positions_provider_for_matches is not None:
                    self._positions = list(self._positions_provider_for_matches(pending))
                else:
                    self._positions = list(self._positions_provider())
                if self._cancelled():
                    self.finished_batch.emit(0, skipped, 0, time.perf_counter() - started, True)
                    return
                self.progress.emit(0, len(pending), "Indexing source positions…")
                self._source_positions_by_group = self._build_source_index(self._positions)

            worker_count = diff_stat_worker_count(len(pending))
            if self._load_source_positions_per_match and self._db_path is not None:
                worker_count = min(worker_count, _MAX_DB_LOAD_DIFF_STAT_WORKERS)
            completed = 0
            pending_iter = iter(pending)
            futures: dict[Future[DiffStatRecalcTaskResult], Postplot4DMatchRow] = {}

            executor = ThreadPoolExecutor(max_workers=worker_count)
            try:
                self._next_pending(pending_iter, futures, executor, worker_count)
                while futures and not self._cancelled():
                    done, _not_done = wait(
                        futures,
                        timeout=_PROGRESS_INTERVAL_S,
                        return_when=FIRST_COMPLETED,
                    )
                    if not done:
                        continue
                    for future in done:
                        match_row = futures.pop(future)
                        try:
                            result = future.result()
                        except Exception as exc:  # noqa: BLE001
                            result = DiffStatRecalcTaskResult(
                                match_row=match_row,
                                error=str(exc),
                            )

                        if result.error:
                            if result.error != "cancelled":
                                failed += 1
                        else:
                            recalculated += 1

                        completed += 1
                        self._emit_progress(
                            completed,
                            len(pending),
                            f"{match_row.baseline_name} -> {match_row.line_name}",
                        )
                    self._next_pending(pending_iter, futures, executor, worker_count)
            finally:
                executor.shutdown(wait=True, cancel_futures=True)
        finally:
            self._close_all_dbs()

        elapsed = time.perf_counter() - started
        self.finished_batch.emit(
            recalculated,
            skipped,
            failed,
            elapsed,
            self._cancelled(),
        )
