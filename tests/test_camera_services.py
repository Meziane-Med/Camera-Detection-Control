import time
import tempfile
import unittest
import asyncio
import os
from types import SimpleNamespace
from threading import Event
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QLabel,
    QPushButton,
    QSlider,
    QTreeWidget,
)

from camera_control.discovery import CameraDiscovery
from camera_control.app import MainWindow, PERIPHERAL_CATEGORIES
from camera_control.capture_backend import create_capture
from camera_control.models import (
    CameraCapabilities,
    CameraInfo,
    DiscoveryReport,
    IdentityConfidence,
    WindowsCameraDevice,
)
from camera_control.peripherals import PeripheralInfo, WindowsPeripheralDiscovery
from camera_control.preview import PreviewController
from camera_control.windows_capabilities import WindowsCameraCapabilityProvider
from camera_control.windows_capture import WindowsMediaCaptureAdapter, _software_bitmap_to_bgr


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


class WhiteBalanceCapture(FakeCapture):
    def __init__(self, index: int, accept_settings: bool = True) -> None:
        super().__init__(index, opened=True, frames=1000000)
        self.accept_settings = accept_settings
        self.settings: list[tuple[int, float]] = []

    def set(self, property_id: int, value: float) -> bool:
        self.settings.append((property_id, value))
        return self.accept_settings


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

    @patch("camera_control.capture_backend.cv2.VideoCapture")
    def test_windows_capture_prefers_msmf_and_falls_back_if_unavailable(
        self,
        video_capture: Mock,
    ) -> None:
        if os.name != "nt":
            self.skipTest("MSMF is a Windows-only backend")
        msmf_capture = Mock()
        msmf_capture.isOpened.return_value = True
        video_capture.return_value = msmf_capture

        self.assertIs(create_capture(2), msmf_capture)
        video_capture.assert_called_once_with(2, cv2.CAP_MSMF)

        video_capture.reset_mock()
        msmf_capture.isOpened.return_value = False
        self.assertIs(create_capture(2), video_capture.return_value)
        self.assertEqual(
            video_capture.call_args_list,
            [unittest.mock.call(2, cv2.CAP_MSMF), unittest.mock.call(2)],
        )
        msmf_capture.release.assert_called_once()

    def test_windows_native_discovery_preserves_device_ids_without_index_probing(self) -> None:
        class CapabilityProvider:
            def discover(self) -> tuple[tuple[CameraCapabilities, ...], tuple[str, ...]]:
                return (
                    (
                        CameraCapabilities(
                            device=WindowsCameraDevice("windows-camera-1", "USB Camera"),
                            profile_supported=False,
                        ),
                    ),
                    (),
                )

        report = CameraDiscovery(
            max_index=3,
            capture_factory=lambda index: FakeCapture(index),
            capability_provider=CapabilityProvider(),
            use_windows_native_capture=True,
        ).discover()

        self.assertEqual(
            report.cameras,
            (CameraInfo(0, "USB Camera", "windows-camera-1"),),
        )
        self.assertEqual(FakeCapture.instances, [])

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

    def test_white_balance_auto_and_temperature_presets(self) -> None:
        controller = PreviewController(
            capture_factory=lambda index: WhiteBalanceCapture(index),
            resolution_candidates=(),
        )
        controller.start(0)
        deadline = time.monotonic() + 2
        while controller.current_resolution is None and time.monotonic() < deadline:
            time.sleep(0.01)

        self.assertTrue(controller.set_white_balance(None))
        self.assertTrue(controller.set_white_balance(5500))
        self.assertEqual(
            [
                setting
                for setting in WhiteBalanceCapture.instances[0].settings
                if setting[0] in (cv2.CAP_PROP_AUTO_WB, cv2.CAP_PROP_WB_TEMPERATURE)
            ],
            [
                (cv2.CAP_PROP_AUTO_WB, 1),
                (cv2.CAP_PROP_AUTO_WB, 0),
                (cv2.CAP_PROP_WB_TEMPERATURE, 5500),
            ],
        )
        controller.stop()

    def test_white_balance_reports_unsupported_camera_setting(self) -> None:
        errors: list[str] = []
        controller = PreviewController(
            capture_factory=lambda index: WhiteBalanceCapture(index, accept_settings=False),
            resolution_candidates=(),
        )
        controller.error.connect(errors.append)
        controller.start(0)
        deadline = time.monotonic() + 2
        while controller.current_resolution is None and time.monotonic() < deadline:
            time.sleep(0.01)

        self.assertFalse(controller.set_white_balance(3200))
        self.assertTrue(any("did not accept manual white balance" in error for error in errors))
        controller.stop()

    def test_focus_manual_control(self) -> None:
        controller = PreviewController(
            capture_factory=lambda index: WhiteBalanceCapture(index),
            resolution_candidates=(),
        )
        controller.start(0)
        deadline = time.monotonic() + 2
        while controller.current_resolution is None and time.monotonic() < deadline:
            time.sleep(0.01)

        self.assertTrue(controller.set_auto_focus(False))
        self.assertTrue(controller.set_focus(120))
        requested_settings = [
            setting
            for setting in WhiteBalanceCapture.instances[0].settings
            if setting[0] in (cv2.CAP_PROP_AUTOFOCUS, cv2.CAP_PROP_FOCUS)
        ]
        self.assertEqual(
            requested_settings,
            [
                (cv2.CAP_PROP_AUTOFOCUS, 0.0),
                (cv2.CAP_PROP_AUTOFOCUS, 0.0),
                (cv2.CAP_PROP_FOCUS, 120.0),
            ],
        )
        controller.stop()

    def test_camera_start_leaves_exposure_at_driver_default(self) -> None:
        controller = PreviewController(
            capture_factory=lambda index: WhiteBalanceCapture(index),
            resolution_candidates=(),
        )
        controller.start(0)
        deadline = time.monotonic() + 2
        while controller.current_resolution is None and time.monotonic() < deadline:
            time.sleep(0.01)

        exposure_properties = {
            cv2.CAP_PROP_AUTO_EXPOSURE,
            cv2.CAP_PROP_EXPOSURE,
        }
        self.assertFalse(
            any(
                property_id in exposure_properties
                for property_id, _ in WhiteBalanceCapture.instances[0].settings
            )
        )
        controller.stop()

    def test_focus_reports_unsupported_control(self) -> None:
        errors: list[str] = []
        controller = PreviewController(
            capture_factory=lambda index: WhiteBalanceCapture(index, accept_settings=False),
            resolution_candidates=(),
        )
        controller.error.connect(errors.append)
        controller.start(0)
        deadline = time.monotonic() + 2
        while controller.current_resolution is None and time.monotonic() < deadline:
            time.sleep(0.01)

        self.assertFalse(controller.set_focus(120))
        self.assertTrue(any("did not accept focus value 120" in error for error in errors))
        controller.stop()

    def test_fps_uses_camera_frame_timestamps_when_available(self) -> None:
        controller = PreviewController()

        self.assertIsNone(controller._measure_fps_locked(10.0))
        self.assertAlmostEqual(controller._measure_fps_locked(10.04), 25.0)


    def test_windows_software_bitmap_converts_to_opencv_frame(self) -> None:
        from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap

        bitmap = SoftwareBitmap(
            BitmapPixelFormat.BGRA8,
            2,
            2,
            BitmapAlphaMode.IGNORE,
        )
        try:
            frame = asyncio.run(_software_bitmap_to_bgr(bitmap))
        finally:
            bitmap.close()

        self.assertEqual(frame.shape, (2, 2, 3))
        self.assertEqual(frame.dtype, np.uint8)

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
        window._white_balance_combo = QComboBox()
        window._auto_focus_checkbox = QCheckBox()
        window._focus_slider = QSlider()
        window._focus_value_label = QLabel()
        window._camera_controls_ready = False
        window._preview = type(
            "PreviewStub",
            (),
            {
                "current_resolution": type("ResolutionStub", (), {"width": 640, "height": 480})(),
                "is_running": False,
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

    def test_peripheral_discovery_lists_device_details(self) -> None:
        async def enumerate_devices() -> list[dict[str, object]]:
            return [
                {
                    "id": "device-a",
                    "name": "USB Keyboard",
                    "kind": "DeviceInterface",
                    "is_enabled": True,
                    "is_internal": False,
                },
                {
                    "id": "device-b",
                    "name": "",
                    "kind": "DeviceContainer",
                    "is_enabled": False,
                    "is_system": True,
                },
            ]

        devices, errors = WindowsPeripheralDiscovery(enumerate_devices).discover()

        self.assertEqual(
            devices,
            (
                PeripheralInfo("USB Keyboard", "device-a", "Device Interface", "Input", True, False),
                PeripheralInfo("device-b", "device-b", "Device Container", "Other", False, True),
            ),
        )
        self.assertEqual(errors, ())

    def test_peripheral_discovery_uses_unknown_for_unreported_system_status(self) -> None:
        async def enumerate_devices() -> list[dict[str, object]]:
            return [{"id": "device-a", "name": "USB Keyboard", "kind": 1}]

        devices, errors = WindowsPeripheralDiscovery(enumerate_devices).discover()
        self.assertEqual(
            devices,
            (PeripheralInfo("USB Keyboard", "device-a", "Device Interface", "Input", None, None),),
        )
        self.assertEqual(errors, ())

    def test_peripheral_discovery_classifies_functional_categories(self) -> None:
        async def enumerate_devices() -> list[dict[str, object]]:
            return [
                {
                    "id": r"\\?\HDAUDIO#FUNC_01#{6994ad04-93ef-11d0-a3cc-00a0c9223196}",
                    "name": "Audio endpoint",
                    "kind": 1,
                },
                {
                    "id": r"\\?\USB#VID_1234#{e5323777-f976-4f5b-9b55-b94699c46e44}",
                    "name": "Integrated Camera",
                    "kind": 1,
                },
                {
                    "id": r"\\?\HID#VID_1234#{4d1e55b2-f16f-11cf-88cb-001111000030}",
                    "name": "USB Keyboard",
                    "kind": 1,
                },
                {"id": r"\\?\USB#VID_1234", "name": "USB Device", "kind": 1},
                {
                    "id": r"\\?\BTH#RADIO#1234",
                    "name": "Bluetooth Adapter",
                    "kind": 1,
                },
                {"id": r"\\?\ACPI#ROOT", "name": "System board", "kind": 1},
            ]

        devices, errors = WindowsPeripheralDiscovery(enumerate_devices).discover()

        self.assertEqual(
            [device.category for device in devices],
            ["Audio", "Camera", "Input", "USB", "Bluetooth", "System"],
        )
        self.assertTrue(devices[-1].is_internal)
        self.assertEqual(errors, ())

    def test_peripheral_discovery_reads_container_ids_and_ignores_windows_placeholder(self) -> None:
        async def enumerate_devices() -> list[dict[str, object]]:
            return [
                {
                    "id": "device-a",
                    "name": "Headphones (EW72)",
                    "kind": 1,
                    "container_id": "container-a",
                },
                {
                    "id": "device-b",
                    "name": "EW72",
                    "kind": 1,
                    "container_id": "container-a",
                },
                {
                    "id": "device-c",
                    "name": "Internal audio interface",
                    "kind": 1,
                    "container_id": "00000000-0000-0000-ffff-ffffffffffff",
                    "device_instance_id": "instance-c",
                },
            ]

        devices, errors = WindowsPeripheralDiscovery(enumerate_devices).discover()

        self.assertEqual([device.container_id for device in devices], ["container-a", "container-a", None])
        self.assertEqual([device.device_instance_id for device in devices], [None, None, "instance-c"])
        self.assertEqual(errors, ())

    def test_peripheral_discovery_reports_missing_ids_and_provider_errors(self) -> None:
        async def enumerate_missing_ids() -> list[dict[str, object]]:
            return [{"name": "Unknown device"}]

        devices, errors = WindowsPeripheralDiscovery(enumerate_missing_ids).discover()
        self.assertEqual(devices, ())
        self.assertTrue(any("without an ID" in error for error in errors))

        async def fail_discovery() -> list[dict[str, object]]:
            raise RuntimeError("enumeration failed")

        devices, errors = WindowsPeripheralDiscovery(fail_discovery).discover()
        self.assertEqual(devices, ())
        self.assertTrue(any("enumeration failed" in error for error in errors))

    def test_peripherals_page_groups_devices_and_filters_by_category(self) -> None:
        window = MainWindow.__new__(MainWindow)
        window._peripherals_table = QTreeWidget()
        window._peripherals_table.setColumnCount(4)
        window._peripheral_type_combo = QComboBox()
        window._peripheral_type_combo.addItems(PERIPHERAL_CATEGORIES)
        window._peripheral_type_combo.currentIndexChanged.connect(window._render_peripherals)
        window._peripherals_status = QLabel()
        window._refresh_peripherals_button = QPushButton()

        devices = (
            PeripheralInfo("Keyboard", "device-1", "Device Interface", "Input", True, False),
            PeripheralInfo("System board", "device-2", "Device Interface", "Other", True, True),
            PeripheralInfo("Audio endpoint", "device-3", "Association Endpoint", "Audio", True, None),
        )
        MainWindow._peripherals_discovered(window, (devices, ()))

        self.assertEqual(window._peripherals_table.topLevelItemCount(), 3)
        self.assertEqual(window._peripherals_table.topLevelItem(1).text(0), "Input (1)")
        self.assertIn("showing 3", window._peripherals_status.text())

        window._peripheral_type_combo.setCurrentText("Audio")

        self.assertEqual(window._peripherals_table.topLevelItemCount(), 1)
        self.assertEqual(window._peripherals_table.topLevelItem(0).text(0), "Audio (1)")
        self.assertEqual(window._peripherals_table.topLevelItem(0).child(0).text(0), "Audio endpoint")
        self.assertIn("showing 1", window._peripherals_status.text())

        window._peripheral_type_combo.setCurrentText("All types")

        self.assertEqual(window._peripherals_table.topLevelItemCount(), 3)

    def test_peripherals_page_groups_related_entries_under_friendly_device_name(self) -> None:
        window = MainWindow.__new__(MainWindow)
        window._peripherals_table = QTreeWidget()
        window._peripherals_table.setColumnCount(4)
        window._peripheral_type_combo = QComboBox()
        window._peripheral_type_combo.addItems(PERIPHERAL_CATEGORIES)
        window._peripherals_status = QLabel()
        window._refresh_peripherals_button = QPushButton()
        devices = (
            PeripheralInfo("AMD HD Audio DP out #1", "device-1", "Device Interface", "Audio", True, False, "container-a"),
            PeripheralInfo("AMD HD Audio HDMI out #1", "device-2", "Association Endpoint", "Audio", True, False, "container-a"),
        )

        MainWindow._peripherals_discovered(window, (devices, ()))

        category = window._peripherals_table.topLevelItem(0)
        self.assertEqual(category.text(0), "Audio (2)")
        self.assertEqual(category.childCount(), 1)
        device_group = category.child(0)
        self.assertEqual(device_group.text(0), "AMD HD Audio (2 interfaces)")
        self.assertEqual(device_group.childCount(), 2)
        self.assertEqual(device_group.child(0).text(3), "device-1")
        self.assertEqual(device_group.child(1).text(3), "device-2")
        self.assertIn("showing 2", window._peripherals_status.text())

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