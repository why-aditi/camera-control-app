from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Optional

import cv2

log = logging.getLogger("camera_app")


@dataclass(slots=True)
class CameraInfo:
    index: int
    name: str
    backend: int
    path: Optional[str] = None


@dataclass(slots=True)
class ControlDescriptor:
    prop_id: int
    name: str
    min_val: float
    max_val: float
    current: float
    step: float = 1.0


def enumerate_cameras() -> list[CameraInfo]:
    try:
        return _enumerate_via_library()
    except Exception:
        log.debug("cv2_enumerate_cameras unavailable, falling back to probe")
        return _enumerate_via_probe()


def _enumerate_via_library() -> list[CameraInfo]:
    from cv2_enumerate_cameras import enumerate_cameras as _enum
    results = []
    for cam in _enum(cv2.CAP_MSMF):
        results.append(CameraInfo(
            index=cam.index,
            name=cam.name or f"Camera {cam.index}",
            backend=cv2.CAP_MSMF,
            path=getattr(cam, "path", None),
        ))
    return results


def _enumerate_via_probe() -> list[CameraInfo]:
    results = []
    for idx in range(10):
        for backend in (cv2.CAP_MSMF, cv2.CAP_DSHOW):
            cap = cv2.VideoCapture(idx, backend)
            if not cap.isOpened():
                cap.release()
                continue
            ok, _ = cap.read()
            cap.release()
            if ok:
                results.append(CameraInfo(
                    index=idx,
                    name=f"Camera {idx}",
                    backend=backend,
                ))
                break
    return results


_CONTROL_DEFS = [
    (cv2.CAP_PROP_BRIGHTNESS,  "Brightness",  -64.0, 64.0),
    (cv2.CAP_PROP_CONTRAST,    "Contrast",      0.0, 95.0),
    (cv2.CAP_PROP_SATURATION,  "Saturation",    0.0, 100.0),
    (cv2.CAP_PROP_SHARPNESS,   "Sharpness",     0.0, 100.0),
    (cv2.CAP_PROP_GAIN,        "Gain",          0.0, 100.0),
    (cv2.CAP_PROP_EXPOSURE,    "Exposure",    -13.0,  0.0),
    (cv2.CAP_PROP_FOCUS,       "Focus",         0.0, 255.0),
]


def probe_controls(cap: cv2.VideoCapture) -> list[ControlDescriptor]:
    result = []
    for prop_id, name, lo, hi in _CONTROL_DEFS:
        val = cap.get(prop_id)
        if val != -1.0:
            result.append(ControlDescriptor(
                prop_id=prop_id, name=name,
                min_val=lo, max_val=hi, current=val,
            ))
    return result
