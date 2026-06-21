from __future__ import annotations
import datetime
import logging
import threading
import time
from pathlib import Path
from typing import Optional

import cv2
from PyQt6.QtCore import QObject, pyqtSignal as Signal

from utils.frame_queue import Frame, FrameQueue

log = logging.getLogger("camera_app")


class RecorderThread(QObject):
    recording_started = Signal(str)   # output path
    recording_stopped = Signal(str)   # output path
    frames_written    = Signal(int)
    error             = Signal(str)

    def __init__(self, record_queue: FrameQueue, output_path: str, fps: int = 30, fmt: str = "MP4") -> None:
        super().__init__()
        self._queue       = record_queue
        self._output_path = output_path
        self._fps         = fps
        self._fmt         = fmt
        self._stop        = threading.Event()

    def request_stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        writer: Optional[cv2.VideoWriter] = None
        fourcc = cv2.VideoWriter.fourcc(*("XVID" if self._fmt == "AVI" else "mp4v"))
        total  = 0
        last_emit = time.monotonic()
        path = self._output_path

        self.recording_started.emit(path)
        log.info("Recording started -> %s", path)

        try:
            while not self._stop.is_set():
                frame = self._queue.get(timeout=0.1)
                if frame is None:
                    continue
                if writer is None:
                    h, w = frame.data.shape[:2]
                    writer = cv2.VideoWriter(path, fourcc, self._fps, (w, h))
                    if not writer.isOpened():
                        self.error.emit(f"Cannot open VideoWriter: {path}")
                        log.error("VideoWriter failed to open: %s", path)
                        return
                writer.write(frame.data)
                total += 1
                now = time.monotonic()
                if now - last_emit >= 1.0:
                    self.frames_written.emit(total)
                    last_emit = now

            # Flush remaining frames
            while True:
                frame = self._queue.get(timeout=0.05)
                if frame is None:
                    break
                if writer:
                    writer.write(frame.data)
                    total += 1
        finally:
            if writer:
                writer.release()
            self.frames_written.emit(total)
            self.recording_stopped.emit(path)
            log.info("Recording stopped -> %s (%d frames)", path, total)
