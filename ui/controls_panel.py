from __future__ import annotations
import queue

import cv2
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QSlider, QGroupBox, QPushButton
from PyQt6.QtCore import Qt

from camera.camera_properties import ControlDescriptor
from camera.capture_thread import ControlCommand, Command


class ControlsPanel(QWidget):
    def __init__(self, command_queue: "queue.SimpleQueue[Command]", parent=None) -> None:
        super().__init__(parent)
        self._command_queue = command_queue
        self._layout = QVBoxLayout(self)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._saved:      dict[int, float] = {}
        self._defaults:   dict[int, float] = {}
        self._sliders:    dict[int, QSlider] = {}
        self._resetting:  bool = False

    def populate(self, controls: list[ControlDescriptor]) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._sliders.clear()

        if not controls:
            self._layout.addWidget(QLabel("No adjustable controls"))
            return

        btn_reset = QPushButton("Reset to Defaults")
        btn_reset.clicked.connect(self._on_reset)
        self._layout.addWidget(btn_reset)

        for ctrl in controls:
            if ctrl.prop_id not in self._defaults:
                self._defaults[ctrl.prop_id] = ctrl.current

            value = self._saved.get(ctrl.prop_id, ctrl.current)
            value = max(ctrl.min_val, min(ctrl.max_val, value))

            box    = QGroupBox(ctrl.name)
            vl     = QVBoxLayout(box)
            lbl    = QLabel(f"{value:.0f}")
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setMinimum(int(ctrl.min_val))
            slider.setMaximum(int(ctrl.max_val))
            slider.setValue(int(value))
            slider.setSingleStep(int(ctrl.step) or 1)
            prop_id = ctrl.prop_id
            self._sliders[prop_id] = slider

            def _on_change(val: int, pid: int = prop_id, l: QLabel = lbl) -> None:
                l.setText(str(val))
                self._saved[pid] = float(val)
                if pid == cv2.CAP_PROP_EXPOSURE and not self._resetting:
                    self._command_queue.put(ControlCommand(prop_id=cv2.CAP_PROP_AUTO_EXPOSURE, value=0.25))
                self._command_queue.put(ControlCommand(prop_id=pid, value=float(val)))

            slider.valueChanged.connect(_on_change)
            vl.addWidget(slider)
            vl.addWidget(lbl)
            self._layout.addWidget(box)

            if ctrl.prop_id in self._saved:
                self._command_queue.put(ControlCommand(prop_id=ctrl.prop_id, value=value))

    def _on_reset(self) -> None:
        self._saved.clear()
        self._resetting = True
        try:
            for prop_id, slider in self._sliders.items():
                default = self._defaults.get(prop_id)
                if default is not None:
                    slider.setValue(int(default))
        finally:
            self._resetting = False
        # re-enable auto-exposure after all sliders are reset so _on_change can't override it
        self._command_queue.put(ControlCommand(prop_id=cv2.CAP_PROP_AUTO_EXPOSURE, value=0.75))
