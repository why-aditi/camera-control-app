from __future__ import annotations
import datetime
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import cv2
from PyQt6.QtCore import pyqtSignal as Signal

from utils.frame_queue import Frame, LatestFrameSlot

log = logging.getLogger("camera_app")


def _write_frame(frame: Frame, output_dir: Path, fmt: str) -> Optional[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = output_dir / f"snapshot_{ts[:23]}.{fmt}"
    params = [cv2.IMWRITE_JPEG_QUALITY, 95] if fmt == "jpg" else []
    ok = cv2.imwrite(str(path), frame.data, params)
    if ok:
        log.info("Snapshot saved: %s", path)
    else:
        log.error("Snapshot write failed: %s", path)
    return str(path) if ok else None


class SnapshotManager:
    def __init__(self) -> None:
        self._pool = ThreadPoolExecutor(max_workers=1)

    def capture(
        self,
        preview_slot: LatestFrameSlot,
        done_signal: "Signal",
        output_dir: Path | str = ".",
        fmt: str = "png",
    ) -> bool:
        frame = preview_slot.peek()
        if frame is None:
            return False
        out = Path(output_dir)
        self._pool.submit(_write_frame, frame, out, fmt).add_done_callback(
            lambda f: done_signal.emit(f.result() or "")
        )
        return True

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False)
