"""Derive capture settings from a video, so the operator doesn't guess.

The streaming setup guide asks two questions that decide GSD — which
drone/camera shot the video, and how high it was flying — and both are
usually recorded *in* the file:

* **Aircraft** — DJI writes it into the MP4's ``encoder`` container tag
  (``"DJI DJI Matrice 4E"``). This is the video counterpart to the EXIF
  Make/Model that image analysis already matches against ``drones.pkl``.
* **Altitude** — the embedded telemetry track carries per-frame
  ``rel_alt`` (height above the takeoff point), the same field the HUD
  and map use.

Getting either wrong is not cosmetic. GSD scales linearly with altitude
and detection area with GSD², so a video shot at 49 ft but configured as
150 ft produces min/max detection areas roughly 9× off — enough to
filter out the very targets the operator is looking for. Picking the
wrong airframe is worse still, because sibling models carry different
sensors (a Matrice 4E has Wide/Medium/Zoom; a 4T has Wide/Zoom/Thermal).

Detection is advisory: the wizard pre-selects what is found and the
operator can override it.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from typing import Optional

from core.services.LoggerService import LoggerService
from core.services.telemetry.TelemetrySourceResolver import load_telemetry_for_video
from helpers.VideoFileHelper import get_video_device_tags

# Container tags that may name the capturing device, best first.
_DEVICE_TAG_KEYS = ("encoder", "model", "com.apple.quicktime.model", "make")


@dataclass
class VideoCaptureInfo:
    """What we could work out about how a video was captured."""

    make: Optional[str] = None
    model: Optional[str] = None
    device_text: Optional[str] = None      # raw tag the model came from
    altitude_agl_m: Optional[float] = None
    altitude_samples: int = 0

    @property
    def has_device(self) -> bool:
        return bool(self.make and self.model)

    @property
    def has_altitude(self) -> bool:
        return self.altitude_agl_m is not None


def read_device_text(video_path, logger=None) -> Optional[str]:
    """Return the container tag most likely to name the capture device."""
    tags = get_video_device_tags(video_path, logger=logger)
    for key in _DEVICE_TAG_KEYS:
        value = tags.get(key)
        if value and value.strip():
            return value.strip()
    return None


def match_drone_model(device_text: str, drones_df) -> Optional[tuple]:
    """Match a container device string against the drone table.

    DJI writes the tag two different ways, and both appear in the wild:

    * the human-readable name, with the make repeated —
      ``"DJI DJI Matrice 4E"``; and
    * the short EXIF-style code — ``"DJI M4TD"``, which lives in the
      table's ``Model (Exif)`` column as ``"M4T, M4TD"``.

    Exact equality is therefore useless. Codes are matched as whole words
    (so ``M4T`` does not match inside ``M4TD``) and names by containment,
    with codes preferred because they are unambiguous.

    Returns:
        ``(manufacturer, model)`` on a confident match, else None.
    """
    if not device_text or drones_df is None or drones_df.empty:
        return None

    haystack = _normalize(device_text)
    words = set(haystack.split())

    code_match = None
    name_match = None
    name_length = 0

    for _, row in drones_df.iterrows():
        make = _clean(row.get("Manufacturer"))
        model = _clean(row.get("Model"))
        if not make or not model:
            continue
        # The make must appear too, so a bare "Mini 3" in some unrelated
        # vendor's tag cannot match a DJI row.
        if _normalize(make) not in haystack:
            continue

        # 1. EXIF-style codes, as whole words.
        for code in _split_codes(row.get("Model (Exif)")):
            if code and code in words:
                code_match = (make, model)
                break
        if code_match:
            break

        # 2. Human-readable name, by containment. Longest wins so
        #    "Matrice 4E" beats a "Matrice 4" row that prefixes it.
        needle = _normalize(model)
        if needle and needle in haystack and len(needle) > name_length:
            name_length = len(needle)
            name_match = (make, model)

    return code_match or name_match


def detect_capture_info(video_path, drones_df=None, logger=None) -> VideoCaptureInfo:
    """Work out the aircraft and flight altitude for ``video_path``.

    Args:
        video_path: Path to the video.
        drones_df: Drone/sensor table. Loaded from ``drones.pkl`` when None.
        logger: Optional logger.

    Returns:
        A :class:`VideoCaptureInfo`; every field is optional, so callers
        must check ``has_device`` / ``has_altitude`` before using it.
    """
    logger = logger or LoggerService()
    info = VideoCaptureInfo()

    # --- aircraft -----------------------------------------------------
    try:
        device_text = read_device_text(video_path, logger=logger)
        info.device_text = device_text
        if device_text:
            if drones_df is None:
                from helpers.PickleHelper import PickleHelper
                drones_df = PickleHelper.get_drone_sensor_info()
            match = match_drone_model(device_text, drones_df)
            if match:
                info.make, info.model = match
    except Exception as e:  # noqa: BLE001 - detection is advisory
        logger.debug(f"Drone detection failed for {video_path}: {e}")

    # --- altitude -----------------------------------------------------
    try:
        resolution = load_telemetry_for_video(video_path, None, logger=logger)
        if resolution.found:
            altitudes = [
                point.altitude_agl_m
                for point in resolution.track.points
                if point.altitude_agl_m is not None
            ]
            if altitudes:
                # Median, not mean: takeoff/landing segments and the odd
                # bad fix would drag an average away from the altitude the
                # bulk of the footage was actually shot at.
                info.altitude_agl_m = float(statistics.median(altitudes))
                info.altitude_samples = len(altitudes)
    except Exception as e:  # noqa: BLE001 - detection is advisory
        logger.debug(f"Altitude detection failed for {video_path}: {e}")

    return info


def _clean(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in ("nan", "none") else text


def _split_codes(value) -> list:
    """Split a ``Model (Exif)`` cell (``"M4T, M4TD"``) into normalized codes."""
    text = _clean(value)
    if not text:
        return []
    return [_normalize(part) for part in text.split(",") if _normalize(part)]


def _normalize(text: str) -> str:
    """Lower-case and collapse punctuation/whitespace for containment tests."""
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()
