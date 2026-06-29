"""Screen-aware layout policy for the main window (interactive UI only).

PDF export uses fixed print dimensions via ``RightPane.prepare_export_snapshot``;
this module never participates in export capture.
"""

from __future__ import annotations

from dataclasses import dataclass

# Design reference — layout the original UI was tuned for.
DESIGN_WIDTH = 1600
DESIGN_HEIGHT = 900

LEFT_PANEL_BASE = 320
RIGHT_PANE_BASE = 432
MINIMAP_BASE_HEIGHT = 215

MIN_LEFT_WIDTH = 220
MAX_LEFT_WIDTH = 320
MIN_RIGHT_WIDTH = 280
MAX_RIGHT_WIDTH = 432
MIN_MAP_WIDTH = 480

# Horizontal chrome: root margins + splitter handles + spacing.
HORIZONTAL_CHROME = 48
VERTICAL_CHROME = 72

MIN_UI_SCALE = 0.78
MAX_UI_SCALE = 1.0

MIN_WINDOW_WIDTH = MIN_LEFT_WIDTH + MIN_MAP_WIDTH + MIN_RIGHT_WIDTH + HORIZONTAL_CHROME
MIN_WINDOW_HEIGHT = 560


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def compute_ui_scale(available_width: int, available_height: int) -> float:
    """Uniform density scale from available client area (logical pixels)."""
    width = max(int(available_width), 1)
    height = max(int(available_height), 1)
    w_scale = width / DESIGN_WIDTH
    h_scale = height / DESIGN_HEIGHT
    return clamp(min(w_scale, h_scale), MIN_UI_SCALE, MAX_UI_SCALE)


@dataclass(frozen=True, slots=True)
class PanelLayout:
    """Recommended interactive panel sizes for the main splitter."""

    ui_scale: float
    left_width: int
    map_width: int
    right_width: int
    minimap_height: int
    logo_height: int
    right_text_scale: float


def _scaled_panel_width(base: int, ui_scale: float, min_w: int, max_w: int) -> int:
    return int(round(clamp(base * ui_scale, min_w, max_w)))


def compute_panel_layout(
    available_width: int,
    available_height: int,
    *,
    horizontal_chrome: int = HORIZONTAL_CHROME,
) -> PanelLayout:
    """Compute splitter sizes that protect map width on any screen."""
    _ = available_height  # reserved for future vertical density tuning
    ui_scale = compute_ui_scale(available_width, available_height)

    inner_w = max(int(available_width) - horizontal_chrome, MIN_MAP_WIDTH + MIN_LEFT_WIDTH + MIN_RIGHT_WIDTH)

    left = _scaled_panel_width(LEFT_PANEL_BASE, ui_scale, MIN_LEFT_WIDTH, MAX_LEFT_WIDTH)
    right = _scaled_panel_width(RIGHT_PANE_BASE, ui_scale, MIN_RIGHT_WIDTH, MAX_RIGHT_WIDTH)
    map_w = inner_w - left - right

    if map_w < MIN_MAP_WIDTH:
        deficit = MIN_MAP_WIDTH - map_w
        right_shrink = min(right - MIN_RIGHT_WIDTH, int(round(deficit * 0.55)))
        right -= right_shrink
        deficit -= right_shrink
        left_shrink = min(left - MIN_LEFT_WIDTH, deficit)
        left -= left_shrink
        map_w = inner_w - left - right

    if map_w < MIN_MAP_WIDTH:
        # Last resort on extremely narrow windows — shrink panels to mins.
        left = MIN_LEFT_WIDTH
        right = MIN_RIGHT_WIDTH
        map_w = max(inner_w - left - right, MIN_MAP_WIDTH // 2)

    pane_ratio = right / RIGHT_PANE_BASE
    minimap_h = int(round(MINIMAP_BASE_HEIGHT * clamp(pane_ratio, 0.78, 1.0)))
    logo_h = int(round(56 * clamp(pane_ratio, 0.78, 1.0)))
    text_scale = 1.2 * clamp(pane_ratio, 0.82, 1.0)

    return PanelLayout(
        ui_scale=ui_scale,
        left_width=left,
        map_width=map_w,
        right_width=right,
        minimap_height=minimap_h,
        logo_height=logo_h,
        right_text_scale=text_scale,
    )


def splitter_sizes(layout: PanelLayout) -> list[int]:
    """Sizes tuple for ``QSplitter.setSizes``."""
    return [layout.left_width, layout.map_width, layout.right_width]
