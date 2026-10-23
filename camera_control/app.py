import socket

from PySide6.QtCore import QObject, QSignalBlocker, QThread, Qt, Signal, Slot
from PySide6.QtGui import (
    QColor,
    QImage,
    QMouseEvent,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSlider,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .discovery import CameraDiscovery
from .models import DiscoveryReport, ResolutionInfo
from .peripherals import PeripheralInfo, WindowsPeripheralDiscovery
from .preview import PreviewController

WHITE_BALANCE_PRESETS = (
    ("Leave unchanged", "default"),
    ("Auto", None),
    ("Daylight (5500 K)", 5500),
    ("Cloudy (6500 K)", 6500),
    ("Tungsten (3200 K)", 3200),
)

PERIPHERAL_CATEGORIES = (
    "All types",
    "Audio",
    "Bluetooth",
    "Camera",
    "Display",
    "Input",
    "Network",
    "Other",
    "Printer",
    "Storage",
    "System",
    "USB",
)


class PreviewLabel(QLabel):
    double_clicked = Signal(float, float)

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._image: QImage | None = None

    def set_image(self, image: QImage) -> None:
        self._image = image
        self._render_image()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._render_image()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        image = self._image
        if image is None or image.width() <= 0 or image.height() <= 0:
            super().mouseDoubleClickEvent(event)
            return

        scale = min(self.width() / image.width(), self.height() / image.height())
        image_width = image.width() * scale
        image_height = image.height() * scale
        image_left = (self.width() - image_width) / 2
        image_top = (self.height() - image_height) / 2
        x = (event.position().x() - image_left) / image_width
        y = (event.position().y() - image_top) / image_height
        if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0:
            self.double_clicked.emit(x, y)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _render_image(self) -> None:
        if self._image is None or self.width() <= 0 or self.height() <= 0:
            return
        scaled = self._image.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(QPixmap.fromImage(scaled))


class DiscoveryWorker(QObject):
    finished = Signal(DiscoveryReport)

    def __init__(self, discovery: CameraDiscovery) -> None:
        super().__init__()
        self._discovery = discovery

    @Slot()
    def run(self) -> None:
        self.finished.emit(self._discovery.discover())


class PeripheralDiscoveryWorker(QObject):
    finished = Signal(object)

    def __init__(self, discovery: WindowsPeripheralDiscovery) -> None:
        super().__init__()
        self._discovery = discovery

    @Slot()
    def run(self) -> None:
        self.finished.emit(self._discovery.discover())


def _friendly_peripheral_name(peripherals: list[PeripheralInfo], category: str) -> str:
    names = {peripheral.name.strip() for peripheral in peripherals if peripheral.name.strip()}
    if not names:
        return f"{category} device"
    hostname = socket.gethostname().casefold()
    names = {
        name
        for name in names
        if name.casefold() != hostname and not name.casefold().startswith(f"{hostname} - ")
    }
    if not names:
        return f"{category} device"
    counts = {
        name: sum(peripheral.name.strip() == name for peripheral in peripherals)
        for name in names
    }
    most_common_name, most_common_count = max(
        counts.items(), key=lambda item: (item[1], item[0].casefold())
    )
    if most_common_count * 2 > sum(counts.values()):
        return most_common_name

    prefix_counts: dict[tuple[str, ...], int] = {}
    prefix_labels: dict[tuple[str, ...], str] = {}
    for name, count in counts.items():
        tokens = name.split()
        for length in range(2, len(tokens) + 1):
            prefix = tuple(token.casefold() for token in tokens[:length])
            prefix_counts[prefix] = prefix_counts.get(prefix, 0) + count
            prefix_labels[prefix] = " ".join(tokens[:length])
    total_names = sum(counts.values())
    common_prefixes = [
        prefix for prefix, count in prefix_counts.items() if count * 2 > total_names
    ]
    if common_prefixes:
        best_prefix = max(
            common_prefixes,
            key=lambda prefix: (len(prefix), prefix_counts[prefix], prefix),
        )
        return prefix_labels[best_prefix]

    technical_terms = (" endpoint", " interface", " mixer", " topology", " wave", " service")
    return min(
        names,
        key=lambda name: (
            sum(term in name.casefold() for term in technical_terms),
            -len(name),
            name.casefold(),
        ),
    )


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Windows Camera Control")
        self.resize(1366, 768)
        self.setMinimumSize(1000, 680)

        self._discovery = CameraDiscovery()
        self._discovery_thread: QThread | None = None
        self._discovery_worker: DiscoveryWorker | None = None
        self._peripheral_discovery = WindowsPeripheralDiscovery()
        self._peripheral_thread: QThread | None = None
        self._peripheral_worker: PeripheralDiscoveryWorker | None = None
        self._preview = PreviewController()

        self._refresh_button = QPushButton("Refresh cameras")
        self._camera_combo = QComboBox()
        self._camera_combo.setEnabled(False)
        self._stop_button = QPushButton("Stop preview")
        self._stop_button.setEnabled(False)
        self._photo_button = QPushButton("Take Photo")
        self._photo_button.setEnabled(False)
        self._start_recording_button = QPushButton("Start Recording")
        self._start_recording_button.setEnabled(False)
        self._stop_recording_button = QPushButton("Stop Recording")
        self._stop_recording_button.setEnabled(False)
        self._resolution_combo = QComboBox()
        self._resolution_combo.setEnabled(False)
        self._white_balance_combo = QComboBox()
        self._white_balance_combo.setEnabled(False)
        for label, value in WHITE_BALANCE_PRESETS:
            self._white_balance_combo.addItem(label, value)
        self._camera_controls_ready = False
        self._auto_focus_checkbox = QCheckBox("Autofocus")
        self._auto_focus_checkbox.setChecked(True)
        self._auto_focus_checkbox.setEnabled(False)
        self._focus_slider = QSlider(Qt.Orientation.Horizontal)
        self._focus_slider.setRange(0, 255)
        self._focus_slider.setValue(0)
        self._focus_slider.setEnabled(False)
        self._focus_value_label = QLabel("Auto")
        self._focus_value_label.setMinimumWidth(35)
        camera_controls_heading = QLabel("CAMERA CONTROLS")
        camera_controls_heading.setObjectName("sectionTitle")
        white_balance_heading = QLabel("WHITE BALANCE")
        white_balance_heading.setObjectName("fieldLabel")
        focus_heading = QLabel("FOCUS")
        focus_heading.setObjectName("fieldLabel")
        focus_group = QVBoxLayout()
        focus_group.setContentsMargins(0, 0, 0, 0)
        focus_group.setSpacing(4)
        focus_group.addWidget(self._auto_focus_checkbox)
        focus_layout = QHBoxLayout()
        focus_layout.setContentsMargins(0, 0, 0, 0)
        focus_layout.addWidget(self._focus_slider, 1)
        focus_layout.addWidget(self._focus_value_label)
        focus_group.addLayout(focus_layout)
        self._fps_cap_combo = QComboBox()
        self._fps_cap_combo.setEnabled(False)
        self._fps_cap_combo.addItem("Uncapped (camera rate)", None)
        self._fps_cap_combo.addItem("Cap: 15 FPS", 15.0)
        self._fps_cap_combo.addItem("Cap: 24 FPS", 24.0)
        self._fps_cap_combo.addItem("Cap: 30 FPS", 30.0)
        self._fps_cap_combo.addItem("Cap: 60 FPS", 60.0)
        self._zoom_label = QLabel("Zoom")
        self._zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._zoom_slider.setRange(100, 400)
        self._zoom_slider.setSingleStep(25)
        self._zoom_slider.setPageStep(100)
        self._zoom_slider.setValue(100)
        self._zoom_slider.setEnabled(False)
        self._zoom_value_label = QLabel("1.00x")
        self._preview_label = PreviewLabel("Select a detected camera to start preview")
        self._preview_label.setMinimumSize(640, 480)
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_hud = QLabel(self._preview_label)
        self._preview_hud.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._preview_hud.setStyleSheet(
            "QLabel { background-color: rgba(16, 16, 16, 180); color: white; border: 1px solid rgba(255,255,255,60); border-radius: 8px; padding: 8px 10px; }"
        )
        self._preview_hud.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._preview_hud.move(12, 12)
        self._preview_hud.hide()
        self._fps_value = "--"
        self._status_label = QLabel("Ready to detect cameras.")
        self._status_label.setWordWrap(True)

        sidebar = QFrame()
        sidebar.setObjectName("controlSidebar")
        sidebar.setFixedWidth(235)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 12, 12, 12)
        sidebar_layout.setSpacing(8)

        camera_heading = QLabel("SELECT CAMERA")
        camera_heading.setObjectName("sectionTitle")
        camera_row = QHBoxLayout()
        camera_row.addWidget(camera_heading, 1)
        camera_row.addWidget(self._refresh_button)
        sidebar_layout.addLayout(camera_row)
        sidebar_layout.addWidget(self._camera_combo)

        settings_heading = QLabel("SETTINGS")
        settings_heading.setObjectName("sectionTitle")
        sidebar_layout.addSpacing(5)
        sidebar_layout.addWidget(settings_heading)
        frame_rate_label = QLabel("FRAME RATE")
        frame_rate_label.setObjectName("fieldLabel")
        sidebar_layout.addWidget(frame_rate_label)
        sidebar_layout.addWidget(self._fps_cap_combo)
        zoom_layout = QHBoxLayout()
        zoom_layout.addWidget(self._zoom_label)
        zoom_layout.addWidget(self._zoom_slider, 1)
        zoom_layout.addWidget(self._zoom_value_label)
        sidebar_layout.addLayout(zoom_layout)

        resolution_heading = QLabel("RESOLUTION")
        resolution_heading.setObjectName("sectionTitle")
        sidebar_layout.addSpacing(3)
        sidebar_layout.addWidget(resolution_heading)
        sidebar_layout.addWidget(self._resolution_combo)

        capture_heading = QLabel("CAPTURE")
        capture_heading.setObjectName("sectionTitle")
        sidebar_layout.addSpacing(3)
        sidebar_layout.addWidget(capture_heading)
        capture_row = QHBoxLayout()
        capture_row.setSpacing(8)
        capture_row.addWidget(self._start_recording_button, 1)
        capture_row.addWidget(self._photo_button, 1)
        sidebar_layout.addLayout(capture_row)
        sidebar_layout.addWidget(self._stop_recording_button)

        preview_heading = QLabel("PREVIEW")
        preview_heading.setObjectName("sectionTitle")
        sidebar_layout.addSpacing(3)
        sidebar_layout.addWidget(preview_heading)
        sidebar_layout.addWidget(self._stop_button)
        sidebar_layout.addSpacing(5)
        sidebar_layout.addWidget(camera_controls_heading)
        sidebar_layout.addWidget(white_balance_heading)
        sidebar_layout.addWidget(self._white_balance_combo)
        sidebar_layout.addWidget(focus_heading)
        sidebar_layout.addLayout(focus_group)
        sidebar_layout.addStretch(1)

        sidebar_scroll = QScrollArea()
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setFrameShape(QFrame.Shape.NoFrame)
        sidebar_scroll.setFixedWidth(255)
        sidebar_scroll.setWidget(sidebar)

        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(6)
        self._preview_label.setStyleSheet("background-color: #101415; color: #f3f4f5;")
        preview_layout.addWidget(self._preview_label, 1)
        self._status_label.setObjectName("statusLabel")
        preview_layout.addWidget(self._status_label)

        container = QWidget()
        container.setObjectName("mainContainer")
        container.setStyleSheet(
            """
            QWidget#mainContainer {
                background-color: #f3f5f6;
                color: #243342;
                font-size: 12px;
            }
            QFrame#controlSidebar {
                background-color: #f0f3f5;
                border: 1px solid #d5dce0;
                border-radius: 5px;
            }
            QLabel#sectionTitle {
                color: #263746;
                font-size: 11px;
                font-weight: 700;
            }
            QLabel#fieldLabel, QLabel#statusLabel {
                color: #566775;
                font-size: 11px;
            }
            QComboBox {
                min-height: 26px;
                padding: 1px 6px;
                background-color: #ffffff;
                border: 1px solid #d7dfe4;
                border-radius: 4px;
            }
            QComboBox::drop-down {
                width: 20px;
                border: none;
                border-top-right-radius: 4px;
                border-bottom-right-radius: 4px;
            }
            QComboBox QAbstractItemView {
                background-color: #ffffff;
                border: 1px solid #d7dfe4;
                selection-background-color: #e8eef2;
                selection-color: #243342;
                outline: none;
            }
            QPushButton {
                min-height: 28px;
                padding: 1px 7px;
                background-color: #ffffff;
                border: 1px solid #d7dfe4;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #e8eef2;
            }
            QPushButton#recordButton {
                background-color: #d93636;
                border: 1px solid #d93636;
                color: #ffffff;
                font-weight: 600;
            }
            QPushButton#recordButton:disabled {
                background-color: #e7b0b0;
                border-color: #e7b0b0;
            }
            QPushButton#photoButton {
                background-color: #087fc1;
                border: 1px solid #087fc1;
                color: #ffffff;
                font-weight: 600;
            }
            QPushButton#photoButton:disabled {
                background-color: #a8cfe4;
                border-color: #a8cfe4;
            }
            QSlider::groove:horizontal {
                height: 3px;
                background: #c8d0d5;
                border-radius: 2px;
                margin: 0 1px;
            }
            QSlider::handle:horizontal {
                width: 11px;
                height: 11px;
                margin: -4px 0;
                background: #ffffff;
                border: 1px solid #96a5ae;
                border-radius: 6px;
            }
            QSlider::handle:horizontal:hover {
                border-color: #087fc1;
            }
            """
        )
        camera_page = QWidget()
        camera_page.setObjectName("cameraPage")
        camera_page_layout = QHBoxLayout(camera_page)
        camera_page_layout.setContentsMargins(9, 9, 9, 9)
        camera_page_layout.setSpacing(10)
        camera_page_layout.addWidget(sidebar_scroll)
        camera_page_layout.addWidget(preview_container, 1)

        peripherals_page = QWidget()
        peripherals_page.setObjectName("peripheralsPage")
        peripherals_layout = QVBoxLayout(peripherals_page)
        peripherals_layout.setContentsMargins(16, 16, 16, 16)
        peripherals_layout.setSpacing(12)
        peripherals_toolbar = QHBoxLayout()
        peripherals_heading = QLabel("Connected peripherals")
        peripherals_heading.setObjectName("pageTitle")
        peripherals_description = QLabel(
            "Related Windows entries are grouped by device when possible."
        )
        peripherals_description.setObjectName("fieldLabel")
        description_layout = QVBoxLayout()
        description_layout.addWidget(peripherals_heading)
        description_layout.addWidget(peripherals_description)
        peripherals_toolbar.addLayout(description_layout, 1)
        self._refresh_peripherals_button = QPushButton("Refresh")
        peripherals_toolbar.addWidget(self._refresh_peripherals_button)
        peripherals_layout.addLayout(peripherals_toolbar)
        peripheral_type_layout = QHBoxLayout()
        peripheral_type_label = QLabel("Device type")
        peripheral_type_label.setObjectName("fieldLabel")
        peripheral_type_layout.addWidget(peripheral_type_label)
        self._peripheral_type_combo = QComboBox()
        self._peripheral_type_combo.addItems(PERIPHERAL_CATEGORIES)
        self._peripheral_type_combo.currentIndexChanged.connect(self._render_peripherals)
        peripheral_type_layout.addWidget(self._peripheral_type_combo)
        peripheral_type_layout.addStretch(1)
        peripherals_layout.addLayout(peripheral_type_layout)
        self._peripheral_results: tuple[PeripheralInfo, ...] = ()
        self._peripherals_table = QTreeWidget()
        self._peripherals_table.setColumnCount(4)
        self._peripherals_table.setHeaderLabels(("Name", "Category", "Status", "Device ID"))
        self._peripherals_table.setEditTriggers(QTreeWidget.EditTrigger.NoEditTriggers)
        self._peripherals_table.setSelectionBehavior(QTreeWidget.SelectionBehavior.SelectRows)
        self._peripherals_table.setAlternatingRowColors(True)
        self._peripherals_table.setRootIsDecorated(True)
        self._peripherals_table.setItemsExpandable(True)
        self._peripherals_table.setUniformRowHeights(True)
        self._peripherals_table.header().setStretchLastSection(True)
        self._peripherals_table.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._peripherals_table.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._peripherals_table.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        peripherals_layout.addWidget(self._peripherals_table, 1)
        self._peripherals_status = QLabel("Open this tab to discover connected peripherals.")
        self._peripherals_status.setObjectName("statusLabel")
        peripherals_layout.addWidget(self._peripherals_status)
        self._peripheral_errors: tuple[str, ...] = ()

        self._tabs = QTabWidget()
        self._tabs.addTab(camera_page, "Camera")
        self._tabs.addTab(peripherals_page, "Peripherals")
        self._tabs.setStyleSheet(
            """
            QTabWidget::pane {
                border: none;
                background-color: #f3f5f6;
            }
            QTabBar::tab {
                min-width: 92px;
                padding: 8px 16px;
                color: #566775;
                background-color: #e7ecef;
                border: 1px solid #d5dce0;
                border-bottom: none;
                border-top-left-radius: 5px;
                border-top-right-radius: 5px;
                margin-right: 3px;
            }
            QTabBar::tab:selected {
                color: #243342;
                background-color: #f3f5f6;
                font-weight: 600;
            }
            QTreeWidget {
                background-color: #ffffff;
                alternate-background-color: #f5f7f8;
                border: 1px solid #d7dfe4;
                gridline-color: #e4e9ec;
                selection-background-color: #dceaf2;
                selection-color: #243342;
            }
            QHeaderView::section {
                padding: 6px 8px;
                background-color: #edf1f3;
                color: #31495b;
                border: none;
                border-bottom: 1px solid #d7dfe4;
                font-weight: 600;
            }
            QLabel#pageTitle {
                color: #263746;
                font-size: 18px;
                font-weight: 600;
            }
            """
        )
        self.setCentralWidget(self._tabs)

        self._refresh_button.setText("Refresh")
        self._refresh_button.setMinimumHeight(32)
        self._start_recording_button.setObjectName("recordButton")
        self._start_recording_button.setText("▶ Start Recording")
        self._photo_button.setObjectName("photoButton")
        self._photo_button.setText("Take Photo")
        self._stop_recording_button.setText("■ Stop Recording")
        self._stop_button.setText("■ Stop preview")

        self._refresh_button.clicked.connect(self.refresh_cameras)
        self._camera_combo.currentIndexChanged.connect(self._camera_selected)
        self._stop_button.clicked.connect(self.stop_preview)
        self._photo_button.clicked.connect(self._preview.take_photo)
        self._start_recording_button.clicked.connect(self._preview.start_recording)
        self._stop_recording_button.clicked.connect(self._preview.stop_recording)
        self._resolution_combo.currentIndexChanged.connect(self._resolution_selected)
        self._white_balance_combo.currentIndexChanged.connect(self._white_balance_selected)
        self._refresh_peripherals_button.clicked.connect(self._refresh_peripherals)
        self._tabs.currentChanged.connect(self._tab_changed)
        self._auto_focus_checkbox.toggled.connect(self._auto_focus_changed)
        self._focus_slider.valueChanged.connect(self._focus_changed)
        self._fps_cap_combo.currentIndexChanged.connect(self._fps_cap_selected)
        self._zoom_slider.valueChanged.connect(self._zoom_changed)
        self._preview.frame_ready.connect(self._show_frame)
        self._preview_label.double_clicked.connect(self._preview_double_clicked)
        self._preview.fps_changed.connect(self._fps_changed)
        self._preview.status_changed.connect(self._set_status)
        self._preview.error.connect(self._show_error)
        self._preview.stopped.connect(self._preview_stopped)
        self._preview.photo_saved.connect(lambda path: self._set_status(f"Photo saved: {path}"))
        self._preview.recording_started.connect(lambda path: self._set_status(f"Recording: {path}"))
        self._preview.recording_saved.connect(lambda path: self._set_status(f"Recording saved: {path}"))
        self._preview.recording_state_changed.connect(self._recording_state_changed)
        self._preview.resolutions_ready.connect(self._resolutions_ready)
        self._preview.resolution_changed.connect(self._resolution_changed)

        self.refresh_cameras()

    @Slot()
    def refresh_cameras(self) -> None:
        self.stop_preview()
        if self._discovery_thread is not None:
            return
        self._refresh_button.setEnabled(False)
        self._camera_combo.setEnabled(False)
        self._camera_combo.clear()
        self._resolution_combo.clear()
        self._resolution_combo.setEnabled(False)
        self._set_status("Detecting cameras. This may take a moment...")

        thread = QThread(self)
        worker = DiscoveryWorker(self._discovery)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._discovery_finished)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._discovery_thread_finished)
        self._discovery_thread = thread
        self._discovery_worker = worker
        thread.start()

    @Slot(DiscoveryReport)
    def _discovery_finished(self, report: DiscoveryReport) -> None:
        with QSignalBlocker(self._camera_combo):
            for camera in report.cameras:
                self._camera_combo.addItem(camera.display_name, camera.index)
                self._camera_combo.setItemData(
                    self._camera_combo.count() - 1,
                    camera.windows_device_id,
                    int(Qt.ItemDataRole.UserRole) + 1,
                )
            self._camera_combo.setCurrentIndex(-1)
        self._camera_combo.setEnabled(bool(report.cameras))
        self._refresh_button.setEnabled(True)
        if report.cameras:
            self._set_status(f"Detected {len(report.cameras)} camera(s). Select one to start preview.")
        else:
            self._set_status("No cameras were found. Check connections and Windows privacy settings.")
        if report.errors:
            self._set_status(self._status_label.text() + " Some probe errors occurred.")
        if report.windows_capabilities and any(
            camera.windows_device_id for camera in report.cameras
        ):
            self._set_status(
                self._status_label.text()
                + " Windows camera IDs are used for the selected preview and camera controls."
            )

    @Slot()
    def _discovery_thread_finished(self) -> None:
        thread = self._discovery_thread
        self._discovery_thread = None
        self._discovery_worker = None
        if thread is not None:
            thread.deleteLater()

    @Slot(int)
    def _camera_selected(self, combo_index: int) -> None:
        if combo_index < 0:
            return
        camera_index = self._camera_combo.itemData(combo_index)
        if camera_index is not None:
            windows_device_id = self._camera_combo.itemData(
                combo_index, int(Qt.ItemDataRole.UserRole) + 1
            )
            if windows_device_id:
                self._preview.start(int(camera_index), str(windows_device_id))
            else:
                self._preview.start(int(camera_index))
            self._camera_controls_ready = False
            with QSignalBlocker(self._white_balance_combo):
                self._white_balance_combo.setCurrentIndex(0)
            with QSignalBlocker(self._auto_focus_checkbox):
                self._auto_focus_checkbox.setChecked(True)
            self._set_camera_control_states()
            self._focus_value_label.setText("Auto")
            self._stop_button.setEnabled(True)
            self._photo_button.setEnabled(True)
            self._start_recording_button.setEnabled(True)
            self._fps_cap_combo.setEnabled(True)
            self._zoom_slider.setEnabled(True)

    @Slot(int)
    def _fps_cap_selected(self, combo_index: int) -> None:
        if combo_index < 0:
            return
        value = self._fps_cap_combo.itemData(combo_index)
        if value is None:
            self._preview.set_fps_cap(None)
            self._set_status("FPS cap removed.")
            return
        fps_cap = float(value)
        self._preview.set_fps_cap(fps_cap)
        self._set_status(f"FPS cap set to {fps_cap:.0f} FPS.")

    @Slot(int)
    def _white_balance_selected(self, combo_index: int) -> None:
        if combo_index < 0:
            return
        temperature = self._white_balance_combo.itemData(combo_index)
        if temperature == "default":
            self._set_status("Using the camera's current white-balance setting.")
            return
        self._preview.set_white_balance(temperature)

    @Slot(int)
    def _tab_changed(self, index: int) -> None:
        if self._tabs.tabText(index) == "Peripherals" and self._peripheral_thread is None:
            self._refresh_peripherals()

    @Slot()
    def _refresh_peripherals(self) -> None:
        if self._peripheral_thread is not None:
            return
        self._refresh_peripherals_button.setEnabled(False)
        self._peripherals_status.setText("Discovering peripherals reported by Windows...")
        thread = QThread(self)
        worker = PeripheralDiscoveryWorker(self._peripheral_discovery)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._peripherals_discovered)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._peripheral_thread_finished)
        self._peripheral_thread = thread
        self._peripheral_worker = worker
        thread.start()

    @Slot(object)
    def _peripherals_discovered(
        self,
        result: tuple[tuple[PeripheralInfo, ...], tuple[str, ...]],
    ) -> None:
        peripherals, errors = result
        self._peripheral_results = peripherals
        self._peripheral_errors = errors
        self._render_peripherals()
        self._refresh_peripherals_button.setEnabled(True)

    @Slot(bool)
    def _render_peripherals(self, _checked: bool = False) -> None:
        if not hasattr(self, "_peripherals_table"):
            return
        grouped: dict[str, list[PeripheralInfo]] = {}
        selected_category = self._peripheral_type_combo.currentText()
        for peripheral in self._peripheral_results:
            if selected_category != "All types" and peripheral.category != selected_category:
                continue
            grouped.setdefault(peripheral.category, []).append(peripheral)

        self._peripherals_table.clear()
        self._peripherals_table.setHeaderLabels(("Name", "Category", "Status", "Device ID"))
        displayed_count = 0
        for category, peripherals in sorted(grouped.items()):
            group_item = QTreeWidgetItem((f"{category} ({len(peripherals)})", "", "", ""))
            self._peripherals_table.addTopLevelItem(group_item)
            by_container: dict[str, list[PeripheralInfo]] = {}
            standalone: list[PeripheralInfo] = []
            for peripheral in peripherals:
                group_key = peripheral.container_id or peripheral.device_instance_id
                if group_key is None:
                    standalone.append(peripheral)
                else:
                    by_container.setdefault(group_key, []).append(peripheral)

            children: list[tuple[str, list[PeripheralInfo], bool]] = [
                (peripheral.name, [peripheral], False) for peripheral in standalone
            ]
            for entries in by_container.values():
                if len(entries) > 1:
                    name = _friendly_peripheral_name(entries, category)
                    children.append((f"{name} ({len(entries)} interfaces)", entries, True))
                else:
                    children.append((entries[0].name, entries, False))

            for child_label, entries, is_device_group in sorted(
                children, key=lambda child: (child[0].casefold(), child[0])
            ):
                if is_device_group:
                    device_item = QTreeWidgetItem((child_label, "", "", ""))
                    device_item.setToolTip(0, "Related Windows entries for the same physical device.")
                    group_item.addChild(device_item)
                    parent_item = device_item
                else:
                    parent_item = group_item

                for peripheral in sorted(
                    entries, key=lambda item: (item.name.casefold(), item.device_id.casefold())
                ):
                    enabled = peripheral.is_enabled
                    status = "Enabled" if enabled is True else "Disabled" if enabled is False else "Unknown"
                    internal = "Internal/system" if peripheral.is_internal is True else "Unknown"
                    item = QTreeWidgetItem(
                        (peripheral.name, peripheral.category, status, peripheral.device_id)
                    )
                    item.setToolTip(0, f"Windows device kind: {peripheral.kind}\nInternal status: {internal}")
                    item.setToolTip(3, peripheral.device_id)
                    parent_item.addChild(item)
                    displayed_count += 1
                if is_device_group:
                    device_item.setExpanded(False)
            group_item.setExpanded(True)

        if self._peripheral_results:
            message = (
                f"Windows returned {len(self._peripheral_results)} device entries; "
                f"showing {displayed_count}."
            )
        elif self._peripheral_errors:
            message = "Windows did not return a peripheral list."
        else:
            message = "Windows returned no peripheral devices."

        if self._peripheral_errors:
            message += " " + " ".join(self._peripheral_errors)
        self._peripherals_status.setText(message)

    @Slot()
    def _peripheral_thread_finished(self) -> None:
        thread = self._peripheral_thread
        self._peripheral_thread = None
        self._peripheral_worker = None
        if thread is not None:
            thread.deleteLater()

    @Slot(bool)
    def _auto_focus_changed(self, enabled: bool) -> None:
        if not self._camera_controls_ready:
            return
        self._preview.set_auto_focus(enabled)
        self._focus_value_label.setText("Auto" if enabled else str(self._focus_slider.value()))
        self._set_camera_control_states()

    @Slot(int)
    def _focus_changed(self, value: int) -> None:
        self._focus_value_label.setText(str(value))
        if self._camera_controls_ready and not self._auto_focus_checkbox.isChecked():
            self._preview.set_focus(value)

    def _set_camera_control_states(self) -> None:
        self._auto_focus_checkbox.setEnabled(self._camera_controls_ready)
        self._focus_slider.setEnabled(
            self._camera_controls_ready and not self._auto_focus_checkbox.isChecked()
        )

    @Slot(int)
    def _zoom_changed(self, slider_value: int) -> None:
        zoom_factor = slider_value / 100.0
        self._preview.set_zoom_factor(zoom_factor)
        self._zoom_value_label.setText(f"{zoom_factor:.2f}x")

    @Slot(float, float)
    def _preview_double_clicked(self, x: float, y: float) -> None:
        zoom_factor = self._preview.focus_zoom_at(x, y)
        with QSignalBlocker(self._zoom_slider):
            self._zoom_slider.setValue(round(zoom_factor * 100))
        self._zoom_value_label.setText(f"{zoom_factor:.2f}x")

    @Slot()
    def stop_preview(self) -> None:
        self._preview.stop()
        self._fps_value = "--"
        self._update_preview_hud()
        self._stop_button.setEnabled(False)
        self._photo_button.setEnabled(False)
        self._start_recording_button.setEnabled(False)
        self._stop_recording_button.setEnabled(False)
        self._resolution_combo.setEnabled(False)
        self._white_balance_combo.setEnabled(False)
        self._camera_controls_ready = False
        self._set_camera_control_states()
        self._fps_cap_combo.setEnabled(False)
        self._zoom_slider.setEnabled(False)
        with QSignalBlocker(self._zoom_slider):
            self._zoom_slider.setValue(100)
        self._zoom_value_label.setText("1.00x")
        self._preview.set_zoom_factor(1.0)
        with QSignalBlocker(self._fps_cap_combo):
            self._fps_cap_combo.setCurrentIndex(0)
        self._preview.set_fps_cap(None)
        self._resolution_combo.clear()
        with QSignalBlocker(self._white_balance_combo):
            self._white_balance_combo.setCurrentIndex(0)
        with QSignalBlocker(self._auto_focus_checkbox):
            self._auto_focus_checkbox.setChecked(True)
        self._focus_value_label.setText("Auto")
        self._preview_label.setText("Select a detected camera to start preview")

    @Slot(object)
    def _show_frame(self, image: object) -> None:
        self._preview_label.set_image(image)
        self._update_preview_hud()

    @Slot(str)
    def _set_status(self, message: str) -> None:
        self._status_label.setText(message)

    @Slot(float)
    def _fps_changed(self, fps: float) -> None:
        self._fps_value = f"{fps:.1f}"
        self._update_preview_hud()

    def _update_preview_hud(self) -> None:
        preview = getattr(self, "_preview", None)
        hud = getattr(self, "_preview_hud", None)
        status = "Connected" if preview is not None and preview.is_running else "Disconnected"

        if hud is not None:
            hud.setText(
                f"Preview FPS: {getattr(self, '_fps_value', '--')}\n"
                f"Connection: {status}"
            )
            hud.setVisible(preview is not None and preview.is_running)

    @Slot(str)
    def _show_error(self, message: str) -> None:
        self._status_label.setText(f"Error: {message}")

    @Slot()
    def _preview_stopped(self) -> None:
        self._fps_value = "--"
        self._update_preview_hud()
        if self._preview.selected_index is None:
            self._stop_button.setEnabled(False)
            self._photo_button.setEnabled(False)
            self._start_recording_button.setEnabled(False)
            self._stop_recording_button.setEnabled(False)
            self._resolution_combo.setEnabled(False)
            self._white_balance_combo.setEnabled(False)
            self._camera_controls_ready = False
            self._set_camera_control_states()

    @Slot(object)
    def _resolutions_ready(self, resolutions: object) -> None:
        with QSignalBlocker(self._resolution_combo):
            self._resolution_combo.clear()
            for resolution in resolutions:
                self._resolution_combo.addItem(resolution.display_name, (resolution.width, resolution.height))
            current = self._preview.current_resolution
            if current is not None:
                index = self._resolution_index(current.width, current.height)
                self._resolution_combo.setCurrentIndex(index if index >= 0 else 0)
        self._resolution_combo.setEnabled(self._preview.is_running and not self._preview.is_recording)
        self._white_balance_combo.setEnabled(self._preview.is_running)
        self._camera_controls_ready = self._preview.is_running
        self._set_camera_control_states()
        if self._camera_controls_ready:
            self._preview.set_auto_focus(True)
        self._update_preview_hud()

    @Slot(int)
    def _resolution_selected(self, combo_index: int) -> None:
        if combo_index < 0:
            return
        value = self._resolution_combo.itemData(combo_index)
        if value is not None:
            self._preview.set_resolution(*value)

    @Slot(object)
    def _resolution_changed(self, resolution: ResolutionInfo) -> None:
        with QSignalBlocker(self._resolution_combo):
            index = self._resolution_index(resolution.width, resolution.height)
            if index >= 0:
                self._resolution_combo.setCurrentIndex(index)
        self._update_preview_hud()

    def _resolution_index(self, width: int, height: int) -> int:
        for index in range(self._resolution_combo.count()):
            value = self._resolution_combo.itemData(index)
            if value is not None and tuple(value) == (width, height):
                return index
        return -1

    @Slot(bool)
    def _recording_state_changed(self, recording: bool) -> None:
        self._start_recording_button.setEnabled(not recording and self._preview.is_running)
        self._stop_recording_button.setEnabled(recording)
        self._photo_button.setEnabled(self._preview.is_running)
        self._resolution_combo.setEnabled(self._preview.is_running and not recording)

    def closeEvent(self, event: object) -> None:
        self.stop_preview()
        if self._discovery_thread is not None:
            self._discovery_thread.quit()
            self._discovery_thread.wait()
        if self._peripheral_thread is not None:
            self._peripheral_thread.quit()
            self._peripheral_thread.wait()
        event.accept()


def main() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    app.exec()