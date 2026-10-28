from PySide6.QtCore import QSignalBlocker, Qt, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from shared.tasks import BackgroundTask
from shared.widgets import button, card, label, page_header

from .discovery import PeripheralDiscovery, PeripheralDiscoveryReport
from .models import DeviceCategory, PeripheralDevice

_DETAILS_HINT = "Select a device to see what Windows reports about it."


class PeripheralPanel(QWidget):
    """Searchable list of Plug and Play devices with a details view."""

    def __init__(self, discovery: PeripheralDiscovery | None = None) -> None:
        super().__init__()
        self._discovery = discovery or PeripheralDiscovery()
        self._devices: tuple[PeripheralDevice, ...] = ()
        self._task = BackgroundTask(self)
        self._loaded = False
        self._build_ui()
        self._task.finished.connect(self._on_discovery_result)
        self._refresh.clicked.connect(self.refresh)
        self._search.textChanged.connect(self._refresh_list)
        self._filter.currentIndexChanged.connect(self._refresh_list)
        self._connected_only.toggled.connect(self._refresh_list)
        self._list.currentItemChanged.connect(self._device_selected)

    def _build_ui(self) -> None:
        self._refresh = button("Refresh", "primary")
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search devices…")
        self._search.setClearButtonEnabled(True)
        self._filter = QComboBox()
        self._filter.setObjectName("deviceFilter")
        self._filter.addItem("All Devices", None)
        for category in DeviceCategory:
            self._filter.addItem(category.value, category)
        self._connected_only = QCheckBox("Connected only")
        self._connected_only.setChecked(True)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        filters.addWidget(self._search, 1)
        filters.addWidget(self._filter)
        filters.addWidget(self._connected_only)

        self._list = QListWidget()
        self._list.setObjectName("deviceList")
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setTextElideMode(Qt.TextElideMode.ElideRight)
        list_card = card(margin=6)
        list_card.layout().addWidget(self._list)
        list_card.setMinimumWidth(260)

        self._details_label = label(_DETAILS_HINT, "pageSubtitle", wrap=True)
        self._details = QFormLayout()
        self._details.setVerticalSpacing(10)
        self._details.setHorizontalSpacing(18)
        details_body = QWidget()
        details_layout = QVBoxLayout(details_body)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(14)
        details_layout.addWidget(self._details_label)
        details_layout.addLayout(self._details)
        details_layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(details_body)
        details_card = card(margin=18)
        details_card.layout().addWidget(scroll)
        details_card.setMinimumWidth(320)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(12)
        splitter.addWidget(list_card)
        splitter.addWidget(details_card)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([340, 560])

        self._status = label("Devices load when this page opens.", "status", wrap=True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(14)
        layout.addLayout(page_header("Peripherals", "Input, output and storage devices reported by Windows.", self._refresh))
        layout.addLayout(filters)
        layout.addWidget(splitter, 1)
        layout.addWidget(self._status)

    def showEvent(self, event: object) -> None:
        # PowerShell discovery takes a few seconds; only pay for it when the page is opened.
        super().showEvent(event)
        if not self._loaded:
            self._loaded = True
            self.refresh()

    @Slot()
    def refresh(self) -> None:
        if not self._task.start(self._discovery.discover):
            return
        self._refresh.setEnabled(False)
        self._list.clear()
        self._clear_details()
        self._status.setText("Detecting Windows devices…")

    @Slot(object)
    def _on_discovery_result(self, result: object) -> None:
        if isinstance(result, Exception):
            result = PeripheralDiscoveryReport((), (f"Peripheral discovery failed: {result}",))
        self._discovery_finished(result)

    def _discovery_finished(self, report: PeripheralDiscoveryReport) -> None:
        self._devices = report.devices
        self._refresh.setEnabled(True)
        self._refresh_list()
        message = f"Detected {len(report.devices)} device(s)." if report.devices else "No devices were returned by Windows."
        self._status.setText(" ".join((message, *report.errors)))

    def _visible_devices(self) -> list[PeripheralDevice]:
        category = self._filter.currentData()
        query = self._search.text().strip().casefold()
        connected_only = self._connected_only.isChecked()
        return [
            device
            for device in self._devices
            if (category is None or category in device.categories)
            and not (connected_only and device.present is False)
            and (not query or query in f"{device.display_name} {device.manufacturer or ''}".casefold())
        ]

    @Slot()
    def _refresh_list(self) -> None:
        with QSignalBlocker(self._list):
            self._list.clear()
            for device in self._visible_devices():
                item = QListWidgetItem(f"{device.display_name}\n{device.category_text}")
                item.setData(Qt.ItemDataRole.UserRole, device)
                self._list.addItem(item)
        self._clear_details()

    @Slot(QListWidgetItem, QListWidgetItem)
    def _device_selected(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        del previous
        self._clear_details()
        device = current.data(Qt.ItemDataRole.UserRole) if current is not None else None
        if not isinstance(device, PeripheralDevice):
            return
        self._details_label.setText(device.display_name)
        present = {True: "Yes", False: "No"}.get(device.present, "Not available")
        fields = (
            ("Name", device.display_name),
            ("Category", device.category_text),
            ("Manufacturer", device.manufacturer or "Not available"),
            ("Status", device.status or "Not available"),
            ("Device ID", device.instance_id or "Not available"),
            ("Device class", device.device_class or "Not available"),
            ("Driver", device.driver or "Not available"),
            ("Connection", device.connection or "Not available"),
            ("Present", present),
            *sorted(device.properties.items()),
        )
        for name, value in fields:
            value_label = label(value, wrap=True)
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._details.addRow(label(name, "fieldLabel"), value_label)

    def _clear_details(self) -> None:
        while self._details.rowCount():
            self._details.removeRow(0)
        self._details_label.setText(_DETAILS_HINT)

    def shutdown(self) -> None:
        """Finish a running discovery before the owning window is destroyed."""

        self._task.wait()
