"""ADIAT Method Test Lab — a standalone developer tool.

Single-image sandbox for evaluating low-contrast SAR detection methods
(spectral-residual saliency, edge/texture anomaly, low-threshold AI
person detection) against ADIAT's existing baselines (RX Anomaly, MRMap,
HSV color range) before any production integration.

This package is intentionally NOT part of the shipped application: it is
not registered in algorithms.conf, has no .ui files and no translations.
The pure detection functions in method_lab.methods are the promotable
core — production integration lifts them into an AlgorithmService plugin.

Run with:  python scripts/method_lab.py [image.jpg]
"""
