from __future__ import annotations
import queue

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QSlider, QGroupBox
from PyQt6.QtCore import Qt

from camera.camera_properties import ControlDescriptor
from camera.capture_thread import ControlCommand, Command


class ControlsPanel(QWidget):
    def __init__(self, command_queue: "queue.SimpleQueue[Command]", parent=None) -> None:
        super().__init__(parent)
        self._command_queue = command_queue
        self._layout = QVBoxLayout(self)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._saved: dict[int, float] = {}

    def populate(self, controls: list[ControlDescriptor]) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not controls:
            self._layout.addWidget(QLabel("No adjustable controls"))
            return

        for ctrl in controls:
            value = self._saved.get(ctrl.prop_id, ctrl.current)
            value = max(ctrl.min_val, min(ctrl.max_val, value))

            box = QGroupBox(ctrl.name)
            vl  = QVBoxLayout(box)
            lbl = QLabel(f"{value:.0f}")
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setMinimum(int(ctrl.min_val))
            slider.setMaximum(int(ctrl.max_val))
            slider.setValue(int(value))
            slider.setSingleStep(int(ctrl.step) or 1)
            prop_id = ctrl.prop_id

            def _on_change(val: int, pid: int = prop_id, l: QLabel = lbl) -> None:
                l.setText(str(val))
                self._saved[pid] = float(val)
                self._command_queue.put(ControlCommand(prop_id=pid, value=float(val)))

            slider.valueChanged.connect(_on_change)
            vl.addWidget(slider)
            vl.addWidget(lbl)
            self._layout.addWidget(box)

            if ctrl.prop_id in self._saved:
                self._command_queue.put(ControlCommand(prop_id=ctrl.prop_id, value=value))
