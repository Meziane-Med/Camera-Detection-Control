from collections.abc import Callable
import os

import cv2

from .capture_backend import create_capture
from .models import CameraInfo, DiscoveryReport
from .windows_capabilities import WindowsCameraCapabilityProvider

CaptureFactory = Callable[[int], object]


class CameraDiscovery:
    """Discover Windows device IDs, with a bounded OpenCV fallback."""

    def __init__(
        self,
        max_index: int = 5,
        capture_factory: CaptureFactory | None = None,
        capability_provider: WindowsCameraCapabilityProvider | None = None,
        use_windows_native_capture: bool = False,
    ) -> None:
        if max_index < 1:
            raise ValueError("max_index must be at least 1")
        self._max_index = max_index
        self._capture_factory = capture_factory or create_capture
        self._use_windows_native_capture = use_windows_native_capture
        self._capability_provider = capability_provider or (
            WindowsCameraCapabilityProvider() if os.name == "nt" else None
        )

    def discover(self) -> DiscoveryReport:
        cameras: list[CameraInfo] = []
        errors: list[str] = []

        windows_capabilities = ()
        if self._capability_provider is not None:
            windows_capabilities, capability_errors = self._capability_provider.discover()
            errors.extend(capability_errors)

        if self._use_windows_native_capture and windows_capabilities:
            cameras = [
                CameraInfo(
                    index=index,
                    name=capability.device.name,
                    windows_device_id=capability.device.device_id,
                )
                for index, capability in enumerate(windows_capabilities)
            ]
            return DiscoveryReport(
                cameras=tuple(cameras),
                errors=tuple(errors),
                windows_capabilities=windows_capabilities,
            )

        for index in range(self._max_index):
            capture = None
            try:
                capture = self._capture_factory(index)
                if capture.isOpened():
                    cameras.append(CameraInfo(index=index))
            except Exception as exc:
                errors.append(f"Camera index {index}: {exc}")
            finally:
                if capture is not None:
                    try:
                        capture.release()
                    except Exception as exc:
                        errors.append(f"Camera index {index} release failed: {exc}")

        camera_names = [
            capability.device.name.strip()
            for capability in windows_capabilities
            if capability.device.name and capability.device.name.strip()
        ]
        if camera_names:
            cameras = tuple(
                CameraInfo(index=camera.index, name=camera_names[i] if i < len(camera_names) else None)
                for i, camera in enumerate(cameras)
            )

        return DiscoveryReport(
            cameras=tuple(cameras),
            errors=tuple(errors),
            windows_capabilities=windows_capabilities,
        )