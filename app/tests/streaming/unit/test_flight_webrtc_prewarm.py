"""Unit tests for loading the WebRTC native libraries.

``aiortc`` pulls in PyAV (FFmpeg bindings), ``cryptography`` (a Rust
extension), ``aioice`` and ``dnspython`` — about a second of native
initialisation. The Flight Viewer front-loads that at window open so the
first Connect click is instant.

This used to happen on a daemon thread, which crashed the interpreter with
``Windows fatal exception: code 0x80000003`` on roughly 40% of full test
runs: the import allocates enough to guarantee a cyclic-GC pass, and
collecting on a worker thread while the Qt main thread destroys QObjects
with the GIL released traverses shiboken wrappers mid-deletion. The load is
now synchronous on the calling thread, which is what these tests pin —
because the temptation to "just move it back off the main thread" is
exactly how the crash returns.
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
def reset_import_state():
    """Run each test against a fresh load state, then restore the real one.

    The cached flag is process-wide, so a test that clears it must not
    leave that visible to the rest of the suite.
    """
    original = fvc._webrtc_imports_loaded
    fvc._webrtc_imports_loaded = None
    yield
    fvc._webrtc_imports_loaded = original


def test_reports_success_when_aiortc_is_available(reset_import_state):
    assert fvc.ensure_webrtc_imports() is True
    assert "aiortc" in sys.modules


def test_result_is_cached_per_process(reset_import_state):
    """N callers must not mean N trips through the import machinery."""
    assert fvc.ensure_webrtc_imports() is True
    assert fvc._webrtc_imports_loaded is True

    # A second call must not re-enter the import system at all.
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__
    calls = []

    def counting_import(name, *args, **kwargs):
        calls.append(name)
        return real_import(name, *args, **kwargs)

    import builtins
    builtins.__import__ = counting_import
    try:
        assert fvc.ensure_webrtc_imports() is True
    finally:
        builtins.__import__ = real_import

    assert calls == []


def test_missing_aiortc_is_reported_not_raised(reset_import_state, monkeypatch):
    """A machine without aiortc must still get a Flight Viewer window."""
    import builtins

    real_import = builtins.__import__

    def refuse_aiortc(name, *args, **kwargs):
        if name.startswith("aiortc"):
            raise ImportError("No module named 'aiortc'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse_aiortc)

    assert fvc.ensure_webrtc_imports() is False
    # Cached, so a machine without the dependency does not retry forever.
    assert fvc._webrtc_imports_loaded is False


def test_runs_on_the_calling_thread(reset_import_state):
    """The crash fix: no worker thread may be spawned to do this.

    Collecting garbage on a non-main thread while Qt tears down QObjects is
    what took the interpreter down, so the load has to happen inline.
    """
    before = {t.ident for t in threading.enumerate()}

    fvc.ensure_webrtc_imports()

    after = {t.ident for t in threading.enumerate()}
    assert after <= before, "ensure_webrtc_imports must not start a thread"


def test_no_prewarm_thread_api_remains():
    """Guard against the old daemon-thread warmup being reintroduced."""
    for name in ("start_webrtc_prewarm", "wait_for_webrtc_prewarm", "_prewarm_thread"):
        assert not hasattr(fvc, name), f"{name} should be gone - it was the crash"


def test_constructing_a_controller_loads_the_imports(reset_import_state):
    controller = FlightViewerController(signaling=InMemorySignalingChannel())
    try:
        assert fvc._webrtc_imports_loaded is True
    finally:
        controller.shutdown()


def test_constructing_two_controllers_loads_once(reset_import_state):
    """Idempotent per process, as the threaded version was."""
    first = FlightViewerController(signaling=InMemorySignalingChannel())
    second = FlightViewerController(signaling=InMemorySignalingChannel())
    try:
        assert fvc._webrtc_imports_loaded is True
    finally:
        first.shutdown()
        second.shutdown()


def test_shutdown_leaves_no_import_thread_behind(reset_import_state):
    """The property the old code could only approximate with a join."""
    names_before = {t.name for t in threading.enumerate()}

    controller = FlightViewerController(signaling=InMemorySignalingChannel())
    controller.shutdown()

    leaked = {t.name for t in threading.enumerate()} - names_before
    assert not any("prewarm" in name for name in leaked)
