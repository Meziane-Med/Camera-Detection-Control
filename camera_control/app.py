from PySide6.QtCore import QObject, QSignalBlocker, QThread, Qt, Signal, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QLabel,
    QMainWindow,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from peripheral_control.ui import PeripheralPanel

from .discovery import CameraDiscovery
from .models import DiscoveryReport, ResolutionInfo
from .preview import PreviewController


class DiscoveryWorker(QObject):
    finished = Signal(DiscoveryReport)

    def __init__(self, discovery: CameraDiscovery) -> None:
        super().__init__()
        self._discovery = discovery

    @Slot()
    def run(self) -> None:
        self.finished.emit(self._discovery.discover())


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Windows Peripheral and Camera Control")
        self.resize(900, 650)
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #111113; color: #e4e4e7;
                                   font-family: "Segoe UI"; font-size: 10pt; }
            QPushButton, QComboBox { min-height: 30px; background: #242428;
                                     color: #f4f4f5; border: 1px solid #45454d;
                                     border-radius: 6px; padding: 5px 12px; }
            QPushButton:hover, QComboBox:hover { background: #303036; border-color: #686873; }
            QPushButton:pressed { background: #18181b; }
            QPushButton:focus, QComboBox:focus, QListWidget:focus {
                border: 1px solid #a1a1aa;
            }
            QPushButton:disabled, QComboBox:disabled { color: #71717a;
                                                       background: #1b1b1f; }
            QComboBox::drop-down { width: 24px; border: 0; }
            QTabWidget::pane { border: 1px solid #323238; border-radius: 8px;
                               background: #111113; top: -1px; }
            QTabBar::tab { background: #18181b; color: #a1a1aa; padding: 10px 20px;
                           border: 1px solid #323238; border-bottom: 0;
                           border-top-left-radius: 7px; border-top-right-radius: 7px; }
            QTabBar::tab:hover { color: #f4f4f5; background: #242428; }
            QTabBar::tab:selected { background: #323238; color: #fafafa; }
            QLabel#pageTitle { color: #fafafa; font-size: 16pt; font-weight: 600; }
            QLabel#pageSubtitle, QLabel#secondaryText { color: #a1a1aa; }
            QFrame#previewHost { background: #18181b; border: 1px solid #323238;
                                 border-radius: 10px; }
            QLabel#preview { background: #09090b; border: 1px solid #3f3f46;
                             border-radius: 10px; }
            QLabel#cameraInfo { color: #a1a1aa; padding: 4px 2px; }
            QLabel#status { color: #a1a1aa; padding: 4px 2px; }
            QListWidget { background: #18181b; color: #e4e4e7;
                          border: 1px solid #323238; border-radius: 8px;
                          padding: 4px; outline: none; }
            QListWidget::item { padding: 9px 8px; border-radius: 5px; }
            QListWidget::item:hover { background: #242428; }
            QListWidget::item:selected { background: #3f3f46; color: #fafafa; }
            QFormLayout QLabel { color: #d4d4d8; }
            """
        )

        self._discovery = CameraDiscovery()
        self._discovery_thread: QThread | None = None
        self._discovery_worker: DiscoveryWorker | None = None
        self._preview = PreviewController()
        self._peripheral_panel = PeripheralPanel()

        self._refresh_button = QPushButton("Refresh")
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
        self._resolution_combo.setMinimumWidth(100)
        self._resolution_combo.setEnabled(False)
        self._fps_combo = QComboBox()
        self._fps_combo.setMinimumWidth(90)
        for fps in self._preview.fps_candidates:
            self._fps_combo.addItem(f"{fps:g} FPS", fps)
        self._fps_combo.setEnabled(False)
        self._zoom_in_button = QPushButton("Zoom +")
        self._zoom_out_button = QPushButton("Zoom -")
        self._reset_zoom_button = QPushButton("Reset")
        for button in (self._zoom_in_button, self._zoom_out_button, self._reset_zoom_button):
            button.setEnabled(False)
        for control in (
            self._refresh_button,
            self._camera_combo,
            self._stop_button,
            self._photo_button,
            self._start_recording_button,
            self._stop_recording_button,
            self._resolution_combo,
            self._fps_combo,
            self._zoom_in_button,
            self._zoom_out_button,
            self._reset_zoom_button,
        ):
            control.setMinimumWidth(0)
            control.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._preview_label = QLabel("Select a detected camera to start preview")
        self._preview_label.setObjectName("preview")
        self._preview_label.setMinimumSize(0, 0)
        self._preview_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._preview_label.setWordWrap(True)
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label = QLabel("Ready to detect cameras.")
        self._status_label.setObjectName("status")
        self._status_label.setWordWrap(True)
        self._camera_info = QLabel("Resolution: Not available | FPS: Not available | Zoom: Software 1.00x")
        self._camera_info.setObjectName("cameraInfo")
        self._camera_info.setWordWrap(True)

        title = QLabel("Camera Control")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Select a camera, preview its feed, and manage captures.")
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        subtitle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        header_copy = QVBoxLayout()
        header_copy.setSpacing(2)
        header_copy.addWidget(title)
        header_copy.addWidget(subtitle)
        header_copy.addStretch()
        camera_selector = QHBoxLayout()
        camera_selector.setSpacing(8)
        camera_selector.addWidget(QLabel("Camera"))
        camera_selector.addWidget(self._camera_combo, 1)
        camera_selector.addWidget(self._refresh_button, 1)
        header = QHBoxLayout()
        header.setSpacing(20)
        header.addLayout(header_copy, 1)
        header.addLayout(camera_selector, 1)

        preview_host = QFrame()
        preview_host.setObjectName("previewHost")
        preview_layout = QVBoxLayout(preview_host)
        preview_layout.setContentsMargins(14, 14, 14, 14)
        preview_layout.addWidget(self._preview_label, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(self._stop_button, 1)
        actions.addWidget(self._photo_button, 1)
        actions.addWidget(self._start_recording_button, 1)
        actions.addWidget(self._stop_recording_button, 1)
        actions.addStretch()

        settings = QHBoxLayout()
        settings.setSpacing(8)
        settings.addWidget(QLabel("Resolution"))
        settings.addWidget(self._resolution_combo, 1)
        settings.addSpacing(12)
        settings.addWidget(QLabel("FPS"))
        settings.addWidget(self._fps_combo, 1)
        settings.addSpacing(12)
        settings.addWidget(QLabel("Zoom"))
        settings.addWidget(self._zoom_out_button, 1)
        settings.addWidget(self._zoom_in_button, 1)
        settings.addWidget(self._reset_zoom_button, 1)
        settings.addStretch()

        layout = QVBoxLayout()
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(12)
        layout.addLayout(header)
        layout.addWidget(preview_host, 1)
        layout.addLayout(actions)
        layout.addLayout(settings)
        layout.addWidget(self._camera_info)
        layout.addWidget(self._status_label)
        camera_container = QWidget()
        camera_container.setLayout(layout)
        tabs = QTabWidget()
        tabs.addTab(camera_container, "Camera Control")
        tabs.addTab(self._peripheral_panel, "Peripheral Detection")
        self.setCentralWidget(tabs)

        self._refresh_button.clicked.connect(self.refresh_cameras)
        self._camera_combo.currentIndexChanged.connect(self._camera_selected)
        self._stop_button.clicked.connect(self.stop_preview)
        self._photo_button.clicked.connect(self._preview.take_photo)
        self._start_recording_button.clicked.connect(self._preview.start_recording)
        self._stop_recording_button.clicked.connect(self._preview.stop_recording)
        self._resolution_combo.currentIndexChanged.connect(self._resolution_selected)
        self._fps_combo.currentIndexChanged.connect(self._fps_selected)
        self._zoom_in_button.clicked.connect(self._preview.zoom_in)
        self._zoom_out_button.clicked.connect(self._preview.zoom_out)
        self._reset_zoom_button.clicked.connect(self._preview.reset_zoom)
        self._preview.frame_ready.connect(self._show_frame)
        self._preview.status_changed.connect(self._set_status)
        self._preview.error.connect(self._show_error)
        self._preview.stopped.connect(self._preview_stopped)
        self._preview.photo_saved.connect(lambda path: self._set_status(f"Photo saved: {path}"))
        self._preview.recording_started.connect(lambda path: self._set_status(f"Recording: {path}"))
        self._preview.recording_saved.connect(lambda path: self._set_status(f"Recording saved: {path}"))
        self._preview.recording_state_changed.connect(self._recording_state_changed)
        self._preview.resolutions_ready.connect(self._resolutions_ready)
        self._preview.resolution_changed.connect(self._resolution_changed)
        self._preview.fps_changed.connect(self._fps_changed)
        self._preview.measured_fps_changed.connect(self._measured_fps_changed)
        self._preview.zoom_changed.connect(self._zoom_changed)

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
        self._fps_combo.setEnabled(False)
        for button in (self._zoom_in_button, self._zoom_out_button, self._reset_zoom_button):
            button.setEnabled(False)
        self._camera_info.setText("Resolution: Not available | FPS: Not available | Zoom: Software 1.00x")
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
            self._camera_combo.setCurrentIndex(-1)
        self._camera_combo.setEnabled(bool(report.cameras))
        self._refresh_button.setEnabled(True)
        if report.cameras:
            self._set_status(f"Detected {len(report.cameras)} camera(s). Select one to start preview.")
        else:
            self._set_status("No camera indexes opened. Check connections and Windows privacy settings.")
        if report.errors:
            self._set_status(self._status_label.text() + " Some probe errors occurred.")
        if report.windows_capabilities:
            self._set_status(
                self._status_label.text()
                + " Windows camera metadata was collected; OpenCV index identity is not assumed exact."
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
            self._preview.start(int(camera_index))
            self._stop_button.setEnabled(True)
            self._photo_button.setEnabled(True)
            self._start_recording_button.setEnabled(True)
            self._fps_combo.setEnabled(True)
            for button in (self._zoom_in_button, self._zoom_out_button, self._reset_zoom_button):
                button.setEnabled(True)

    @Slot()
    def stop_preview(self) -> None:
        self._preview.stop()
        self._stop_button.setEnabled(False)
        self._photo_button.setEnabled(False)
        self._start_recording_button.setEnabled(False)
        self._stop_recording_button.setEnabled(False)
        self._resolution_combo.setEnabled(False)
        self._resolution_combo.clear()
        self._fps_combo.setEnabled(False)
        for button in (self._zoom_in_button, self._zoom_out_button, self._reset_zoom_button):
            button.setEnabled(False)
        self._preview_label.setText("Select a detected camera to start preview")
        self._camera_info.setText("Resolution: Not available | FPS: Not available | Zoom: Software 1.00x")

    @Slot(object)
    def _show_frame(self, image: object) -> None:
        pixmap = QPixmap.fromImage(image)
        self._preview_label.setPixmap(
            pixmap.scaled(
                self._preview_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    @Slot(str)
    def _set_status(self, message: str) -> None:
        self._status_label.setText(message)

    @Slot(str)
    def _show_error(self, message: str) -> None:
        self._status_label.setText(f"Error: {message}")

    @Slot()
    def _preview_stopped(self) -> None:
        if self._preview.selected_index is None:
            self._stop_button.setEnabled(False)
            self._photo_button.setEnabled(False)
            self._start_recording_button.setEnabled(False)
            self._stop_recording_button.setEnabled(False)
            self._resolution_combo.setEnabled(False)
            self._fps_combo.setEnabled(False)
            for button in (self._zoom_in_button, self._zoom_out_button, self._reset_zoom_button):
                button.setEnabled(False)

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
        if hasattr(self, "_camera_info") and self._preview.current_resolution is not None:
            self._update_camera_info(resolution=self._preview.current_resolution.display_name)

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
        self._update_camera_info(resolution=resolution.display_name)

    @Slot(int)
    def _fps_selected(self, combo_index: int) -> None:
        if combo_index >= 0:
            value = self._fps_combo.itemData(combo_index)
            if value is not None:
                self._preview.set_fps(float(value))

    @Slot(object)
    def _fps_changed(self, values: object) -> None:
        requested, actual = values
        if actual is not None:
            self._update_camera_info(fps=f"requested {requested:g}, reported {actual:g}")

    @Slot(float)
    def _measured_fps_changed(self, value: float) -> None:
        self._update_camera_info(fps=f"measured {value:.1f}")

    @Slot(float)
    def _zoom_changed(self, value: float) -> None:
        self._update_camera_info(zoom=f"Software {value:.2f}x")

    def _update_camera_info(
        self,
        resolution: str | None = None,
        fps: str | None = None,
        zoom: str | None = None,
    ) -> None:
        text = self._camera_info.text()
        if resolution is not None:
            text = self._replace_info(text, "Resolution", resolution)
        if fps is not None:
            text = self._replace_info(text, "FPS", fps)
        if zoom is not None:
            text = self._replace_info(text, "Zoom", zoom)
        self._camera_info.setText(text)

    @staticmethod
    def _replace_info(text: str, label: str, value: str) -> str:
        parts = text.split(" | ")
        for index, part in enumerate(parts):
            if part.startswith(f"{label}:"):
                parts[index] = f"{label}: {value}"
        return " | ".join(parts)

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
        self._peripheral_panel.shutdown()
        if self._discovery_thread is not None:
            self._discovery_thread.quit()
            self._discovery_thread.wait()
        event.accept()


def main() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    app.exec()