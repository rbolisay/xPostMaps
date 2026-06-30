"""Tests for editable survey plot titles."""

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from xpostmaps.ui.postplot_4d_survey_plots.survey_plot_title_edit import SurveyPlotTitleEdit


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_reset_default_sets_display_and_default(qapp) -> None:
    edit = SurveyPlotTitleEdit()
    edit.reset_default("Default Aerial Title")
    assert edit.default_text() == "Default Aerial Title"
    assert edit.title_text() == "Default Aerial Title"
    assert not edit.is_customized()


def test_user_edit_is_customized_and_preserved_on_reload_same_key(qapp) -> None:
    edit = SurveyPlotTitleEdit()
    edit.reset_default("Original")
    edit.setText("My Custom Title")
    assert edit.is_customized()
    assert edit.title_text() == "My Custom Title"


def test_reset_default_on_new_survey_load(qapp) -> None:
    edit = SurveyPlotTitleEdit()
    edit.reset_default("Survey A")
    edit.setText("Edited A")
    edit.reset_default("Survey B")
    assert edit.title_text() == "Survey B"
    assert not edit.is_customized()
