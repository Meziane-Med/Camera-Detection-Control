"""Read-only Windows peripheral enumeration through PyWinRT."""

import asyncio
import inspect
import os
import re
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

PeripheralEnumerator = Callable[[], Awaitable[Iterable[Any]]]


@dataclass(frozen=True)
class PeripheralInfo:
    name: str
    device_id: str
    kind: str
    category: str
    is_enabled: bool | None
    is_internal: bool | None
    container_id: str | None = None
    device_instance_id: str | None = None


class WindowsPeripheralDiscovery:
    def __init__(self, device_enumerator: PeripheralEnumerator | None = None) -> None:
        self._device_enumerator = device_enumerator

    def discover(self) -> tuple[tuple[PeripheralInfo, ...], tuple[str, ...]]:
        if self._device_enumerator is None and os.name != "nt":
            return (), ("Peripheral discovery is only available on Windows.",)
        try:
            return asyncio.run(self._discover_async())
        except Exception as exc:
            return (), (f"Windows peripheral discovery failed: {exc}",)

    async def _discover_async(self) -> tuple[tuple[PeripheralInfo, ...], tuple[str, ...]]:
        enumerate_devices = self._device_enumerator or self._load_enumerator()
        devices = enumerate_devices()
        if inspect.isawaitable(devices):
            devices = await devices

        peripherals: list[PeripheralInfo] = []
        errors: list[str] = []
        for device in devices:
            device_id = _read_value(device, "id", "")
            name = _read_value(device, "name", "")
            if not device_id:
                errors.append("Windows peripheral enumeration returned a device without an ID.")
                continue
            kind = _read_value(device, "kind", None)
            if kind is None:
                kind_name = "Unknown"
            else:
                kind_name = _device_kind_name(kind)
            device_name = str(name).strip() or str(device_id)
            peripherals.append(
                PeripheralInfo(
                    name=device_name,
                    device_id=str(device_id),
                    kind=kind_name,
                    category=_device_category(device_name, str(device_id)),
                    is_enabled=_read_value(device, "is_enabled", None),
                    is_internal=_read_internal_status(device, str(device_id)),
                    container_id=_read_container_id(device),
                    device_instance_id=_read_device_instance_id(device),
                )
            )

        return tuple(peripherals), tuple(errors)

    @staticmethod
    def _load_enumerator() -> PeripheralEnumerator:
        try:
            from winrt.windows.devices.enumeration import DeviceInformation
        except ImportError as exc:
            raise RuntimeError(
                "PyWinRT device-enumeration packages are unavailable."
            ) from exc

        async def enumerate_devices() -> Iterable[Any]:
            return await DeviceInformation.find_all_async()

        return enumerate_devices


def _read_value(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _device_kind_name(kind: Any) -> str:
    name = getattr(kind, "name", None)
    if name:
        return str(name).replace("_", " ").title()
    if isinstance(kind, int):
        return {
            0: "Unknown",
            1: "Device Interface",
            2: "Device Container",
            3: "Device",
            4: "Device Interface Class",
            5: "Association Endpoint",
            6: "Association Endpoint Container",
            7: "Association Endpoint Service",
            8: "Device Panel",
            9: "Association Endpoint Protocol",
        }.get(kind, f"Device Kind {kind}")
    if isinstance(kind, str):
        words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", kind)
        return words.replace("_", " ").replace("-", " ").title()
    return str(kind)


def _device_category(name: str, device_id: str) -> str:
    normalized_name = name.casefold()
    normalized_id = device_id.casefold()
    interface_guid = ""
    match = re.search(r"\{([0-9a-f-]{36})\}", normalized_id)
    if match is not None:
        interface_guid = match.group(1)

    if (
        interface_guid == "e5323777-f976-4f5b-9b55-b94699c46e44"
        or any(term in normalized_name for term in ("camera", "webcam"))
    ):
        return "Camera"
    if (
        interface_guid
        in {
            "6994ad04-93ef-11d0-a3cc-00a0c9223196",
            "65e8773d-8f56-11d0-a3b9-00a0c9223196",
            "65e8773e-8f56-11d0-a3b9-00a0c9223196",
            "dda54a40-1e4c-11d1-a050-405705c10000",
        }
        or normalized_id.startswith(("\\\\?\\hdaudio#", "\\\\?\\acp#"))
        or any(term in normalized_name for term in ("audio", "microphone", "mic input", "speaker", "headphone", "headset", "sound"))
    ):
        return "Audio"
    if (
        interface_guid
        in {
            "4d1e55b2-f16f-11cf-88cb-001111000030",
            "884b96c3-56ef-11d1-bc8c-00a0c91405dd",
            "378de44c-56ef-11d1-bc8c-00a0c91405dd",
        }
        or normalized_id.startswith("\\\\?\\hid#")
        or any(term in normalized_name for term in ("keyboard", "mouse", "touchpad", "human interface"))
    ):
        return "Input"
    if normalized_id.startswith("\\\\?\\bth#") or "bluetooth" in normalized_name:
        return "Bluetooth"
    if (
        interface_guid == "cac88484-7515-4c03-82e6-71a87abac361"
        or any(term in normalized_name for term in ("network", "wi-fi", "wireless", "ethernet", "bluetooth"))
    ):
        return "Network"
    if (
        interface_guid in {"53f56307-b6bf-11d0-94f2-00a0c91efb8b", "53f5630d-b6bf-11d0-94f2-00a0c91efb8b"}
        or any(term in normalized_name for term in ("disk", "storage", "drive", "volume", "memory card"))
    ):
        return "Storage"
    if any(term in normalized_name for term in ("printer", "print queue")):
        return "Printer"
    if any(term in normalized_name for term in ("display", "monitor", "graphics", "radeon", "geforce")):
        return "Display"
    if (
        interface_guid == "a5dcbf10-6530-11d2-901f-00c04fb951ed"
        or normalized_id.startswith("\\\\?\\usb#")
    ):
        return "USB"
    if normalized_id.startswith(("\\\\?\\acpi#", "\\\\?\\root#")):
        return "System"
    return "Other"


def _read_internal_status(device: Any, device_id: str) -> bool | None:
    direct_keys = ("is_internal", "is_system", "is_system_device")
    for key in direct_keys:
        value = _read_value(device, key, None)
        if isinstance(value, bool):
            return value

    normalized_id = device_id.casefold()
    if normalized_id.startswith(("\\\\?\\acpi#", "\\\\?\\root#")):
        return True

    properties = _read_value(device, "properties", None)
    if properties is None:
        return None

    metadata_keys = (
        "System.Devices.IsInternal",
        "System.Devices.IsSystemDevice",
        "System.Devices.IsSystem",
    )
    for key in metadata_keys:
        try:
            value = properties.get(key)
        except (AttributeError, KeyError, TypeError):
            value = None
        if isinstance(value, bool):
            return value
    return None


def _read_container_id(device: Any) -> str | None:
    value = _read_value(device, "container_id", None)
    if value is None:
        properties = _read_value(device, "properties", None)
        if properties is not None:
            try:
                value = properties.get("System.Devices.ContainerId")
            except (AttributeError, KeyError, TypeError):
                value = None
    if value is None:
        return None

    if isinstance(value, str):
        container_id = value
    else:
        try:
            from winrt.windows.foundation import IPropertyValue

            container_id = str(value.as_(IPropertyValue).get_guid())
        except (ImportError, AttributeError, OSError, TypeError):
            return None

    normalized_id = container_id.casefold()
    if normalized_id in {
        "",
        "00000000-0000-0000-ffff-ffffffffffff",
        "00000000-0000-0000-0000-000000000000",
    }:
        return None
    return container_id


def _read_device_instance_id(device: Any) -> str | None:
    value = _read_value(device, "device_instance_id", None)
    if value is None:
        properties = _read_value(device, "properties", None)
        if properties is not None:
            try:
                value = properties.get("System.Devices.DeviceInstanceId")
            except (AttributeError, KeyError, TypeError):
                value = None
    if value is None:
        return None

    if isinstance(value, str):
        instance_id = value
    else:
        try:
            from winrt.windows.foundation import IPropertyValue

            instance_id = value.as_(IPropertyValue).get_string()
        except (ImportError, AttributeError, OSError, TypeError):
            return None
    return instance_id.strip() or None
