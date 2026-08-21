"""Closing a live WebRTC feed must not report on itself.

Field report, on app close during a live feed::

    FlightTileController(SG7EZM): service error: Video track error:
    Task was destroyed but it is pending!
    task: <Task pending name='Task-4756' coro=<WebRTCStreamService._tear_down() ...>>
    task: <Task cancelling name='Task-6' coro=<..._consume_signaling() ...>>
    task: <Task pending name='Task-11' coro=<Connection.keepalive() ...>>

Every line there is the ordinary close path complaining about itself. The
unit tests cover the pieces; this drives the whole thing - ``run()`` on
this thread, then a close from "the UI thread" - and asserts the console
stays clean, which is the thing the operator actually sees.
"""

from __future__ import annotations

import asyncio
import gc
import io
import os
import sys
import threading
from contextlib import redirect_stderr

import pytest
from PySide6.QtWidgets import QApplication

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from core.services.streaming.signaling import InMemorySignalingChannel  # noqa: E402
from core.services.streaming.WebRTCStreamService import WebRTCStreamService  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _SessionLikeMain:
    """Stands in for ``_main``: the task shape a held session leaves behind.

    A live session has a signaling consumer subscribed over a websocket
    (whose library keeps its own keepalive task alive), and holds in a
    poll loop until stop is signalled. Those are the three tasks in the
    field report.
    """

    def __init__(self, service):
        self.service = service
        self.holding = threading.Event()
        self.signaling_cancelled = threading.Event()

    async def __call__(self) -> None:
        svc = self.service

        async def keepalive():
            while True:
                await asyncio.sleep(30)

        async def consume_signaling():
            try:
                # Blocked in ws.recv(), which is where the field report
                # caught it - not polling _stop, so only the cancel from
                # _tear_down ends it.
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                # A real cancel unwinds through the websocket close, which
                # yields before it is done.
                await asyncio.sleep(0)
                self.signaling_cancelled.set()
                raise

        asyncio.ensure_future(keepalive())
        svc._signaling_task = asyncio.ensure_future(consume_signaling())

        self.holding.set()
        # The hold loop from _negotiate_once: exits on stop.
        while not svc._stop.is_set():
            await asyncio.sleep(0.01)


def _close_from_the_ui_thread(service, main, *, explicit: bool):
    """Wait until the session is held, then close it the way the app does."""

    def closer():
        assert main.holding.wait(5.0), "session never reached its hold loop"
        if explicit:
            service.request_disconnect()   # the tile's X
        else:
            service.cleanup()              # app exit / viewer window X

    thread = threading.Thread(target=closer, daemon=True)
    thread.start()
    return thread


@pytest.mark.parametrize("explicit", [True, False], ids=["tile-x", "app-exit"])
def test_closing_a_live_feed_prints_nothing(qapp, monkeypatch, explicit) -> None:
    service = WebRTCStreamService(
        signaling=InMemorySignalingChannel(), pairing_code="ABC234"
    )
    main = _SessionLikeMain(service)
    monkeypatch.setattr(service, "_main", main)

    errors = []
    service.errorOccurred.connect(errors.append)

    closer = _close_from_the_ui_thread(service, main, explicit=explicit)
    noise = io.StringIO()
    with redirect_stderr(noise):
        service.run()
        # asyncio reports abandoned tasks from their __del__, so collection
        # is when a leak would surface.
        gc.collect()
    closer.join(5.0)

    assert "was destroyed but it is pending" not in noise.getvalue(), noise.getvalue()
    assert errors == []


@pytest.mark.parametrize("explicit", [True, False], ids=["tile-x", "app-exit"])
def test_closing_a_live_feed_unwinds_the_signaling_consumer(
        qapp, monkeypatch, explicit) -> None:
    """The pending task in the report was a half-run teardown, and what it
    was suspended on was this cancel. Left unfinished, the websocket never
    got closed - so proving it *completes* is the point, not just that the
    console is quiet."""
    service = WebRTCStreamService(
        signaling=InMemorySignalingChannel(), pairing_code="ABC234"
    )
    main = _SessionLikeMain(service)
    monkeypatch.setattr(service, "_main", main)

    closer = _close_from_the_ui_thread(service, main, explicit=explicit)
    service.run()
    closer.join(5.0)

    assert main.signaling_cancelled.is_set(), \
        "the signaling consumer's cancellation never finished unwinding"
    assert service._teardown_task is None
    assert service._loop is None


def test_a_closed_feed_reports_disconnected_once(qapp, monkeypatch) -> None:
    """Whatever the shutdown does internally, the UI still gets its one
    status transition - the tile's badge depends on it."""
    service = WebRTCStreamService(
        signaling=InMemorySignalingChannel(), pairing_code="ABC234"
    )
    main = _SessionLikeMain(service)
    monkeypatch.setattr(service, "_main", main)

    statuses = []
    service.connectionStatusChanged.connect(
        lambda connected, text: statuses.append((connected, text))
    )

    closer = _close_from_the_ui_thread(service, main, explicit=True)
    service.run()
    closer.join(5.0)

    assert statuses[-1] == (False, "Disconnected")
    assert statuses.count((False, "Disconnected")) == 1


@pytest.mark.parametrize("explicit", [True, False], ids=["tile-x", "app-exit"])
def test_the_worker_session_is_deleted_at_most_once(qapp, monkeypatch, explicit) -> None:
    """Teardown is the only place ``delete_session`` is called, and closing
    must call it exactly once - the tile's X ends the session on the
    Worker, an accidental close deliberately leaves it for the orphan
    handler so the next launch can reconnect on the same code (plan §20).

    A regression guard, not a fix: the reworked shutdown decides *which*
    teardown runs, so this pins the §20 gating to the close path rather
    than to whichever teardown happened to get there first.
    """
    signaling = InMemorySignalingChannel()
    deletes = []
    original = signaling.delete_session

    async def counting_delete(code):
        deletes.append(code)
        return await original(code)

    monkeypatch.setattr(signaling, "delete_session", counting_delete)

    service = WebRTCStreamService(signaling=signaling, pairing_code="ABC234")
    main = _SessionLikeMain(service)
    monkeypatch.setattr(service, "_main", main)

    closer = _close_from_the_ui_thread(service, main, explicit=explicit)
    service.run()
    closer.join(5.0)

    assert deletes == (["ABC234"] if explicit else [])
