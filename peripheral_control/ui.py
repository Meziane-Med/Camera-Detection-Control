from PySide6.QtCore import QObject, QSignalBlocker, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .discovery import PeripheralDiscovery, PeripheralDiscoveryReport
from .models import DeviceCategory, PeripheralDevice


class PeripheralDiscoveryWorker(QObject):
    finished = Signal(object)

    def __init__(self, discovery: PeripheralDiscovery) -> None:
        super().__init__()
        self._discovery = discovery

    @Slot()
    def run(self) -> None:
        try:
            report = self._discovery.discover()
        except Exception as exc:
            report = PeripheralDiscoveryReport(
                (),
                (f"Peripheral discovery failed: {exc}",),
            )
        self.finished.emit(report)


class PeripheralPanel(QWidget):
    def __init__(self, discovery: PeripheralDiscovery | None = None) -> None:
        super().__init__()
        self._discovery = discovery or PeripheralDiscovery()
        self._devices: tuple[PeripheralDevice, ...] = ()
        self._thread: QThread | None = None
        self._worker: PeripheralDiscoveryWorker | None = None
        self._filter = QComboBox()
        self._filter.setObjectName("deviceFilter")
        self._filter.addItem("All Devices", None)
        for category in DeviceCategory:
            self._filter.addItem(category.value, category)
        self._refresh = QPushButton("Refresh devices")
        self._refresh.setObjectName("secondaryButton")
        self._list = QListWidget()
        self._list.setObjectName("deviceList")
        self._details = QFormLayout()
        self._details.setContentsMargins(4, 8, 4, 4)
        self._details.setVerticalSpacing(10)
        self._details_label = QLabel("Select a device to inspect the properties Windows provided.")
        self._details_label.setObjectName("pageSubtitle")
        self._details_label.setWordWrap(True)
        self._status = QLabel("Ready to detect Windows devices.")
        self._status.setObjectName("status")
        self._status.setWordWrap(True)
        self._build_layout()
        self._filter.currentIndexChanged.connect(self._filter_changed)
        self._refresh.clicked.connect(self.refresh)
        self._list.currentItemChanged.connect(self._device_selected)
        self.refresh()

    def _build_layout(self) -> None:
        controls = QVBoxLayout()
        controls.setContentsMargins(0, 0, 8, 0)
        controls.setSpacing(10)
        controls.addWidget(self._filter)
        controls.addWidget(self._refresh)
        controls.addWidget(self._list, 1)
        left = QWidget()
        left.setLayout(controls)
        details = QWidget()
        details_layout = QVBoxLayout()
        details_layout.setContentsMargins(16, 4, 8, 0)
        details_layout.setSpacing(10)
        details_layout.addWidget(self._details_label)
        details_layout.addLayout(self._details)
        details_layout.addStretch()
        details.setLayout(details_layout)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.addWidget(left)
        splitter.addWidget(details)
        left.setMinimumWidth(230)
        details.setMinimumWidth(300)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 520])
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addWidget(splitter, 1)
        layout.addWidget(self._status)
        self.setLayout(layout)

    @Slot()
    def refresh(self) -> None:
        if self._thread is not None:
            return
        self._refresh.setEnabled(False)
        self._filter.setEnabled(False)
        self._list.clear()
        self._clear_details()
        self._status.setText("Detecting Windows devices. This may take a moment...")
        thread = QThread(self)
        worker = PeripheralDiscoveryWorker(self._discovery)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._discovery_finished)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._thread_finished)
        self._thread, self._worker = thread, worker
        thread.start()

    @Slot(object)
    def _discovery_finished(self, report: PeripheralDiscoveryReport) -> None:
        self._devices = report.devices
        self._refresh_list()
        self._refresh.setEnabled(True)
        self._filter.setEnabled(True)
        if report.devices:
            message = f"Detected {len(report.devices)} device(s). Windows does not guarantee exhaustive enumeration."
        else:
            message = "No devices were returned by Windows."
        if report.errors:
            message += " " + " ".join(report.errors)
        self._status.setText(message)

    @Slot()
    def _thread_finished(self) -> None:
        thread = self._thread
        self._thread, self._worker = None, None
        if thread is not None:
            thread.deleteLater()

    @Slot()
    def _filter_changed(self) -> None:
        self._refresh_list()

    def _refresh_list(self) -> None:
        category = self._filter.currentData()
        with QSignalBlocker(self._list):
            self._list.clear()
            for device in self._devices:
                if category is not None and category not in device.categories:
                    continue
                item = QListWidgetItem(f"{device.display_name} — {device.category_text}")
                item.setData(Qt.ItemDataRole.UserRole, device)
                self._list.addItem(item)
        self._clear_details()

    @Slot(QListWidgetItem, QListWidgetItem)
    def _device_selected(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        del previous
        self._clear_details()
        device = current.data(Qt.ItemDataRole.UserRole) if current is not None else None
        if isinstance(device, PeripheralDevice):
            self._details_label.setText(f"Details for {device.display_name}")
            fields = (
                ("Name", device.display_name),
                ("Category", device.category_text),
                ("Manufacturer", device.manufacturer or "Not available"),
                ("Status", device.status or "Not available"),
                ("Device ID", device.instance_id or "Not available"),
                ("Device class", device.device_class or "Not available"),
                ("Driver", device.driver or "Not available"),
                ("Connection", device.connection or "Not available"),
                ("Present", "Yes" if device.present is True else "No" if device.present is False else "Not available"),
            )
            for label, value in fields:
                self._details.addRow(label, QLabel(value))
            for label, value in sorted(device.properties.items()):
                self._details.addRow(label, QLabel(value))

    def _clear_details(self) -> None:
        while self._details.rowCount():
            self._details.removeRow(0)
        self._details_label.setText("Select a device to inspect the properties Windows provided.")

    def closeEvent(self, event: object) -> None:
        self.shutdown()
        event.accept()

    def shutdown(self) -> None:
        """Stop a discovery worker before the owning window is destroyed."""

        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._thread = None
            self._worker = None
