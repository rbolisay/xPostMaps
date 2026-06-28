"""Grid and scale-bar harmonization at true map scale."""

from __future__ import annotations

import math
from dataclasses import dataclass

# Standard cartographic "nice" steps (1–2–5 decades).
_NICE_STEPS = (1, 2, 5, 10)

# Scale bar always uses four segments in the postplot card layout.
SCALE_BAR_SEGMENTS = 4

# Even totals (m) divisible by 8 so labels read 0, total/2, total as whole even
# numbers (e.g. 0–8 km, 0–20 km, 0–200 m). Largest first.
_PREFERRED_TOTAL_M: tuple[float, ...] = (
    200_000,
    100_000,
    80_000,
    60_000,
    40_000,
    20_000,
    10_000,
    8_000,
    4_000,
    2_000,
    800,
    400,
    200,
    80,
    40,
    8,
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


def _snap_even_total_m(total_m: float, *, segments: int) -> float:
    """Snap to an even whole total divisible by 8 (even 0 / mid / end labels)."""
    minimum = float(max(segments * 2, 8))
    total_m = max(float(total_m), minimum)
    snapped = math.floor(total_m / 8.0) * 8.0
    return max(snapped, minimum)


def _snap_even_interval_m(interval_m: float) -> float:
    """Snap to an even whole interval (m)."""
    interval_m = max(float(interval_m), 2.0)
    return max(math.floor(interval_m / 2.0) * 2.0, 2.0)


def format_scale_distance_label(total_km: float) -> str:
    """Format a scale-bar distance using whole numbers only (no decimals)."""
    meters = int(round(total_km * 1000))
    if meters >= 1000 and meters % 1000 == 0:
        return f"{meters // 1000} km"
    return f"{meters} m"


def compute_pretty_grid_interval_m(
    span_m: float,
    *,
    segments: int = SCALE_BAR_SEGMENTS,
) -> float:
    """Pick a round even ground distance for major grid ticks across ``span_m``."""
    span_m = max(float(span_m), 1.0)
    target = span_m / max(int(segments), 1)
    return _snap_even_interval_m(_nice_number(target, round_up=True))


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


def zebra_segment_bounds_px(
    lo: float,
    hi: float,
    edge_lo: float,
    edge_hi: float,
    interval_m: float,
) -> list[float]:
    """Pixel boundaries for zebra segments — each full block equals one scale-bar division."""
    span = hi - lo
    axis_len = edge_hi - edge_lo
    if span <= 0 or axis_len <= 0 or interval_m <= 0:
        return [edge_lo, edge_hi]

    bounds = [edge_lo]
    start = math.ceil(lo / interval_m - 1e-12) * interval_m
    if start < lo - interval_m * 1e-9:
        start += interval_m
    value = start
    while value <= hi + interval_m * 1e-9:
        if lo - interval_m * 1e-9 <= value <= hi + interval_m * 1e-9:
            frac = (value - lo) / span
            px_pos = edge_lo + frac * axis_len
            if edge_lo + 0.5 < px_pos < edge_hi - 0.5:
                bounds.append(px_pos)
        value += interval_m
    bounds.append(edge_hi)
    return bounds


def scale_bar_total_km(interval_m: float, *, segments: int = SCALE_BAR_SEGMENTS) -> float:
    """Total scale-bar length matching ``segments`` grid intervals."""
    interval_m = max(float(interval_m), 1.0)
    return max(segments * interval_m / 1000.0, 0.001)


def _largest_preferred_total(
    meters_per_px: float,
    max_bar_width_px: float,
    *,
    segments: int,
    min_interval_m: float = 0.0,
) -> tuple[float, float, float] | None:
    """Return ``(interval_m, total_km, bar_width_px)`` for the largest preferred total that fits."""
    for total_m in _PREFERRED_TOTAL_M:
        interval_m = total_m / segments
        if min_interval_m > 0 and interval_m + 1e-9 < min_interval_m:
            continue
        bar_width_px = total_m / meters_per_px
        if bar_width_px <= max_bar_width_px + 0.5:
            return interval_m, total_m / 1000.0, bar_width_px
    return None


def _harmonization_from_interval(
    interval_m: float,
    *,
    segments: int,
    meters_per_px: float,
    max_bar_width_px: float,
) -> tuple[float, float, float]:
    """Build ``(interval_m, total_km, bar_width_px)`` keeping four equal segments."""
    interval_m = _snap_even_interval_m(interval_m)
    total_m = _snap_even_total_m(segments * interval_m, segments=segments)
    interval_m = total_m / segments
    bar_width_px = total_m / meters_per_px
    if bar_width_px > max_bar_width_px + 0.5:
        total_m = _snap_even_total_m(max_bar_width_px * meters_per_px, segments=segments)
        interval_m = total_m / segments
        bar_width_px = total_m / meters_per_px
    return interval_m, total_m / 1000.0, bar_width_px


def _pick_preferred_total(
    span_m: float,
    meters_per_px: float,
    max_bar_width_px: float,
    *,
    segments: int,
    min_interval_m: float,
) -> tuple[float, float, float] | None:
    """Prefer round even totals; only enforce ``min_interval_m`` when the zebra would crowd."""
    best = _largest_preferred_total(
        meters_per_px,
        max_bar_width_px,
        segments=segments,
        min_interval_m=0.0,
    )
    if best is None:
        return None
    interval_m, total_km, bar_w = best
    if span_m / interval_m <= _MAX_TICKS_PER_AXIS + 0.5:
        return best
    filtered = _largest_preferred_total(
        meters_per_px,
        max_bar_width_px,
        segments=segments,
        min_interval_m=min_interval_m,
    )
    return filtered if filtered is not None else best


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
    distance (each zebra block equals one scale-bar black/white segment).

    Scale-bar labels use whole even numbers only (e.g. 0–8 km, 0–200 m).
    """
    span_m = max(float(span_m), 1.0)
    map_width_px = max(float(map_width_px), 1.0)
    max_bar_width_px = max(float(max_bar_width_px), 40.0)
    meters_per_px = span_m / map_width_px

    min_interval_m = _snap_even_interval_m(
        _nice_number(span_m / _MAX_TICKS_PER_AXIS, round_up=False)
    )
    max_total_m = max_bar_width_px * meters_per_px
    max_interval_m = _snap_even_interval_m(
        _nice_number(max_total_m / max(int(segments), 1), round_up=False)
    )

    preferred = _pick_preferred_total(
        span_m,
        meters_per_px,
        max_bar_width_px,
        segments=segments,
        min_interval_m=min_interval_m,
    )

    if preferred is not None:
        interval_m, total_km, bar_width_px = preferred
    elif min_interval_m > max_interval_m:
        loose = _largest_preferred_total(
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
            interval_m, total_km, bar_width_px = _harmonization_from_interval(
                min_interval_m,
                segments=segments,
                meters_per_px=meters_per_px,
                max_bar_width_px=max_bar_width_px,
            )
    else:
        interval_m, total_km, bar_width_px = _harmonization_from_interval(
            max_interval_m,
            segments=segments,
            meters_per_px=meters_per_px,
            max_bar_width_px=max_bar_width_px,
        )

    return MapScaleHarmonization(
        interval_m=interval_m,
        total_km=total_km,
        bar_width_px=bar_width_px,
        map_width_px=map_width_px,
        span_m=span_m,
    )
