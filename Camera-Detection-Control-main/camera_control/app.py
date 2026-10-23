from PySide6.QtCore import QObject, QSignalBlocker, QThread, Qt, Signal, Slot
from PySide6.QtGui import QImage, QMouseEvent, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .discovery import CameraDiscovery
from .models import DiscoveryReport, ResolutionInfo
from .preview import PreviewController


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

        layout = QVBoxLayout()
        layout.addWidget(self._refresh_button)
        layout.addWidget(self._camera_combo)
        layout.addWidget(self._fps_cap_combo)
        zoom_layout = QHBoxLayout()
        zoom_layout.addWidget(self._zoom_label)
        zoom_layout.addWidget(self._zoom_slider, 1)
        zoom_layout.addWidget(self._zoom_value_label)
        layout.addLayout(zoom_layout)
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
        event.accept()


def main() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    app.exec()