# Windows Camera Control

This is the final Windows 10/11 camera-control application delivery.
It detects cameras with a bounded OpenCV index probe, previews only the camera
explicitly selected in the UI, and captures photos or recordings from that same
preview stream.

## Requirements

- Python 3.10 or newer
- Windows 10 or Windows 11
- The packages listed in `requirements.txt`
- `build-requirements.txt` when building the executable

Install dependencies in a virtual environment when setting up a new checkout:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The existing environment already has compatible OpenCV and PySide6 installations;
the commands above are instructions only and are not run by the application.

## Run

```powershell
.\.venv\Scripts\python.exe -m camera_control
```

The app has a **Camera** tab and a read-only **Peripherals** tab. The
Peripherals tab uses Windows device enumeration to show device names, types,
enabled status when available, and Windows device IDs reported to the app.
Windows may return multiple entries for one physical device, and results depend
on what Windows and device drivers expose; this is not a guarantee that every
physical device is visible to the application.
Choose a functional category (Audio, Camera, Input, Network, Bluetooth,
Storage, Printer, Display, USB, System, or Other) from the type dropdown to
filter the list, or choose **All types**. Categories are inferred from reported
Windows interface IDs and device names and are best-effort; a device can expose
multiple entries. When Windows provides a reliable device-container or device
instance ID, related entries are grouped under a clearer device label; expand
the group to see each original Windows entry and its device ID. Entries without
a reliable grouping ID remain listed individually, and an unrecognized entry
appears under Other. The
device list includes Windows entries regardless of whether they are internal
or external.

The application probes a bounded range of OpenCV camera indexes in a worker
thread. Select a detected index from the dropdown to start preview. **Take
Photo** saves the latest preview frame under `captures/`. **Start Recording**
uses the existing preview stream and saves finalized MP4 files under
`recordings/`. Use **Stop Recording**, **Stop preview**, or close the window to
finalize the current recording and release the selected camera.

The Frame Rate setting leaves preview output uncapped by default, or caps its
output cadence at 15, 24, 30, or 60 FPS. The Zoom slider provides digital zoom
from 1x to 4x; double-click a point in the preview to zoom in around that
point. Return the slider to 1x to restore the full frame. Zoom is digital
rather than optical and is also applied to photos and recordings from the
preview stream. The FPS cap affects output cadence, not the camera's sensor
capture rate.

Recording uses the selected camera's reported FPS when it is within a practical
range, otherwise it uses a 20 FPS fallback. The actual preview frame dimensions
are used for the writer. Only one recording can be active at a time.

On the OpenCV path, the Resolution selector tests a bounded candidate
list (320x240, 640x480, 1280x720, and 1920x1080) using actual returned frame
dimensions. A candidate is shown only after verification on the active camera;
the current resolution is restored after probing, and changes are disabled
during recording.

The White balance selector offers Auto and common temperature presets
(Daylight, Cloudy, and Tungsten). The active camera backend receives these
requests; support and visible results vary by camera and driver. The Leave
unchanged choice does not send a white-balance request to the camera.

Exposure controls have been removed. The app leaves exposure under the camera
driver's default automatic behavior. Focus controls remain available and are
backend-dependent; drivers may reject requests or accept them without applying
the value.

On Windows, cameras are opened through OpenCV Media Foundation (MSMF) by
default to preserve the earlier camera behavior. Discovery uses OpenCV camera
indexes and obtains friendly names separately from Windows enumeration, so
ordering may not match perfectly when several cameras are connected. MSMF is
tried first, with OpenCV's default backend used if MSMF cannot open the index.
Supported FPS and image brightness still depend on the camera, driver, and
lighting. OpenCV does not guarantee discovery of every camera. Driver support,
privacy permissions, and supported camera controls still vary by PC.

## Build the Windows executable

Install the build-only dependency into the workspace environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r build-requirements.txt
```

Build from the repository root:

```powershell
.\.venv\Scripts\pyinstaller.exe --clean --noconfirm camera_control.spec
```

The executable is created at `dist\WindowsCameraControl.exe`. Launch it with:

```powershell
.\dist\WindowsCameraControl.exe
```

The build was verified on this Windows 11 machine only. Camera permissions,
drivers, supported resolutions, FPS behavior, and hardware controls vary by
computer and camera.

## Verified features

- Camera discovery and selection.
- Live preview through OpenCV MSMF on the test machine (about 30 FPS at
  640x480 in the measured run).
- JPEG photo capture under `captures\`.
- MP4 recording and finalization under `recordings\`.
- Resolution changes verified from actual frames, including restoration.
- Windows device ID discovery through PyWinRT when the driver exposes it.
- Safe handling of unknown FPS and zoom support.

## Troubleshooting

- If no camera appears, check Windows camera privacy permissions and whether
	 another application is using the camera.
- OpenCV index discovery is bounded and may not find every Windows camera.
- A Windows device ID is not automatically treated as an exact OpenCV index
	 match.
- Advertised profiles are metadata; actual preview dimensions and measured FPS
	remain the runtime authority.
- MSMF may print warnings when unsupported resolution candidates are probed.
- If the executable reports missing camera access, enable camera access for
	 desktop applications in Windows Privacy settings and relaunch it.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```