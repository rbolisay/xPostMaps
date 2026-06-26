"""QGIS-style symbology sizes in millimeters (canvas / print units)."""

from __future__ import annotations

MM_PER_INCH = 25.4
DEFAULT_SCREEN_DPI = 96.0
PDF_EXPORT_DPI = 300.0
MIN_SCATTER_PX = 1.0
MIN_LINE_PX = 0.75

# Values at/above 0.6 up to 12 were stored as screen pixels before mm symbology.
_LEGACY_LINE_WIDTH_PX_MIN = 0.6
_LEGACY_LINE_WIDTH_PX_MAX = 12.0
_LEGACY_DOT_RADIUS_PX_CUTOFF = 2.5


def mm_to_pixels(dpi: float, mm: float) -> float:
    """Convert millimeters to device pixels at ``dpi``."""
    if mm <= 0.0:
        return MIN_LINE_PX
    return max(MIN_LINE_PX, mm * dpi / MM_PER_INCH)


def scatter_size_px(dpi: float, radius_mm: float) -> float:
    """ScatterPlotItem ``size`` is diameter in pixels when ``pxMode=True``."""
    diameter_mm = max(radius_mm * 2.0, 0.1)
    return max(MIN_SCATTER_PX, mm_to_pixels(dpi, diameter_mm))


def migrate_line_width_mm(value: float) -> float:
    """Convert legacy pixel line widths from older projects to millimeters."""
    if value <= 0.0:
        return 0.35
    if value < _LEGACY_LINE_WIDTH_PX_MIN:
        return value
    if value <= _LEGACY_LINE_WIDTH_PX_MAX:
        return max(0.1, value / (DEFAULT_SCREEN_DPI / MM_PER_INCH))
    return value


def migrate_dot_radius_mm(value: float) -> float:
    """Convert legacy pixel scatter radius from older projects to millimeters."""
    if value <= 0.0:
        return 0.8
    if value > _LEGACY_DOT_RADIUS_PX_CUTOFF:
        diameter_px = value * 2.0
        diameter_mm = diameter_px / (DEFAULT_SCREEN_DPI / MM_PER_INCH)
        return max(0.1, diameter_mm * 0.5)
    return value


def migrate_dash_length_mm(value: float) -> float:
    """Dash length is stored directly in millimeters (slider tenths-of-mm).

    Unlike scatter radius it must NOT pass through the legacy dot-radius diameter
    math, which would shrink the pattern until the dashes collapse into a solid
    stroke. Only clamp non-positive values to a sensible default.
    """
    if value <= 0.0:
        return 3.0
    return float(value)


def widget_screen_dpi(widget) -> float:
    """Best-effort logical DPI for the widget's screen."""
    try:
        window = widget.window() if widget is not None else None
        target = window or widget
        if target is not None:
            screen = target.screen()
            if screen is not None:
                dpi = float(screen.logicalDotsPerInch())
                if dpi > 0.0:
                    return dpi
    except Exception:  # noqa: BLE001
        pass
    return DEFAULT_SCREEN_DPI


def metric_slider_to_mm(slider_value: int) -> float:
    """Legend sliders store tenths of a millimeter."""
    return max(0.1, slider_value / 10.0)


def mm_to_metric_slider(mm: float, minimum: int, maximum: int) -> int:
    return int(max(minimum, min(maximum, round(mm * 10.0))))
