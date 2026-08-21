"""Tests for the one place the app starts a terrain download.

The controller's whole job is to be harmless and identical for every
trigger: put the work on a thread, say what happened once, cancel when the
caller goes away, and never raise into whoever called it.
"""

from unittest.mock import MagicMock, patch

import pytest

from PySide6.QtWidgets import QApplication

from core.controllers.images.TerrainAcquisitionController import (
    TerrainAcquisitionController,
)
from core.services.terrain.TerrainAcquisitionService import (
    SKIP_COVERED,
    SKIP_OFFLINE,
    TRIGGER_ANALYSIS,
    TRIGGER_EXPORT,
    TRIGGER_VIEWER_OPEN,
    AcquisitionOutcome,
    AcquisitionPlan,
)


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def controller():
    return TerrainAcquisitionController(
        settings_service=MagicMock(), logger=MagicMock())


def _plan():
    return AcquisitionPlan(provider_id='fake', bounds=(0, 0, 1, 1),
                           estimated_mb=1.0, detail='AWS Terrain Tiles')


def _service(enabled=True, outcome=None, boom=None):
    service = MagicMock()
    service.enabled.return_value = enabled
    if boom is not None:
        service.run.side_effect = boom
    else:
        service.run.return_value = outcome or AcquisitionOutcome(
            plan=_plan(), tiles_written=3, registered=True)
    return service


def _patched(service):
    return patch(
        'core.controllers.images.TerrainAcquisitionController.TerrainAcquisitionService',
        return_value=service,
    )


class TestStartConditions:
    def test_the_service_gates_decide_whether_anything_starts(self, controller, tmp_path):
        """The controller re-implements no policy of its own."""
        service = _service(enabled=False)
        with _patched(service):
            assert controller.ensure(input_folder=str(tmp_path)) is False
        service.run.assert_not_called()

    def test_an_explicit_bbox_needs_no_images(self, controller, qtbot):
        with _patched(_service()):
            assert controller.ensure(bounds=(-97.8, 30.6, -97.7, 30.7)) is True
        qtbot.waitUntil(lambda: controller._worker is None, timeout=3000)

    def test_a_folder_with_no_images_starts_nothing(self, controller, tmp_path):
        with _patched(_service()):
            assert controller.ensure(input_folder=str(tmp_path)) is False

    def test_a_missing_folder_starts_nothing(self, controller):
        with _patched(_service()):
            assert controller.ensure(input_folder="Z:/no/such/folder") is False

    def test_no_area_at_all_starts_nothing(self, controller):
        with _patched(_service()):
            assert controller.ensure() is False

    def test_a_service_that_explodes_on_construction_is_swallowed(
            self, controller, tmp_path):
        """Whatever triggered this must not fail because terrain did."""
        (tmp_path / "a.jpg").write_bytes(b"x")
        with patch(
            'core.controllers.images.TerrainAcquisitionController.TerrainAcquisitionService',
            side_effect=RuntimeError("no settings"),
        ):
            assert controller.ensure(input_folder=str(tmp_path)) is False


class TestTriggerParity:
    """Every trigger reaches the service the same way."""

    @pytest.mark.parametrize("trigger", [
        TRIGGER_ANALYSIS, TRIGGER_VIEWER_OPEN, TRIGGER_EXPORT])
    def test_the_trigger_is_passed_through_verbatim(self, controller, qtbot, trigger):
        service = _service()
        with _patched(service):
            controller.ensure(bounds=(0, 0, 1, 1), trigger=trigger)
        qtbot.waitUntil(lambda: controller._worker is None, timeout=3000)
        assert service.run.call_args.kwargs['trigger'] == trigger

    def test_images_and_bounds_both_reach_the_service(self, controller, qtbot):
        service = _service()
        images = [{'path': 'a.jpg'}]
        with _patched(service):
            controller.ensure(images=images, trigger=TRIGGER_VIEWER_OPEN)
        qtbot.waitUntil(lambda: controller._worker is None, timeout=3000)
        assert service.run.call_args.kwargs['images'] == images


class TestImageDiscovery:
    def test_only_image_files_are_collected(self, tmp_path):
        for name in ("a.jpg", "b.JPG", "c.tif", "d.png", "notes.txt", "e.raw"):
            (tmp_path / name).write_bytes(b"x")
        found = TerrainAcquisitionController._images_in(str(tmp_path))
        names = sorted(rec['path'].rsplit('\\', 1)[-1].rsplit('/', 1)[-1]
                       for rec in found)
        assert names == ["a.jpg", "b.JPG", "c.tif", "d.png"]

    def test_case_variants_are_not_double_counted(self, tmp_path):
        """Windows matches globs case-insensitively; the set must dedupe."""
        (tmp_path / "a.jpg").write_bytes(b"x")
        assert len(TerrainAcquisitionController._images_in(str(tmp_path))) == 1

    def test_a_missing_folder_yields_nothing(self):
        assert TerrainAcquisitionController._images_in("Z:/nope") == []


class TestReporting:
    @staticmethod
    def _run(controller, service, qtbot):
        messages = []
        controller.message.connect(messages.append)
        with _patched(service):
            assert controller.ensure(bounds=(0, 0, 1, 1)) is True
        qtbot.waitUntil(lambda: controller._worker is None, timeout=3000)
        return messages

    def test_a_successful_download_names_the_source(self, controller, qtbot):
        messages = self._run(controller, _service(), qtbot)
        assert any("3 AWS Terrain Tiles" in m for m in messages)

    def test_an_actionable_skip_is_reported(self, controller, qtbot):
        """Over the size limit is something the operator can act on."""
        messages = self._run(controller, _service(outcome=AcquisitionOutcome(
            skipped_reason="estimated 900 MB exceeds the 250 MB limit")), qtbot)
        assert any("skipped" in m and "900 MB" in m for m in messages)

    def test_offline_is_reported(self, controller, qtbot):
        messages = self._run(controller, _service(
            outcome=AcquisitionOutcome(skipped_reason=SKIP_OFFLINE)), qtbot)
        assert any("skipped" in m for m in messages)

    def test_the_ordinary_quiet_case_says_nothing(self, controller, qtbot):
        """Already covered fires on every viewer open and every export."""
        messages = self._run(controller, _service(
            outcome=AcquisitionOutcome(skipped_reason=SKIP_COVERED)), qtbot)
        assert messages == []

    def test_a_crash_inside_the_worker_is_reported_not_raised(self, controller, qtbot):
        messages = self._run(controller, _service(boom=RuntimeError("socket died")),
                             qtbot)
        assert any("failed" in m and "socket died" in m for m in messages)

    def test_a_cancelled_download_says_nothing(self, controller, qtbot):
        """Cancelling is the operator's own action; it needs no report."""
        messages = self._run(controller, _service(
            outcome=AcquisitionOutcome(cancelled=True)), qtbot)
        assert messages == []


class TestCancellation:
    def test_cancel_is_safe_when_nothing_is_running(self, controller):
        controller.cancel()          # must not raise
        controller.wait()

    def test_the_run_observes_cancellation(self, controller, qtbot):
        """Cancelling has to reach the download, not just orphan it."""
        seen = {}

        def run(images=None, bounds=None, trigger=None, cancel_check=None):
            seen['cancel_check'] = cancel_check
            return AcquisitionOutcome(cancelled=True)

        service = _service()
        service.run.side_effect = run
        with _patched(service):
            controller.ensure(bounds=(0, 0, 1, 1))
        controller.cancel()
        qtbot.waitUntil(lambda: controller._worker is None, timeout=3000)
        assert callable(seen.get('cancel_check'))
