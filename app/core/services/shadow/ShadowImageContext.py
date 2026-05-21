"""ShadowImageContext - per-image data shared across all of an image's AOIs.

Building a CameraModel, projecting service, and resolving the sun position
each cost a metadata read and an image decode. When a whole folder of AOIs is
annotated, those costs should be paid once per image, not once per AOI. This
module gathers them into a context that ShadowMatcher and ShadowHeightEstimator
both accept.

Kept in its own module so both consumers can import it without a cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import cv2

from helpers.MetaDataHelper import MetaDataHelper
from helpers.LocationInfo import LocationInfo
from core.services.image.AOIService import AOIService
from core.services.CameraModel import CameraModel
from core.services.LoggerService import LoggerService
from core.services.shadow.SolarPosition import (
    get_solar_position,
    resolve_capture_utc,
)


@dataclass
class ShadowImageContext:
    """Reusable per-image inputs for the shadow matcher.

    Attributes:
        image: the ADIAT image-metadata dict.
        img_bgr: the decoded image in BGR order, or None if it could not load.
        exif_data: piexif-format EXIF dict, or None.
        xmp_data: parsed XMP dict, or None.
        aoi_service: an AOIService for pixel/ground projection, or None.
        camera: a CameraModel for the image pose, or None.
        utc_dt: resolved capture time (UTC), or None.
        sun_elevation_deg, sun_azimuth_deg: sun position, or None.
        error: a short reason string when the context is unusable.
    """

    image: dict
    img_bgr: Optional[object] = None
    exif_data: Optional[dict] = None
    xmp_data: Optional[dict] = None
    aoi_service: Optional[AOIService] = None
    camera: Optional[CameraModel] = None
    utc_dt: Optional[datetime] = None
    sun_elevation_deg: Optional[float] = None
    sun_azimuth_deg: Optional[float] = None
    error: Optional[str] = None

    def is_valid(self) -> bool:
        """True when the context has everything the matcher needs."""
        return (
            self.error is None
            and self.img_bgr is not None
            and self.camera is not None
            and self.sun_elevation_deg is not None
            and self.sun_azimuth_deg is not None
        )


def build_shadow_context(image: dict, logger: Optional[LoggerService] = None) -> ShadowImageContext:
    """Assemble a ShadowImageContext for one image.

    Never raises: any missing or malformed metadata leaves the corresponding
    field None and sets `error`, so the matcher can return an 'unmeasurable'
    descriptor instead of crashing a batch.

    Args:
        image: the ADIAT image-metadata dict (must contain 'path').
        logger: optional LoggerService for diagnostics.

    Returns:
        A ShadowImageContext; check is_valid() before use.
    """
    logger = logger or LoggerService()
    context = ShadowImageContext(image=image)

    # Projection service - also gives us the decoded image and CameraModel.
    try:
        context.aoi_service = AOIService(image)
        rgb = context.aoi_service.image_service.img_array
        if rgb is not None:
            context.img_bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        context.camera = CameraModel.from_image_service(
            context.aoi_service.image_service
        )
    except Exception as exc:
        context.error = f"Could not load image for shadow analysis: {exc}"
        logger.error(context.error)
        return context

    if context.img_bgr is None:
        context.error = "Image pixels could not be decoded."
        return context
    if context.camera is None:
        context.error = "Camera pose unavailable (intrinsics, altitude or pitch missing)."
        return context

    # EXIF / XMP - needed for sun position and reused by ShadowHeightEstimator.
    try:
        context.exif_data = MetaDataHelper.get_exif_data_piexif(image['path'])
    except Exception as exc:
        context.error = f"Could not read EXIF: {exc}"
        return context
    try:
        context.xmp_data = MetaDataHelper.get_xmp_data(image['path'], parse=True)
    except Exception:
        context.xmp_data = None

    # Sun position at the image-centre GPS - the sun barely moves across the
    # few hundred metres an image covers, so a per-image value is enough.
    gps = LocationInfo.get_gps(exif_data=context.exif_data)
    if not gps:
        context.error = "Image has no GPS coordinates; cannot place the sun."
        return context
    try:
        context.utc_dt, _ = resolve_capture_utc(context.exif_data, context.xmp_data)
    except Exception as exc:
        context.error = f"Could not resolve capture time: {exc}"
        return context
    try:
        elevation, azimuth = get_solar_position(
            gps['latitude'], gps['longitude'], context.utc_dt
        )
    except Exception as exc:
        context.error = f"Could not compute sun position: {exc}"
        return context
    context.sun_elevation_deg = elevation
    context.sun_azimuth_deg = azimuth
    return context
