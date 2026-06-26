"""Tests for grid / scale-bar harmonization at true map scale."""

from __future__ import annotations

import math

import pytest

from xpostmaps.core.map_grid_interval import (
    SCALE_BAR_SEGMENTS,
    compute_map_scale_harmonization,
    compute_pretty_grid_interval_m,
    scale_bar_total_km,
    ticks_for_interval,
)


@pytest.mark.parametrize(
    ("span_m", "expected_interval_m"),
    [
        (40_000, 10_000),
        (37_000, 10_000),
        (8_000, 2_000),
        (800, 200),
    ],
)
def test_compute_pretty_grid_interval(span_m: float, expected_interval_m: float) -> None:
    interval = compute_pretty_grid_interval_m(span_m, segments=SCALE_BAR_SEGMENTS)
    assert interval == expected_interval_m


def test_scale_bar_total_matches_segments() -> None:
    interval_m = 5_000
    assert scale_bar_total_km(interval_m) == 20.0


def test_ticks_for_interval_aligns_to_grid() -> None:
    ticks = ticks_for_interval(698_500, 701_500, 1_000)
    assert ticks == [699_000.0, 700_000.0, 701_000.0]


def test_true_scale_bar_matches_map_ratio() -> None:
    span_m = 200_000.0
    map_px = 1000.0
    max_bar_px = 400.0
    harm = compute_map_scale_harmonization(span_m, map_px, max_bar_px)
    assert harm.bar_width_px <= max_bar_px + 0.5
    map_km = span_m / 1000.0
    assert math.isclose(
        harm.bar_width_px / map_px,
        harm.total_km / map_km,
        rel_tol=1e-6,
    )
    assert math.isclose(
        harm.total_km * 1000.0 / harm.interval_m,
        SCALE_BAR_SEGMENTS,
        rel_tol=1e-6,
    )


def test_segment_interval_matches_grid() -> None:
    harm = compute_map_scale_harmonization(40_000, 800, 350)
    assert harm.interval_m > 0
    assert harm.total_km == pytest.approx(
        SCALE_BAR_SEGMENTS * harm.interval_m / 1000.0,
        rel=1e-6,
    )
