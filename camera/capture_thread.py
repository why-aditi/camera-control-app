from __future__ import annotations
import logging
import queue
import time
import threading
from dataclasses import dataclass
from typing import Optional

import cv2
from PyQt6.QtCore import QObject, pyqtSignal as Signal

from utils.frame_queue import Frame, LatestFrameSlot, FrameQueue
from camera.camera_properties import ControlDescriptor, probe_controls

log = logging.getLogger("camera_app")

_BACKOFF = (0.5, 1.0, 2.0, 4.0, 8.0)

_SAVED_PROPS = (
    cv2.CAP_PROP_FRAME_WIDTH,
    cv2.CAP_PROP_FRAME_HEIGHT,
    cv2.CAP_PROP_FPS,
    cv2.CAP_PROP_BRIGHTNESS,
    cv2.CAP_PROP_CONTRAST,
    cv2.CAP_PROP_SATURATION,
    cv2.CAP_PROP_SHARPNESS,
    cv2.CAP_PROP_GAIN,
    cv2.CAP_PROP_EXPOSURE,
    cv2.CAP_PROP_FOCUS,
)


@dataclass
class ControlCommand:
    prop_id: int
    value: float


@dataclass
class ResolutionCommand:
    width: int
    height: int
    fps: int


Command = ControlCommand | ResolutionCommand


class CaptureThread(QObject):
    frame_ready    = Signal(object)       # Frame
    state_changed  = Signal(str)          # "LIVE" | "RECONNECTING" | "DISCONNECTED"
    controls_ready = Signal(list)         # list[ControlDescriptor]
    stats_update   = Signal(float, int)   # fps, dropped_total
    error          = Signal(str)

    def __init__(
        self,
        preview_slot: LatestFrameSlot,
        record_queue: FrameQueue,
        command_queue: "queue.SimpleQueue[Command]",
        device_index: int,
        device_name: str = "",
        backend: int = cv2.CAP_MSMF,
        width: int = 1280,
        height: int = 720,
        fps: int = 30,
    ) -> None:
        super().__init__()
        self._preview_slot  = preview_slot
        self._record_queue  = record_queue
        self._command_queue = command_queue
        self._device_index  = device_index
        self._device_name   = device_name
        self._backend       = backend
        self._width         = width
        self._height        = height
        self._fps           = fps

        self._stop_event    = threading.Event()
        self._recording     = threading.Event()
        self._reopen_event  = threading.Event()

        self._sequence      = 0
        self._frame_times:  list[float] = []
        self._last_stats_emit = 0.0
        self._res_rollback: Optional[tuple[int, int, int]] = None
        self._orig_props: dict[int, float] = {}

    def start_recording(self) -> None:
        self._recording.set()

    def stop_recording(self) -> None:
        self._recording.clear()

    def request_stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        backoff_idx = 0
        while not self._stop_event.is_set():
            cap = self._open_capture()
            if cap is None:
                delay = _BACKOFF[min(backoff_idx, len(_BACKOFF) - 1)]
                backoff_idx += 1
                self.state_changed.emit("RECONNECTING")
                log.warning("Open failed, retrying in %.1fs", delay)
                self._stop_event.wait(delay)
                continue

            backoff_idx = 0
            controls = probe_controls(cap)
            self.controls_ready.emit(controls)
            self.state_changed.emit("LIVE")
            log.info("Opened %s (%dx%d @ %dfps)", self._device_name, self._width, self._height, self._fps)

            result = self._read_loop(cap)
            self._restore_props(cap)
            cap.release()

            if result == "stopped":
                break
            if result == "reopen":
                continue
            # read_failure — backoff reconnect
            delay = _BACKOFF[min(backoff_idx, len(_BACKOFF) - 1)]
            backoff_idx += 1
            self.state_changed.emit("RECONNECTING")
            log.warning("Read failure, reconnecting in %.1fs", delay)
            self._stop_event.wait(delay)

        self.state_changed.emit("DISCONNECTED")

    def _open_capture(self) -> Optional[cv2.VideoCapture]:
        for backend in (self._backend, cv2.CAP_DSHOW):
            cap = cv2.VideoCapture(self._device_index, backend)
            if not cap.isOpened():
                cap.release()
                continue
            # Save originals before touching anything
            self._orig_props = {p: cap.get(p) for p in _SAVED_PROPS}
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self._width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
            cap.set(cv2.CAP_PROP_FPS,          self._fps)
            ok, _ = cap.read()
            if ok:
                return cap
            self._restore_props(cap)
            cap.release()
        return None

    def _restore_props(self, cap: cv2.VideoCapture) -> None:
        for prop_id, value in self._orig_props.items():
            if value != -1.0:
                cap.set(prop_id, value)
        log.debug("Camera props restored")

    def _read_loop(self, cap: cv2.VideoCapture) -> str:
        fail_streak = 0
        frame_count = 0

        while not self._stop_event.is_set() and not self._reopen_event.is_set():
            try:
                ok, bgr = cap.read()
            except cv2.error:
                continue

            if not ok:
                fail_streak += 1
                if fail_streak >= 5:
                    return "read_failure"
                continue
            fail_streak = 0

            ts = time.monotonic()
            self._sequence += 1
            frame = Frame.from_array(bgr, ts, self._sequence)

            self._preview_slot.put(frame)
            self.frame_ready.emit(frame)

            if self._recording.is_set():
                self._record_queue.put(frame)

            frame_count += 1
            self._frame_times.append(ts)
            if frame_count % 10 == 0:
                self._drain_commands(cap)
            if ts - self._last_stats_emit >= 1.0:
                self._emit_stats(ts)

        if self._stop_event.is_set():
            return "stopped"
        self._reopen_event.clear()
        return "reopen"

    def _drain_commands(self, cap: cv2.VideoCapture) -> None:
        coalesced: dict[int, float] = {}
        reopen_cmd: Optional[ResolutionCommand] = None
        while True:
            try:
                cmd = self._command_queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(cmd, ControlCommand):
                coalesced[cmd.prop_id] = cmd.value
            elif isinstance(cmd, ResolutionCommand):
                reopen_cmd = cmd

        for prop_id, value in coalesced.items():
            cap.set(prop_id, value)

        if reopen_cmd is not None:
            self._res_rollback = (self._width, self._height, self._fps)
            self._width, self._height, self._fps = reopen_cmd.width, reopen_cmd.height, reopen_cmd.fps
            self._reopen_event.set()

    def _emit_stats(self, now: float) -> None:
        cutoff = now - 1.0
        self._frame_times = [t for t in self._frame_times if t > cutoff]
        self.stats_update.emit(float(len(self._frame_times)), self._record_queue.dropped_count())
        self._last_stats_emit = now
