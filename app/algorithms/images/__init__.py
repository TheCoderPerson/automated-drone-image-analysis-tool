"""
Image analysis algorithms for batch processing and single-image analysis.

This module contains algorithms for analyzing static images and image batches:
- ColorRange: RGB color range detection
- HSVColorRange: HSV color range detection
- MatchedFilter: Spectral matched filter detection
- RXAnomaly: RX anomaly detection
- MRMap: Mahalanobis-Reed anomaly mapping
- RectilinearShape: Man-made rectangles of a known physical size (geometry, not colour)
- ThermalRange: Thermal temperature range detection
- ThermalAnomaly: Thermal anomaly detection
- ThermalResidualAnomaly: Local delta-T residual anomaly detection
- AIPersonDetector: AI-based person detection
- GroundMessage: letters, numbers and symbols laid out on the ground (e.g. SOS spelled in branches)
- SnowTrack: human foot-track trails in snow, by print spacing, width and cadence
"""

__all__ = [
    'ColorRange',
    'HSVColorRange',
    'MatchedFilter',
    'RXAnomaly',
    'MRMap',
    'RectilinearShape',
    'ThermalRange',
    'ThermalAnomaly',
    'ThermalResidualAnomaly',
    'AIPersonDetector',
    'GroundMessage',
    'SnowTrack',
    'Shared'
]
