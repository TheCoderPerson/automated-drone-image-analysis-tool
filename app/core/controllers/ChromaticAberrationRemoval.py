"""
Controller for the Chromatic Aberration Removal Dialog.

This dialog allows users to batch remove chromatic aberrations from images
in a selected folder, with options for detection sensitivity and correction methods.
"""

import os
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Slot
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QPushButton,
    QLineEdit, QRadioButton, QCheckBox, QSlider, QProgressBar, QPlainTextEdit,
    QFileDialog, QMessageBox, QDoubleSpinBox, QSpinBox, QButtonGroup
)
from PySide6.QtGui import QIcon

from core.services.ChromaticAberrationRemovalService import ChromaticAberrationRemovalService
from core.services.LoggerService import LoggerService


class ChromaticAberrationRemoval(QDialog):
    """Dialog for batch chromatic aberration removal from images."""

    def __init__(self, parent=None, theme='Dark'):
        """
        Initialize the Chromatic Aberration Removal dialog.

        Args:
            parent: Parent widget.
            theme: UI theme ('Light' or 'Dark').
        """
        super().__init__(parent)
        self.theme = theme
        self.logger = LoggerService()
        self.__threads = []
        self.running = False

        self.setWindowTitle("Chromatic Aberration Removal")
        self.setMinimumWidth(700)
        self.setMinimumHeight(600)

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        """Set up the user interface."""
        main_layout = QVBoxLayout()

        # Folder selection group
        folder_group = QGroupBox("Folders")
        folder_layout = QVBoxLayout()

        # Input folder
        input_layout = QHBoxLayout()
        input_layout.addWidget(QLabel("Input Folder:"))
        self.input_line = QLineEdit()
        self.input_line.setReadOnly(True)
        input_layout.addWidget(self.input_line, 1)
        self.input_button = QPushButton("Select")
        input_layout.addWidget(self.input_button)
        folder_layout.addLayout(input_layout)

        # Output folder
        output_layout = QHBoxLayout()
        output_layout.addWidget(QLabel("Output Folder:"))
        self.output_line = QLineEdit()
        self.output_line.setReadOnly(True)
        output_layout.addWidget(self.output_line, 1)
        self.output_button = QPushButton("Select")
        output_layout.addWidget(self.output_button)
        folder_layout.addLayout(output_layout)

        folder_group.setLayout(folder_layout)
        main_layout.addWidget(folder_group)

        # Options group
        options_group = QGroupBox("Correction Options")
        options_layout = QVBoxLayout()

        # Method selection
        method_label = QLabel("Removal Method:")
        options_layout.addWidget(method_label)

        method_layout = QHBoxLayout()
        self.method_group = QButtonGroup(self)
        self.method_desaturate = QRadioButton("Desaturate (Fast)")
        self.method_desaturate.setChecked(True)
        self.method_group.addButton(self.method_desaturate, 0)
        method_layout.addWidget(self.method_desaturate)

        self.method_replace = QRadioButton("Replace (Better Quality)")
        self.method_group.addButton(self.method_replace, 1)
        method_layout.addWidget(self.method_replace)

        self.method_both = QRadioButton("Both (Best Quality, Slower)")
        self.method_group.addButton(self.method_both, 2)
        method_layout.addWidget(self.method_both)
        method_layout.addStretch()
        options_layout.addLayout(method_layout)

        # Sensitivity
        sensitivity_layout = QHBoxLayout()
        sensitivity_layout.addWidget(QLabel("Detection Sensitivity:"))
        self.sensitivity_spin = QDoubleSpinBox()
        self.sensitivity_spin.setRange(0.5, 2.0)
        self.sensitivity_spin.setSingleStep(0.1)
        self.sensitivity_spin.setValue(1.0)
        self.sensitivity_spin.setToolTip(
            "Higher values detect more CA but may include legitimate colors.\n"
            "0.5 = Low (conservative), 1.0 = Normal, 2.0 = High (aggressive)"
        )
        sensitivity_layout.addWidget(self.sensitivity_spin)
        sensitivity_layout.addWidget(QLabel("(0.5 = Low, 1.0 = Normal, 2.0 = High)"))
        sensitivity_layout.addStretch()
        options_layout.addLayout(sensitivity_layout)

        # Edge threshold
        edge_layout = QHBoxLayout()
        edge_layout.addWidget(QLabel("Edge Detection Threshold:"))
        self.edge_spin = QSpinBox()
        self.edge_spin.setRange(10, 200)
        self.edge_spin.setValue(50)
        self.edge_spin.setToolTip(
            "Controls edge detection sensitivity.\n"
            "Lower values = more edges detected, higher values = fewer edges"
        )
        edge_layout.addWidget(self.edge_spin)
        edge_layout.addWidget(QLabel("(Lower = More Edges)"))
        edge_layout.addStretch()
        options_layout.addLayout(edge_layout)

        # Lateral correction
        self.lateral_check = QCheckBox("Apply Lateral Chromatic Aberration Correction")
        self.lateral_check.setToolTip(
            "Realigns RGB channels to correct color fringing.\n"
            "Use for images with strong edge fringing."
        )
        options_layout.addWidget(self.lateral_check)

        lateral_strength_layout = QHBoxLayout()
        lateral_strength_layout.addSpacing(20)
        lateral_strength_layout.addWidget(QLabel("Lateral Correction Strength:"))
        self.lateral_strength_spin = QDoubleSpinBox()
        self.lateral_strength_spin.setRange(0.0, 2.0)
        self.lateral_strength_spin.setSingleStep(0.1)
        self.lateral_strength_spin.setValue(1.0)
        self.lateral_strength_spin.setEnabled(False)
        lateral_strength_layout.addWidget(self.lateral_strength_spin)
        lateral_strength_layout.addWidget(QLabel("(0.0 = None, 1.0 = Normal, 2.0 = Strong)"))
        lateral_strength_layout.addStretch()
        options_layout.addLayout(lateral_strength_layout)

        options_group.setLayout(options_layout)
        main_layout.addWidget(options_group)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)

        # Output log
        log_label = QLabel("Processing Log:")
        main_layout.addWidget(log_label)
        self.output_window = QPlainTextEdit()
        self.output_window.setReadOnly(True)
        self.output_window.setMaximumHeight(150)
        main_layout.addWidget(self.output_window)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.start_button = QPushButton("Start")
        self.start_button.setMinimumWidth(100)
        self.start_button.setStyleSheet("background-color: rgb(0, 136, 0); color: rgb(228, 231, 235);")
        button_layout.addWidget(self.start_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setMinimumWidth(100)
        self.cancel_button.setEnabled(False)
        button_layout.addWidget(self.cancel_button)

        self.close_button = QPushButton("Close")
        self.close_button.setMinimumWidth(100)
        button_layout.addWidget(self.close_button)

        main_layout.addLayout(button_layout)

        self.setLayout(main_layout)

    def _connect_signals(self):
        """Connect UI signals to slots."""
        self.input_button.clicked.connect(self._input_button_clicked)
        self.output_button.clicked.connect(self._output_button_clicked)
        self.start_button.clicked.connect(self._start_button_clicked)
        self.cancel_button.clicked.connect(self._cancel_button_clicked)
        self.close_button.clicked.connect(self.close)
        self.lateral_check.stateChanged.connect(self._lateral_check_changed)

    def _input_button_clicked(self):
        """Handle input folder selection button click."""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Input Folder",
            self.input_line.text() or "",
            QFileDialog.ShowDirsOnly
        )
        if directory:
            self.input_line.setText(directory)
            if os.name == 'nt':
                self.input_line.setText(directory.replace('/', '\\'))

    def _output_button_clicked(self):
        """Handle output folder selection button click."""
        # Default to input folder + "_CA_Removed" if input is set
        default_dir = self.output_line.text()
        if not default_dir and self.input_line.text():
            input_path = Path(self.input_line.text())
            default_dir = str(input_path.parent / f"{input_path.name}_CA_Removed")

        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Output Folder",
            default_dir or "",
            QFileDialog.ShowDirsOnly
        )
        if directory:
            self.output_line.setText(directory)
            if os.name == 'nt':
                self.output_line.setText(directory.replace('/', '\\'))

    def _lateral_check_changed(self, state):
        """Enable/disable lateral strength spinner based on checkbox."""
        self.lateral_strength_spin.setEnabled(state == Qt.Checked)

    def _start_button_clicked(self):
        """Handle start button click to begin CA removal."""
        try:
            # Validate inputs
            if not self.input_line.text() or not self.output_line.text():
                self._show_error("Please select both input and output folders.")
                return

            input_path = Path(self.input_line.text())
            if not input_path.exists() or not input_path.is_dir():
                self._show_error("Input folder does not exist.")
                return

            # Get options
            method_map = {0: "desaturate", 1: "replace", 2: "both"}
            method = method_map[self.method_group.checkedId()]

            # Disable controls
            self._set_controls_enabled(False)
            self._set_start_button(False)
            self._set_cancel_button(True)
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)

            self._add_log_entry("--- Starting chromatic aberration removal ---")
            self._add_log_entry(f"Input: {self.input_line.text()}")
            self._add_log_entry(f"Output: {self.output_line.text()}")
            self._add_log_entry(f"Method: {method}")
            self._add_log_entry(f"Sensitivity: {self.sensitivity_spin.value()}")

            # Initialize service
            self.removal_service = ChromaticAberrationRemovalService(
                service_id=1,
                input_folder=self.input_line.text(),
                output_folder=self.output_line.text(),
                method=method,
                sensitivity=self.sensitivity_spin.value(),
                apply_lateral=self.lateral_check.isChecked(),
                lateral_strength=self.lateral_strength_spin.value(),
                edge_threshold=self.edge_spin.value()
            )

            # Move to thread
            thread = QThread()
            self.__threads.append((thread, self.removal_service))
            self.removal_service.moveToThread(thread)

            # Connect signals
            self.removal_service.sig_msg.connect(self._on_worker_msg)
            self.removal_service.sig_progress.connect(self._on_worker_progress)
            self.removal_service.sig_done.connect(self._on_worker_done)

            # Start processing
            thread.started.connect(self.removal_service.process_images)
            thread.start()
            self.running = True

        except Exception as e:
            self.logger.error(f"Error starting CA removal: {e}")
            self._show_error(f"Error: {str(e)}")
            self._reset_ui()

    def _cancel_button_clicked(self):
        """Handle cancel button click."""
        if self.running:
            self.removal_service.process_cancel()
            self._set_cancel_button(False)
            self._add_log_entry("Cancelling...")

    def closeEvent(self, event):
        """Handle dialog close event."""
        if self.running:
            reply = QMessageBox.question(
                self,
                'Confirmation',
                'Processing is in progress. Are you sure you want to cancel and close?',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )

            if reply == QMessageBox.Yes:
                if hasattr(self, 'removal_service'):
                    self.removal_service.process_cancel()
                for thread, _ in self.__threads:
                    thread.quit()
                    thread.wait()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

    @Slot(str)
    def _on_worker_msg(self, text):
        """Handle log messages from worker thread."""
        self._add_log_entry(text)

    @Slot(int, int)
    def _on_worker_progress(self, current, total):
        """Handle progress updates from worker thread."""
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)

    @Slot(int, int)
    def _on_worker_done(self, service_id, images_processed):
        """Handle completion signal from worker thread."""
        self._add_log_entry("--- Processing Completed ---")
        self._add_log_entry(f"Processed {images_processed} images")

        if images_processed > 0:
            QMessageBox.information(
                self,
                "Processing Complete",
                f"Successfully processed {images_processed} images.\n\n"
                f"Output saved to:\n{self.output_line.text()}"
            )

        self._reset_ui()

    def _add_log_entry(self, text):
        """Add a log entry to the output window."""
        self.output_window.appendPlainText(text)

    def _set_start_button(self, enabled):
        """Enable or disable the start button."""
        if enabled:
            self.start_button.setStyleSheet("background-color: rgb(0, 136, 0); color: rgb(228, 231, 235);")
            self.start_button.setEnabled(True)
        else:
            self.start_button.setStyleSheet("")
            self.start_button.setEnabled(False)

    def _set_cancel_button(self, enabled):
        """Enable or disable the cancel button."""
        if enabled:
            self.cancel_button.setStyleSheet("background-color: rgb(136, 0, 0); color: rgb(228, 231, 235);")
            self.cancel_button.setEnabled(True)
        else:
            self.cancel_button.setStyleSheet("")
            self.cancel_button.setEnabled(False)

    def _set_controls_enabled(self, enabled):
        """Enable or disable input controls."""
        self.input_button.setEnabled(enabled)
        self.output_button.setEnabled(enabled)
        self.method_desaturate.setEnabled(enabled)
        self.method_replace.setEnabled(enabled)
        self.method_both.setEnabled(enabled)
        self.sensitivity_spin.setEnabled(enabled)
        self.edge_spin.setEnabled(enabled)
        self.lateral_check.setEnabled(enabled)
        if enabled:
            self.lateral_strength_spin.setEnabled(self.lateral_check.isChecked())
        else:
            self.lateral_strength_spin.setEnabled(False)

    def _reset_ui(self):
        """Reset UI to initial state after processing."""
        self.running = False
        self._set_start_button(True)
        self._set_cancel_button(False)
        self._set_controls_enabled(True)
        self.progress_bar.setVisible(False)

        for thread, _ in self.__threads:
            thread.quit()
            thread.wait()
        self.__threads.clear()

    def _show_error(self, text):
        """Display an error message."""
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Critical)
        msg.setText(text)
        msg.setWindowTitle("Error")
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec()
