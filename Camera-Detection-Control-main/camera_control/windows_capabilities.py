"""Optional Windows camera capability discovery through PyWinRT.

This provider reports Windows-advertised profiles only. It deliberately does
not map a Windows device ID to an OpenCV numeric index, because OpenCV does not
expose that identity through ``VideoCapture(index)``.
"""

import asyncio
import inspect
import re
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from .models import AdvertisedMediaType, CameraCapabilities, IdentityConfidence, WindowsCameraDevice

DeviceEnumerator = Callable[[], Awaitable[Iterable[Any]]]
ProfileSupportChecker = Callable[[str], bool | Awaitable[bool]]
ProfileEnumerator = Callable[[str], Iterable[Any] | Awaitable[Iterable[Any]]]


class WindowsCapabilityError(RuntimeError):
    """A capability query failed without invalidating the whole discovery."""


class WindowsCameraCapabilityProvider:
    """Discover Windows camera IDs and advertised WinRT video profiles."""

    def __init__(
        self,
        device_enumerator: DeviceEnumerator | None = None,
        profile_support_checker: ProfileSupportChecker | None = None,
        profile_enumerator: ProfileEnumerator | None = None,
    ) -> None:
        self._device_enumerator = device_enumerator
        self._profile_support_checker = profile_support_checker
        self._profile_enumerator = profile_enumerator

    def discover(self) -> tuple[tuple[CameraCapabilities, ...], tuple[str, ...]]:
        try:
            return asyncio.run(self._discover_async())
        except Exception as exc:
            return (), (f"Windows camera capability discovery failed: {exc}",)

    async def _discover_async(self) -> tuple[tuple[CameraCapabilities, ...], tuple[str, ...]]:
        enumerate_devices, check_profiles, enumerate_profiles = self._load_apis()
        devices = await _maybe_await(enumerate_devices())
        capabilities: list[CameraCapabilities] = []
        errors: list[str] = []

        for raw_device in devices:
            device_id = _read_value(raw_device, "id")
            name = _read_value(raw_device, "name") or device_id
            enabled = _read_value(raw_device, "is_enabled", None)
            if not device_id:
                errors.append("Windows camera enumeration returned a device without an ID.")
                continue
            device = WindowsCameraDevice(device_id=str(device_id), name=str(name), is_enabled=enabled)
            try:
                profile_supported = await _maybe_await(check_profiles(device.device_id))
            except Exception as exc:
                capabilities.append(CameraCapabilities(device=device, profile_supported=None))
                errors.append(f"Could not query profiles for {device.name}: {exc}")
                continue

            if not profile_supported:
                capabilities.append(CameraCapabilities(device=device, profile_supported=False))
                continue

            try:
                profiles = await _maybe_await(enumerate_profiles(device.device_id))
                preview, record = _extract_media_types(profiles)
                capabilities.append(
                    CameraCapabilities(
                        device=device,
                        profile_supported=True,
                        preview_media_types=tuple(preview),
                        record_media_types=tuple(record),
                    )
                )
            except Exception as exc:
                capabilities.append(CameraCapabilities(device=device, profile_supported=True))
                errors.append(f"Could not enumerate profiles for {device.name}: {exc}")

        return tuple(capabilities), tuple(errors)

    def _load_apis(self) -> tuple[DeviceEnumerator, ProfileSupportChecker, ProfileEnumerator]:
        if self._device_enumerator and self._profile_support_checker and self._profile_enumerator:
            return self._device_enumerator, self._profile_support_checker, self._profile_enumerator
        try:
            from winrt.windows.devices.enumeration import DeviceInformation
            from winrt.windows.media.capture import MediaCapture
            from winrt.windows.media.devices import MediaDevice
        except ImportError as exc:
            raise WindowsCapabilityError(
                "PyWinRT camera packages are unavailable; install the Windows capability dependencies."
            ) from exc

        async def enumerate_devices() -> Iterable[Any]:
            selector = MediaDevice.get_video_capture_selector()
            # PyWinRT 3.2.1 exposes only the no-argument overload here. Apply
            # the exact interface GUID from the documented selector locally.
            all_devices = await DeviceInformation.find_all_async()
            interface_guid = _selector_interface_guid(selector)
            return tuple(
                device for device in all_devices
                if interface_guid and interface_guid in str(device.id).lower()
            )

        return (
            enumerate_devices,
            MediaCapture.is_video_profile_supported,
            MediaCapture.find_all_video_profiles,
        )


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _read_value(value: Any, name: str, default: Any = "") -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _extract_media_types(profiles: Iterable[Any]) -> tuple[list[AdvertisedMediaType], list[AdvertisedMediaType]]:
    preview: list[AdvertisedMediaType] = []
    record: list[AdvertisedMediaType] = []
    seen_preview: set[tuple[Any, ...]] = set()
    seen_record: set[tuple[Any, ...]] = set()

    for profile in profiles:
        for property_name, stream_kind, target, seen in (
            ("supported_preview_media_description", "preview", preview, seen_preview),
            ("supported_record_media_description", "record", record, seen_record),
        ):
            descriptions = _read_value(profile, property_name, ()) or ()
            for description in descriptions:
                media_type = _media_type_from_description(description, stream_kind)
                key = (media_type.width, media_type.height, media_type.frame_rate, media_type.subtype)
                if key not in seen:
                    seen.add(key)
                    target.append(media_type)
    return preview, record


def _media_type_from_description(description: Any, stream_kind: str) -> AdvertisedMediaType:
    frame_rate = _read_value(description, "frame_rate", None)
    if frame_rate is not None:
        try:
            frame_rate = float(frame_rate)
        except (TypeError, ValueError):
            frame_rate = None
    return AdvertisedMediaType(
        width=_as_int(_read_value(description, "width", None)),
        height=_as_int(_read_value(description, "height", None)),
        frame_rate=frame_rate,
        subtype=_read_value(description, "subtype", None),
        stream_kind=stream_kind,
    )


def _as_int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _selector_interface_guid(selector: str) -> str | None:
    match = re.search(r"\{([0-9a-f-]{36})\}", selector, re.IGNORECASE)
    return None if match is None else match.group(1).lower()