"""Regression tests: the PDF export scale bar stays at true map scale.

The export pane is widened by ``_EXPORT_WIDTH_SCALE`` only to give the minimap and
legend more horizontal room. The map and pane are scaled to the *same* height in the
PDF layout, so the scale bar must keep the live (true-scale) ``bar_width_px``. Scaling
the bar by the pane-width factor would make a "40 km" bar span ~54 km of map (the
1.35 factor that caused a 100 km line to read ~74 km).
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from xpostmaps.ui.right_pane import RightPane


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _drawn_bar_width_px(pane: RightPane) -> float:
    return float(pane._card._scale._bar_width_px)


def test_export_scale_bar_uses_live_true_scale_width(qapp) -> None:
    pane = RightPane()
    pane._harm_total_km = 40.0
    pane._harm_bar_width_px = 200.0

    pane.apply_export_scale_bar()

    # The bar must be the live true-scale width, NOT widened by the pane factor.
    assert _drawn_bar_width_px(pane) == pytest.approx(200.0, rel=1e-9)
    assert _drawn_bar_width_px(pane) != pytest.approx(
        200.0 * RightPane._EXPORT_WIDTH_SCALE, rel=1e-9
    )


def test_export_and_live_scale_bar_widths_match(qapp) -> None:
    pane = RightPane()
    pane._harm_total_km = 20.0
    pane._harm_bar_width_px = 137.0

    pane.apply_export_scale_bar()
    export_width = _drawn_bar_width_px(pane)

    pane.restore_live_scale_bar()
    live_width = _drawn_bar_width_px(pane)

    assert export_width == pytest.approx(live_width, rel=1e-9)
