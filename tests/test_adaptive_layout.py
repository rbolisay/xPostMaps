"""Tests for screen-aware main-window layout policy."""

from __future__ import annotations

from xpostmaps.ui.adaptive_layout import (
    DESIGN_HEIGHT,
    DESIGN_WIDTH,
    MIN_MAP_WIDTH,
    MIN_UI_SCALE,
    MAX_UI_SCALE,
    compute_panel_layout,
    compute_ui_scale,
)


def test_ui_scale_full_design_reference():
    assert compute_ui_scale(DESIGN_WIDTH, DESIGN_HEIGHT) == MAX_UI_SCALE


def test_ui_scale_shrinks_on_small_laptop():
    # 1536×960 logical (3840×2400 @ 250% Windows scaling).
    scale = compute_ui_scale(1536, 960)
    assert MIN_UI_SCALE <= scale < MAX_UI_SCALE


def test_panel_layout_protects_map_width_on_narrow_screen():
    layout = compute_panel_layout(1536, 960)
    assert layout.map_width >= MIN_MAP_WIDTH // 2
    assert layout.left_width >= 220
    assert layout.right_width >= 280
    assert layout.left_width + layout.map_width + layout.right_width <= 1536


def test_panel_layout_full_size_on_large_monitor():
    layout = compute_panel_layout(2560, 1440)
    assert layout.left_width == 320
    assert layout.right_width == 432
    assert layout.ui_scale == MAX_UI_SCALE


def test_minimap_scales_with_right_pane():
    small = compute_panel_layout(1280, 800)
    large = compute_panel_layout(2560, 1440)
    assert small.minimap_height <= large.minimap_height
