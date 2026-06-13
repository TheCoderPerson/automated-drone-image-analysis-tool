"""
lab_window.py - Main window of the Method Test Lab (dev tool).

Single-image sandbox: open a drone photo, pick a method tab, tune its
parameters, Run, and compare overlays. Each method's last result stays
toggleable (mask tint + AOI circles in the method's color, or its score
heatmap), so experimental methods can be judged side by side against
the production baselines on the same frame.

Dev tool: plain strings (no translations), code-built UI (no .ui file)
by design — see the package docstring.
"""

import os

import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout, QFormLayout,
    QTabWidget, QPushButton, QSpinBox, QDoubleSpinBox, QComboBox, QCheckBox,
    QLabel, QFileDialog, QGroupBox, QApplication, QScrollArea
)

from core.views.images.viewer.widgets.QtImageViewer import QtImageViewer
from method_lab import adapters

# Method registry: display name -> runner, overlay color (RGB) and the
# parameter spec used to build that method's tab.
# Param spec rows: (key, label, kind, *kind_args)
#   ('int',    min, max, default)
#   ('float',  min, max, default, step)
#   ('choice', [values], default)
#   ('bool',   default)
METHODS = {
    'Saliency': {
        'runner': adapters.run_saliency,
        'color': (255, 64, 64),
        'params': [
            ('sensitivity', 'Sensitivity (1-10)', 'int', 1, 10, 5),
            ('segments', 'Segments', 'choice', [1, 4, 9, 16], 4),
        ],
    },
    'Edge/Texture': {
        'runner': adapters.run_edge_texture,
        'color': (255, 170, 0),
        'params': [
            ('canny_lo', 'Canny low', 'int', 0, 255, 60),
            ('canny_hi', 'Canny high', 'int', 0, 255, 180),
            ('window', 'Window (px)', 'int', 5, 101, 31),
            ('deviation_percentile', 'Percentile', 'float', 90.0, 99.99, 99.5, 0.05),
        ],
    },
    'AI Person': {
        'runner': adapters.run_ai,
        'color': (64, 160, 255),
        'params': [
            ('confidence_pct', 'Confidence %', 'int', 1, 95, 10),
            ('cpu_only', 'CPU only', 'bool', False),
        ],
    },
    'RX Anomaly': {
        'runner': adapters.run_rx,
        'color': (0, 220, 130),
        'params': [
            ('sensitivity', 'Sensitivity (1-10)', 'int', 1, 10, 5),
            ('segments', 'Segments', 'choice', [1, 4, 9, 16], 4),
        ],
    },
    'MRMap': {
        'runner': adapters.run_mrmap,
        'color': (200, 120, 255),
        'params': [
            ('threshold', 'Threshold (1-200)', 'int', 1, 200, 100),
            ('window', 'Window (1-10)', 'int', 1, 10, 5),
            ('segments', 'Segments', 'choice', [1, 4, 9, 16], 4),
            ('colorspace', 'Colorspace', 'choice', ['LAB', 'RGB', 'HSV'], 'LAB'),
        ],
    },
    'HSV Range': {
        'runner': adapters.run_hsv,
        'color': (255, 230, 0),
        'params': [
            ('h_min', 'Hue min (deg)', 'int', 0, 360, 0),
            ('h_max', 'Hue max (deg)', 'int', 0, 360, 30),
            ('s_min', 'Sat min %', 'int', 0, 100, 30),
            ('s_max', 'Sat max %', 'int', 0, 100, 100),
            ('v_min', 'Val min %', 'int', 0, 100, 20),
            ('v_max', 'Val max %', 'int', 0, 100, 100),
        ],
    },
}


class MethodLabWindow(QMainWindow):
    """Main window: image canvas, method tabs and overlay toggles."""

    def __init__(self, image_path=None):
        super().__init__()
        self.setWindowTitle("ADIAT Method Test Lab")
        self.image_path = None
        self.img_bgr = None
        self.img_rgb = None
        self.results = {}        # method name -> LabResult
        self.param_widgets = {}  # method name -> {key: widget}
        self.result_rows = {}    # method name -> {'show', 'heat', 'label'}

        self._build_ui()
        self.resize(1500, 950)
        if image_path:
            self.load_image(image_path)

    # ------------------------------------------------------------------ #
    #  UI construction
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        splitter = QSplitter(Qt.Horizontal)
        self.setCentralWidget(splitter)

        self.viewer = QtImageViewer(self)
        splitter.addWidget(self.viewer)

        panel = QWidget()
        panel_layout = QVBoxLayout(panel)

        open_row = QHBoxLayout()
        open_button = QPushButton("Open Image…")
        open_button.clicked.connect(self._open_image_dialog)
        self.image_label = QLabel("No image loaded")
        self.image_label.setWordWrap(True)
        open_row.addWidget(open_button)
        open_row.addWidget(self.image_label, 1)
        panel_layout.addLayout(open_row)

        common_group = QGroupBox("Common AOI parameters")
        common_form = QFormLayout(common_group)
        self.min_area_spin = QSpinBox()
        self.min_area_spin.setRange(1, 100000)
        self.min_area_spin.setValue(10)
        self.aoi_radius_spin = QSpinBox()
        self.aoi_radius_spin.setRange(0, 200)
        self.aoi_radius_spin.setValue(15)
        common_form.addRow("Min area (px)", self.min_area_spin)
        common_form.addRow("AOI radius pad", self.aoi_radius_spin)
        panel_layout.addWidget(common_group)

        self.tabs = QTabWidget()
        for name, spec in METHODS.items():
            self.tabs.addTab(self._build_method_tab(name, spec), name)
        panel_layout.addWidget(self.tabs)

        results_group = QGroupBox("Results / overlays")
        results_layout = QVBoxLayout(results_group)
        for name, spec in METHODS.items():
            row = QHBoxLayout()
            show = QCheckBox()
            show.setChecked(True)
            show.toggled.connect(self._refresh_display)
            heat = QCheckBox("heatmap")
            heat.setEnabled(False)
            heat.toggled.connect(self._refresh_display)
            swatch = QLabel("■")
            r, g, b = spec['color']
            swatch.setStyleSheet(f"color: rgb({r},{g},{b}); font-size: 16px;")
            label = QLabel(f"{name}: not run")
            row.addWidget(show)
            row.addWidget(swatch)
            row.addWidget(label, 1)
            row.addWidget(heat)
            results_layout.addLayout(row)
            self.result_rows[name] = {'show': show, 'heat': heat, 'label': label}
        panel_layout.addWidget(results_group)
        panel_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        scroll.setMinimumWidth(360)
        splitter.addWidget(scroll)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)

    def _build_method_tab(self, name, spec):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        form = QFormLayout()
        widgets = {}
        for row in spec['params']:
            key, label, kind = row[0], row[1], row[2]
            if kind == 'int':
                widget = QSpinBox()
                widget.setRange(row[3], row[4])
                widget.setValue(row[5])
            elif kind == 'float':
                widget = QDoubleSpinBox()
                widget.setRange(row[3], row[4])
                widget.setValue(row[5])
                widget.setSingleStep(row[6])
                widget.setDecimals(2)
            elif kind == 'choice':
                widget = QComboBox()
                for value in row[3]:
                    widget.addItem(str(value), value)
                widget.setCurrentIndex(row[3].index(row[4]))
            elif kind == 'bool':
                widget = QCheckBox()
                widget.setChecked(row[3])
            else:
                raise ValueError(f"Unknown param kind: {kind}")
            form.addRow(label, widget)
            widgets[key] = widget
        self.param_widgets[name] = widgets
        layout.addLayout(form)

        run_button = QPushButton(f"Run {name}")
        run_button.clicked.connect(lambda checked=False, n=name: self.run_method(n))
        layout.addWidget(run_button)
        layout.addStretch(1)
        return tab

    # ------------------------------------------------------------------ #
    #  Image handling
    # ------------------------------------------------------------------ #
    def _open_image_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open image", "",
            "Images (*.jpg *.jpeg *.png *.tif *.tiff *.dng)"
        )
        if path:
            self.load_image(path)

    def load_image(self, path):
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        if img is None:
            self.image_label.setText(f"Could not read: {path}")
            return
        self.image_path = path
        self.img_bgr = img
        self.img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        self.results.clear()
        for name, row in self.result_rows.items():
            row['label'].setText(f"{name}: not run")
            row['heat'].setEnabled(False)
        h, w = img.shape[:2]
        self.image_label.setText(f"{os.path.basename(path)}  ({w}x{h})")
        self._refresh_display()
        self.viewer.resetZoom()

    # ------------------------------------------------------------------ #
    #  Method execution and display
    # ------------------------------------------------------------------ #
    def _gather_params(self, name):
        params = {
            'min_area': self.min_area_spin.value(),
            'max_area': 0,
            'aoi_radius': self.aoi_radius_spin.value(),
        }
        for key, widget in self.param_widgets[name].items():
            if isinstance(widget, QComboBox):
                params[key] = widget.currentData()
            elif isinstance(widget, QCheckBox):
                params[key] = widget.isChecked()
            else:
                params[key] = widget.value()
        return params

    def run_method(self, name):
        if self.img_bgr is None:
            self.result_rows[name]['label'].setText(f"{name}: open an image first")
            return

        row = self.result_rows[name]
        row['label'].setText(f"{name}: running…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            result = METHODS[name]['runner'](
                self.img_bgr, self.image_path, self._gather_params(name)
            )
        finally:
            QApplication.restoreOverrideCursor()

        self.results[name] = result
        if result.error:
            row['label'].setText(f"{name}: ERROR — {result.error}")
        else:
            detected = int((result.mask > 0).sum()) if result.mask is not None else 0
            row['label'].setText(
                f"{name}: {len(result.aois)} AOIs, {detected} px, {result.elapsed_s:.2f}s"
            )
        row['heat'].setEnabled(result.score_map is not None)
        row['show'].setChecked(True)
        self._refresh_display()

    def _refresh_display(self):
        if self.img_rgb is None:
            return
        canvas = self.img_rgb.copy()

        for name, spec in METHODS.items():
            result = self.results.get(name)
            row = self.result_rows[name]
            if result is None or result.error or not row['show'].isChecked():
                continue
            color = np.array(spec['color'], np.uint8)

            if row['heat'].isChecked() and result.score_map is not None:
                heat = cv2.applyColorMap(
                    (np.clip(result.score_map, 0, 1) * 255).astype(np.uint8),
                    cv2.COLORMAP_JET
                )
                heat = cv2.cvtColor(heat, cv2.COLOR_BGR2RGB)
                canvas = cv2.addWeighted(canvas, 0.45, heat, 0.55, 0)
            elif result.mask is not None and result.mask.shape[:2] == canvas.shape[:2]:
                selected = result.mask > 0
                if selected.any():
                    canvas[selected] = (
                        (canvas[selected].astype(np.float32) * 0.45)
                        + (color.astype(np.float32) * 0.55)
                    ).astype(np.uint8)

            for aoi in result.aois:
                center = tuple(int(v) for v in aoi.get('center', (0, 0)))
                radius = int(aoi.get('radius', 10))
                cv2.circle(canvas, center, radius,
                           tuple(int(c) for c in spec['color']), 3)

        self.viewer.setImage(canvas)
