"""
Image analysis algorithms for batch processing and single-image analysis.

This module contains algorithms for analyzing static images and image batches:
- ColorRange: RGB color range detection
- HSVColorRange: HSV color range detection
- MatchedFilter: Spectral matched filter detection
- RXAnomaly: RX anomaly detection
- MRMap: Mahalanobis-Reed anomaly mapping
- ThermalRange: Thermal temperature range detection
- ThermalAnomaly: Thermal anomaly detection
- ThermalResidualAnomaly: Local delta-T residual anomaly detection
- AIPersonDetector: AI-based person detection
- SnowTrack: human foot-track trails in snow, by print spacing, width and cadence
"""

__all__ = [
    'ColorRange',
    'HSVColorRange',
    'MatchedFilter',
    'RXAnomaly',
    'MRMap',
    'ThermalRange',
    'ThermalAnomaly',
    'ThermalResidualAnomaly',
    'AIPersonDetector',
    'SnowTrack',
    'Shared'
]
