"""Signaling subpackage for WebRTC pairing.

Provides the abstract :class:`SignalingChannel` interface plus concrete
implementations used by the Flight Viewer to exchange SDP / ICE /
fingerprint data with paired ADIAT Mobile publishers via the
``adiat-flight-signaling`` Cloudflare Worker.
"""

from .SignalingChannel import (
    CodeAlreadyAnswered,
    CodeNotFound,
    SessionState,
    SignalingChannel,
    ViewerCapReached,
)
from .HttpSignalingChannel import DEFAULT_WORKER_URL, HttpSignalingChannel
from .InMemorySignalingChannel import InMemorySignalingChannel
from . import pairing


def default_signaling_channel() -> SignalingChannel:
    """Pick the signaling backend based on operator configuration.

    Production default is :class:`HttpSignalingChannel` pointed at the
    canonical ``signal.adiat.app`` Cloudflare Worker. Operators can
    override via ``config.toml``:

    .. code-block:: toml

        [signaling]
        base_url = "https://my-self-hosted-worker.example/"

    If ``httpx`` is not installed (development environment without the
    WebRTC deps), falls back to :class:`InMemorySignalingChannel` so the
    UI still loads rather than failing at import time.

    Shared by the Flight Viewer and by the ADIAT Flight streaming source
    so both resolve the same Worker for a given install.
    """
    url = DEFAULT_WORKER_URL
    try:
        from helpers.AppConfig import get_section

        signaling_cfg = get_section("signaling")
        override = signaling_cfg.get("base_url")
        if isinstance(override, str) and override.strip():
            url = override.strip()
    except Exception:  # pragma: no cover - defensive
        pass

    try:
        return HttpSignalingChannel(base_url=url)
    except ImportError:
        return InMemorySignalingChannel()


__all__ = [
    "CodeAlreadyAnswered",
    "CodeNotFound",
    "DEFAULT_WORKER_URL",
    "HttpSignalingChannel",
    "InMemorySignalingChannel",
    "SessionState",
    "SignalingChannel",
    "ViewerCapReached",
    "default_signaling_channel",
    "pairing",
]
