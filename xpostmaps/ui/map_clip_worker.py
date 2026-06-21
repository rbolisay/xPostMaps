"""Background view clipping for large map layers."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from xpostmaps.utils.spatial_clip import clip_and_prepare_items, prepare_motion_lod


class MapClipSignals(QObject):
    finished = Signal(int, object, object)
    motion_prepared = Signal(int, object)


class PrepareMotionTask(QRunnable):
    """Precompute RDP motion LOD for dense line layers off the UI thread."""

    def __init__(
        self,
        generation: int,
        items: list[dict],
        signals: MapClipSignals,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._generation = generation
        self._items = items
        self._signals = signals

    def run(self) -> None:
        results = prepare_motion_lod(self._items)
        self._signals.motion_prepared.emit(self._generation, results)


class MapClipTask(QRunnable):
    """Clip registered map items to a padded view bounding box off the UI thread."""

    def __init__(
        self,
        generation: int,
        items: list[dict],
        bbox: tuple[float, float, float, float],
        signals: MapClipSignals,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._generation = generation
        self._items = items
        self._bbox = bbox
        self._signals = signals

    def run(self) -> None:
        results = clip_and_prepare_items(self._items, self._bbox)
        self._signals.finished.emit(self._generation, self._bbox, results)


class MapClipWorker:
    """Submit clip jobs and discard stale results via a monotonic generation counter."""

    def __init__(self, parent: QObject | None = None) -> None:
        self._signals = MapClipSignals(parent)
        self._pool = QThreadPool.globalInstance()
        self._generation = 0

    @property
    def signals(self) -> MapClipSignals:
        return self._signals

    def next_generation(self) -> int:
        self._generation += 1
        return self._generation

    @property
    def generation(self) -> int:
        return self._generation

    def submit(
        self,
        generation: int,
        items: list[dict],
        bbox: tuple[float, float, float, float],
    ) -> None:
        task = MapClipTask(generation, items, bbox, self._signals)
        self._pool.start(task)

    def submit_prepare_motion(
        self,
        generation: int,
        items: list[dict],
    ) -> None:
        task = PrepareMotionTask(generation, items, self._signals)
        self._pool.start(task)
