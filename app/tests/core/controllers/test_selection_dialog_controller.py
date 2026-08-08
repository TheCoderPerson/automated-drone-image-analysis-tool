from unittest.mock import patch

from core.controllers import SelectionDialog as selection_module
from core.controllers.SelectionDialog import SelectionDialog


def test_selection_dialog_runs_startup_update_check(qtbot):
    """The automatic update check is wired on the initial selection dialog.

    The prompt must appear before the user chooses Images / Real-time / Flight
    Viewer, so the UpdateController and its startup check live here rather than
    in MainWindow / StreamViewerWindow.
    """
    with patch.object(selection_module, "UpdateController") as mock_controller_cls, \
            patch.object(selection_module, "SettingsService") as mock_settings_cls:
        mock_settings = mock_settings_cls.return_value
        mock_settings.get_setting.return_value = "2.1.0 Beta 1"

        dialog = SelectionDialog("Dark")
        qtbot.addWidget(dialog)

    # Controller constructed with the dialog as parent so prompts are modal to it.
    mock_controller_cls.assert_called_once()
    _, kwargs = mock_controller_cls.call_args
    assert mock_controller_cls.call_args.args[0] is dialog
    assert kwargs["settings_service"] is mock_settings

    # The startup check is scheduled exactly once.
    dialog.update_controller.schedule_startup_check.assert_called_once_with()

    # app_version is sourced from settings for the version comparison / User-Agent.
    assert dialog.app_version == "2.1.0 Beta 1"


def test_selection_buttons_ordered_review_first(qtbot):
    """Review Results leads the launcher: reviewing a completed analysis is
    the most common entry, so its button comes before Image Analysis and
    Stream Analysis (field request)."""
    with patch.object(selection_module, "UpdateController"), \
            patch.object(selection_module, "SettingsService"):
        dialog = SelectionDialog("Dark")
        qtbot.addWidget(dialog)

    layout = dialog.horizontalLayout_2
    # The layout can also hold non-widget items (spacers); order only the
    # actual selection panels.
    widgets = [layout.itemAt(i).widget() for i in range(layout.count())]
    order = [w.objectName() for w in widgets if w is not None]
    assert order[:3] == ['resultsWidget', 'imageWidget', 'streamWidget']


def test_flight_viewer_button_hidden_when_feature_disabled(qtbot):
    """Flight Viewer visibility is gated: when
    FeatureFlags.FLIGHT_VIEWER_ENABLED is False the Selection dialog must
    hide its button so the feature is unreachable. The flag is patched
    explicitly so the gated-off path stays covered regardless of the
    shipping default."""
    with patch.object(selection_module.FeatureFlags, "FLIGHT_VIEWER_ENABLED", False), \
            patch.object(selection_module, "UpdateController"), \
            patch.object(selection_module, "SettingsService"):
        dialog = SelectionDialog("Dark")
        qtbot.addWidget(dialog)

    # The whole third column is hidden (not just the button), so it stops
    # consuming layout width. isHidden() reflects the explicit hide flag even
    # before the dialog is shown (isVisible() would be False either way).
    assert dialog.flightWidget.isHidden()
    assert dialog.streamWidget.isVisible() or not dialog.streamWidget.isHidden()
    # Dialog shrinks below the full design width (770). The exact width is
    # font/DPI-dependent (the heading label can set the floor), so assert the
    # relationship rather than a pixel value.
    assert dialog.width() < 770
    # Height is unchanged from the .ui design (two rows are identical).
    assert dialog.height() == 290


def test_flight_viewer_button_shown_when_feature_enabled(qtbot):
    """With the flag enabled the button is restored (the shipping path)."""
    with patch.object(selection_module.FeatureFlags, "FLIGHT_VIEWER_ENABLED", True), \
            patch.object(selection_module, "UpdateController"), \
            patch.object(selection_module, "SettingsService"):
        dialog = SelectionDialog("Dark")
        qtbot.addWidget(dialog)

    assert not dialog.flightWidget.isHidden()
    # Full four-tile layout keeps its designed size (Image / Review Results /
    # Stream / Flight Viewer).
    assert dialog.width() == 770


def test_flight_viewer_disabled_by_default():
    """Flight Viewer is held back from the current release build.

    This guards the shipping default in the same way the previous assertion
    guarded the enabled state: it catches an accidental flip, so re-enabling
    has to be a deliberate edit here and in helpers/FeatureFlags.py.
    """
    assert selection_module.FeatureFlags.FLIGHT_VIEWER_ENABLED is False


def test_review_results_tile_emits_selection(qtbot):
    """The Review Results tile records the choice and signals __main__.

    The dedicated signal fires after accept() so the handler constructs the
    MainWindow with the dialog already dismissed, mirroring the flight tile.
    """
    with patch.object(selection_module, "UpdateController"),             patch.object(selection_module, "SettingsService"):
        dialog = SelectionDialog("Dark")
        qtbot.addWidget(dialog)

    selections = []
    requested = []
    dialog.selectionMade.connect(selections.append)
    dialog.reviewResultsRequested.connect(lambda: requested.append(True))

    dialog.resultsButton.click()

    assert dialog.selection == "results"
    assert selections == ["results"]
    assert requested == [True]
