from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class CameraInfo:
    """A camera identified by the backend-specific index used to open it."""

    index: int
    name: str | None = None
    windows_device_id: str | None = None

    @property
    def display_name(self) -> str:
        if self.name:
            return self.name
        return f"Camera index {self.index}"


@dataclass(frozen=True)
class ResolutionInfo:
    width: int
    height: int

    @property
    def display_name(self) -> str:
        return f"{self.width} x {self.height}"


class IdentityConfidence(Enum):
    EXACT = "exact"
    HEURISTIC = "heuristic"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class WindowsCameraDevice:
    device_id: str
    name: str
    is_enabled: bool | None = None


@dataclass(frozen=True)
class AdvertisedMediaType:
    width: int | None
    height: int | None
    frame_rate: float | None
    subtype: str | None
    stream_kind: str
    advertised: bool = True
    verified: bool = False


@dataclass(frozen=True)
class CameraCapabilities:
    device: WindowsCameraDevice
    profile_supported: bool | None
    preview_media_types: tuple[AdvertisedMediaType, ...] = ()
    record_media_types: tuple[AdvertisedMediaType, ...] = ()
    identity_confidence: IdentityConfidence = IdentityConfidence.UNKNOWN


@dataclass(frozen=True)
class DiscoveryReport:
    cameras: tuple[CameraInfo, ...]
    errors: tuple[str, ...] = ()
    windows_capabilities: tuple[CameraCapabilities, ...] = ()