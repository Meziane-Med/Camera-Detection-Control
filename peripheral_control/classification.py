from collections.abc import Mapping
from typing import Any

from .models import DeviceCategory, PeripheralDevice


def classify_device(device: PeripheralDevice) -> tuple[DeviceCategory, ...]:
    """Classify by Windows class and descriptive metadata, not USB alone."""

    text = " ".join(
        str(value or "")
        for value in (
            device.name,
            device.device_class,
            device.properties.get("Service"),
            device.properties.get("HardwareID"),
        )
    ).lower()
    device_class = (device.device_class or "").lower()
    categories: list[DeviceCategory] = []

    if device_class in {"keyboard", "mouse", "hidclass", "image", "camera"}:
        categories.append(DeviceCategory.INPUT)
    if any(word in text for word in ("microphone", "mic ", "microphone array", "webcam", "camera")):
        if DeviceCategory.INPUT not in categories:
            categories.append(DeviceCategory.INPUT)

    if device_class in {"monitor", "printer", "audioendpoint", "sound"}:
        categories.append(DeviceCategory.OUTPUT)
    if any(word in text for word in ("speaker", "headphone", "headset", "printer", "display", "monitor")):
        if DeviceCategory.OUTPUT not in categories:
            categories.append(DeviceCategory.OUTPUT)

    storage_classes = {"diskdrive", "volume", "wpd", "portabledevices", "scsiadapter", "hdc"}
    if device_class in storage_classes or any(
        word in text
        for word in ("mass storage", "usb storage", "usbstor", "uaspstor", "flash drive", "external hard")
    ):
        categories.append(DeviceCategory.STORAGE)
    if device_class == "hidclass" and any(
        word in text for word in ("touchscreen", "touch screen", "touchpad", "digitizer")
    ):
        categories.append(DeviceCategory.INPUT_OUTPUT)

    return tuple(categories)


def device_from_mapping(raw: Mapping[str, Any]) -> PeripheralDevice | None:
    instance_id = _text(raw.get("InstanceId"))
    if not instance_id:
        return None
    name = _text(raw.get("FriendlyName")) or _text(raw.get("Name")) or instance_id
    known = {
        "InstanceId",
        "FriendlyName",
        "Name",
        "Manufacturer",
        "Status",
        "Class",
        "DriverProviderName",
        "DriverVersion",
        "LocationInfo",
        "Present",
    }
    properties = {
        str(key): _text(value)
        for key, value in raw.items()
        if str(key) not in known and _text(value)
    }
    driver_provider = _text(raw.get("DriverProviderName"))
    driver_version = _text(raw.get("DriverVersion"))
    driver = " ".join(value for value in (driver_provider, driver_version) if value) or None
    device = PeripheralDevice(
        instance_id=instance_id,
        name=name,
        manufacturer=_text(raw.get("Manufacturer")),
        status=_text(raw.get("Status")),
        device_class=_text(raw.get("Class")),
        driver=driver,
        connection=_text(raw.get("LocationInfo")),
        present=_bool(raw.get("Present")),
        properties=properties,
    )
    return PeripheralDevice(**{**device.__dict__, "categories": classify_device(device)})


def deduplicate_devices(devices: list[PeripheralDevice]) -> tuple[PeripheralDevice, ...]:
    """Remove repeated provider rows while retaining the first complete row."""

    unique: dict[str, PeripheralDevice] = {}
    for device in devices:
        key = device.instance_id.strip().lower() or (
            f"{device.name.strip().lower()}|{(device.manufacturer or '').strip().lower()}"
        )
        existing = unique.get(key)
        if existing is None or len(device.properties) > len(existing.properties):
            unique[key] = device
    return tuple(sorted(unique.values(), key=lambda item: item.display_name.casefold()))


def _text(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    lowered = str(value).strip().lower()
    if lowered in {"true", "1"}:
        return True
    if lowered in {"false", "0"}:
        return False
    return None
