"""Background spatial tile geometry build for GPU-resident line layers."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from xpostmaps.utils.spatial_clip import SpatialGridIndex, _TILE_TARGET_POINTS_PER_CELL
from xpostmaps.utils.spatial_tiles import SpatialLineTile, build_spatial_line_tile_vertex


class MapTileSignals(QObject):
    finished = Signal(int, int, object)


class MapTileBuildTask(QRunnable):
    """Build grid-cell line tiles off the UI thread."""

    def __init__(
        self,
        generation: int,
        layer_id: int,
        index_x: np.ndarray,
        index_y: np.ndarray,
        keys: list[tuple[int, int]],
        signals: MapTileSignals,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._generation = generation
        self._layer_id = layer_id
        self._index_x = index_x
        self._index_y = index_y
        self._keys = keys
        self._signals = signals

    def run(self) -> None:
        grid = SpatialGridIndex(
            self._index_x,
            self._index_y,
            target_points_per_cell=_TILE_TARGET_POINTS_PER_CELL,
        )
        built: list[tuple[tuple[int, int], SpatialLineTile]] = []
        for key in self._keys:
            tile = build_spatial_line_tile_vertex(
                self._index_x,
                self._index_y,
                grid,
                key,
            )
            if tile is not None:
                built.append((key, tile))
        self._signals.finished.emit(self._generation, self._layer_id, built)


class MapTileWorker:
    """Submit tile-build jobs; discard stale results via generation counter."""

    def __init__(self, parent: QObject | None = None) -> None:
        self._signals = MapTileSignals(parent)
        self._pool = QThreadPool.globalInstance()
        self._generation = 0

    @property
    def signals(self) -> MapTileSignals:
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
        layer_id: int,
        keys: list[tuple[int, int]],
        index_x: np.ndarray,
        index_y: np.ndarray,
    ) -> None:
        if not keys:
            return
        task = MapTileBuildTask(
            generation,
            layer_id,
            index_x,
            index_y,
            keys,
            self._signals,
        )
        self._pool.start(task)
