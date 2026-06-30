"""Tests for 4D Stat plot shotpoint selection helpers."""

from __future__ import annotations

import unittest

from xpostmaps.core.postplot_4d_survey_spec import merge_excluded_shotpoints_text
from xpostmaps.ui.postplot_4d_stat_plot.shotpoint_selection import (
    format_selection_overlay,
    group_selected_by_sequence,
    pick_points_in_rect,
    sequence_no_from_plot_source_key,
)


class TestShotpointSelectionHelpers(unittest.TestCase):
    def test_pick_points_in_rect(self) -> None:
        points = [
            (1460.0, 5.7, "G02"),
            (1462.0, 7.8, "G02"),
            (1470.0, 17.0, "G02"),
            (1471.0, 21.0, "G01"),
        ]
        keys = pick_points_in_rect(points, 1461, 0, 1472, 25)
        self.assertEqual(keys, [(1462, "G02"), (1470, "G02"), (1471, "G01")])

    def test_pick_points_in_rect_reverse_drag(self) -> None:
        points = [(1459.0, 12.1, "G01"), (1481.0, 14.5, "G01")]
        keys = pick_points_in_rect(points, 1485, 20, 1455, 10)
        self.assertEqual(keys, [(1459, "G01"), (1481, "G01")])

    def test_sequence_no_from_combined_key(self) -> None:
        self.assertEqual(
            sequence_no_from_plot_source_key("G01 \u00b7 Seq 070", "999"),
            "070",
        )
        self.assertEqual(sequence_no_from_plot_source_key("G01", "070"), "070")

    def test_group_selected_by_sequence(self) -> None:
        grouped = group_selected_by_sequence(
            [(1459, "G01"), (1471, "G01 \u00b7 Seq 070")],
            "070",
        )
        self.assertEqual(grouped["070"], {1459, 1471})

    def test_format_selection_overlay(self) -> None:
        text = format_selection_overlay([(1461, "G01"), (1463, "G01")])
        self.assertIn("2 shotpoints", text)
        self.assertIn("1461-1463", text)

    def test_merge_excluded_shotpoints_text(self) -> None:
        merged = merge_excluded_shotpoints_text("1459", {1461, 1462, 1463})
        self.assertIn("1459", merged)
        self.assertIn("1461", merged)
        self.assertIn("1463", merged)


if __name__ == "__main__":
    unittest.main()
