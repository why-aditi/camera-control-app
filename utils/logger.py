from __future__ import annotations
import logging
import sys
from pathlib import Path


def setup_logger(log_dir: str | Path = ".") -> logging.Logger:
    log = logging.getLogger("camera_app")
    if log.handlers:
        return log
    log.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    fh = logging.FileHandler(Path(log_dir) / "camera_app.log")
    fh.setFormatter(fmt)
    log.addHandler(sh)
    log.addHandler(fh)
    return log
