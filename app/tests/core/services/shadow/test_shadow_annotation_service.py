"""Unit tests for core.services.shadow.ShadowAnnotationService."""

import xml.etree.ElementTree as ET

import pytest

from core.services.XmlService import XmlService
from core.services.shadow.ShadowAnnotationService import ShadowAnnotationService
from core.services.shadow.ShadowDescriptor import (
    STATUS_NO_SHADOW,
    STATUS_OK,
    ShadowDescriptor,
)


def _make_results_xml(tmp_path):
    """Write a minimal ADIAT_Data.xml with 2 images and 3 AOIs."""
    root = ET.Element('data')
    images = ET.SubElement(root, 'images')
    specs = [('img1.jpg', [(100, 100), (200, 200)]), ('img2.jpg', [(50, 50)])]
    for path, centers in specs:
        image = ET.SubElement(images, 'image')
        image.set('path', path)
        for center in centers:
            aoi = ET.SubElement(image, 'areas_of_interest')
            aoi.set('center', str(center))
            aoi.set('radius', '5')
            aoi.set('area', '50')
    xml_path = tmp_path / 'ADIAT_Data.xml'
    ET.ElementTree(root).write(str(xml_path))
    return xml_path


class _FakeMatcher:
    """Returns a fixed descriptor and counts calls."""

    def __init__(self, descriptor):
        self.descriptor = descriptor
        self.calls = 0

    def measure(self, image, aoi, context=None):
        self.calls += 1
        return self.descriptor


class _FlakyMatcher:
    """Raises for one specific AOI; returns 'no_shadow' for the rest."""

    def measure(self, image, aoi, context=None):
        if tuple(aoi['center']) == (200, 200):
            raise RuntimeError("simulated per-AOI failure")
        return ShadowDescriptor(status=STATUS_NO_SHADOW)


@pytest.fixture(autouse=True)
def _stub_context(monkeypatch):
    """The matcher is faked, so a real per-image context is not needed."""
    monkeypatch.setattr(
        'core.services.shadow.ShadowAnnotationService.build_shadow_context',
        lambda image: None,
    )


def test_annotate_xml_writes_and_persists_descriptors(tmp_path):
    xml_path = _make_results_xml(tmp_path)
    descriptor = ShadowDescriptor(
        status=STATUS_OK, implied_height_m=1.8, sigma_m=0.2, attached=True,
        sun_elevation_deg=30.0, sun_azimuth_deg=100.0,
    )
    matcher = _FakeMatcher(descriptor)

    summary = ShadowAnnotationService(matcher=matcher).annotate_xml(str(xml_path))

    assert matcher.calls == 3
    assert summary['aois'] == 3
    assert summary['images'] == 2
    assert summary[STATUS_OK] == 3

    # Reload from disk and confirm every descriptor round-tripped.
    reloaded = XmlService(str(xml_path)).get_images()
    aois = [aoi for image in reloaded for aoi in image['areas_of_interest']]
    assert len(aois) == 3
    for aoi in aois:
        assert 'shadow' in aoi
        restored = ShadowDescriptor.from_xml_attribs(aoi['shadow'])
        assert restored.status == STATUS_OK
        assert restored.implied_height_m == pytest.approx(1.8)


def test_annotate_xml_isolates_per_aoi_failures(tmp_path):
    xml_path = _make_results_xml(tmp_path)

    summary = ShadowAnnotationService(matcher=_FlakyMatcher()).annotate_xml(str(xml_path))

    # The failing AOI is skipped; the other two are still annotated.
    assert summary['aois'] == 2
    assert summary[STATUS_NO_SHADOW] == 2


def test_annotate_xml_handles_a_project_with_no_aois(tmp_path):
    root = ET.Element('data')
    ET.SubElement(root, 'images')
    xml_path = tmp_path / 'empty.xml'
    ET.ElementTree(root).write(str(xml_path))

    summary = ShadowAnnotationService(
        matcher=_FakeMatcher(ShadowDescriptor())
    ).annotate_xml(str(xml_path))

    assert summary['aois'] == 0
    assert summary['images'] == 0
