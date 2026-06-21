# Camera Control App

A real-time camera control and visualization desktop application built with Python, PyQt6, and OpenCV.

## Features

- **Live feed** — mirrored preview (natural laptop-camera orientation) with FPS counter and dropped-frame tracking
- **Open / Close camera** — clean start/stop with proper thread teardown and property restoration
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
├── main.py                    # Entry point: logger setup, QApplication, MainWindow
├── ui/
│   ├── main_window.py         # Main window, thread wiring, signal routing, state machine
│   └── controls_panel.py      # Dynamic sliders, auto-exposure toggle, reset
├── camera/
│   ├── camera_manager.py      # QThread + CaptureThread lifecycle
│   ├── capture_thread.py      # Frame loop, reconnect backoff, command queue drain
│   └── camera_properties.py   # CameraInfo, enumerate_cameras, probe_controls
├── recording/
│   ├── recorder.py            # QThread + RecorderThread lifecycle
│   └── recorder_thread.py     # VideoWriter loop, MP4/AVI output, flush on stop
├── snapshots/
│   └── snapshot_manager.py    # Off-thread imwrite via ThreadPoolExecutor(1)
└── utils/
    ├── frame_queue.py         # LatestFrameSlot (preview), FrameQueue (record), Frame dataclass
    └── logger.py              # File + stdout logging setup
```

## Threading model

```
GUI Thread (MainWindow)
│  PyQt signals (queued connections — thread-safe by default)
│
├─ EnumerationThread  [QThread, transient]
│     enumerate_cameras() at startup and on refresh
│     emits finished → populates camera combo box
│
├─ CaptureThread  [QThread]
│     VideoCapture.read() loop (MSMF primary, DirectShow fallback)
│     Saves original property values at open; restores them at close
│     Drains command queue every 10 frames (ControlCommand, ResolutionCommand)
│     Emits: frame_ready, state_changed, controls_ready, stats_update, error
│     Exponential backoff reconnect: 0.5 → 1 → 2 → 4 → 8 s
│
│     ├─► LatestFrameSlot   — 1-slot drop-old buffer → preview
│     └─► FrameQueue        — bounded 256-frame FIFO → recording
│
├─ RecorderThread  [QThread]
│     Drains FrameQueue, writes frames via cv2.VideoWriter (MP4 or AVI)
│     On stop: flushes remaining queued frames before releasing writer
│     Emits: recording_started, recording_stopped, error
│
└─ SnapshotManager  [ThreadPoolExecutor(1)]
      peek() on LatestFrameSlot (non-consuming), cv2.imwrite off GUI thread
```

The GUI thread never touches `VideoCapture`, `VideoWriter`, or `imwrite`. All camera I/O, file writes, and blocking waits happen in background threads. Thread communication uses PyQt signals (queued connections) for GUI updates and lock-free queues for data flow.

## Startup flow

1. `main.py` — sets up logger, creates `QApplication`, instantiates `MainWindow`
2. `MainWindow.__init__` — creates shared buffers (`LatestFrameSlot`, `FrameQueue`), command queue (`SimpleQueue`), managers, and UI widgets
3. Camera enumeration runs in a transient `QThread` so the window appears immediately
4. User selects a camera and clicks **Open Camera** → `CameraManager` spawns `CaptureThread`
5. `CaptureThread` emits `controls_ready` → `ControlsPanel` populates sliders from probed values
6. Frame loop runs → `frame_ready` signals drive the preview widget
7. Resolution/FPS **Apply** or auto-exposure toggle → `ResolutionCommand` enqueued → capture thread reopens
8. **Close Camera** / window close → threads stopped in order (capture → recorder), camera released, original properties restored

## Key design decisions

**LatestFrameSlot vs FrameQueue** — preview uses a 1-slot "latest wins" buffer so a slow renderer never builds up a backlog. Recording uses a bounded FIFO so frames aren't silently dropped without accounting.

**Command queue for camera controls** — slider changes are enqueued as `ControlCommand` objects and drained every 10 frames inside the capture loop, keeping all `cap.set()` calls on the camera thread with no locking on the hot path.

**Reopen for resolution/FPS and auto-exposure** — `ResolutionCommand` signals the capture thread to release and re-open the capture. This is the only reliable path on Windows MSMF for changing stream parameters; auto-exposure re-engagement also requires a reopen because `CAP_PROP_AUTO_EXPOSURE` values (`0.75` = auto, `0.25` = manual) are not reliably applied mid-stream.

**Property save/restore** — all probed properties are snapshotted at open time before any `cap.set()` calls. On close (including during resolution changes) the originals are restored, leaving the device in a known state for the next session or another app.

**Backoff reconnect** — delays of 0.5 → 1 → 2 → 4 → 8 s prevent hammering the driver on persistent failure. State transitions (`LIVE`, `RECONNECTING`, `DISCONNECTED`) are surfaced to the UI via signal.

**Camera control discovery** — `probe_controls()` reads each property at open time; controls returning `−1` (unsupported by the driver) are silently omitted from the UI. Ranges follow MSMF conventions (0–255 for most properties, −13–0 for exposure).

**Windows-specific backend selection** — MSMF (`CAP_MSMF`) is tried first for better device name support and modern codec access. DirectShow (`CAP_DSHOW`) is the fallback for older or incompatible hardware.

## Output

Recordings and snapshots are saved to the current directory by default. Change via **Output Folder…**.

```
recording_YYYYMMDD_HHMMSS.mp4   (or .avi)
snapshot_YYYYMMDD_HHMMSS_mmm.png
camera_app.log
```
