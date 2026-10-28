# Device Control

**Camera preview, capture and peripheral detection for Windows 10/11.**

Device Control is a desktop application built with Python, PySide6 (Qt) and
OpenCV. It previews a webcam, takes photos and records video, and lists the
input, output and storage devices that Windows reports through Plug and Play.

![Version](https://img.shields.io/badge/version-1.0.0-4f7cff)
![Platform](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078d4)
![Python](https://img.shields.io/badge/python-3.10%2B-3776ab)

---

## Contents

- [Features](#features)
- [Quick start (executable)](#quick-start-executable)
- [Run from source](#run-from-source)
- [Using the application](#using-the-application)
- [Build the executable](#build-the-executable)
- [Project structure](#project-structure)
- [Testing](#testing)
- [Design notes and limitations](#design-notes-and-limitations)
- [Troubleshooting](#troubleshooting)

## Features

### Camera

| Feature | Details |
| --- | --- |
| Camera detection | Probes OpenCV indexes 0–4 in a background thread, so the UI never freezes |
| Live preview | Starts only after you select a camera; stops cleanly and releases the device |
| Photo capture | Saves the latest preview frame as JPEG under `captures\` |
| Video recording | Records MP4 from the live stream under `recordings\`; one recording at a time |
| Resolution | Offers only modes verified on the active camera (320×240, 640×480, 1280×720, 1920×1080 tested) |
| Frame rate | Requests 15, 24, 30 or 60 FPS and shows both the camera-reported and measured FPS |
| Zoom | Software preview zoom from 1.00× to 4.00× in 0.25× steps |

### Peripherals

| Feature | Details |
| --- | --- |
| Device discovery | Read-only query of Windows Plug and Play (`Get-PnpDevice`) |
| Classification | Input, Output, Input/Output and Storage categories |
| Filtering | Category filter, text search, and a *Connected only* toggle |
| Details view | Name, category, manufacturer, status, device ID, class, driver, connection and more |

## Quick start (executable)

No Python installation is required.

1. Copy `DeviceControl-1.0.0.exe` to any folder.
2. Double-click it. The first launch takes a few seconds while the bundle unpacks.
3. If no camera appears, allow camera access for desktop apps in
   **Settings → Privacy & security → Camera**.

Photos and recordings are saved in `captures\` and `recordings\` inside the
folder the application is started from.

## Run from source

### Requirements

- Windows 10 or Windows 11
- Python 3.10 or newer
- A webcam (optional, for the camera page)

### Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### Launch

```powershell
python -m camera_control
```

## Using the application

The window has a sidebar with two pages.

### Camera page

1. Wait for detection to finish, then pick a camera from the dropdown at the
   top right. The preview starts immediately.
2. **Take photo** saves the current frame.
3. **Record** starts a recording; the button turns red and reads
   **Stop recording**. Click it again to finalize the MP4 file.
4. Use **Resolution**, **FPS** and the **− / + / 1x** zoom buttons in the
   toolbar. The information line below shows the active resolution, FPS and zoom.
5. **Stop** ends the preview and releases the camera. **Refresh** runs
   detection again.

Resolution changes are disabled while recording. Closing the window finalizes
any active recording and releases the camera.

### Peripherals page

Devices load the first time the page is opened (this takes a few seconds).
Use the search box, the category filter and **Connected only** to narrow the
list, then select a device to see everything Windows returned about it.
Values Windows does not provide are shown as *Not available*. **Refresh**
runs discovery again.

## Build the executable

```powershell
python -m pip install -r requirements.txt -r build-requirements.txt
python -m PyInstaller --clean --noconfirm camera_control.spec
```

The output is `dist\DeviceControl-<version>.exe`: a single-file, windowed
executable (no console) with Windows version information embedded in its file
properties.

The version is defined once, in `camera_control/__init__.py`
(`__version__`). The spec file reads it for both the file name and the
embedded metadata, and the application shows it at the bottom of the sidebar.
To release a new version, change that value and rebuild.

## Project structure

```
tp-system/
├── camera_control/            Camera page and application entry point
│   ├── app.py                 Main window: sidebar navigation and page stack
│   ├── page.py                Camera page UI
│   ├── preview.py             Preview thread, capture, recording, resolution/FPS/zoom
│   ├── discovery.py           Bounded OpenCV camera index probe
│   ├── windows_capabilities.py  Windows device and media-profile discovery (PyWinRT)
│   └── models.py              Camera data models
├── peripheral_control/        Peripherals page
│   ├── ui.py                  Device list, filters and details view
│   ├── discovery.py           Get-PnpDevice query through PowerShell
│   ├── classification.py      Input / output / storage classification rules
│   └── models.py              Device data models
├── shared/                    Code used by both pages
│   ├── theme.py               Colour tokens and Qt stylesheet
│   ├── widgets.py             Button, label, card and page-header helpers
│   └── tasks.py               Run blocking work off the UI thread
├── tests/                     Unit tests
├── run_camera_control.py      Executable entry script
├── camera_control.spec        PyInstaller build configuration
├── requirements.txt           Runtime dependencies
└── build-requirements.txt     Build-only dependencies
```

## Testing

```powershell
python -m unittest discover -s tests -v
```

The suite covers camera discovery, preview start/stop, photo and recording
(including writer failures), resolution verification and restoration, FPS
readback, zoom bounds, Windows capability parsing, peripheral parsing,
classification, de-duplication and the peripheral page filters. Tests use
fake cameras and fake PowerShell output, so no hardware is required.

## Design notes and limitations

- **Camera detection is bounded.** OpenCV cannot enumerate Windows cameras by
  name, so the application probes indexes 0–4. A camera at a higher index, or
  one in use by another application, may not appear.
- **Resolutions are verified, not assumed.** Each candidate is applied and
  kept only if the camera returns frames of that exact size. The original
  resolution is restored after probing.
- **FPS is a request.** Drivers may ignore it. The application shows the value
  the camera reports and the frame rate actually measured from the stream.
- **Zoom is digital.** It crops and scales the preview only; it does not drive
  optical or hardware zoom, and recordings keep the full camera frame.
- **Windows device IDs are not matched to OpenCV indexes.** PyWinRT discovery
  reports device IDs and advertised profiles when the driver exposes them,
  but the actual preview frames remain the authority for what the camera does.
- **Peripheral detection reflects what Windows reports.** Results depend on
  drivers, permissions and device state, and are not guaranteed to be
  exhaustive. A USB connection alone does not make a device *Input/Output*;
  classification is based on the device class and its description.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| No camera detected | Camera privacy settings for desktop apps; close other apps using the camera; click **Refresh** |
| Preview is black or stops | Another application may have taken the camera; select it again |
| A resolution is missing | The camera did not return frames at that size, so it is not offered |
| FPS differs from the request | The driver ignored or adjusted the request; the measured value is the real rate |
| Peripheral list is empty or times out | PowerShell must be available; click **Refresh** to retry |
| Exe is slow to start | Normal for a single-file build: it unpacks to a temporary folder first |

Messages such as `CvCapture_MSMF::initStream` or `obsensor ... out of range`
in a terminal when running from source are OpenCV diagnostics printed while
probing indexes and resolutions. They are expected and harmless.

---

Version 1.0.0 · Verified on Windows 11 with Python 3.13 and PyInstaller 6.22.3.
