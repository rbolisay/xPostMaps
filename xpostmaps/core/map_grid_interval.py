"""Grid and scale-bar harmonization at true map scale."""

from __future__ import annotations

import math
from dataclasses import dataclass

# Standard cartographic "nice" steps (1–2–5 decades).
_NICE_STEPS = (1, 2, 5, 10)

# Scale bar always uses four segments in the postplot card layout.
SCALE_BAR_SEGMENTS = 4


@dataclass(frozen=True)
class MapScaleHarmonization:
    """Grid interval and scale-bar sizing tied to the visible map extent."""

    interval_m: float
    total_km: float
    bar_width_px: float
    map_width_px: float
    span_m: float


def _nice_number(value: float, *, round_up: bool) -> float:
    if value <= 0:
        return 1.0
    exponent = math.floor(math.log10(value))
    fraction = value / (10.0**exponent)
    steps = _NICE_STEPS if round_up else reversed(_NICE_STEPS)
    for step in steps:
        if round_up:
            if fraction <= step:
                return step * (10.0**exponent)
        elif fraction >= step:
            return step * (10.0**exponent)
    return 10.0 ** (exponent + 1)


def compute_pretty_grid_interval_m(
    span_m: float,
    *,
    segments: int = SCALE_BAR_SEGMENTS,
) -> float:
    """Pick a round ground distance for major grid ticks across ``span_m``."""
    span_m = max(float(span_m), 1.0)
    target = span_m / max(int(segments), 1)
    return _nice_number(target, round_up=True)


def ticks_for_interval(lo: float, hi: float, interval_m: float) -> list[float]:
    """Major tick values aligned to ``interval_m`` within ``[lo, hi]``."""
    interval_m = max(float(interval_m), 1.0)
    if hi <= lo:
        return []
    start = math.ceil(lo / interval_m) * interval_m
    ticks: list[float] = []
    value = start
    limit = hi + interval_m * 1.0e-9
    while value <= limit:
        if lo - interval_m * 1.0e-9 <= value <= hi + interval_m * 1.0e-9:
            ticks.append(value)
        value += interval_m
    return ticks


def scale_bar_total_km(interval_m: float, *, segments: int = SCALE_BAR_SEGMENTS) -> float:
    """Total scale-bar length matching ``segments`` grid intervals."""
    interval_m = max(float(interval_m), 1.0)
    return max(segments * interval_m / 1000.0, 0.001)


def compute_map_scale_harmonization(
    span_m: float,
    map_width_px: float,
    max_bar_width_px: float,
    *,
    segments: int = SCALE_BAR_SEGMENTS,
) -> MapScaleHarmonization:
    """Pick grid interval and a pane scale bar that fits at true map scale.

    ``bar_width_px / map_width_px == total_km / (span_m / 1000)`` so the same
    on-screen length on the map and on the scale bar represents the same ground
    distance (each segment equals one grid / zebra interval).
    """
    span_m = max(float(span_m), 1.0)
    map_width_px = max(float(map_width_px), 1.0)
    max_bar_width_px = max(float(max_bar_width_px), 40.0)
    meters_per_px = span_m / map_width_px

    max_total_m = max_bar_width_px * meters_per_px
    max_interval_m = max(max_total_m / max(int(segments), 1), 1.0)
    interval_m = max(_nice_number(max_interval_m, round_up=False), 1.0)

    total_m = segments * interval_m
    bar_width_px = total_m / meters_per_px

    if bar_width_px > max_bar_width_px + 0.5:
        total_m = max_bar_width_px * meters_per_px
        bar_width_px = max_bar_width_px
        interval_m = max(total_m / segments, 1.0)

    total_km = total_m / 1000.0
    return MapScaleHarmonization(
        interval_m=interval_m,
        total_km=total_km,
        bar_width_px=bar_width_px,
        map_width_px=map_width_px,
        span_m=span_m,
    )
