from __future__ import annotations
import queue
import sys
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QComboBox, QStatusBar,
    QFileDialog, QMessageBox, QSplitter, QGroupBox, QScrollArea,
)
from PyQt6.QtCore import Qt, QThread, QObject, pyqtSignal as Signal, pyqtSlot as Slot
from PyQt6.QtGui import QImage, QPainter

from utils.frame_queue import Frame, LatestFrameSlot, FrameQueue
from camera.camera_properties import CameraInfo, ControlDescriptor, enumerate_cameras
from camera.camera_manager import CameraManager
from camera.capture_thread import Command, ResolutionCommand
from recording.recorder import Recorder
from snapshots.snapshot_manager import SnapshotManager
from ui.controls_panel import ControlsPanel

_RESOLUTIONS = [
    ("1920 × 1080 (1080p)", 1920, 1080),
    ("1280 × 720 (720p)",   1280,  720),
    ("960 × 540",            960,  540),
    ("640 × 480 (VGA)",      640,  480),
]
_FPS_OPTIONS = [60, 30, 24, 15]
_RECORD_QUEUE_SIZE = 256


class _VideoView(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._image: Optional[QImage] = None
        self.setMinimumSize(640, 360)

    def update_frame(self, frame: Frame) -> None:
        h, w = frame.data.shape[:2]
        rgb = cv2.cvtColor(cv2.flip(frame.data, 1), cv2.COLOR_BGR2RGB)
        self._image = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format.Format_RGB888).copy()
        self.update()

    def paintEvent(self, _) -> None:
        painter = QPainter(self)
        if self._image:
            scaled = self._image.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = (self.width()  - scaled.width())  // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawImage(x, y, scaled)
        else:
            painter.fillRect(self.rect(), Qt.GlobalColor.black)


class _EnumWorker(QObject):
    finished = Signal(list)

    @Slot()
    def run(self) -> None:
        self.finished.emit(enumerate_cameras())


class MainWindow(QMainWindow):
    _snapshot_done = Signal(str)

    def __init__(self, output_dir: str = ".") -> None:
        super().__init__()
        self.setWindowTitle("Camera Control")
        self.resize(1280, 800)
        self._output_dir = Path(output_dir)

        self._preview_slot   = LatestFrameSlot()
        self._record_queue   = FrameQueue(_RECORD_QUEUE_SIZE)
        self._command_queue: queue.SimpleQueue[Command] = queue.SimpleQueue()

        self._cameras: list[CameraInfo] = []
        self._camera_mgr  = CameraManager()
        self._recorder    = Recorder()
        self._snap_mgr    = SnapshotManager()
        self._recording   = False

        self._snapshot_done.connect(self._on_snapshot_done)
        self._build_ui()
        self._enumerate_cameras()

    # ---------------------------------------------------------------- UI ---

    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)

        # Left: video
        left = QWidget()
        lv   = QVBoxLayout(left)
        self._video_view = _VideoView()
        lv.addWidget(self._video_view, stretch=1)

        # Stats bar
        stats = QHBoxLayout()
        self._lbl_fps     = QLabel("FPS: —")
        self._lbl_dropped = QLabel("Dropped: 0")
        self._lbl_state   = QLabel("—")
        for w in (self._lbl_fps, self._lbl_dropped, self._lbl_state):
            stats.addWidget(w)
        lv.addLayout(stats)

        # Right: controls sidebar
        right  = QWidget()
        rv     = QVBoxLayout(right)
        right.setMaximumWidth(280)

        # Camera selector
        cam_box = QGroupBox("Camera")
        cbl     = QVBoxLayout(cam_box)
        self._cam_combo = QComboBox()
        self._cam_combo.setEnabled(False)
        self._btn_open  = QPushButton("Open Camera")
        self._btn_open.setEnabled(False)
        self._btn_open.clicked.connect(self._on_open_camera)
        self._btn_close = QPushButton("Close Camera")
        self._btn_close.setEnabled(False)
        self._btn_close.clicked.connect(self._on_close_camera)
        cbl.addWidget(self._cam_combo)
        cbl.addWidget(self._btn_open)
        cbl.addWidget(self._btn_close)
        rv.addWidget(cam_box)

        # Resolution / FPS
        res_box = QGroupBox("Resolution / FPS")
        rbl     = QVBoxLayout(res_box)
        self._res_combo = QComboBox()
        for label, *_ in _RESOLUTIONS:
            self._res_combo.addItem(label)
        self._res_combo.setCurrentIndex(1)  # default 720p
        self._fps_combo = QComboBox()
        for f in _FPS_OPTIONS:
            self._fps_combo.addItem(f"{f} fps", f)
        self._fps_combo.setCurrentIndex(1)  # default 30
        btn_apply = QPushButton("Apply")
        btn_apply.clicked.connect(self._on_apply_resolution)
        rbl.addWidget(self._res_combo)
        rbl.addWidget(self._fps_combo)
        rbl.addWidget(btn_apply)
        rv.addWidget(res_box)

        # Actions
        act_box = QGroupBox("Actions")
        abl     = QVBoxLayout(act_box)
        self._btn_record   = QPushButton("⏺  Start Recording")
        self._btn_snapshot = QPushButton("📷  Snapshot")
        self._btn_output   = QPushButton("Output Folder…")
        self._btn_record.setEnabled(False)
        self._btn_snapshot.setEnabled(False)
        self._btn_record.clicked.connect(self._on_toggle_record)
        self._btn_snapshot.clicked.connect(self._on_snapshot)
        self._btn_output.clicked.connect(self._on_choose_output)
        for b in (self._btn_record, self._btn_snapshot, self._btn_output):
            abl.addWidget(b)
        rv.addWidget(act_box)

        # Camera controls (scrollable)
        ctrl_box    = QGroupBox("Camera Controls")
        ctrl_layout = QVBoxLayout(ctrl_box)
        scroll      = QScrollArea()
        scroll.setWidgetResizable(True)
        self._controls_panel = ControlsPanel(self._command_queue)
        scroll.setWidget(self._controls_panel)
        ctrl_layout.addWidget(scroll)
        rv.addWidget(ctrl_box, stretch=1)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)

        self.setStatusBar(QStatusBar())

    # --------------------------------------------------------- Enumerate ---

    def _enumerate_cameras(self) -> None:
        self._enum_thread = QThread(self)
        self._enum_worker = _EnumWorker()
        self._enum_worker.moveToThread(self._enum_thread)
        self._enum_thread.started.connect(self._enum_worker.run)
        self._enum_worker.finished.connect(self._on_cameras_enumerated)
        self._enum_thread.start()
        self.statusBar().showMessage("Enumerating cameras…")

    @Slot(list)
    def _on_cameras_enumerated(self, cameras: list[CameraInfo]) -> None:
        self._enum_thread.quit()
        self._cameras = cameras
        self._cam_combo.clear()
        if not cameras:
            self.statusBar().showMessage("No cameras found")
            return
        for c in cameras:
            self._cam_combo.addItem(c.name, c)
        self._cam_combo.setEnabled(True)
        self._btn_open.setEnabled(True)
        self.statusBar().showMessage(f"{len(cameras)} camera(s) found")

    # -------------------------------------------------------- Open camera --

    @Slot()
    def _on_open_camera(self) -> None:
        cam: CameraInfo = self._cam_combo.currentData()
        if cam is None:
            return
        _, w, h = _RESOLUTIONS[self._res_combo.currentIndex()]
        fps = self._fps_combo.currentData()

        worker = self._camera_mgr.open(
            camera=cam,
            preview_slot=self._preview_slot,
            record_queue=self._record_queue,
            command_queue=self._command_queue,
            width=w, height=h, fps=fps,
        )
        worker.frame_ready.connect(self._on_frame)
        worker.state_changed.connect(self._on_state_changed)
        worker.controls_ready.connect(self._on_controls_ready)
        worker.stats_update.connect(self._on_stats_update)
        worker.error.connect(self._on_capture_error)

        self._btn_close.setEnabled(True)
        self._btn_record.setEnabled(True)
        self._btn_snapshot.setEnabled(True)

    @Slot()
    def _on_close_camera(self) -> None:
        self._camera_mgr.close()
        self._video_view._image = None
        self._video_view.update()
        self._btn_close.setEnabled(False)
        self._btn_record.setEnabled(False)
        self._btn_snapshot.setEnabled(False)
        self._lbl_state.setText("—")

    # ------------------------------------------------------ Frame / state --

    @Slot(object)
    def _on_frame(self, frame: Frame) -> None:
        self._video_view.update_frame(frame)

    @Slot(str)
    def _on_state_changed(self, state: str) -> None:
        self._lbl_state.setText(state)

    @Slot(list)
    def _on_controls_ready(self, controls: list[ControlDescriptor]) -> None:
        self._controls_panel.populate(controls)

    @Slot(float, int)
    def _on_stats_update(self, fps: float, dropped: int) -> None:
        self._lbl_fps.setText(f"FPS: {fps:.1f}")
        self._lbl_dropped.setText(f"Dropped: {dropped}")

    @Slot(str)
    def _on_capture_error(self, msg: str) -> None:
        hint = "\n\nHint: Check Windows camera privacy settings." if sys.platform == "win32" else ""
        QMessageBox.warning(self, "Camera Error", msg + hint)

    # --------------------------------------------------------- Resolution --

    @Slot()
    def _on_apply_resolution(self) -> None:
        _, w, h = _RESOLUTIONS[self._res_combo.currentIndex()]
        fps = self._fps_combo.currentData()
        self._command_queue.put(ResolutionCommand(width=w, height=h, fps=fps))

    # ---------------------------------------------------------- Recording --

    @Slot()
    def _on_toggle_record(self) -> None:
        if not self._recording:
            worker = self._recorder.start(self._record_queue, self._output_dir)
            worker.recording_started.connect(lambda p: self.statusBar().showMessage(f"Recording: {p}"))
            worker.recording_stopped.connect(lambda p: self.statusBar().showMessage(f"Saved: {p}", 5000))
            worker.error.connect(lambda m: QMessageBox.warning(self, "Recorder Error", m))
            self._camera_mgr.start_recording()
            self._btn_record.setText("⏹  Stop Recording")
            self._btn_record.setStyleSheet("color: red;")
            self._recording = True
        else:
            self._camera_mgr.stop_recording()
            self._recorder.stop()
            self._btn_record.setText("⏺  Start Recording")
            self._btn_record.setStyleSheet("")
            self._recording = False

    # ----------------------------------------------------------- Snapshot --

    @Slot()
    def _on_snapshot(self) -> None:
        if not self._snap_mgr.capture(self._preview_slot, self._snapshot_done, self._output_dir):
            self.statusBar().showMessage("No frame available for snapshot", 2000)

    @Slot(str)
    def _on_snapshot_done(self, path: str) -> None:
        if path:
            self.statusBar().showMessage(f"Snapshot saved: {path}", 3000)
        else:
            self.statusBar().showMessage("Snapshot write failed", 2000)

    # -------------------------------------------------------- Output dir ---

    @Slot()
    def _on_choose_output(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Output Folder", str(self._output_dir))
        if d:
            self._output_dir = Path(d)
            self.statusBar().showMessage(f"Output: {d}", 2000)

    # -------------------------------------------------------------- Close --

    def closeEvent(self, event) -> None:
        self._snap_mgr.shutdown()
        if self._recording:
            self._camera_mgr.stop_recording()
            self._recorder.stop()
        self._camera_mgr.close()
        event.accept()
