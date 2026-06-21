"""Benchmark pan/zoom cost drivers for the map widget."""

from __future__ import annotations

import sys
import time

import numpy as np

from xpostmaps.utils.spatial_clip import SpatialGridIndex, build_coarse_preview, clip_arrays_to_bbox


def _make_survey(n: int = 2_000_000) -> tuple[np.ndarray, np.ndarray]:
    xs = np.linspace(0.0, 100_000.0, n, dtype=np.float64)
    ys = np.sin(xs * 0.0003) * 500.0
    return xs, ys


def bench_clip(label: str, n: int, bbox: tuple[float, float, float, float]) -> float:
    xs, ys = _make_survey(n)
    grid = SpatialGridIndex(xs, ys)
    start = time.perf_counter()
    clip_arrays_to_bbox(xs, ys, bbox, kind="line", grid=grid)
    return time.perf_counter() - start


def bench_setdata_if_qt(max_points: int) -> float | None:
    try:
        from PySide6.QtWidgets import QApplication
        import pyqtgraph as pg
    except ImportError:
        return None

    app = QApplication.instance() or QApplication(sys.argv)
    n = max_points
    xs = np.linspace(0, 1000, n, dtype=np.float64)
    ys = np.sin(xs * 0.01)

    curve = pg.PlotCurveItem(xs, ys, antialias=False, skipFiniteCheck=True)
    curve.setSegmentedLineMode("off")

    start = time.perf_counter()
    curve.setData(xs, ys)
    elapsed = time.perf_counter() - start
    app.processEvents()
    return elapsed


def main() -> None:
    bbox = (40_000.0, 60_000.0, 200.0, 800.0)
    xs, ys = _make_survey(2_000_000)
    cx, cy = clip_arrays_to_bbox(xs, ys, bbox, kind="line", grid=SpatialGridIndex(xs, ys))
    coarse_x, coarse_y = build_coarse_preview(cx, cy, max_points=4_000)

    print("=== Pan/zoom bottleneck analysis ===")
    print(f"Settled view clip size: {cx.size:,} vertices")
    print(f"Coarse preview (4k cap): {coarse_x.size:,} vertices")
    print(f"Reduction factor:       {cx.size / max(coarse_x.size, 1):.1f}x")
    print()

    clip_2m = bench_clip("2M spatial clip", 2_000_000, bbox)
    print(f"Background clip (2M, spatial index): {clip_2m * 1000:.1f} ms")

    for n in (10_000, 50_000, 200_000, cx.size):
        t = bench_setdata_if_qt(min(n, cx.size if n == cx.size else n))
        if t is None:
            print("Qt setData benchmark skipped (PySide6 unavailable)")
            break
        print(f"PlotCurveItem.setData ({min(n, cx.size):,} pts): {t * 1000:.1f} ms")

    print()
    print("Highest-impact fixes applied:")
    print("  1. Coarse LOD (~4k pts) + DeviceCoordinateCache during pan")
    print("  2. Hide scatter shotpoints during motion")
    print("  3. Spatial-index clip off UI thread on settle")


if __name__ == "__main__":
    main()
