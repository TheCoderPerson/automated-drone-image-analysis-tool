"""Tests for FormatHelper."""

import pytest

from helpers.FormatHelper import FormatHelper


def test_format_duration_seconds():
    """Durations under a minute show only seconds."""
    assert FormatHelper.format_duration(0) == '0s'
    assert FormatHelper.format_duration(45) == '45s'
    assert FormatHelper.format_duration(59.4) == '59s'


def test_format_duration_minutes():
    """Durations under an hour show minutes and seconds."""
    assert FormatHelper.format_duration(60) == '1m 0s'
    assert FormatHelper.format_duration(312) == '5m 12s'


def test_format_duration_hours():
    """Durations of an hour or more show hours, minutes and seconds."""
    assert FormatHelper.format_duration(3600) == '1h 0m 0s'
    assert FormatHelper.format_duration(5025) == '1h 23m 45s'


def test_format_duration_negative_is_zero():
    """Negative durations are clamped to zero."""
    assert FormatHelper.format_duration(-10) == '0s'


def test_format_megabytes_two_decimal_places():
    """Byte counts render as megabytes with exactly two decimals."""
    assert FormatHelper.format_megabytes(0) == '0.00'
    assert FormatHelper.format_megabytes(1024 * 1024) == '1.00'
    # 32,768,000 bytes / 1,048,576 == 31.25 MB
    assert FormatHelper.format_megabytes(32768000) == '31.25'
    # 403,572,640 bytes (the value from the download dialog) ~= 384.87 MB
    assert FormatHelper.format_megabytes(403572640) == '384.88'


def test_format_megabytes_negative_is_zero():
    """Negative byte counts are clamped to zero."""
    assert FormatHelper.format_megabytes(-500) == '0.00'


class TestAltitudeReferenceLabels:
    """ATO and AGL must never be labelled as each other.

    The two are equal over flat ground and differ by the whole terrain
    change everywhere else, so a wrong label reads as correct on the bench
    and misleads over the ridge a search team is actually working.
    """

    def test_takeoff_is_abbreviated_ato(self):
        assert FormatHelper.altitude_reference_abbreviation(
            FormatHelper.ALTITUDE_REFERENCE_TAKEOFF) == 'ATO'

    def test_terrain_is_abbreviated_agl(self):
        assert FormatHelper.altitude_reference_abbreviation(
            FormatHelper.ALTITUDE_REFERENCE_TERRAIN) == 'AGL'

    def test_an_operator_entered_height_is_agl(self):
        """The operator is asked for height above the ground being flown over."""
        assert FormatHelper.altitude_reference_abbreviation(
            FormatHelper.ALTITUDE_REFERENCE_MANUAL) == 'AGL'

    def test_takeoff_phrase_names_the_plane(self):
        assert FormatHelper.altitude_reference_phrase(
            FormatHelper.ALTITUDE_REFERENCE_TAKEOFF
        ) == 'ATO (above the takeoff point)'

    def test_terrain_phrase_names_the_plane(self):
        assert FormatHelper.altitude_reference_phrase(
            FormatHelper.ALTITUDE_REFERENCE_TERRAIN
        ) == 'AGL (above the terrain)'

    def test_manual_phrase_says_who_entered_it(self):
        assert FormatHelper.altitude_reference_phrase(
            FormatHelper.ALTITUDE_REFERENCE_MANUAL
        ) == 'AGL (operator-entered)'

    @pytest.mark.parametrize("junk", [None, '', 'AGL', 'nonsense', 0])
    def test_unknown_references_fall_back_to_takeoff(self, junk):
        """An unmarked RelativeAltitude is takeoff-relative; assume the least.

        Guessing AGL would present a takeoff-relative number as ground
        clearance, which is the one direction this label must never err in.
        """
        assert FormatHelper.altitude_reference_abbreviation(junk) == 'ATO'
        assert 'takeoff' in FormatHelper.altitude_reference_phrase(junk)


class TestAltitudeRendering:
    """One renderer per output shape; no site formats altitudes itself."""

    def _readings(self, **kwargs):
        from core.services.image.ImageService import AltitudeReadings
        return AltitudeReadings(**kwargs)

    def test_inline_shows_one_plane(self):
        readings = self._readings(
            value=171.0, unit='ft',
            reference=FormatHelper.ALTITUDE_REFERENCE_TAKEOFF)
        assert FormatHelper.altitude_inline(readings) == "171.0 ft ATO"

    def test_inline_leads_with_agl(self):
        """AGL is what clearance and image scale depend on; it reads first."""
        readings = self._readings(
            value=171.0, unit='ft', terrain_agl=141.2,
            reference=FormatHelper.ALTITUDE_REFERENCE_TAKEOFF)
        assert FormatHelper.altitude_inline(readings) == "141.2 ft AGL · 171.0 ft ATO"

    def test_inline_is_none_without_an_altitude(self):
        assert FormatHelper.altitude_inline(self._readings(value=None)) is None
        assert FormatHelper.altitude_inline(None) is None

    def test_lines_spell_the_plane_out(self):
        readings = self._readings(
            value=171.0, unit='ft',
            reference=FormatHelper.ALTITUDE_REFERENCE_TAKEOFF)
        assert FormatHelper.altitude_lines(readings) == [
            "Altitude: 171.0 ft ATO (above the takeoff point)"]

    def test_lines_carry_both_planes_agl_first(self):
        readings = self._readings(
            value=171.0, unit='ft', terrain_agl=141.2,
            reference=FormatHelper.ALTITUDE_REFERENCE_TAKEOFF)
        assert FormatHelper.altitude_lines(readings) == [
            "Altitude: 141.2 ft AGL (above the terrain, from DEM)",
            "Altitude: 171.0 ft ATO (above the takeoff point)",
        ]

    def test_the_shared_tooltip_explains_the_pair(self):
        """One string, so every surface teaches the same distinction."""
        tip = FormatHelper.ALTITUDE_TOOLTIP
        assert tip.index("AGL") < tip.index("ATO")
        assert "clearance" in tip
        assert "takeoff point" in tip
        assert "flat ground" in tip

    def test_lines_are_empty_without_an_altitude(self):
        assert FormatHelper.altitude_lines(self._readings(value=None)) == []
        assert FormatHelper.altitude_lines(None) == []

    def test_zero_is_a_value_not_an_absence(self):
        """A landed aircraft reads 0; that is not "no altitude"."""
        readings = self._readings(value=0.0, unit='ft')
        assert FormatHelper.altitude_inline(readings) == "0.0 ft ATO"
