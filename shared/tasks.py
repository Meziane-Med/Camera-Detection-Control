from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal, Slot


class _Worker(QObject):
    finished = Signal(object)

    def __init__(self, job: Callable[[], Any]) -> None:
        super().__init__()
        self._job = job

    @Slot()
    def run(self) -> None:
        try:
            result = self._job()
        except Exception as exc:  # reported to the UI instead of killing the thread
            result = exc
        self.finished.emit(result)


class BackgroundTask(QObject):
    """Run one blocking call at a time off the UI thread.

    ``finished`` is delivered on the UI thread with the call's return value,
    or with the raised exception so the page can show it.
    """

    finished = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        # Held so Python does not collect the parentless worker mid-run.
        self._worker: _Worker | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None

    def start(self, job: Callable[[], Any]) -> bool:
        if self._thread is not None:
            return False
        thread = QThread(self)
        worker = _Worker(job)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._deliver)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._release)
        self._thread, self._worker = thread, worker
        thread.start()
        return True

    def wait(self) -> None:
        """Block until the current call ends; used when the window closes."""

        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._release()

    @Slot(object)
    def _deliver(self, result: object) -> None:
        self.finished.emit(result)

    @Slot()
    def _release(self) -> None:
        thread, self._thread, self._worker = self._thread, None, None
        if thread is not None:
            thread.deleteLater()
