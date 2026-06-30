"""Regression guardrails for survey plot PDF/preview raster layout."""

from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage

_AERIAL_LEGEND_MIN_PX = 120
_AERIAL_LEGEND_WIDTH_RATIO = 0.14


def _legend_reserve_px(image_width: int) -> int:
    return max(
        _AERIAL_LEGEND_MIN_PX,
        int(round(image_width * _AERIAL_LEGEND_WIDTH_RATIO)),
    )


def _heatmap_sample_x1(image_width: int) -> int:
    """Right edge for heatmap-only sampling (exclude legend column)."""
    return max(1, image_width - _legend_reserve_px(image_width))


def _legend_sample_bounds(image_width: int) -> tuple[int, int]:
    """Region where the vertical colorbar is expected (not far-right padding)."""
    # PyQtGraph leaves white margin on the right at high DPI; the bar sits
    # in the middle of the legend column, not flush with the page edge.
    x0 = int(round(image_width * 0.52))
    x1 = int(round(image_width * 0.80))
    x0 = max(0, min(x0, image_width - 2))
    x1 = max(x0 + 1, min(x1, image_width - 4))
    return x0, x1


_MIN_AERIAL_THIRD_COLORED = 8
_MIN_AERIAL_CENTER_COLORED = 12
_MIN_AERIAL_HORIZONTAL_SPAN_RATIO = 0.45


def _is_white(color: QColor, *, threshold: int = 248) -> bool:
    return (
        color.red() >= threshold
        and color.green() >= threshold
        and color.blue() >= threshold
    )


def _sample_colored(
    image: QImage,
    x0: int,
    x1: int,
    y0: int,
    y1: int,
    *,
    step: int = 6,
) -> int:
    colored = 0
    for y in range(max(0, y0), max(0, y1), step):
        for x in range(max(0, x0), max(0, x1), step):
            if not _is_white(image.pixelColor(x, y)):
                colored += 1
    return colored


def _colored_horizontal_span(
    image: QImage,
    x0: int,
    x1: int,
    y0: int,
    y1: int,
    *,
    step: int = 8,
) -> int:
    xs: list[int] = []
    for y in range(max(0, y0), max(0, y1), step):
        for x in range(max(0, x0), max(0, x1), step):
            if not _is_white(image.pixelColor(x, y)):
                xs.append(x)
    if not xs:
        return 0
    return max(xs) - min(xs)


def survey_plot_content_region(image: QImage) -> tuple[int, int, int, int]:
    """Plot band below the PDF page header (x0, x1, y0, y1)."""
    width = image.width()
    height = image.height()
    margin = max(12, int(round(width * 0.012)))
    header_h = max(1, int(height * 0.14))
    return margin, width - margin, header_h + margin, height - margin


def validate_aerial_plot_body(
    image: QImage,
    *,
    page_key: str = "aerial",
) -> list[str]:
    """Validate a captured aerial plot body (heatmap + legend bitmap)."""
    if image.isNull():
        return [f"{page_key}: null image"]

    width = image.width()
    height = image.height()
    x0 = 0
    y0 = 0
    y1 = height
    data_x1 = _heatmap_sample_x1(width)
    plot_w = max(1, data_x1 - x0)
    legend_x0, legend_x1 = _legend_sample_bounds(width)

    left = _sample_colored(image, x0, x0 + plot_w // 3, y0, y1)
    center = _sample_colored(
        image,
        x0 + plot_w // 3,
        x0 + (2 * plot_w) // 3,
        y0,
        y1,
    )
    legend = _sample_colored(image, legend_x0, legend_x1, y0, y1)
    span = _colored_horizontal_span(image, x0, data_x1, y0, y1)
    min_span = int(plot_w * _MIN_AERIAL_HORIZONTAL_SPAN_RATIO)

    errors: list[str] = []
    if left < _MIN_AERIAL_THIRD_COLORED:
        errors.append(
            f"{page_key}: heatmap missing left coverage (left={left})"
        )
    if center < _MIN_AERIAL_CENTER_COLORED:
        errors.append(
            f"{page_key}: heatmap clustered too small (center={center}, need "
            f">={_MIN_AERIAL_CENTER_COLORED})"
        )
    if span < min_span:
        errors.append(
            f"{page_key}: heatmap horizontal span too narrow "
            f"(span={span}px, need >={min_span}px)"
        )
    if legend < _MIN_AERIAL_THIRD_COLORED:
        errors.append(f"{page_key}: color legend too sparse (legend={legend})")
    return errors


def validate_aerial_page_image(
    image: QImage,
    *,
    page_key: str = "aerial",
) -> list[str]:
    """Validate a composed PDF/preview page by checking its plot band."""
    if image.isNull():
        return [f"{page_key}: null image"]

    x0, x1, y0, y1 = survey_plot_content_region(image)
    body_w = max(1, x1 - x0)
    body_h = max(1, y1 - y0)
    plot_band = image.copy(QRect(x0, y0, body_w, body_h))
    return validate_aerial_plot_body(plot_band, page_key=page_key)
