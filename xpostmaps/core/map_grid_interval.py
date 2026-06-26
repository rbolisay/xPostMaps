"""Grid and scale-bar harmonization at true map scale."""

from __future__ import annotations

import math
from dataclasses import dataclass

# Standard cartographic "nice" steps (1–2–5 decades).
_NICE_STEPS = (1, 2, 5, 10)

# Scale bar always uses four segments in the postplot card layout.
SCALE_BAR_SEGMENTS = 4

# Prefer these totals (km) so the bar shows round values like 0–40 km, not 0–8 km.
_PREFERRED_TOTAL_KM = (
    100.0,
    50.0,
    40.0,
    20.0,
    10.0,
    8.0,
    5.0,
    4.0,
    2.0,
    1.0,
)

# Keep the zebra neatline and coordinate labels readable when zoomed in.
_MAX_TICKS_PER_AXIS = 6


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


def _largest_preferred_total_km(
    meters_per_px: float,
    max_bar_width_px: float,
    *,
    segments: int,
    min_interval_m: float = 0.0,
) -> tuple[float, float, float] | None:
    """Return ``(interval_m, total_km, bar_width_px)`` for the largest preferred total that fits."""
    for total_km in _PREFERRED_TOTAL_KM:
        interval_m = (total_km * 1000.0) / segments
        if min_interval_m > 0 and interval_m + 1e-9 < min_interval_m:
            continue
        bar_width_px = (total_km * 1000.0) / meters_per_px
        if bar_width_px <= max_bar_width_px + 0.5:
            return interval_m, total_km, bar_width_px
    return None


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

    Prefers round totals such as 40 km over 8 km when both fit, and avoids
    overcrowding the zebra border when zoomed in.
    """
    span_m = max(float(span_m), 1.0)
    map_width_px = max(float(map_width_px), 1.0)
    max_bar_width_px = max(float(max_bar_width_px), 40.0)
    meters_per_px = span_m / map_width_px

    min_interval_m = _nice_number(span_m / _MAX_TICKS_PER_AXIS, round_up=False)
    max_total_m = max_bar_width_px * meters_per_px
    max_interval_m = _nice_number(max_total_m / max(int(segments), 1), round_up=False)

    preferred = _largest_preferred_total_km(
        meters_per_px,
        max_bar_width_px,
        segments=segments,
        min_interval_m=min_interval_m,
    )
    if preferred is None:
        loose = _largest_preferred_total_km(
            meters_per_px,
            max_bar_width_px,
            segments=segments,
            min_interval_m=0.0,
        )
        if loose is not None:
            interval_m_loose, total_km_loose, _bar_w = loose
            ticks_across = span_m / interval_m_loose
            if (
                interval_m_loose + 1e-9 >= min_interval_m
                or ticks_across <= _MAX_TICKS_PER_AXIS + 0.5
                or total_km_loose >= 20.0
            ):
                preferred = loose

    if preferred is not None:
        interval_m, total_km, bar_width_px = preferred
    elif min_interval_m > max_interval_m:
        loose = _largest_preferred_total_km(
            meters_per_px,
            max_bar_width_px,
            segments=segments,
            min_interval_m=0.0,
        )
        if loose is not None and (
            loose[1] >= 10.0 or loose[0] + 1e-9 >= min_interval_m
        ):
            interval_m, total_km, bar_width_px = loose
        else:
            interval_m = min_interval_m
            bar_width_px = max_bar_width_px
            total_km = (bar_width_px * meters_per_px) / 1000.0
    else:
        interval_m = max_interval_m
        total_m = segments * interval_m
        bar_width_px = total_m / meters_per_px
        if bar_width_px > max_bar_width_px + 0.5:
            bar_width_px = max_bar_width_px
            total_m = bar_width_px * meters_per_px
            interval_m = max(total_m / segments, 1.0)
        total_km = total_m / 1000.0

    return MapScaleHarmonization(
        interval_m=interval_m,
        total_km=total_km,
        bar_width_px=bar_width_px,
        map_width_px=map_width_px,
        span_m=span_m,
    )
