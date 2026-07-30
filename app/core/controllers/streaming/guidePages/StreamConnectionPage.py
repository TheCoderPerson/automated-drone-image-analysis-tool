"""Connection details page for the streaming setup wizard."""

import os

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtWidgets import QFileDialog, QVBoxLayout, QApplication

try:
    import cv2
except ImportError:
    cv2 = None

from .BasePage import BasePage
from core.services.streaming.RTMPStreamService import (
    SOURCE_TYPE_ADIAT_FLIGHT,
    SOURCE_TYPE_FILE,
    SOURCE_TYPE_HDMI,
    SOURCE_TYPE_RTMP,
)
from core.services.streaming.signaling import pairing
from core.views.components.LabeledSlider import TextLabeledSlider


class DeviceScanWorker(QObject):
    """Worker that scans for capture devices in a background thread."""

    finished = Signal(object, object)  # found_devices, device_backends (use object for dict compatibility)

    def __init__(self):
        super().__init__()

    def run(self):
        """Scan for devices - runs in background thread."""
        if cv2 is None:
            self.finished.emit({}, {})
            return

        # Define backends to try (in order of preference for Windows)
        backends = []
        if hasattr(cv2, 'CAP_MSMF'):
            backends.append((cv2.CAP_MSMF, "MSMF"))
        if hasattr(cv2, 'CAP_DSHOW'):
            backends.append((cv2.CAP_DSHOW, "DirectShow"))
        backends.append((cv2.CAP_ANY, "Auto"))

        found_devices = {}  # {index: (label, backend_id, backend_name)}
        device_backends = {}  # {combo_idx: backend_id}
        max_devices = 5  # Reduced from 10 for faster scanning

        for backend_id, backend_name in backends:
            consecutive_failures = 0
            for index in range(max_devices):
                # Skip if we already found this device with a preferred backend
                if index in found_devices:
                    consecutive_failures = 0
                    continue

                # Stop scanning this backend after 2 consecutive failures (faster)
                if consecutive_failures >= 2:
                    break

                cap = None
                try:
                    cap = cv2.VideoCapture(index, backend_id)
                    if cap is not None and cap.isOpened():
                        # Use generic device name - platform-agnostic approach
                        label = f"Device {index} ({backend_name})"
                        found_devices[index] = (label, backend_id, backend_name)
                        consecutive_failures = 0
                    else:
                        consecutive_failures += 1
                except Exception:
                    consecutive_failures += 1
                finally:
                    if cap is not None:
                        try:
                            cap.release()
                        except Exception:
                            pass

        # Build device_backends mapping
        combo_idx = 0
        for dev_index in sorted(found_devices.keys()):
            _, backend_id, _ = found_devices[dev_index]
            device_backends[combo_idx] = backend_id
            combo_idx += 1

        self.finished.emit(found_devices, device_backends)


class StreamConnectionPage(BasePage):
    """Page for providing stream URL/path and auto-connect preference."""

    def __init__(self, wizard_data, settings_service, dialog):
        super().__init__(wizard_data, settings_service, dialog)
        # The video path the selected metadata file belongs to, so switching
        # videos drops a metadata file that is no longer about this flight.
        self._metadata_source_url = ""

    def setup_ui(self) -> None:
        # Initialize HDMI device combo with placeholder
        if hasattr(self.dialog, "deviceComboBox"):
            self.dialog.deviceComboBox.clear()
            self.dialog.deviceComboBox.addItem(
                self.tr("Click Scan to find devices..."),
                None
            )
            self.dialog.deviceComboBox.setEnabled(False)
            self.dialog.labelHdmiDevices.setVisible(False)
            self.dialog.deviceComboBox.setVisible(False)
            self.dialog.scanDevicesButton.setVisible(False)

        # Create resolution slider with user-friendly labels
        # Map: 25% = 480p, 50% = 720p, 75% = 1080p, 100% = 4K
        if hasattr(self.dialog, "resolutionSliderWidget"):
            layout = QVBoxLayout(self.dialog.resolutionSliderWidget)
            layout.setContentsMargins(0, 0, 0, 0)

            # Presets: (label, percentage_value)
            resolution_presets = [
                (self.tr("480p"), 25),
                (self.tr("720p"), 50),
                (self.tr("1080p"), 75),
                (self.tr("4K"), 100)
            ]

            self.resolution_slider = TextLabeledSlider(
                parent=self.dialog.resolutionSliderWidget,
                presets=resolution_presets
            )
            # Set default to 1080p (index 2)
            self.resolution_slider.setValue(2)
            layout.addWidget(self.resolution_slider)

    def connect_signals(self) -> None:
        self.dialog.streamUrlLineEdit.textChanged.connect(self._on_stream_url_changed)
        self.dialog.browseButton.clicked.connect(self._on_browse_clicked)
        self.dialog.metadataFileLineEdit.textChanged.connect(self._on_metadata_file_changed)
        self.dialog.metadataBrowseButton.clicked.connect(self._on_metadata_browse_clicked)
        self.dialog.autoConnectCheckBox.stateChanged.connect(self._on_auto_connect_changed)
        if hasattr(self.dialog, "scanDevicesButton"):
            self.dialog.scanDevicesButton.clicked.connect(self._on_scan_devices_clicked)
        if hasattr(self.dialog, "deviceComboBox"):
            self.dialog.deviceComboBox.currentIndexChanged.connect(self._on_device_selected)
        if hasattr(self, "resolution_slider"):
            self.resolution_slider.valueChanged.connect(self._on_resolution_changed)

    def load_data(self) -> None:
        # Don't load previous file selection - start fresh each time
        stream_url = self.wizard_data.get("stream_url", "")
        metadata_path = self.wizard_data.get("metadata_path", "")
        auto_connect_raw = self.wizard_data.get("auto_connect", False)

        if stream_url:
            self.dialog.streamUrlLineEdit.setText(stream_url)
        if metadata_path:
            self.dialog.metadataFileLineEdit.setText(metadata_path)
        self.dialog.autoConnectCheckBox.setChecked(bool(auto_connect_raw))

        self._apply_stream_type_settings()

        # Load resolution preference. File sources are high-res recordings meant for deep
        # analysis -> default to max detail (4K, capped to native on first frame) so the
        # tiling+letterbox pass isn't fed a pre-downscaled frame. Live sources
        # (RTMP/HDMI/ADIAT Flight) keep a framerate-friendly 1080p default. An explicit
        # saved preference still wins.
        stream_type = self.wizard_data.get("stream_type", SOURCE_TYPE_FILE)
        fallback_resolution = 100 if stream_type == SOURCE_TYPE_FILE else 75
        default_resolution_str = self.settings_service.get_setting(
            "StreamingProcessingResolution", f"{fallback_resolution}%")
        # Convert "75%" to 75
        try:
            default_resolution = int(default_resolution_str.rstrip('%'))
        except (ValueError, AttributeError):
            default_resolution = fallback_resolution

        # Get current resolution from wizard_data (as integer) or use default
        current_resolution = self.wizard_data.get("processing_resolution")
        if current_resolution is None:
            current_resolution = default_resolution
        elif isinstance(current_resolution, str):
            # Handle string like "75%"
            try:
                current_resolution = int(current_resolution.rstrip('%'))
            except (ValueError, AttributeError):
                current_resolution = default_resolution

        # Map percentage to slider index
        # 25% = index 0 (480p), 50% = index 1 (720p), 75% = index 2 (1080p), 100% = index 3 (4K)
        resolution_to_index = {25: 0, 50: 1, 75: 2, 100: 3}
        slider_index = resolution_to_index.get(current_resolution, 2)  # Default to 1080p

        if hasattr(self, "resolution_slider"):
            self.resolution_slider.setValue(slider_index)

        # Initialize wizard data
        self.wizard_data["stream_url"] = self.dialog.streamUrlLineEdit.text().strip()
        self.wizard_data["metadata_path"] = self.dialog.metadataFileLineEdit.text().strip()
        self.wizard_data["auto_connect"] = self.dialog.autoConnectCheckBox.isChecked()
        self.wizard_data["processing_resolution"] = current_resolution

    def on_enter(self) -> None:
        self._apply_stream_type_settings()

        # Auto-scan for devices when HDMI is selected
        stream_type = self.wizard_data.get("stream_type", SOURCE_TYPE_FILE)
        if stream_type == SOURCE_TYPE_HDMI:
            # Only auto-scan if no devices found yet
            if hasattr(self.dialog, "deviceComboBox"):
                if self.dialog.deviceComboBox.count() <= 1:  # Only placeholder
                    self._on_scan_devices_clicked()

    def validate(self) -> bool:
        stream_type = self.wizard_data.get("stream_type", SOURCE_TYPE_FILE)
        if stream_type == SOURCE_TYPE_HDMI:
            # For HDMI, validate that a device is selected
            if hasattr(self.dialog, "deviceComboBox"):
                data = self.dialog.deviceComboBox.currentData()
                return data is not None
            return False
        if stream_type == SOURCE_TYPE_ADIAT_FLIGHT:
            # Nothing to validate: the pairing code is collected at connect
            # time because it expires ~30 s after ADIAT Flight issues it.
            return True
        return bool(self.dialog.streamUrlLineEdit.text().strip())

    def save_data(self) -> None:
        self.wizard_data["stream_url"] = self.dialog.streamUrlLineEdit.text().strip()
        self.wizard_data["auto_connect"] = self.dialog.autoConnectCheckBox.isChecked()
        # Only file sources can take a metadata file; anything left in the
        # field from a previous selection must not follow a live source
        # through to the viewer.
        if self.wizard_data.get("stream_type", SOURCE_TYPE_FILE) == SOURCE_TYPE_FILE:
            self.wizard_data["metadata_path"] = (
                self.dialog.metadataFileLineEdit.text().strip()
            )
        else:
            self.wizard_data["metadata_path"] = ""
        if hasattr(self, "resolution_slider"):
            # Get the numeric value (percentage) from the selected preset
            numeric_value = self.resolution_slider.getNumericValue()
            if numeric_value is not None:
                self.wizard_data["processing_resolution"] = numeric_value
            else:
                # Fallback: map index to percentage
                index = self.resolution_slider.value()
                index_to_resolution = {0: 25, 1: 50, 2: 75, 3: 100}
                self.wizard_data["processing_resolution"] = index_to_resolution.get(index, 75)

        # ADIAT Flight carries no URL: the pairing code is requested at
        # connect time. Persisting a stale code here would let the viewer
        # try an expired one.
        if self.wizard_data.get("stream_type") == SOURCE_TYPE_ADIAT_FLIGHT:
            self.wizard_data["stream_url"] = ""

        # For HDMI, also store the selected backend and device label
        stream_type = self.wizard_data.get("stream_type", SOURCE_TYPE_FILE)
        if stream_type == SOURCE_TYPE_HDMI and hasattr(self.dialog, "deviceComboBox"):
            idx = self.dialog.deviceComboBox.currentIndex()
            # Store the device label (friendly name)
            if idx >= 0:
                self.wizard_data["device_label"] = self.dialog.deviceComboBox.currentText()
            # Store the backend info if available
            if hasattr(self, "_device_backends") and idx in self._device_backends:
                self.wizard_data["hdmi_backend"] = self._device_backends[idx]

    def _apply_stream_type_settings(self) -> None:
        stream_type = self.wizard_data.get("stream_type", SOURCE_TYPE_FILE)
        settings = self._get_stream_type_settings(stream_type)
        self.dialog.labelConnectionInstructions.setText(settings["instructions"])

        # Two source types collect nothing in this row:
        #  * HDMI picks a device from the combo below.
        #  * ADIAT Flight codes expire after 30 s of inactivity, so the code
        #    is requested at connect time instead of here — a pass through
        #    the remaining wizard pages would outlive it.
        is_hdmi = stream_type == SOURCE_TYPE_HDMI
        is_flight = stream_type == SOURCE_TYPE_ADIAT_FLIGHT
        hide_url_row = is_hdmi or is_flight

        # Show/hide URL input row based on stream type
        self.dialog.labelStreamUrl.setVisible(not hide_url_row)
        self.dialog.streamUrlLineEdit.setVisible(not hide_url_row)
        self.dialog.browseButton.setVisible(settings["show_browse"] and not hide_url_row)

        # A secondary metadata file only applies to a video file. Live feeds
        # either carry telemetry in-band (ADIAT Flight) or not at all, so
        # offering the row would promise something it cannot deliver.
        is_file = stream_type == SOURCE_TYPE_FILE
        self.dialog.labelMetadataFile.setVisible(is_file)
        self.dialog.metadataFileLineEdit.setVisible(is_file)
        self.dialog.metadataBrowseButton.setVisible(is_file)
        if not is_file:
            self.dialog.metadataFileLineEdit.setText("")
            self.wizard_data["metadata_path"] = ""

        # Only set placeholder for types that actually take input here
        if not hide_url_row:
            self.dialog.labelStreamUrl.setText(settings["field_label"])
            self.dialog.streamUrlLineEdit.setPlaceholderText(settings["placeholder"])

        # HDMI device selection UI
        if hasattr(self.dialog, "labelHdmiDevices"):
            self.dialog.labelHdmiDevices.setVisible(is_hdmi)
        if hasattr(self.dialog, "deviceComboBox"):
            self.dialog.deviceComboBox.setVisible(is_hdmi)
            # Enable when HDMI is selected - will be populated by scan
            self.dialog.deviceComboBox.setEnabled(is_hdmi)
        if hasattr(self.dialog, "scanDevicesButton"):
            self.dialog.scanDevicesButton.setVisible(is_hdmi)

        # Auto-populate sensible defaults for types that take input here
        if not hide_url_row:
            current_value = self.dialog.streamUrlLineEdit.text().strip()
            if not current_value and settings.get("default_value"):
                self.dialog.streamUrlLineEdit.setText(settings["default_value"])
        elif is_flight:
            # Drop anything a previously-selected source left behind so it
            # cannot be mistaken for a pairing code later.
            self.dialog.streamUrlLineEdit.setText("")
            self.wizard_data["stream_url"] = ""

    def _get_stream_type_settings(self, stream_type: str) -> dict:
        mapping = {
            SOURCE_TYPE_FILE: {
                "instructions": self.tr(
                    "Choose the video file you want to analyze. Use Browse to pick a file from disk.\n\n"
                    "Location data is optional and usually detected automatically — ADIAT reads an "
                    ".SRT sitting next to the video, or telemetry embedded in the video, on its own. "
                    "Set it only to override that, or to supply location data the video does not "
                    "have: a DJI .SRT or a .CSV flight log."
                ),
                "field_label": self.tr("Video File:"),
                "placeholder": self.tr("Click Browse to select a video file..."),
                "show_browse": True,
                "default_value": "",
            },
            SOURCE_TYPE_HDMI: {
                "instructions": self.tr(
                    "Click Scan to detect available capture devices, then select one from the dropdown."
                ),
                "field_label": self.tr("Device:"),
                "placeholder": self.tr(""),
                "show_browse": False,
                "default_value": "",
            },
            SOURCE_TYPE_RTMP: {
                "instructions": self.tr(
                    "Enter the RTMP URL provided by your streaming server (rtmp://server:port/app/key)."
                ),
                "field_label": self.tr("Stream URL:"),
                "placeholder": self.tr("rtmp://server:port/app/streamKey"),
                "show_browse": False,
                "default_value": "",
            },
            SOURCE_TYPE_ADIAT_FLIGHT: {
                "instructions": self.tr(
                    "You'll be prompted for the pairing code when you connect — pairing "
                    "codes expire about 30 seconds after ADIAT Flight shows them, so don't "
                    "generate one until you're ready.\n\n"
                    "Finish this setup first, then start sharing in ADIAT Flight and enter "
                    "the code. Detections reported by ADIAT Flight are ignored — this "
                    "desktop runs its own analysis on the video."
                ),
                "field_label": self.tr("Pairing Code:"),
                "placeholder": self.tr(""),
                "show_browse": False,
                "default_value": "",
            },
        }
        return mapping.get(stream_type, mapping[SOURCE_TYPE_FILE])

    def _on_scan_devices_clicked(self) -> None:
        """Scan for available HDMI capture devices using OpenCV with multiple backends."""
        if cv2 is None:
            self.dialog.deviceComboBox.clear()
            self.dialog.deviceComboBox.addItem(self.tr("OpenCV not available"), None)
            self.dialog.deviceComboBox.setEnabled(False)
            return

        # Show scanning state
        self.dialog.deviceComboBox.clear()
        self.dialog.deviceComboBox.addItem(self.tr("Scanning..."), None)
        self.dialog.deviceComboBox.setEnabled(False)
        self.dialog.scanDevicesButton.setEnabled(False)
        self.dialog.scanDevicesButton.setText(self.tr("Scanning..."))
        QApplication.processEvents()  # Update UI immediately

        self._device_backends = {}

        # Create worker and thread
        self._scan_thread = QThread()
        self._scan_worker = DeviceScanWorker()
        self._scan_worker.moveToThread(self._scan_thread)

        # Connect signals
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_worker.finished.connect(self._scan_thread.quit)
        self._scan_worker.finished.connect(self._scan_worker.deleteLater)
        self._scan_thread.finished.connect(self._scan_thread.deleteLater)

        # Start scanning
        self._scan_thread.start()

    def _on_scan_finished(self, found_devices: dict, device_backends: dict) -> None:
        """Handle scan completion - update UI with results."""
        # Restore button state
        self.dialog.scanDevicesButton.setEnabled(True)
        self.dialog.scanDevicesButton.setText(self.tr("Scan"))

        self._device_backends = device_backends
        self.dialog.deviceComboBox.clear()

        if not found_devices:
            self.dialog.deviceComboBox.addItem(self.tr("No capture devices found"), None)
            self.dialog.deviceComboBox.setEnabled(False)
        else:
            # Add found devices to combo box, sorted by index
            for dev_index in sorted(found_devices.keys()):
                label, backend_id, backend_name = found_devices[dev_index]
                # Translate the label
                translated_label = self.tr("Device {index} ({backend})").format(
                    index=dev_index, backend=backend_name)
                self.dialog.deviceComboBox.addItem(translated_label, dev_index)

            self.dialog.deviceComboBox.setEnabled(True)
            self.dialog.deviceComboBox.setCurrentIndex(0)
            self._sync_device_to_url()

    def _on_device_selected(self, index: int) -> None:
        """Update URL field when a device is selected from the combo box."""
        if index < 0:
            return
        self._sync_device_to_url()

    def _sync_device_to_url(self) -> None:
        """Sync selected device index into the URL field and wizard data."""
        if not hasattr(self.dialog, "deviceComboBox"):
            return
        data = self.dialog.deviceComboBox.currentData()
        if data is None:
            return
        self.dialog.streamUrlLineEdit.setText(str(data))
        self.wizard_data["stream_url"] = str(data)

    def _on_stream_url_changed(self, text: str) -> None:
        cleaned = text.strip()
        if os.name == "nt":
            cleaned = cleaned.replace("/", "\\")
        self.wizard_data["stream_url"] = cleaned
        # Compare on the raw field text, not the separator-normalized form,
        # so this matches what _on_metadata_file_changed records.
        self._drop_stale_metadata(text.strip())
        if hasattr(self, "on_validation_changed"):
            self.on_validation_changed()

    def _drop_stale_metadata(self, video_path: str) -> None:
        """Clear the metadata file when a different video is selected.

        A metadata file *overrides* the video's own embedded telemetry, so
        one left over from a previous video does not merely linger — it
        geotags the new video with the old flight's positions. SRT cue times
        are video-relative, so the result looks plausible and is wrong.
        """
        if video_path == self._metadata_source_url:
            return
        self._metadata_source_url = video_path
        if self.dialog.metadataFileLineEdit.text():
            self.dialog.metadataFileLineEdit.clear()
            self.wizard_data["metadata_path"] = ""

    def _on_metadata_file_changed(self, text: str) -> None:
        cleaned = text.strip()
        # Always a local file, so normalizing separators is safe here in a
        # way it is not for the URL field.
        if os.name == "nt":
            cleaned = cleaned.replace("/", "\\")
        self.wizard_data["metadata_path"] = cleaned
        # Bind it to the video selected now, so it survives until that changes.
        self._metadata_source_url = self.dialog.streamUrlLineEdit.text().strip()

    def _on_auto_connect_changed(self, state: int) -> None:
        self.wizard_data["auto_connect"] = state == Qt.Checked

    def _on_browse_clicked(self) -> None:
        current = self.dialog.streamUrlLineEdit.text().strip() or os.getcwd()
        file_path, _ = QFileDialog.getOpenFileName(
            self.dialog,
            self.tr("Select Video File"),
            current,
            self.tr(
                "Video Files (*.mp4 *.avi *.mov *.mkv *.flv *.wmv *.m4v *.3gp *.webm);;All Files (*)"
            ),
        )
        if file_path:
            self.dialog.streamUrlLineEdit.setText(file_path)

    def _on_metadata_browse_clicked(self) -> None:
        """Pick an SRT or CSV metadata file.

        Starts in the video's folder, which is where a sidecar or an
        exported flight log usually sits. Filter matches the image-analysis
        Video Parser so both surfaces accept the same files.
        """
        current = self.dialog.metadataFileLineEdit.text().strip()
        if not current:
            video = self.dialog.streamUrlLineEdit.text().strip()
            current = os.path.dirname(video) if video else os.getcwd()
        file_path, _ = QFileDialog.getOpenFileName(
            self.dialog,
            self.tr("Select a Metadata File"),
            current,
            self.tr(
                "Metadata Files (*.srt *.csv);;SRT Files (*.srt);;"
                "CSV Flight Logs (*.csv);;All Files (*)"
            ),
        )
        if file_path:
            self.dialog.metadataFileLineEdit.setText(file_path)

    def _on_resolution_changed(self, index: int) -> None:
        """Handle resolution slider change."""
        # Map slider index to percentage value
        index_to_resolution = {0: 25, 1: 50, 2: 75, 3: 100}
        resolution_value = index_to_resolution.get(index, 75)
        self.wizard_data["processing_resolution"] = resolution_value
