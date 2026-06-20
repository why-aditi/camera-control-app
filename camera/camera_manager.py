from __future__ import annotations
import logging
import queue
from typing import Optional

import cv2
from PyQt6.QtCore import QThread

from utils.frame_queue import LatestFrameSlot, FrameQueue
from camera.capture_thread import CaptureThread, Command
from camera.camera_properties import CameraInfo

log = logging.getLogger("camera_app")

_STOP_TIMEOUT_MS = 10_000


class CameraManager:
    """Owns the QThread + CaptureThread pair. MainWindow calls this."""

    def __init__(self) -> None:
        self._thread: Optional[QThread]        = None
        self._worker: Optional[CaptureThread]  = None

    @property
    def worker(self) -> Optional[CaptureThread]:
        return self._worker

    def open(
        self,
        camera: CameraInfo,
        preview_slot: LatestFrameSlot,
        record_queue: FrameQueue,
        command_queue: "queue.SimpleQueue[Command]",
        width: int = 1280,
        height: int = 720,
        fps: int = 30,
    ) -> CaptureThread:
        self.close()
        worker = CaptureThread(
            preview_slot=preview_slot,
            record_queue=record_queue,
            command_queue=command_queue,
            device_index=camera.index,
            device_name=camera.name,
            backend=camera.backend,
            width=width,
            height=height,
            fps=fps,
        )
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        thread.start()
        self._worker = worker
        self._thread = thread
        log.debug("CaptureThread started for %s", camera.name)
        return worker

    def close(self) -> None:
        if self._worker:
            self._worker.request_stop()
        if self._thread:
            self._thread.quit()
            if not self._thread.wait(_STOP_TIMEOUT_MS):
                log.warning("CaptureThread did not stop in time; terminating")
                self._thread.terminate()
                self._thread.wait()
        self._worker = None
        self._thread = None

    def start_recording(self) -> None:
        if self._worker:
            self._worker.start_recording()

    def stop_recording(self) -> None:
        if self._worker:
            self._worker.stop_recording()
