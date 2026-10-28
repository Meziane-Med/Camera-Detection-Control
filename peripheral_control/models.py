from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


class DeviceCategory(Enum):
    INPUT = "Input Devices"
    OUTPUT = "Output Devices"
    INPUT_OUTPUT = "Input/Output Devices"
    STORAGE = "Storage Devices"


@dataclass(frozen=True)
class PeripheralDevice:
    """Information returned by Windows for one physical or logical device."""

    instance_id: str
    name: str
    manufacturer: str | None = None
    status: str | None = None
    device_class: str | None = None
    driver: str | None = None
    connection: str | None = None
    present: bool | None = None
    categories: tuple[DeviceCategory, ...] = ()
    properties: Mapping[str, str] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        return self.name or self.instance_id or "Unknown device"

    @property
    def category_text(self) -> str:
        return ", ".join(category.value for category in self.categories) or "Unknown"
