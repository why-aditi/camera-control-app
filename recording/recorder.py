from __future__ import annotations
import datetime
import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QThread

from utils.frame_queue import FrameQueue
from recording.recorder_thread import RecorderThread

log = logging.getLogger("camera_app")

_STOP_TIMEOUT_MS = 10_000


class Recorder:
    """Owns RecorderThread + QThread. MainWindow calls start/stop."""

    def __init__(self) -> None:
        self._thread: Optional[QThread]         = None
        self._worker: Optional[RecorderThread]  = None

    @property
    def worker(self) -> Optional[RecorderThread]:
        return self._worker

    def start(self, record_queue: FrameQueue, output_dir: Path | str = ".", fps: int = 30, fmt: str = "MP4") -> RecorderThread:
        self.stop()
        ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        ext  = "avi" if fmt == "AVI" else "mp4"
        path = str(Path(output_dir) / f"recording_{ts}.{ext}")

        worker = RecorderThread(record_queue, path, fps, fmt)
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        thread.start()
        self._worker = worker
        self._thread = thread
        log.debug("RecorderThread started")
        return worker

    def stop(self) -> None:
        if self._worker:
            self._worker.request_stop()
        if self._thread:
            self._thread.quit()
            if not self._thread.wait(_STOP_TIMEOUT_MS):
                log.warning("RecorderThread did not stop in time; terminating")
                self._thread.terminate()
                self._thread.wait()
        self._worker = None
        self._thread = None
