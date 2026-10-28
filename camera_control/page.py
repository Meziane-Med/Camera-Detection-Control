from PySide6.QtCore import QSignalBlocker, Qt, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from shared.tasks import BackgroundTask
from shared.theme import repolish
from shared.widgets import button, card, label, page_header

from .discovery import CameraDiscovery
from .models import DiscoveryReport, ResolutionInfo
from .preview import PreviewController

_EMPTY_INFO = {"Resolution": "—", "FPS": "—", "Zoom": "1.00x"}
_IDLE_TEXT = "Select a camera to start the preview"


class CameraPage(QWidget):
    """Camera selection, live preview, capture and stream settings."""

    def __init__(
        self,
        discovery: CameraDiscovery | None = None,
        preview: PreviewController | None = None,
    ) -> None:
        super().__init__()
        self._discovery = discovery or CameraDiscovery()
        self._preview = preview or PreviewController()
        self._task = BackgroundTask(self)
        self._info = dict(_EMPTY_INFO)
        self._build_ui()
        self._connect_signals()
        self.refresh_cameras()

    # ---- layout -------------------------------------------------------

    def _build_ui(self) -> None:
        self._camera_combo = QComboBox()
        self._camera_combo.setMinimumWidth(200)
        self._camera_combo.setPlaceholderText("Select a camera")
        self._camera_combo.setEnabled(False)
        self._refresh_button = button("Refresh")

        self._preview_label = QLabel(_IDLE_TEXT)
        self._preview_label.setObjectName("preview")
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        preview_card = card(margin=10)
        preview_card.layout().addWidget(self._preview_label, 1)

        self._stop_button = button("Stop", enabled=False)
        self._photo_button = button("Take photo", "primary", enabled=False)
        self._record_button = button("Record", enabled=False)
        self._resolution_combo = QComboBox()
        self._resolution_combo.setEnabled(False)
        self._fps_combo = QComboBox()
        for fps in self._preview.fps_candidates:
            self._fps_combo.addItem(f"{fps:g} FPS", fps)
        self._zoom_out_button = button("−", "icon")
        self._zoom_in_button = button("+", "icon")
        self._reset_zoom_button = button("1x", "icon")
        self._zoom_out_button.setToolTip("Zoom out")
        self._zoom_in_button.setToolTip("Zoom in")
        self._reset_zoom_button.setToolTip("Reset zoom")
        # Enabled together while a preview is running.
        self._session_controls = (
            self._stop_button,
            self._photo_button,
            self._record_button,
            self._fps_combo,
            self._zoom_out_button,
            self._zoom_in_button,
            self._reset_zoom_button,
        )

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        for widget in (self._photo_button, self._record_button, self._stop_button):
            toolbar.addWidget(widget)
        toolbar.addStretch()
        toolbar.addWidget(label("Resolution", "fieldLabel"))
        toolbar.addWidget(self._resolution_combo)
        toolbar.addSpacing(8)
        toolbar.addWidget(label("FPS", "fieldLabel"))
        toolbar.addWidget(self._fps_combo)
        toolbar.addSpacing(8)
        toolbar.addWidget(label("Zoom", "fieldLabel"))
        for widget in (self._zoom_out_button, self._zoom_in_button, self._reset_zoom_button):
            toolbar.addWidget(widget)
        toolbar_card = card(toolbar, margin=10)

        self._info_label = label("", "muted")
        self._status_label = label("Ready to detect cameras.", "status", wrap=True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(14)
        layout.addLayout(
            page_header(
                "Camera",
                "Preview a camera, take photos and record video.",
                self._camera_combo,
                self._refresh_button,
            )
        )
        layout.addWidget(preview_card, 1)
        layout.addWidget(toolbar_card)
        layout.addWidget(self._info_label)
        layout.addWidget(self._status_label)
        self._set_session_enabled(False)

    def _connect_signals(self) -> None:
        preview = self._preview
        self._task.finished.connect(self._on_discovery_result)
        self._refresh_button.clicked.connect(self.refresh_cameras)
        self._camera_combo.currentIndexChanged.connect(self._camera_selected)
        self._stop_button.clicked.connect(self.stop_preview)
        self._photo_button.clicked.connect(preview.take_photo)
        self._record_button.clicked.connect(self._toggle_recording)
        self._resolution_combo.currentIndexChanged.connect(self._resolution_selected)
        self._fps_combo.currentIndexChanged.connect(self._fps_selected)
        self._zoom_in_button.clicked.connect(preview.zoom_in)
        self._zoom_out_button.clicked.connect(preview.zoom_out)
        self._reset_zoom_button.clicked.connect(preview.reset_zoom)
        preview.frame_ready.connect(self._show_frame)
        preview.status_changed.connect(self._set_status)
        preview.error.connect(lambda message: self._set_status(f"Error: {message}"))
        preview.stopped.connect(self._preview_stopped)
        preview.photo_saved.connect(lambda path: self._set_status(f"Photo saved: {path}"))
        preview.recording_started.connect(lambda path: self._set_status(f"Recording: {path}"))
        preview.recording_saved.connect(lambda path: self._set_status(f"Recording saved: {path}"))
        preview.recording_state_changed.connect(self._recording_state_changed)
        preview.resolutions_ready.connect(self._resolutions_ready)
        preview.resolution_changed.connect(self._resolution_changed)
        preview.fps_changed.connect(self._fps_changed)
        preview.measured_fps_changed.connect(lambda value: self._update_info(FPS=f"{value:.1f}"))
        preview.zoom_changed.connect(lambda value: self._update_info(Zoom=f"{value:.2f}x"))

    # ---- discovery ----------------------------------------------------

    @Slot()
    def refresh_cameras(self) -> None:
        self.stop_preview()
        if self._task.is_running:
            return
        self._refresh_button.setEnabled(False)
        self._camera_combo.setEnabled(False)
        self._camera_combo.clear()
        self._set_status("Detecting cameras…")
        self._task.start(self._discovery.discover)

    @Slot(object)
    def _on_discovery_result(self, result: object) -> None:
        if isinstance(result, Exception):
            result = DiscoveryReport(cameras=(), errors=(f"Camera discovery failed: {result}",))
        self._discovery_finished(result)

    def _discovery_finished(self, report: DiscoveryReport) -> None:
        with QSignalBlocker(self._camera_combo):
            for camera in report.cameras:
                self._camera_combo.addItem(camera.display_name, camera.index)
            self._camera_combo.setCurrentIndex(-1)
        self._camera_combo.setEnabled(bool(report.cameras))
        self._refresh_button.setEnabled(True)
        if report.cameras:
            parts = [f"Detected {len(report.cameras)} camera(s). Select one to start the preview."]
        else:
            parts = ["No camera found. Check the connection and Windows camera privacy settings."]
        if report.errors:
            parts.append("Some probe errors occurred.")
        self._set_status(" ".join(parts))

    # ---- preview session ----------------------------------------------

    @Slot(int)
    def _camera_selected(self, combo_index: int) -> None:
        camera_index = self._camera_combo.itemData(combo_index) if combo_index >= 0 else None
        if camera_index is not None:
            self._preview.start(int(camera_index))
            self._set_session_enabled(True)

    @Slot()
    def stop_preview(self) -> None:
        self._preview.stop()
        self._reset_session()

    @Slot()
    def _preview_stopped(self) -> None:
        if self._preview.selected_index is None:
            self._reset_session()

    def _reset_session(self) -> None:
        self._set_session_enabled(False)
        self._resolution_combo.clear()
        self._resolution_combo.setEnabled(False)
        self._preview_label.clear()
        self._preview_label.setText(_IDLE_TEXT)
        self._recording_state_changed(False)
        self._info = dict(_EMPTY_INFO)
        self._update_info()

    def _set_session_enabled(self, enabled: bool) -> None:
        for control in self._session_controls:
            control.setEnabled(enabled)

    @Slot(object)
    def _show_frame(self, image: object) -> None:
        self._preview_label.setPixmap(
            QPixmap.fromImage(image).scaled(
                self._preview_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    @Slot()
    def _toggle_recording(self) -> None:
        if self._preview.is_recording:
            self._preview.stop_recording()
        else:
            self._preview.start_recording()

    @Slot(bool)
    def _recording_state_changed(self, recording: bool) -> None:
        self._record_button.setText("Stop recording" if recording else "Record")
        self._record_button.setProperty("kind", "danger" if recording else "secondary")
        repolish(self._record_button)
        self._resolution_combo.setEnabled(
            self._preview.is_running and not recording and self._resolution_combo.count() > 0
        )

    # ---- stream settings ----------------------------------------------

    @Slot(object)
    def _resolutions_ready(self, resolutions: object) -> None:
        current = self._preview.current_resolution
        with QSignalBlocker(self._resolution_combo):
            self._resolution_combo.clear()
            for resolution in resolutions:
                self._resolution_combo.addItem(resolution.display_name, (resolution.width, resolution.height))
            if current is not None:
                self._resolution_combo.setCurrentIndex(max(self._resolution_index(current.width, current.height), 0))
        self._resolution_combo.setEnabled(self._preview.is_running and not self._preview.is_recording)
        if current is not None:
            self._update_info(Resolution=current.display_name)

    @Slot(int)
    def _resolution_selected(self, combo_index: int) -> None:
        value = self._resolution_combo.itemData(combo_index) if combo_index >= 0 else None
        if value is not None:
            self._preview.set_resolution(*value)

    @Slot(object)
    def _resolution_changed(self, resolution: ResolutionInfo) -> None:
        index = self._resolution_index(resolution.width, resolution.height)
        if index >= 0:
            with QSignalBlocker(self._resolution_combo):
                self._resolution_combo.setCurrentIndex(index)
        self._update_info(Resolution=resolution.display_name)

    @Slot(int)
    def _fps_selected(self, combo_index: int) -> None:
        value = self._fps_combo.itemData(combo_index) if combo_index >= 0 else None
        if value is not None:
            self._preview.set_fps(float(value))

    @Slot(object)
    def _fps_changed(self, values: object) -> None:
        requested, actual = values
        # ``requested`` is None when the camera reports its FPS before any request.
        if actual is not None:
            suffix = f" (requested {requested:g})" if requested is not None else ""
            self._update_info(FPS=f"{actual:g}{suffix}")

    def _resolution_index(self, width: int, height: int) -> int:
        for index in range(self._resolution_combo.count()):
            value = self._resolution_combo.itemData(index)
            if value is not None and tuple(value) == (width, height):
                return index
        return -1

    # ---- feedback -----------------------------------------------------

    def _update_info(self, **values: str) -> None:
        self._info.update(values)
        self._info_label.setText("   ·   ".join(f"{key} {value}" for key, value in self._info.items()))

    @Slot(str)
    def _set_status(self, message: str) -> None:
        self._status_label.setText(message)

    def shutdown(self) -> None:
        """Release the camera and finish discovery before the window closes."""

        self.stop_preview()
        self._task.wait()
