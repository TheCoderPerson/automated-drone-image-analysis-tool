"""Reader for ``video.csv`` — the video/telemetry data dictionary.

``xmp.csv`` records where each telemetry value lives in an image's XMP.
This is its video counterpart: where each value lives in a video's SRT, and
what the aircraft means by it. The two differ in a way that forces a
separate table rather than extra ``drones.csv`` columns:

* **The identity key is different.** Images are matched on the EXIF model
  (``FC3411``, ``M4E``); videos are matched on the *container* tag, which
  DJI writes either as a human name (``DJI DJI Matrice 4E``) or a short code
  (``DJI M4TD``). ``Video Device Tag`` holds those verbatim, comma-separated.
* **Values are encoded differently between firmware generations, and not
  uniformly.** Legacy writes ``focal_len: 224`` for 22.4 mm (/10),
  ``fnum: 280`` for f/2.8 (/100) and ``dzoom_ratio: 10000`` for 1.0x
  (/10000) — three different divisors in one stream. ``Value Scales``
  therefore holds per-key divisors rather than one factor.

The rows are per ``(Model, Camera)`` because the camera decides which sensor
row in ``drones.csv`` applies, and two different signals identify it:

* **``Filename Suffix``** — a Matrice 30T records one video per camera
  (``..._W.MP4`` / ``_Z`` / ``_T``). This is the stronger signal: it survives
  remuxing and needs no telemetry. It cannot identify the *model*, though —
  plenty of DJI aircraft write ``_W``.
* **``SRT Focal Len``** — a Matrice 4E writes a single ``_V`` file and reports
  ``focal_len: 24.00`` for Wide.

Airframe-level facts repeat across a model's camera rows, the same way
``drones.csv`` repeats ``Model (Exif)``.

Facts this table exists to carry, none of which a video states about itself:

``Altitude Datum``
    ``Relative`` / ``MSL`` for the legacy single ``altitude`` key, whose
    meaning differs between aircraft, or ``Both`` when the explicit
    ``rel_alt``/``abs_alt`` pair is written. Blank means unverified, and the
    parser infers from the track instead.
``Gimbal * Key`` / ``Nadir Convention``
    Which keys carry the gimbal triad, and what pitch value means straight
    down (DJI: ``-90``). Legacy sidecars carry **no** gimbal fields at all,
    so tilt is unknowable for those aircraft — which matters, because
    ignoring a 46 deg tilt at 88 m AGL misplaces a detection by ~93 m.
``Telemetry Location``
    ``Sidecar`` telemetry is a separate file an operator can leave on the
    card, losing all GPS; ``Embedded`` travels with the video.

Every lookup degrades to None rather than raising: the table may be absent,
may predate a column, and any remuxed video loses its device tag entirely
(it becomes ``Lavf...``), so callers must always have a fallback.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, replace
from typing import List, Optional

# Altitude datum values, normalized. The CSV holds human spellings.
DATUM_MSL = "msl"
DATUM_RELATIVE = "relative"
# The aircraft writes the explicit rel_alt/abs_alt pair, so nothing is
# ambiguous and no datum needs applying. Recorded so a verified modern
# aircraft is distinguishable from one nobody has checked.
DATUM_EXPLICIT = "explicit"

LOCATION_SIDECAR = "sidecar"
LOCATION_EMBEDDED = "embedded"

_DATUM_ALIASES = {
    "msl": DATUM_MSL, "asl": DATUM_MSL, "abs": DATUM_MSL,
    "absolute": DATUM_MSL, "sealevel": DATUM_MSL,
    "agl": DATUM_RELATIVE, "rel": DATUM_RELATIVE, "relative": DATUM_RELATIVE,
    "takeoff": DATUM_RELATIVE, "takeoffrelative": DATUM_RELATIVE,
    "both": DATUM_EXPLICIT, "explicit": DATUM_EXPLICIT, "pair": DATUM_EXPLICIT,
    "relaltabsalt": DATUM_EXPLICIT,
}


def normalize_datum(value) -> Optional[str]:
    """Map a CSV cell onto a ``DATUM_*`` value, or None if unreadable.

    None must leave the decision to inference rather than silently picking
    a datum.
    """
    key = _alnum(value)
    return _DATUM_ALIASES.get(key) if key else None


@dataclass
class VideoProfile:
    """One row of ``video.csv``: how to read one camera's telemetry."""

    manufacturer: str = ""
    model: str = ""
    camera: str = ""
    filename_suffix: str = ""
    device_tags: List[str] = field(default_factory=list)
    srt_focal_len: Optional[float] = None
    telemetry_location: Optional[str] = None
    telemetry_format: Optional[str] = None
    value_scales: dict = field(default_factory=dict)
    latitude_key: Optional[str] = None
    longitude_key: Optional[str] = None
    altitude_msl_key: Optional[str] = None
    altitude_agl_key: Optional[str] = None
    altitude_datum: Optional[str] = None
    gimbal_pitch_key: Optional[str] = None
    gimbal_yaw_key: Optional[str] = None
    gimbal_roll_key: Optional[str] = None
    nadir_convention: Optional[float] = None
    zoom_ratio_key: Optional[str] = None

    @property
    def has_gimbal(self) -> bool:
        """True when this aircraft reports a gimbal pitch.

        False means tilt cannot be recovered from the stream at all, so a
        nadir assumption is a guess rather than a measurement — the caller
        should say so instead of quietly computing as if it were nadir.
        """
        return bool(self.gimbal_pitch_key)

    @property
    def writes_sidecar(self) -> Optional[bool]:
        if self.telemetry_location == LOCATION_SIDECAR:
            return True
        if self.telemetry_location == LOCATION_EMBEDDED:
            return False
        return None

    def descale(self, key: str, value) -> Optional[float]:
        """Convert a raw SRT number for ``key`` into real units.

        The divisor is per-key, not per-firmware: the same legacy stream
        writes ``focal_len: 224`` for 22.4 mm, ``fnum: 280`` for f/2.8 and
        ``dzoom_ratio: 10000`` for 1.0x. Assuming one factor for all three
        is wrong by 10x on two of them.
        """
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        divisor = self.value_scales.get(str(key).strip().lower())
        if not divisor:
            return number
        return number / divisor

    def off_nadir_degrees(self, gimbal_pitch) -> Optional[float]:
        """Angle between the camera axis and straight down, in degrees.

        Needs ``Nadir Convention`` because the reported value is not an
        off-nadir angle: DJI writes ``-90`` for straight down, so a reported
        ``-43.5`` is 46.5 deg off nadir, not 43.5.

        Signed subtraction, not a difference of magnitudes: a gimbal tilted
        *above* the horizon reports a positive pitch, and taking absolute
        values first folds it back down. With ``-90`` as nadir, a reported
        ``+30`` is 120 deg off nadir; ``abs(abs(-90) - abs(30))`` gives 60.
        """
        if self.nadir_convention is None:
            return None
        try:
            pitch = float(gimbal_pitch)
        except (TypeError, ValueError):
            return None
        return abs(self.nadir_convention - pitch)


def load_profiles(video_df=None) -> List[VideoProfile]:
    """Read every row of ``video.csv`` into :class:`VideoProfile` objects."""
    try:
        if video_df is None:
            from helpers.PickleHelper import PickleHelper
            video_df = PickleHelper.get_video_telemetry_info()
        if video_df is None or video_df.empty:
            return []
        return [_profile_from_row(row) for _, row in video_df.iterrows()]
    except Exception:  # noqa: BLE001 - reference data, never load-bearing
        return []


def profiles_for_device_tag(device_text, video_df=None) -> List[VideoProfile]:
    """Every profile whose ``Video Device Tag`` matches a container tag.

    Tags are matched as bounded phrases on a normalized form, so ``M4T``
    does not match inside ``M4TD`` while a multi-word name such as
    ``DJI DJI Matrice 4E`` still does.
    """
    if not device_text:
        return []
    haystack = f" {_normalize(device_text)} "
    matched = []
    for profile in load_profiles(video_df):
        for tag in profile.device_tags:
            if tag and f" {_normalize(tag)} " in haystack:
                matched.append(profile)
                break
    return matched


def suffix_from_filename(video_path) -> Optional[str]:
    """The camera suffix in a DJI filename, e.g. ``W`` from ``..._0019_W.MP4``.

    Survives remuxing, since it is part of the name rather than the
    container — which is why it beats ``focal_len`` for picking the camera.
    """
    if not video_path:
        return None
    stem = os.path.splitext(os.path.basename(str(video_path)))[0]
    match = re.search(r"_([A-Za-z])$", stem)
    return match.group(1).upper() if match else None


def profile_for_video(video_path, video_df=None, logger=None,
                      focal_len=None) -> Optional[VideoProfile]:
    """Resolve the profile for a video, by container tag then camera.

    Args:
        video_path: Path to the video. Its filename suffix is used to pick
            the camera when the airframe records one file per camera.
        video_df: Dictionary table; loaded from ``video.csv`` when None.
        logger: Optional logger.
        focal_len: The stream's raw ``focal_len``, a fallback camera signal
            for airframes that write a single file. Without either signal
            the first row for the airframe is returned, which is correct for
            every airframe-level field.

    Returns:
        A :class:`VideoProfile`, or None when the aircraft cannot be
        identified — which is the case for any remuxed video, since the
        suffix names a camera but never a model.
    """
    try:
        from helpers.VideoFileHelper import get_video_device_tags
        tags = get_video_device_tags(video_path, logger=logger) or {}
        suffix = suffix_from_filename(video_path)
        for key in ("encoder", "model", "com.apple.quicktime.model", "make"):
            text = tags.get(key)
            if not text or not str(text).strip():
                continue
            matches = profiles_for_device_tag(str(text).strip(), video_df)
            if not matches:
                continue
            # Filename suffix first: it is unambiguous and needs no telemetry.
            if suffix:
                declared = [p for p in matches if p.filename_suffix]
                for profile in declared:
                    if profile.filename_suffix == suffix:
                        return profile
                if declared:
                    # This airframe records one file per camera, but *this*
                    # camera is not in the table. Falling through would return
                    # some other camera's row, handing the caller the wrong
                    # sensor geometry — a Mavic 3T ``_W`` video would come back
                    # as Thermal. Keep the airframe facts, which are shared,
                    # and state no camera rather than the wrong one.
                    return replace(matches[0], camera="", filename_suffix="",
                                   srt_focal_len=None)
            if focal_len is not None:
                for profile in matches:
                    if profile.srt_focal_len is not None and _close(
                            profile.srt_focal_len, focal_len):
                        return profile
            return matches[0]
    except Exception as exc:  # noqa: BLE001 - advisory
        if logger:
            logger.debug(f"Video profile lookup failed for {video_path}: {exc}")
    return None


def datum_for_video(video_path, video_df=None, logger=None) -> Optional[str]:
    """The recorded altitude datum for a video's aircraft, or None.

    None whenever the aircraft cannot be identified or its datum is
    unverified, which leaves the parser's inference in charge.
    """
    profile = profile_for_video(video_path, video_df=video_df, logger=logger)
    return profile.altitude_datum if profile else None


# ----------------------------------------------------------------------
# internals
# ----------------------------------------------------------------------


def _profile_from_row(row) -> VideoProfile:
    return VideoProfile(
        manufacturer=_text(row.get("Manufacturer")),
        model=_text(row.get("Model")),
        camera=_text(row.get("Camera")),
        filename_suffix=_text(row.get("Filename Suffix")).lstrip("_").upper(),
        device_tags=[t.strip() for t in _text(row.get("Video Device Tag")).split(",")
                     if t.strip()],
        srt_focal_len=_number(row.get("SRT Focal Len")),
        telemetry_location=_lower(row.get("Telemetry Location")) or None,
        telemetry_format=_lower(row.get("Telemetry Format")) or None,
        value_scales=_parse_scales(row.get("Value Scales")),
        latitude_key=_text(row.get("Latitude Key")) or None,
        longitude_key=_text(row.get("Longitude Key")) or None,
        altitude_msl_key=_text(row.get("Altitude MSL Key")) or None,
        altitude_agl_key=_text(row.get("Altitude AGL Key")) or None,
        altitude_datum=normalize_datum(row.get("Altitude Datum")),
        gimbal_pitch_key=_text(row.get("Gimbal Pitch Key")) or None,
        gimbal_yaw_key=_text(row.get("Gimbal Yaw Key")) or None,
        gimbal_roll_key=_text(row.get("Gimbal Roll Key")) or None,
        nadir_convention=_number(row.get("Nadir Convention")),
        zoom_ratio_key=_text(row.get("Zoom Ratio Key")) or None,
    )


def _parse_scales(value) -> dict:
    """Parse ``"focal_len:10, fnum:100"`` into ``{key: divisor}``.

    Unparseable pairs are dropped rather than defaulted, so a typo leaves
    the raw value untouched instead of scaling it by a guess.
    """
    scales: dict = {}
    for part in _text(value).split(","):
        if ":" not in part:
            continue
        key, _, divisor = part.partition(":")
        number = _number(divisor)
        if key.strip() and number:
            scales[key.strip().lower()] = number
    return scales


def _text(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in ("nan", "none") else text


def _lower(value) -> str:
    return _text(value).lower()


def _alnum(value) -> str:
    return "".join(ch for ch in _text(value).lower() if ch.isalnum())


def _number(value) -> Optional[float]:
    text = _text(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _normalize(text) -> str:
    """Lower-case and collapse punctuation, matching drones.csv matching."""
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def _close(a: float, b) -> bool:
    try:
        return abs(float(a) - float(b)) < 0.51
    except (TypeError, ValueError):
        return False
