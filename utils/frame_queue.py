from __future__ import annotations
import queue
import threading
from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass(slots=True)
class Frame:
    data: np.ndarray
    timestamp: float
    sequence: int

    @classmethod
    def from_array(cls, bgr: np.ndarray, ts: float, seq: int) -> "Frame":
        return cls(data=bgr, timestamp=ts, sequence=seq)

    @property
    def width(self) -> int:
        return self.data.shape[1]

    @property
    def height(self) -> int:
        return self.data.shape[0]


class LatestFrameSlot:
    """1-slot drop-old buffer. put() replaces; peek() is non-consuming."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame: Optional[Frame] = None

    def put(self, frame: Frame) -> None:
        with self._lock:
            self._frame = frame

    def get(self) -> Optional[Frame]:
        with self._lock:
            f, self._frame = self._frame, None
            return f

    def peek(self) -> Optional[Frame]:
        with self._lock:
            return self._frame


class FrameQueue:
    """Bounded FIFO wrapping queue.Queue. Drops newest frame on overflow."""

    def __init__(self, maxsize: int = 256) -> None:
        self._q: queue.Queue[Frame] = queue.Queue(maxsize)
        self._dropped = 0

    def put(self, frame: Frame) -> None:
        try:
            self._q.put_nowait(frame)
        except queue.Full:
            self._dropped += 1

    def get(self, timeout: float = 0.1) -> Optional[Frame]:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def qsize(self) -> int:
        return self._q.qsize()

    def dropped_count(self) -> int:
        return self._dropped
