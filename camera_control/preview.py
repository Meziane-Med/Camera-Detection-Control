from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from threading import Event, Lock, Thread, current_thread

import cv2
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from .models import ResolutionInfo

CaptureFactory = Callable[[int], object]
WriterFactory = Callable[[str, int, float, tuple[int, int]], object]
ImageWriter = Callable[[str, object], bool]

# Used only when Windows capability data cannot be matched to the OpenCV stream.
DEFAULT_RESOLUTION_FALLBACK_CANDIDATES = ((320, 240), (640, 480), (1280, 720), (1920, 1080))


class PreviewController(QObject):
    """Owns the capture for the currently selected camera only."""

    frame_ready = Signal(QImage)
    status_changed = Signal(str)
    error = Signal(str)
    stopped = Signal()
    photo_saved = Signal(str)
    recording_started = Signal(str)
    recording_saved = Signal(str)
    recording_state_changed = Signal(bool)
    resolutions_ready = Signal(object)
    resolution_changed = Signal(object)

    def __init__(
        self,
        capture_factory: CaptureFactory | None = None,
        writer_factory: WriterFactory | None = None,
        image_writer: ImageWriter | None = None,
        output_root: Path | None = None,
        resolution_candidates: tuple[tuple[int, int], ...] = DEFAULT_RESOLUTION_FALLBACK_CANDIDATES,
    ) -> None:
        super().__init__()
        self._capture_factory = capture_factory or cv2.VideoCapture
        self._lock = Lock()
        self._capture = None
        self._thread: Thread | None = None
        self._stop_event = Event()
        self._selected_index: int | None = None
        self._latest_frame = None
        self._writer_factory = writer_factory or self._create_writer
        self._image_writer = image_writer or cv2.imwrite
        self._output_root = output_root or Path.cwd()
        self._writer = None
        self._recording_path: Path | None = None
        self._resolution_candidates = resolution_candidates
        self._current_resolution: ResolutionInfo | None = None

    @property
    def selected_index(self) -> int | None:
        return self._selected_index

    @property
    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._writer is not None

    @property
    def current_resolution(self) -> ResolutionInfo | None:
        with self._lock:
            return self._current_resolution

    def start(self, index: int) -> None:
        self.stop()
        with self._lock:
            self._latest_frame = None
            self._current_resolution = None
        self._selected_index = index
        self._stop_event = Event()
        self._thread = Thread(target=self._run, args=(index, self._stop_event,), daemon=True)
        self._thread.start()
        self.status_changed.emit(f"Starting preview for camera index {index}...")

    def stop(self) -> None:
        self.stop_recording()
        self._stop_event.set()
        with self._lock:
            capture = self._capture
            if capture is not None:
                try:
                    capture.release()
                except Exception as exc:
                    self.error.emit(f"Could not release the camera: {exc}")

        thread = self._thread
        if thread is not None and thread is not current_thread():
            thread.join()
        self._thread = None
        self._selected_index = None

    def take_photo(self) -> None:
        with self._lock:
            frame = None if self._latest_frame is None else self._latest_frame.copy()
            index = self._selected_index
        if not self.is_running or frame is None or index is None:
            self.error.emit("Take Photo requires an active preview frame.")
            return

        output_dir = self._output_root / "captures"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            path = output_dir / f"camera_{index}_{self._timestamp()}.jpg"
            if not self._image_writer(str(path), frame):
                raise RuntimeError("the image writer rejected the frame")
        except Exception as exc:
            self.error.emit(f"Could not save photo: {exc}")
            return
        self.photo_saved.emit(str(path))

    def start_recording(self) -> None:
        with self._lock:
            frame = None if self._latest_frame is None else self._latest_frame.copy()
            index = self._selected_index
            capture = self._capture
            already_recording = self._writer is not None
        if already_recording:
            self.error.emit("A recording is already in progress.")
            return
        if not self.is_running or frame is None or index is None or capture is None:
            self.error.emit("Start Recording requires an active preview frame.")
            return

        try:
            height, width = frame.shape[:2]
            fps = self._capture_fps(capture)
            output_dir = self._output_root / "recordings"
            output_dir.mkdir(parents=True, exist_ok=True)
            path = output_dir / f"camera_{index}_{self._timestamp()}.mp4"
            writer = self._writer_factory(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
            if not writer.isOpened():
                writer.release()
                raise RuntimeError("the video writer could not be opened")
        except Exception as exc:
            self.error.emit(f"Could not start recording: {exc}")
            return

        with self._lock:
            self._writer = writer
            self._recording_path = path
        self.recording_state_changed.emit(True)
        self.recording_started.emit(str(path))

    def stop_recording(self) -> None:
        with self._lock:
            writer = self._writer
            path = self._recording_path
            self._writer = None
            self._recording_path = None
            if writer is None:
                return
            try:
                writer.release()
            except Exception as exc:
                release_error = f"Could not finalize recording: {exc}"
                saved_path = None
            else:
                release_error = None
                saved_path = None if path is None else str(path)
        if release_error is not None:
            self.error.emit(release_error)
        elif saved_path is not None:
            self.recording_saved.emit(saved_path)
        self.recording_state_changed.emit(False)

    def set_resolution(self, width: int, height: int) -> bool:
        requested = (int(width), int(height))
        error_message = None
        with self._lock:
            if self._writer is not None:
                error_message = "Stop recording before changing resolution."
                verified = None
            else:
                capture = self._capture
                previous = self._current_resolution
                if capture is None or previous is None or not self.is_running:
                    error_message = "Resolution requires an active preview."
                    verified = None
                elif requested == (previous.width, previous.height):
                    return True
                else:
                    verified = self._set_and_verify_resolution_locked(capture, requested, previous)
                    if verified is None:
                        error_message = f"Camera did not accept resolution {width} x {height}; restored {previous.display_name}."
                    else:
                        self._current_resolution = verified
        if error_message is not None:
            self.error.emit(error_message)
            return False
        if verified is None:
            return False
        self.resolution_changed.emit(verified)
        self.status_changed.emit(f"Resolution set to {verified.display_name}.")
        return True

    def _run(self, index: int, stop_event: Event) -> None:
        capture = None
        try:
            capture = self._capture_factory(index)
            with self._lock:
                self._capture = capture
            if not capture.isOpened():
                self.error.emit(f"Camera index {index} is unavailable or busy.")
                return

            self.status_changed.emit(f"Previewing camera index {index}.")
            with self._lock:
                returned, frame = capture.read()
                if not returned:
                    self.error.emit(f"Camera index {index} did not provide an initial frame.")
                    return
                current = ResolutionInfo(frame.shape[1], frame.shape[0])
                self._latest_frame = frame.copy()
                self._current_resolution = current
                verified = self._probe_resolutions_locked(capture, current)
            self.resolutions_ready.emit(tuple(verified))
            while not stop_event.is_set():
                with self._lock:
                    returned, frame = capture.read()
                if not returned:
                    if not stop_event.is_set():
                        self.error.emit(f"Camera index {index} stopped returning frames.")
                    break
                with self._lock:
                    self._latest_frame = frame.copy()
                    writer = self._writer
                    write_error = None
                    if writer is not None:
                        try:
                            writer.write(frame)
                        except Exception as exc:
                            write_error = f"Could not write recording: {exc}"
                if write_error is not None:
                    self._stop_recording_after_error(write_error)
                self.frame_ready.emit(self._to_qimage(frame))
        except Exception as exc:
            self.error.emit(f"Could not start camera index {index}: {exc}")
        finally:
            self.stop_recording()
            if capture is not None:
                try:
                    capture.release()
                except Exception as exc:
                    self.error.emit(f"Could not release camera index {index}: {exc}")
            with self._lock:
                if self._capture is capture:
                    self._capture = None
            self.stopped.emit()

    def _probe_resolutions_locked(self, capture: object, current: ResolutionInfo) -> list[ResolutionInfo]:
        verified: list[ResolutionInfo] = [current]
        for candidate in self._resolution_candidates:
            requested = (int(candidate[0]), int(candidate[1]))
            if requested == (current.width, current.height):
                continue
            result = self._set_and_verify_resolution_locked(capture, requested, current)
            if result is not None and result not in verified:
                verified.append(result)
        restored = self._set_and_verify_resolution_locked(
            capture,
            (current.width, current.height),
            current,
        )
        if restored is None:
            self.error.emit(f"Could not restore initial resolution {current.display_name} after capability probing.")
        return verified

    def _set_and_verify_resolution_locked(
        self,
        capture: object,
        requested: tuple[int, int],
        fallback: ResolutionInfo,
    ) -> ResolutionInfo | None:
        try:
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, requested[0])
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, requested[1])
            returned, frame = capture.read()
            if returned and frame.shape[1] == requested[0] and frame.shape[0] == requested[1]:
                self._latest_frame = frame.copy()
                return ResolutionInfo(*requested)
        except Exception:
            pass
        self._restore_resolution_locked(capture, fallback)
        return None

    def _restore_resolution_locked(self, capture: object, fallback: ResolutionInfo) -> ResolutionInfo | None:
        try:
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, fallback.width)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, fallback.height)
            returned, frame = capture.read()
            if returned and frame.shape[1] == fallback.width and frame.shape[0] == fallback.height:
                self._latest_frame = frame.copy()
                return fallback
        except Exception:
            pass
        return None

    def _stop_recording_after_error(self, message: str) -> None:
        self.error.emit(message)
        self.stop_recording()

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    @staticmethod
    def _create_writer(path: str, fourcc: int, fps: float, size: tuple[int, int]) -> object:
        return cv2.VideoWriter(path, fourcc, fps, size)

    @staticmethod
    def _capture_fps(capture: object) -> float:
        try:
            fps = float(capture.get(cv2.CAP_PROP_FPS))
        except (AttributeError, TypeError, ValueError):
            fps = 0.0
        return fps if 1.0 <= fps <= 60.0 else 20.0

    @staticmethod
    def _to_qimage(frame: object) -> QImage:
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width, channels = rgb_frame.shape
        return QImage(
            rgb_frame.data,
            width,
            height,
            channels * width,
            QImage.Format.Format_RGB888,
        ).copy()