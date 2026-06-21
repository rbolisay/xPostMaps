"""Symbology unit tests and map clipping performance checks."""

from __future__ import annotations

import time

import numpy as np

from xpostmaps.utils.spatial_clip import SpatialGridIndex, build_coarse_preview, clip_arrays_to_bbox
from xpostmaps.utils.symbology_units import (
    DEFAULT_SCREEN_DPI,
    migrate_dot_radius_mm,
    migrate_line_width_mm,
    mm_to_pixels,
    scatter_size_px,
)


def test_legacy_pixel_migration_matches_qgis_scale() -> None:
    """Old 3 px radius and 1.2 px line map to ~0.8 mm / ~0.32 mm on screen."""
    radius_mm = migrate_dot_radius_mm(3.0)
    width_mm = migrate_line_width_mm(1.2)
    assert 0.7 <= radius_mm <= 0.9
    assert 0.25 <= width_mm <= 0.4


def test_mm_to_pixels_at_default_dpi() -> None:
    px = mm_to_pixels(DEFAULT_SCREEN_DPI, 1.0)
    assert 3.0 <= px <= 4.0


def test_scatter_size_uses_diameter() -> None:
    radius_mm = 0.8
    size_px = scatter_size_px(DEFAULT_SCREEN_DPI, radius_mm)
    expected = mm_to_pixels(DEFAULT_SCREEN_DPI, radius_mm * 2.0)
    assert abs(size_px - expected) < 0.01


def test_spatial_clip_matches_full_scan() -> None:
    n = 250_000
    xs = np.linspace(0.0, 50_000.0, n, dtype=np.float64)
    ys = np.sin(xs * 0.0003) * 1000.0
    xs = np.concatenate([xs, np.array([np.nan]), xs + 500.0])
    ys = np.concatenate([ys, np.array([np.nan]), ys + 250.0])
    bbox = (10_000.0, 20_000.0, -500.0, 500.0)
    grid = SpatialGridIndex(xs, ys)

    full_x, full_y = clip_arrays_to_bbox(xs, ys, bbox, kind="line", grid=None)
    fast_x, fast_y = clip_arrays_to_bbox(xs, ys, bbox, kind="line", grid=grid)

    assert full_x.shape == fast_x.shape
    assert np.allclose(full_x, fast_x, equal_nan=True)
    assert np.allclose(full_y, fast_y, equal_nan=True)


def test_spatial_clip_performance_under_one_second() -> None:
    """2M-point clip with spatial index should stay well under 1 s (QGIS-class snappy)."""
    n = 2_000_000
    xs = np.linspace(0.0, 100_000.0, n, dtype=np.float64)
    ys = (xs * 0.001) % 1000.0
    bbox = (40_000.0, 60_000.0, 200.0, 800.0)
    grid = SpatialGridIndex(xs, ys)
    assert grid.use_index

    start = time.perf_counter()
    clip_arrays_to_bbox(xs, ys, bbox, kind="scatter", grid=grid)
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0, f"clip took {elapsed:.3f}s, expected < 1.0s"


def test_coarse_preview_caps_vertices() -> None:
    xs = np.arange(500_000, dtype=np.float64)
    ys = np.sin(xs * 0.001)
    cx, cy = build_coarse_preview(xs, ys, max_points=4_000)
    assert cx.size <= 4_000


if __name__ == "__main__":
    tests = [
        test_legacy_pixel_migration_matches_qgis_scale,
        test_mm_to_pixels_at_default_dpi,
        test_scatter_size_uses_diameter,
        test_spatial_clip_matches_full_scan,
        test_spatial_clip_performance_under_one_second,
        test_coarse_preview_caps_vertices,
    ]
    for test in tests:
        name = test.__name__
        test()
        print(f"PASS {name}")
    print("All symbology and performance checks passed.")
