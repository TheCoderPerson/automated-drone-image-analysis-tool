"""Controller for the Snow Footprint Tracks algorithm panel in the main window."""

from PySide6.QtWidgets import QWidget

from algorithms.AlgorithmController import AlgorithmController
from algorithms.images.SnowTrack.services.SnowTrackOptions import (
    DEFAULT_OPTIONS,
    GSD_MODE_AUTO,
    GSD_MODE_MANUAL,
    SnowTrackParams,
)
from algorithms.images.SnowTrack.views.SnowTrack_ui import Ui_SnowTrack


class SnowTrackController(QWidget, Ui_SnowTrack, AlgorithmController):
    """Exposes every SnowTrack option: GSD source, gait geometry, cadence and sensitivity."""

    def __init__(self, config, theme):
        """Initialize the panel.

        Args:
            config (dict): Algorithm config information.
            theme (str): Name of the active theme (unused; part of the controller contract).
        """
        QWidget.__init__(self)
        AlgorithmController.__init__(self, config)
        self.setupUi(self)
        # Stable option values behind the translated combo labels (.ui item order)
        self.gsdModeComboBox.setItemData(0, GSD_MODE_AUTO)
        self.gsdModeComboBox.setItemData(1, GSD_MODE_MANUAL)
        self.fixComboBoxForMacOS(self.gsdModeComboBox)

        self.sensitivitySlider.valueChanged.connect(self._update_sensitivity_label)
        self.gsdModeComboBox.currentIndexChanged.connect(self._update_gsd_label)
        self.load_options(DEFAULT_OPTIONS)

    def _update_sensitivity_label(self):
        """Mirror the slider position in the value label."""
        self.sensitivityValueLabel.setText(str(self.sensitivitySlider.value()))

    def _update_gsd_label(self):
        """Name the GSD box after its role: the only value, or the fallback for missing metadata."""
        if self.gsdModeComboBox.currentData() == GSD_MODE_MANUAL:
            self.gsdValueLabel.setText(self.tr("Fixed GSD (cm/px):"))
        else:
            self.gsdValueLabel.setText(self.tr("Fallback GSD (cm/px):"))

    def get_options(self):
        """Read the panel into an options dictionary.

        Returns:
            dict: Options keyed as documented in SnowTrackOptions.
        """
        return {
            'gsd_mode': str(self.gsdModeComboBox.currentData()),
            'gsd_cm': float(self.gsdSpinBox.value()),
            'print_diameter_cm': float(self.printDiameterSpinBox.value()),
            'step_min_cm': float(self.stepMinSpinBox.value()),
            'step_max_cm': float(self.stepMaxSpinBox.value()),
            'max_trail_width_cm': float(self.trailWidthSpinBox.value()),
            'min_prints': int(self.minPrintsSpinBox.value()),
            'max_step_variation': int(self.stepVariationSpinBox.value()),
            'sensitivity': int(self.sensitivitySlider.value()),
        }

    def validate(self):
        """Check that the gait geometry is physically consistent.

        Returns:
            str or None: Error message if validation fails, else None.
        """
        step_min = self.stepMinSpinBox.value()
        step_max = self.stepMaxSpinBox.value()
        if step_min >= step_max:
            return self.tr("The minimum step length must be smaller than the maximum step length.")
        if self.printDiameterSpinBox.value() >= step_min:
            return self.tr(
                "The print diameter must be smaller than the minimum step length, "
                "otherwise consecutive prints would overlap."
            )
        return None

    def load_options(self, options):
        """Populate the panel from an options dictionary.

        Missing or malformed keys (older configs, hand-edited files) fall back
        to their defaults through the same rules the service applies.

        Args:
            options (dict): Options to display.
        """
        if not isinstance(options, dict):
            return
        params = SnowTrackParams.from_options(options)

        index = self.gsdModeComboBox.findData(params.gsd_mode)
        self.gsdModeComboBox.setCurrentIndex(index if index >= 0 else 0)
        self.gsdSpinBox.setValue(params.gsd_cm)
        self.printDiameterSpinBox.setValue(int(round(params.print_diameter_cm)))
        self.stepMinSpinBox.setValue(int(round(params.step_min_cm)))
        self.stepMaxSpinBox.setValue(int(round(params.step_max_cm)))
        self.trailWidthSpinBox.setValue(int(round(params.max_trail_width_cm)))
        self.minPrintsSpinBox.setValue(params.min_prints)
        self.stepVariationSpinBox.setValue(int(round(params.max_step_variation * 100.0)))
        self.sensitivitySlider.setValue(params.sensitivity)
        # Labels follow their widgets even when the value did not change (no signal)
        self._update_sensitivity_label()
        self._update_gsd_label()
