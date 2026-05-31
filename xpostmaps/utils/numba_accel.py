"""Numba-accelerated coordinate processing."""

from __future__ import annotations

import numpy as np
from numba import njit


@njit(cache=True)
def compute_bounds(xs: np.ndarray, ys: np.ndarray) -> tuple[float, float, float, float]:
    if xs.size == 0:
        return 0.0, 0.0, 0.0, 0.0
    return float(xs.min()), float(xs.max()), float(ys.min()), float(ys.max())


@njit(cache=True)
def infer_line_direction(point_nums: np.ndarray) -> int:
    """Return 1 for up-line, -1 for down-line based on point progression."""
    if point_nums.size < 2:
        return 1
    ascending = 0
    descending = 0
    for i in range(1, point_nums.size):
        if point_nums[i] > point_nums[i - 1]:
            ascending += 1
        elif point_nums[i] < point_nums[i - 1]:
            descending += 1
    return 1 if ascending >= descending else -1


@njit(cache=True)
def filter_valid_coords(xs: np.ndarray, ys: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mask = np.isfinite(xs) & np.isfinite(ys) & (xs != 0.0) & (ys != 0.0)
    return xs[mask], ys[mask]
