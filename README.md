# Camera Control App

A real-time camera control and visualization desktop application built with Python, PyQt6, and OpenCV.

## Features

- **Live feed** — mirrored preview (natural laptop-camera orientation) with FPS counter and dropped-frame tracking
- **Open / Close camera** — clean start/stop with proper thread teardown
- **Resolution & FPS** — dropdown selectors (1080p / 720p / VGA, 60 / 30 / 15 fps); negotiated actual values shown if the camera falls back to a different mode
- **Dynamic camera controls** — brightness, contrast, saturation, sharpness, gain, exposure, focus; ranges read from the camera at open time, unsupported controls omitted automatically
- **Auto-exposure toggle** — "Auto" checkbox on the Exposure slider; unchecking switches to manual, checking triggers a camera reopen to fully re-engage auto-exposure; slider tracks the live auto-managed value in real time
- **Camera controls persist** across resolution/FPS changes; "Reset to Defaults" restores all sliders to their at-open values
- **Snapshot** — saves a PNG frame off the GUI thread (ThreadPoolExecutor)
- **Video recording** — MP4 (mp4v) or AVI (XVID) selectable before starting; written off the GUI thread
- **Robustness** — exponential backoff reconnect on disconnect or read failure; device busy / permission errors surfaced to the user; dropped frames counted and displayed

## Requirements

- Python 3.11+
- Windows (MSMF primary backend; DirectShow fallback)

```
pip install -r requirements.txt
```

## Run

```
python main.py
```

## Architecture

```
camera-control-app/
├── main.py                    # Entry point, output-dir arg
├── ui/
│   ├── main_window.py         # Main window, thread wiring, signal routing
│   └── controls_panel.py      # Dynamic sliders, auto-exposure toggle, reset
├── camera/
│   ├── camera_manager.py      # QThread + CaptureThread lifecycle
│   ├── capture_thread.py      # Frame loop, reconnect backoff, command queue
│   └── camera_properties.py   # CameraInfo, enumerate_cameras, probe_controls
├── recording/
│   ├── recorder.py            # QThread + RecorderThread lifecycle
│   └── recorder_thread.py     # VideoWriter loop, MP4/AVI output
├── snapshots/
│   └── snapshot_manager.py    # Off-thread imwrite via ThreadPoolExecutor
└── utils/
    ├── frame_queue.py         # LatestFrameSlot, FrameQueue, Frame dataclass
    └── logger.py              # File + stdout logging setup
```

## Threading model

```
GUI Thread (MainWindow)
│  pyqtSignal (frame_ready, stats_update, prop_update, …)
▼
CaptureThread  [QThread]
│  — VideoCapture.read() loop
│  — Exponential backoff reconnect
│  — Command queue (ControlCommand, ResolutionCommand)
│  — Emits live prop values (e.g. exposure) every second
│
├─► LatestFrameSlot   — 1-slot drop-old buffer → preview
└─► FrameQueue        — bounded 256-frame buffer → recording

RecorderThread  [QThread]
│  — VideoWriter.write() loop
│  — Drains FrameQueue, writes MP4 or AVI
│  — Flush remaining frames on stop

SnapshotManager  [ThreadPoolExecutor(1)]
   — cv2.imwrite() off the GUI thread
```

The GUI thread never touches I/O or `VideoCapture`. All camera interaction, file writing, and blocking waits happen in background threads. Communication is via PyQt signals (thread-safe queued connections) and lock-free queues.

## Key design decisions

- **LatestFrameSlot vs FrameQueue** — preview uses a 1-slot "latest wins" buffer so a slow renderer never builds up a backlog. Recording uses a bounded FIFO so frames aren't dropped silently without accounting.
- **Command queue for camera controls** — slider changes are enqueued as `ControlCommand` objects and drained every 10 frames inside the capture loop, keeping cap.set() calls on the camera thread.
- **Reopen for resolution/FPS and auto-exposure restore** — `ResolutionCommand` signals the capture thread to release and re-open the capture, the only reliable path on Windows MSMF for changing stream parameters or re-engaging auto-exposure.
- **Backoff reconnect** — delays of 0.5 → 1 → 2 → 4 → 8 s prevent hammering the driver on persistent failure.
- **Camera control ranges from camera** — `probe_controls()` reads the current value from each property at open time; controls returning −1 (unsupported) are silently omitted. Ranges use MSMF conventions (0–255 for most, −13–0 for exposure).

## Output

Recordings and snapshots are saved to the current directory by default. Change via **Output Folder…**.

```
recording_YYYYMMDD_HHMMSS.mp4   (or .avi)
snapshot_YYYYMMDD_HHMMSS_mmm.png
```
