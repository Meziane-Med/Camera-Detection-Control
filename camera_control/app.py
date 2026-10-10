from PySide6.QtCore import QObject, QSignalBlocker, QThread, Qt, Signal, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

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
        self.setWindowTitle("Windows Camera Control")
        self.resize(900, 650)

        self._discovery = CameraDiscovery()
        self._discovery_thread: QThread | None = None
        self._discovery_worker: DiscoveryWorker | None = None
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
        self._preview_label = QLabel("Select a detected camera to start preview")
        self._preview_label.setMinimumSize(640, 480)
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label = QLabel("Ready to detect cameras.")
        self._status_label.setWordWrap(True)

        layout = QVBoxLayout()
        layout.addWidget(self._refresh_button)
        layout.addWidget(self._camera_combo)
        layout.addWidget(self._resolution_combo)
        layout.addWidget(self._stop_button)
        layout.addWidget(self._photo_button)
        layout.addWidget(self._start_recording_button)
        layout.addWidget(self._stop_recording_button)
        layout.addWidget(self._preview_label, 1)
        layout.addWidget(self._status_label)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self._refresh_button.clicked.connect(self.refresh_cameras)
        self._camera_combo.currentIndexChanged.connect(self._camera_selected)
        self._stop_button.clicked.connect(self.stop_preview)
        self._photo_button.clicked.connect(self._preview.take_photo)
        self._start_recording_button.clicked.connect(self._preview.start_recording)
        self._stop_recording_button.clicked.connect(self._preview.stop_recording)
        self._resolution_combo.currentIndexChanged.connect(self._resolution_selected)
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

    @Slot()
    def stop_preview(self) -> None:
        self._preview.stop()
        self._stop_button.setEnabled(False)
        self._photo_button.setEnabled(False)
        self._start_recording_button.setEnabled(False)
        self._stop_recording_button.setEnabled(False)
        self._resolution_combo.setEnabled(False)
        self._resolution_combo.clear()
        self._preview_label.setText("Select a detected camera to start preview")

    @Slot(object)
    def _show_frame(self, image: object) -> None:
        self._preview_label.setPixmap(QPixmap.fromImage(image))

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
        event.accept()


def main() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    app.exec()