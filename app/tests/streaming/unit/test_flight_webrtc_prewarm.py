"""Unit tests for the WebRTC import warmup's lifecycle.

The warmup loads aiortc's native dependencies (PyAV, cryptography, dns) off
the Qt main thread so the first Connect click does not stall the UI. Two
properties keep that from being a hazard, and both are pinned here:

* it runs **once per process** - a thread per controller construction
  re-imported modules already in ``sys.modules`` for nothing;
* the thread stays **reachable and joinable** - an unjoined thread running
  native imports outlived the code that started it and took the whole
  interpreter down with "Windows fatal exception: code 0x80000003", raised
  while garbage-collecting mid-import.
"""

from __future__ import annotations

import importlib
import os
import sys
import threading

import pytest
from PySide6.QtWidgets import QApplication

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from core.services.streaming.signaling import InMemorySignalingChannel  # noqa: E402

# The package __init__ re-exports the class under the module's own name, so
# reach the module itself explicitly - these tests manipulate its globals.
fvc = importlib.import_module("core.controllers.flight.FlightViewerController")
FlightViewerController = fvc.FlightViewerController


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def reset_prewarm():
    """Run each test against a fresh warmup state, then restore the real one.

    The module-level handle is process-wide, so a test that starts a warmup
    must not leave that visible to the rest of the suite.
    """
    original = fvc._prewarm_thread
    fvc._prewarm_thread = None
    yield
    fvc.wait_for_webrtc_prewarm(timeout=30.0)
    fvc._prewarm_thread = original


def test_start_returns_a_live_or_finished_thread(reset_prewarm):
    thread = fvc.start_webrtc_prewarm()

    assert isinstance(thread, threading.Thread)
    assert thread.name == "adiat-webrtc-prewarm"
    # Daemon so a wedged native import can never hold the process open.
    assert thread.daemon is True


def test_second_call_reuses_the_first_run(reset_prewarm):
    """Idempotent per process: N callers must not mean N import threads."""
    first = fvc.start_webrtc_prewarm()
    second = fvc.start_webrtc_prewarm()

    assert first is second


def test_wait_reports_completion(reset_prewarm):
    fvc.start_webrtc_prewarm()

    assert fvc.wait_for_webrtc_prewarm(timeout=30.0) is True
    assert not fvc._prewarm_thread.is_alive()


def test_wait_with_no_warmup_started_is_true(reset_prewarm):
    """Nothing to join is success, not a timeout."""
    assert fvc.wait_for_webrtc_prewarm(timeout=0) is True


def test_wait_reports_a_thread_that_has_not_finished(reset_prewarm):
    """A zero timeout on a blocked warmup reports 'still running', not True."""
    release = threading.Event()
    try:
        fvc._prewarm_thread = threading.Thread(
            target=release.wait, name="adiat-webrtc-prewarm", daemon=True)
        fvc._prewarm_thread.start()

        assert fvc.wait_for_webrtc_prewarm(timeout=0) is False
    finally:
        release.set()
        fvc._prewarm_thread.join(timeout=30.0)


def test_constructing_two_controllers_starts_one_warmup(reset_prewarm, tmp_path):
    """The leak this fixes: every controller used to spawn its own thread."""
    first = FlightViewerController(
        signaling=InMemorySignalingChannel())
    started = fvc._prewarm_thread
    second = FlightViewerController(
        signaling=InMemorySignalingChannel())

    assert fvc._prewarm_thread is started

    first.shutdown()
    second.shutdown()


def test_shutdown_leaves_no_warmup_running(reset_prewarm):
    """shutdown() joins the warmup so it cannot outlive the viewer."""
    controller = FlightViewerController(
        signaling=InMemorySignalingChannel())

    controller.shutdown()

    assert not fvc._prewarm_thread.is_alive()
