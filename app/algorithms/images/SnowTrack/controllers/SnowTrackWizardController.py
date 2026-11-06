"""Wizard controller for the Snow Footprint Tracks algorithm.

Offers a guided choice of track type, GSD source and search aggressiveness,
and maps it onto the full option set the service and the main-window panel use.
"""

from PySide6.QtWidgets import QButtonGroup, QVBoxLayout, QWidget

from algorithms.AlgorithmController import AlgorithmController
from algorithms.images.SnowTrack.services.SnowTrackOptions import (
    DEFAULT_OPTIONS,
    GSD_MODE_AUTO,
    GSD_MODE_MANUAL,
    TRACK_PRESETS,
    TRACK_TYPE_BOOT,
    TRACK_TYPE_POSTHOLE,
    SnowTrackParams,
    closest_track_type,
)
from algorithms.images.SnowTrack.views.SnowTrackWizard_ui import Ui_SnowTrackWizard
from core.views.components.LabeledSlider import TextLabeledSlider

# Aggressiveness preset index -> (sensitivity, min_prints). The middle preset is
# the service default; more aggressive presets accept fainter prints and shorter
# trails (every trail must still beat the chance of lining up clutter).
AGGRESSIVENESS_PRESETS = (
    (2, 10),  # Very Conservative
    (4, 8),   # Conservative
    (5, 6),   # Moderate
    (7, 5),   # Aggressive
    (9, 4),   # Very Aggressive
)
DEFAULT_AGGRESSIVENESS = 2


class SnowTrackWizardController(QWidget, Ui_SnowTrackWizard, AlgorithmController):
    """Guided configuration for SnowTrack."""

    def __init__(self, config, theme):
        """Initialize the wizard page.

        Args:
            config (dict): Algorithm configuration dictionary.
            theme (str): Theme name (unused; part of the controller contract).
        """
        QWidget.__init__(self)
        AlgorithmController.__init__(self, config)
        self.theme = theme
        self.setupUi(self)
        self._wire_up_ui()

    def _wire_up_ui(self):
        """Group the radio buttons and attach the aggressiveness slider."""
        self._track_type_group = QButtonGroup(self)
        self._track_type_group.addButton(self.radioPosthole)
        self._track_type_group.addButton(self.radioBoot)
        self._gsd_group = QButtonGroup(self)
        self._gsd_group.addButton(self.radioGsdAuto)
        self._gsd_group.addButton(self.radioGsdManual)

        self.aggressivenessSlider = TextLabeledSlider(
            self,
            presets=[
                self.tr("Very \nConservative"),
                self.tr("Conservative"),
                self.tr("Moderate"),
                self.tr("Aggressive"),
                self.tr("Very \nAggressive"),
            ],
        )
        layout = QVBoxLayout(self.aggressivenessSliderPlaceholder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.aggressivenessSlider)
        self.aggressivenessSlider.setValue(DEFAULT_AGGRESSIVENESS)
        self.gsdSpinBox.setValue(DEFAULT_OPTIONS['gsd_cm'])

    def _track_type(self):
        return TRACK_TYPE_BOOT if self.radioBoot.isChecked() else TRACK_TYPE_POSTHOLE

    def get_options(self):
        """Translate the wizard answers into algorithm options.

        Returns:
            dict: Every service option, plus the wizard's own answers
            ('track_type', 'aggressiveness_index', 'aggressiveness_label') so
            the page can be restored exactly.
        """
        track_type = self._track_type()
        index = self.aggressivenessSlider.value()
        sensitivity, min_prints = AGGRESSIVENESS_PRESETS[index]
        label, _ = self.aggressivenessSlider.getCurrentPreset()

        options = dict(DEFAULT_OPTIONS)
        options.update(TRACK_PRESETS[track_type])
        options.update({
            'gsd_mode': GSD_MODE_MANUAL if self.radioGsdManual.isChecked() else GSD_MODE_AUTO,
            'gsd_cm': float(self.gsdSpinBox.value()),
            'sensitivity': sensitivity,
            'min_prints': min_prints,
            'track_type': track_type,
            'aggressiveness_index': index,
            'aggressiveness_label': label,
        })
        return options

    def validate(self):
        """Every combination of answers is valid.

        Returns:
            None
        """
        return None

    def load_options(self, options):
        """Restore the wizard answers from previously saved options.

        Options saved by the main-window panel carry no wizard answers; the
        closest track type and aggressiveness preset are inferred instead.

        Args:
            options (dict): Saved algorithm options.
        """
        if not isinstance(options, dict):
            return
        params = SnowTrackParams.from_options(options)

        track_type = options.get('track_type')
        if track_type not in TRACK_PRESETS:
            track_type = closest_track_type(params.print_diameter_cm)
        self.radioBoot.setChecked(track_type == TRACK_TYPE_BOOT)
        self.radioPosthole.setChecked(track_type != TRACK_TYPE_BOOT)

        self.radioGsdManual.setChecked(params.gsd_mode == GSD_MODE_MANUAL)
        self.radioGsdAuto.setChecked(params.gsd_mode != GSD_MODE_MANUAL)
        self.gsdSpinBox.setValue(params.gsd_cm)

        index = options.get('aggressiveness_index')
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(AGGRESSIVENESS_PRESETS):
            # Nearest preset by sensitivity; ties go to the more conservative one
            index = min(range(len(AGGRESSIVENESS_PRESETS)),
                        key=lambda i: abs(AGGRESSIVENESS_PRESETS[i][0] - params.sensitivity))
        self.aggressivenessSlider.setValue(index)
