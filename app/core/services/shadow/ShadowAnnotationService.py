"""ShadowAnnotationService - annotate every AOI in a project with shadow data.

The Phase 2 batch pass. Walks an ADIAT_Data.xml, measures the shadow beside
every AOI once, and writes a ShadowDescriptor onto each AOI element. Per-image
inputs (image decode, camera pose, sun position) are built once and shared
across that image's AOIs via a ShadowImageContext. A failure on one image is
isolated so the rest of the project still annotates.
"""

from __future__ import annotations

import traceback
from typing import Callable, Optional

from core.services.LoggerService import LoggerService
from core.services.XmlService import XmlService
from core.services.shadow.ShadowDescriptor import (
    STATUS_NO_SHADOW,
    STATUS_OK,
    STATUS_UNMEASURABLE,
)
from core.services.shadow.ShadowImageContext import build_shadow_context
from core.services.shadow.ShadowMatcher import ShadowMatcher


class ShadowAnnotationService:
    """Measure and persist a shadow descriptor for every AOI in a project."""

    def __init__(self, matcher: Optional[ShadowMatcher] = None,
                 logger: Optional[LoggerService] = None):
        """
        Args:
            matcher: the ShadowMatcher used per AOI. Injectable for testing.
            logger: optional LoggerService.
        """
        self.matcher = matcher or ShadowMatcher()
        self.logger = logger or LoggerService()

    def annotate_xml(self, xml_path: str,
                     progress_callback: Optional[Callable[[int, int], None]] = None) -> dict:
        """Annotate every AOI in an ADIAT results file with shadow data.

        Args:
            xml_path: path to an ADIAT_Data.xml. It is rewritten in place with
                a shadow descriptor on each AOI.
            progress_callback: optional callable invoked as (done, total) after
                each image.

        Returns:
            A summary dict with per-status counts plus 'images' and 'aois'.
        """
        xml_service = XmlService(xml_path)
        images = xml_service.get_images()
        summary = self.annotate_images(images, progress_callback)
        xml_service.save_xml_file(xml_path)
        return summary

    def annotate_images(
        self,
        images: list,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> dict:
        """Annotate an already-loaded list of image dicts in place.

        Descriptors are written onto each AOI's 'xml' element and its 'shadow'
        key, so a caller holding the same list (e.g. the viewer) sees the
        results immediately and can persist them with its own XmlService.

        Args:
            images: image dicts as returned by XmlService.get_images().
            progress_callback: optional callable invoked as (done, total).
            should_cancel: optional callable; when it returns True the pass
                stops after the current image.

        Returns:
            A summary dict with per-status counts, 'images', 'aois' and
            'cancelled'.
        """
        summary = {
            STATUS_OK: 0,
            STATUS_NO_SHADOW: 0,
            STATUS_UNMEASURABLE: 0,
            'images': 0,
            'aois': 0,
            'cancelled': False,
        }

        total = len(images)
        for index, image in enumerate(images):
            if should_cancel is not None and should_cancel():
                summary['cancelled'] = True
                break
            aois = image.get('areas_of_interest', [])
            if aois:
                self._annotate_image(image, aois, summary)
                summary['images'] += 1
            if progress_callback:
                progress_callback(index + 1, total)

        return summary

    def _annotate_image(self, image: dict, aois: list, summary: dict) -> None:
        """Measure and persist a descriptor for every AOI of one image."""
        try:
            context = build_shadow_context(image)
        except Exception:
            # build_shadow_context is not expected to raise, but a batch run
            # must survive it if it does.
            self.logger.error(traceback.format_exc())
            context = None

        for aoi in aois:
            try:
                descriptor = self.matcher.measure(image, aoi, context=context)
            except Exception:
                self.logger.error(traceback.format_exc())
                continue
            self._write_descriptor(aoi, descriptor)
            summary[descriptor.status] = summary.get(descriptor.status, 0) + 1
            summary['aois'] += 1

    @staticmethod
    def _write_descriptor(aoi: dict, descriptor) -> None:
        """Write a descriptor onto an AOI's XML element and dict."""
        attribs = descriptor.to_xml_attribs()
        element = aoi.get('xml')
        if element is not None:
            for key, value in attribs.items():
                element.set(key, value)
        # Mirror XmlService.get_images(): aoi['shadow'] holds the attrib dict.
        aoi['shadow'] = attribs
