"""Windows MediaCapture adapter for device-ID-based camera preview."""

import asyncio
import threading
from typing import Any

import cv2
import numpy as np


class WindowsMediaCaptureAdapter:
    is_windows_native = True
    release_on_owner_thread = True

    def __init__(self, device_id: str) -> None:
        self._device_id = device_id
        self._owner_thread = threading.get_ident()
        self._loop = asyncio.new_event_loop()
        self._capture: Any = None
        self._reader: Any = None
        self._opened = False
        self._frame_size: tuple[int, int] | None = None
        self._last_frame_timestamp: float | None = None
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._initialize())
        except Exception:
            try:
                if self._capture is not None:
                    self._loop.run_until_complete(self._close_capture())
            finally:
                self._loop.close()
                asyncio.set_event_loop(None)
            raise

    async def _initialize(self) -> None:
        from winrt.windows.media.capture import (
            MediaCapture,
            MediaCaptureInitializationSettings,
            MediaCaptureMemoryPreference,
            StreamingCaptureMode,
        )
        from winrt.windows.media.capture.frames import (
            MediaFrameReaderStartStatus,
            MediaFrameSourceKind,
        )

        settings = MediaCaptureInitializationSettings()
        settings.video_device_id = self._device_id
        settings.streaming_capture_mode = StreamingCaptureMode.VIDEO
        settings.memory_preference = MediaCaptureMemoryPreference.CPU
        capture = MediaCapture()
        self._capture = capture
        try:
            await capture.initialize_with_settings_async(settings)
            source = next(
                (
                    frame_source
                    for frame_source in capture.frame_sources.values()
                    if frame_source.info.source_kind == MediaFrameSourceKind.COLOR
                ),
                None,
            )
            if source is None:
                raise RuntimeError("The selected camera has no color frame source.")
            self._reader = await capture.create_frame_reader_with_subtype_async(source, "Bgra8")
            start_status = await self._reader.start_async()
            if start_status != MediaFrameReaderStartStatus.SUCCESS:
                raise RuntimeError(f"Windows could not start the camera frame reader: {start_status}.")
        except Exception:
            await self._close_capture()
            raise
        self._opened = True

    def isOpened(self) -> bool:
        return self._opened

    def read(self) -> tuple[bool, np.ndarray | None]:
        if not self._opened or threading.get_ident() != self._owner_thread:
            return False, None
        frame = self._loop.run_until_complete(self._read_frame())
        if frame is None:
            return False, None
        self._frame_size = (frame.shape[1], frame.shape[0])
        return True, frame

    async def _read_frame(self) -> np.ndarray | None:
        for _ in range(100):
            frame = self._reader.try_acquire_latest_frame()
            if frame is not None:
                try:
                    timestamp = frame.system_relative_time
                    self._last_frame_timestamp = (
                        timestamp.total_seconds() if timestamp is not None else None
                    )
                    bitmap = frame.video_media_frame.software_bitmap
                    if bitmap is not None:
                        return await _software_bitmap_to_bgr(bitmap)
                finally:
                    frame.close()
            await asyncio.sleep(0.01)
        return None

    def get_last_frame_timestamp(self) -> float | None:
        return self._last_frame_timestamp

    def getBackendName(self) -> str:
        return "Windows MediaCapture"

    def get(self, property_id: int) -> float:
        if property_id == cv2.CAP_PROP_FRAME_WIDTH and self._frame_size is not None:
            return float(self._frame_size[0])
        if property_id == cv2.CAP_PROP_FRAME_HEIGHT and self._frame_size is not None:
            return float(self._frame_size[1])
        if property_id == cv2.CAP_PROP_FPS:
            return 30.0
        control, auto_property = self._control_for_property(property_id)
        if control is None:
            return 0.0
        if auto_property:
            result = control.try_get_auto()
            return float(result[-1]) if isinstance(result, tuple) and result[0] else 0.0
        result = control.try_get_value()
        return float(result[-1]) if isinstance(result, tuple) and result[0] else 0.0

    def set(self, property_id: int, value: float) -> bool:
        control, auto_property = self._control_for_property(property_id)
        if control is None:
            return False
        if auto_property:
            return bool(control.try_set_auto(bool(value)))
        return bool(control.try_set_value(float(value)))

    def _control_for_property(self, property_id: int) -> tuple[Any | None, bool]:
        controller = self._capture.video_device_controller
        if property_id == cv2.CAP_PROP_AUTOFOCUS:
            return controller.focus, True
        if property_id == cv2.CAP_PROP_FOCUS:
            return controller.focus, False
        if property_id == cv2.CAP_PROP_AUTO_WB:
            return controller.white_balance, True
        if property_id == cv2.CAP_PROP_WB_TEMPERATURE:
            return controller.white_balance, False
        return None, False

    def release(self) -> None:
        if threading.get_ident() != self._owner_thread:
            return
        self._opened = False
        try:
            self._loop.run_until_complete(self._close_capture())
        finally:
            self._loop.close()
            asyncio.set_event_loop(None)

    async def _close_capture(self) -> None:
        try:
            if self._reader is not None:
                try:
                    await self._reader.stop_async()
                finally:
                    self._reader.close()
                    self._reader = None
        finally:
            if self._capture is not None:
                try:
                    self._capture.close()
                finally:
                    self._capture = None


async def _software_bitmap_to_bgr(bitmap: Any) -> np.ndarray:
    from winrt.windows.graphics.imaging import (
        BitmapEncoder,
        BitmapPixelFormat,
        SoftwareBitmap,
    )
    from winrt.windows.storage.streams import DataReader, InMemoryRandomAccessStream

    converted_bitmap = None
    stream = InMemoryRandomAccessStream()
    reader = None
    try:
        if bitmap.bitmap_pixel_format != BitmapPixelFormat.BGRA8:
            converted_bitmap = SoftwareBitmap.convert(bitmap, BitmapPixelFormat.BGRA8)
            bitmap = converted_bitmap
        encoder = await BitmapEncoder.create_async(BitmapEncoder.jpeg_encoder_id, stream)
        encoder.set_software_bitmap(bitmap)
        await encoder.flush_async()
        stream.seek(0)
        reader = DataReader(stream.get_input_stream_at(0))
        await reader.load_async(stream.size)
        encoded_image = bytearray(stream.size)
        reader.read_bytes(encoded_image)
    finally:
        if reader is not None:
            reader.close()
        stream.close()
        if converted_bitmap is not None:
            converted_bitmap.close()

    image = cv2.imdecode(np.frombuffer(encoded_image, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("Windows MediaCapture returned a frame that could not be decoded.")
    return image
