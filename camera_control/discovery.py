from collections.abc import Callable
import os

import cv2

from .models import CameraInfo, DiscoveryReport
from .windows_capabilities import WindowsCameraCapabilityProvider

CaptureFactory = Callable[[int], object]


class CameraDiscovery:
    """Bounded OpenCV fallback discovery.

    The service intentionally reports only indexes that opened successfully. It
    can later be replaced by a Windows-specific enumeration provider without
    changing the UI or preview controller contracts.
    """

    def __init__(
        self,
        max_index: int = 5,
        capture_factory: CaptureFactory | None = None,
        capability_provider: WindowsCameraCapabilityProvider | None = None,
    ) -> None:
        if max_index < 1:
            raise ValueError("max_index must be at least 1")
        self._max_index = max_index
        self._capture_factory = capture_factory or cv2.VideoCapture
        self._capability_provider = capability_provider or (
            WindowsCameraCapabilityProvider() if os.name == "nt" else None
        )

    def discover(self) -> DiscoveryReport:
        cameras: list[CameraInfo] = []
        errors: list[str] = []

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

        windows_capabilities = ()
        if self._capability_provider is not None:
            windows_capabilities, capability_errors = self._capability_provider.discover()
            errors.extend(capability_errors)

        return DiscoveryReport(
            cameras=tuple(cameras),
            errors=tuple(errors),
            windows_capabilities=windows_capabilities,
        )