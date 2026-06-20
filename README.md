# Camera Control App

PyQt6 desktop app for live camera preview, MP4 recording, and snapshots.

## Features

- Live preview with FPS monitor
- MP4 recording (mp4v codec, lazy VideoWriter init)
- PNG/JPEG snapshots saved off the GUI thread
- Automatic reconnect with exponential backoff
- Dynamic camera controls (brightness, contrast, exposure, focus, etc.)
- Camera enumeration via `cv2-enumerate-cameras` with probe fallback
- Structured logging to `camera_app.log`

## Requirements

- Python 3.11+
- Windows (MSMF backend; DSHOW fallback)

```
pip install -r requirements.txt
```

## Run

```
python main.py
```

## Structure

```
camera-control-app/
├── main.py                        # Entry point
├── ui/
│   ├── main_window.py             # Main window, thread wiring
│   └── controls_panel.py          # Dynamic slider controls
├── camera/
│   ├── camera_manager.py          # QThread + CaptureThread lifecycle
│   ├── capture_thread.py          # Frame loop, reconnect, FPS stats
│   └── camera_properties.py       # CameraInfo, enumerate_cameras, ControlDescriptor
├── recording/
│   ├── recorder.py                # QThread + RecorderThread lifecycle
│   └── recorder_thread.py         # VideoWriter loop, MP4 output
├── snapshots/
│   └── snapshot_manager.py        # Off-thread imwrite via ThreadPoolExecutor
├── utils/
│   ├── frame_queue.py             # LatestFrameSlot, FrameQueue, Frame dataclass
│   └── logger.py                  # setup_logger() — file + stdout handlers
└── requirements.txt
```

## Thread model

```
GUI Thread (MainWindow)
    │ pyqtSignal
    ▼
CaptureThread          — VideoCapture.read(), reconnect backoff
    │ LatestFrameSlot  — preview (1-slot, drop-old)
    │ FrameQueue       — recording (bounded 256, drop-newest on overflow)
    ▼
RecorderThread         — VideoWriter.write() → .mp4

SnapshotManager        — ThreadPoolExecutor(1) → cv2.imwrite()
```

## Output

Recordings and snapshots are saved to the current directory by default.
Change via **Output Folder…** button. Files are named:

```
recording_YYYYMMDD_HHMMSS.mp4
snapshot_YYYYMMDD_HHMMSS_mmm.png
```
