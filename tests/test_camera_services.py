import time
import tempfile
import unittest
from threading import Event
from pathlib import Path

import numpy as np
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QPushButton

from camera_control.discovery import CameraDiscovery
from camera_control.app import MainWindow
from camera_control.models import CameraInfo, DiscoveryReport, IdentityConfidence
from camera_control.preview import PreviewController
from camera_control.windows_capabilities import WindowsCameraCapabilityProvider


class FakeCapture:
    instances: list["FakeCapture"] = []

    def __init__(self, index: int, opened: bool = True, frames: int = 0) -> None:
        self.index = index
        self.opened = opened
        self.frames = frames
        self.release_count = 0
        self.__class__.instances.append(self)

    def isOpened(self) -> bool:
        return self.opened

    def read(self) -> tuple[bool, object]:
        if self.frames:
            self.frames -= 1
            return True, np.zeros((2, 3, 3), dtype=np.uint8)
        return False, None

    def get(self, property_id: int) -> float:
        return 30.0

    def release(self) -> None:
        self.release_count += 1


class SlowStoppingCapture(FakeCapture):
    started = Event()
    finished = Event()

    def read(self) -> tuple[bool, object]:
        self.__class__.started.set()
        time.sleep(2.2)
        self.__class__.finished.set()
        return False, None


class RaisingReleaseCapture(FakeCapture):
    def release(self) -> None:
        self.release_count += 1
        raise RuntimeError("release failed")


class SerializedCapture(FakeCapture):
    active_read = Event()
    released_during_read = False

    def read(self) -> tuple[bool, object]:
        self.__class__.active_read.set()
        time.sleep(0.05)
        self.__class__.active_read.clear()
        return True, np.zeros((2, 3, 3), dtype=np.uint8)

    def release(self) -> None:
        if self.__class__.active_read.is_set():
            self.__class__.released_during_read = True
        super().release()


class ResolutionCapture(FakeCapture):
    def __init__(self, index: int, supported: set[tuple[int, int]]) -> None:
        super().__init__(index, opened=True, frames=1000000)
        self.supported = supported
        self.width = 640
        self.height = 480
        self.pending_width = self.width
        self.pending_height = self.height

    def set(self, property_id: int, value: float) -> bool:
        if property_id == 3:
            self.pending_width = int(value)
        elif property_id == 4:
            self.pending_height = int(value)
        if (self.pending_width, self.pending_height) in self.supported:
            self.width = self.pending_width
            self.height = self.pending_height
            return True
        return False

    def read(self) -> tuple[bool, object]:
        return True, np.zeros((self.height, self.width, 3), dtype=np.uint8)


class FpsCapture(ResolutionCapture):
    def __init__(self, index: int) -> None:
        super().__init__(index, {(640, 480)})
        self.fps = 30.0

    def set(self, property_id: int, value: float) -> bool:
        if property_id == 5:
            self.fps = float(value)
            return True
        return super().set(property_id, value)

    def get(self, property_id: int) -> float:
        return self.fps if property_id == 5 else super().get(property_id)


class FakeWriter:
    def __init__(self, opened: bool = True, fail_write: bool = False, fail_release: bool = False) -> None:
        self.opened = opened
        self.fail_write = fail_write
        self.fail_release = fail_release
        self.frames: list[object] = []
        self.release_count = 0

    def isOpened(self) -> bool:
        return self.opened

    def write(self, frame: object) -> None:
        if self.fail_write:
            raise RuntimeError("write failed")
        self.frames.append(frame)

    def release(self) -> None:
        self.release_count += 1
        if self.fail_release:
            raise RuntimeError("writer release failed")


class CameraServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt_app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        FakeCapture.instances.clear()

    def test_discovery_is_bounded_and_releases_every_probe(self) -> None:
        def factory(index: int) -> FakeCapture:
            return FakeCapture(index, opened=index in {0, 2})

        report = CameraDiscovery(max_index=4, capture_factory=factory).discover()

        self.assertEqual([camera.index for camera in report.cameras], [0, 2])
        self.assertEqual([capture.index for capture in FakeCapture.instances], [0, 1, 2, 3])
        self.assertTrue(all(capture.release_count == 1 for capture in FakeCapture.instances))

    def test_unavailable_preview_reports_stop_and_releases_capture(self) -> None:
        stopped = Event()

        def factory(index: int) -> FakeCapture:
            return FakeCapture(index, opened=False)

        controller = PreviewController(capture_factory=factory)
        controller.stopped.connect(stopped.set)
        controller.start(3)

        deadline = time.monotonic() + 2
        while not stopped.is_set() and time.monotonic() < deadline:
            self.qt_app.processEvents()
            time.sleep(0.01)
        self.assertTrue(stopped.is_set())
        controller.stop()
        self.assertFalse(controller.is_running)
        self.assertIsNone(controller.selected_index)
        self.assertEqual(FakeCapture.instances[0].release_count, 1)

    def test_stop_releases_running_preview(self) -> None:
        def factory(index: int) -> FakeCapture:
            return FakeCapture(index, opened=True, frames=1000000)

        controller = PreviewController(capture_factory=factory)
        controller.start(1)
        deadline = time.monotonic() + 2
        while not FakeCapture.instances and time.monotonic() < deadline:
            time.sleep(0.01)

        controller.stop()

        self.assertFalse(controller.is_running)
        self.assertIsNone(controller.selected_index)
        self.assertGreaterEqual(FakeCapture.instances[0].release_count, 1)

    def test_stop_waits_for_worker_to_finish(self) -> None:
        SlowStoppingCapture.started.clear()
        SlowStoppingCapture.finished.clear()

        def factory(index: int) -> SlowStoppingCapture:
            return SlowStoppingCapture(index, opened=True)

        controller = PreviewController(capture_factory=factory)
        controller.start(1)
        deadline = time.monotonic() + 2
        while not FakeCapture.instances and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(SlowStoppingCapture.started.wait(timeout=2))

        controller.stop()

        self.assertTrue(SlowStoppingCapture.finished.is_set())
        self.assertFalse(controller.is_running)
        self.assertIsNone(controller.selected_index)

    def test_stop_does_not_release_capture_during_read(self) -> None:
        SerializedCapture.active_read.clear()
        SerializedCapture.released_during_read = False

        controller = PreviewController(
            capture_factory=lambda index: SerializedCapture(index, opened=True),
        )
        controller.start(1)
        self.assertTrue(SerializedCapture.active_read.wait(timeout=2))

        controller.stop()

        self.assertFalse(SerializedCapture.released_during_read)
        self.assertFalse(controller.is_running)

    def test_resolution_probe_verifies_candidates_and_restores_initial_mode(self) -> None:
        resolutions: list[tuple[int, int]] = []
        ready = Event()

        controller = PreviewController(
            capture_factory=lambda index: ResolutionCapture(index, {(640, 480), (1280, 720)}),
            resolution_candidates=((320, 240), (640, 480), (1280, 720)),
        )
        controller.resolutions_ready.connect(
            lambda values: (resolutions.extend((value.width, value.height) for value in values), ready.set())
        )
        controller.start(0)
        deadline = time.monotonic() + 2
        while not ready.is_set() and time.monotonic() < deadline:
            self.qt_app.processEvents()
            time.sleep(0.01)

        self.assertTrue(ready.is_set())
        self.assertEqual(resolutions, [(640, 480), (1280, 720)])
        self.assertEqual((controller.current_resolution.width, controller.current_resolution.height), (640, 480))
        controller.stop()

    def test_resolution_change_rejects_unsupported_mode_and_restores_previous(self) -> None:
        controller = PreviewController(
            capture_factory=lambda index: ResolutionCapture(index, {(640, 480), (1280, 720)}),
            resolution_candidates=((640, 480),),
        )
        controller.start(0)
        deadline = time.monotonic() + 2
        while controller.current_resolution is None and time.monotonic() < deadline:
            time.sleep(0.01)

        self.assertTrue(controller.set_resolution(1280, 720))
        self.assertEqual((controller.current_resolution.width, controller.current_resolution.height), (1280, 720))
        self.assertFalse(controller.set_resolution(800, 600))
        self.assertEqual((controller.current_resolution.width, controller.current_resolution.height), (1280, 720))
        controller.stop()

    def test_fps_request_reads_back_camera_value(self) -> None:
        controller = PreviewController(
            capture_factory=lambda index: FpsCapture(index),
            resolution_candidates=((640, 480),),
        )
        controller.start(0)
        deadline = time.monotonic() + 2
        while not controller.is_running and time.monotonic() < deadline:
            time.sleep(0.01)
        while controller.current_resolution is None and time.monotonic() < deadline:
            time.sleep(0.01)

        self.assertTrue(controller.set_fps(24))
        self.assertEqual(controller.requested_fps, 24)
        self.assertEqual(controller.reported_fps, 24)
        controller.stop()

    def test_software_zoom_is_bounded_and_resettable(self) -> None:
        controller = PreviewController()
        self.assertFalse(controller.zoom_in() is False)
        self.assertEqual(controller.zoom, 1.25)
        controller.set_zoom(99)
        self.assertEqual(controller.zoom, 4.0)
        controller.set_zoom(0)
        self.assertEqual(controller.zoom, 1.0)
        controller.zoom_out()
        self.assertEqual(controller.zoom, 1.0)

    def test_discovery_leaves_camera_unselected_until_user_action(self) -> None:
        window = MainWindow.__new__(MainWindow)
        window._camera_combo = QComboBox()
        window._refresh_button = QPushButton()
        window._stop_button = QPushButton()
        window._stop_button.setEnabled(False)
        window._status_label = QLabel()

        MainWindow._discovery_finished(
            window,
            DiscoveryReport(cameras=(CameraInfo(index=0),)),
        )

        self.assertEqual(window._camera_combo.currentIndex(), -1)
        self.assertFalse(window._stop_button.isEnabled())

    def test_resolution_list_selects_initial_verified_mode(self) -> None:
        window = MainWindow.__new__(MainWindow)
        window._resolution_combo = QComboBox()
        window._preview = type(
            "PreviewStub",
            (),
            {
                "current_resolution": type("ResolutionStub", (), {"width": 640, "height": 480})(),
                "is_running": True,
                "is_recording": False,
            },
        )()

        MainWindow._resolutions_ready(
            window,
            (type("ResolutionStub", (), {"width": 640, "height": 480, "display_name": "640 x 480"})(),),
        )

        self.assertEqual(window._resolution_combo.currentText(), "640 x 480")

    def test_resolution_index_normalizes_qt_item_data(self) -> None:
        window = MainWindow.__new__(MainWindow)
        window._resolution_combo = QComboBox()
        window._resolution_combo.addItem("320 x 240", [320, 240])

        self.assertEqual(window._resolution_index(320, 240), 0)

    def test_windows_provider_extracts_devices_profiles_and_deduplicates_media_types(self) -> None:
        devices = [{"id": "device-a", "name": "Built-in webcam", "is_enabled": True}, {"id": "device-b", "name": "USB webcam"}]
        profiles = {
            "device-a": [
                {
                    "supported_preview_media_description": [
                        {"width": 640, "height": 480, "frame_rate": 30, "subtype": "Nv12"},
                        {"width": 640, "height": 480, "frame_rate": 30, "subtype": "Nv12"},
                    ],
                    "supported_record_media_description": [
                        {"width": 1280, "height": 720, "frame_rate": 30, "subtype": "Mjpg"},
                    ],
                }
            ],
            "device-b": [],
        }
        provider = WindowsCameraCapabilityProvider(
            device_enumerator=lambda: devices,
            profile_support_checker=lambda device_id: device_id == "device-a",
            profile_enumerator=lambda device_id: profiles[device_id],
        )

        capabilities, errors = provider.discover()

        self.assertFalse(errors)
        self.assertEqual([capability.device.device_id for capability in capabilities], ["device-a", "device-b"])
        self.assertEqual(len(capabilities[0].preview_media_types), 1)
        self.assertEqual(capabilities[0].record_media_types[0].width, 1280)
        self.assertEqual(capabilities[1].profile_supported, False)
        self.assertEqual(capabilities[0].identity_confidence, IdentityConfidence.UNKNOWN)

    def test_windows_provider_preserves_unknown_profile_failures(self) -> None:
        provider = WindowsCameraCapabilityProvider(
            device_enumerator=lambda: [{"id": "device-a", "name": "Camera"}],
            profile_support_checker=lambda device_id: (_ for _ in ()).throw(PermissionError("denied")),
            profile_enumerator=lambda device_id: (),
        )

        capabilities, errors = provider.discover()

        self.assertEqual(len(capabilities), 1)
        self.assertIsNone(capabilities[0].profile_supported)
        self.assertTrue(any("Could not query profiles" in error for error in errors))

    def test_windows_provider_handles_provider_exception_without_crashing(self) -> None:
        provider = WindowsCameraCapabilityProvider(
            device_enumerator=lambda: (_ for _ in ()).throw(RuntimeError("enumeration failed")),
            profile_support_checker=lambda device_id: False,
            profile_enumerator=lambda device_id: (),
        )

        capabilities, errors = provider.discover()

        self.assertEqual(capabilities, ())
        self.assertTrue(any("discovery failed" in error for error in errors))

    def test_release_failure_is_reported_without_worker_crash(self) -> None:
        stopped = Event()
        errors: list[str] = []

        def factory(index: int) -> RaisingReleaseCapture:
            return RaisingReleaseCapture(index, opened=False)

        controller = PreviewController(capture_factory=factory)
        controller.stopped.connect(stopped.set)
        controller.error.connect(errors.append)
        controller.start(4)

        deadline = time.monotonic() + 2
        while not stopped.is_set() and time.monotonic() < deadline:
            self.qt_app.processEvents()
            time.sleep(0.01)

        self.assertTrue(stopped.is_set())
        self.assertTrue(any("Could not release camera index 4" in error for error in errors))
        controller.stop()

    def test_photo_requires_preview_and_saves_latest_frame(self) -> None:
        saved: list[str] = []
        written: list[object] = []

        with tempfile.TemporaryDirectory() as directory:
            controller = PreviewController(
                capture_factory=lambda index: FakeCapture(index, opened=True, frames=1000000),
                image_writer=lambda path, frame: (written.append(frame) or True),
                output_root=Path(directory),
            )
            controller.photo_saved.connect(saved.append)
            controller.take_photo()
            self.assertFalse(saved)

            controller.start(0)
            self._wait_for_frame(controller)
            controller.take_photo()
            controller.stop()

        self.assertEqual(len(written), 1)
        self.assertEqual(len(saved), 1)
        self.assertIn("captures", saved[0])

    def test_recording_writes_frames_and_finalizes_on_stop(self) -> None:
        writers: list[FakeWriter] = []
        saved: list[str] = []

        def writer_factory(path: str, fourcc: int, fps: float, size: tuple[int, int]) -> FakeWriter:
            writer = FakeWriter()
            writers.append(writer)
            self.assertEqual(size, (3, 2))
            self.assertEqual(fps, 30.0)
            return writer

        with tempfile.TemporaryDirectory() as directory:
            controller = PreviewController(
                capture_factory=lambda index: FakeCapture(index, opened=True, frames=1000000),
                writer_factory=writer_factory,
                output_root=Path(directory),
            )
            controller.recording_saved.connect(saved.append)
            controller.start(0)
            self._wait_for_frame(controller)
            controller.start_recording()
            deadline = time.monotonic() + 2
            while not writers and time.monotonic() < deadline:
                time.sleep(0.01)
            deadline = time.monotonic() + 2
            while writers and not writers[0].frames and time.monotonic() < deadline:
                time.sleep(0.01)
            controller.stop_recording()
            controller.stop()

        self.assertEqual(len(writers), 1)
        self.assertGreater(len(writers[0].frames), 0)
        self.assertEqual(writers[0].release_count, 1)
        self.assertEqual(len(saved), 1)

    def test_recording_writer_open_failure_is_reported(self) -> None:
        errors: list[str] = []
        writers: list[FakeWriter] = []

        def writer_factory(path: str, fourcc: int, fps: float, size: tuple[int, int]) -> FakeWriter:
            writer = FakeWriter(opened=False)
            writers.append(writer)
            return writer

        with tempfile.TemporaryDirectory() as directory:
            controller = PreviewController(
                capture_factory=lambda index: FakeCapture(index, opened=True, frames=1000000),
                writer_factory=writer_factory,
                output_root=Path(directory),
            )
            controller.error.connect(errors.append)
            controller.start(0)
            self._wait_for_frame(controller)
            controller.start_recording()
            controller.stop()

        self.assertEqual(len(writers), 1)
        self.assertEqual(writers[0].release_count, 1)
        self.assertTrue(any("video writer could not be opened" in error for error in errors))

    def test_recording_write_failure_finalizes_writer(self) -> None:
        errors: list[str] = []
        writers: list[FakeWriter] = []

        def writer_factory(path: str, fourcc: int, fps: float, size: tuple[int, int]) -> FakeWriter:
            writer = FakeWriter(fail_write=True)
            writers.append(writer)
            return writer

        with tempfile.TemporaryDirectory() as directory:
            controller = PreviewController(
                capture_factory=lambda index: FakeCapture(index, opened=True, frames=1000000),
                writer_factory=writer_factory,
                output_root=Path(directory),
            )
            controller.error.connect(errors.append)
            controller.start(0)
            self._wait_for_frame(controller)
            controller.start_recording()
            deadline = time.monotonic() + 2
            while not writers or writers[0].release_count == 0:
                self.qt_app.processEvents()
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.01)
            controller.stop()
            for _ in range(3):
                self.qt_app.processEvents()

        self.assertEqual(writers[0].release_count, 1)
        self.assertTrue(any("Could not write recording" in error for error in errors))

    def _wait_for_frame(self, controller: PreviewController) -> None:
        deadline = time.monotonic() + 2
        while controller._latest_frame is None and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIsNotNone(controller._latest_frame)


if __name__ == "__main__":
    unittest.main()