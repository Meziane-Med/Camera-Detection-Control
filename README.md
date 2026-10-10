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

The application probes a bounded range of OpenCV camera indexes in a worker
thread. Select a detected index from the dropdown to start preview. **Take
Photo** saves the latest preview frame under `captures/`. **Start Recording**
uses the existing preview stream and saves finalized MP4 files under
`recordings/`. Use **Stop Recording**, **Stop preview**, or close the window to
finalize the current recording and release the selected camera.

Recording uses the selected camera's reported FPS when it is within a practical
range, otherwise it uses a 20 FPS fallback. The actual preview frame dimensions
are used for the writer. Only one recording can be active at a time.

The Resolution selector tests a bounded candidate list (320x240, 640x480,
1280x720, and 1920x1080) using actual returned frame dimensions. OpenCV cannot
reliably enumerate every Windows camera mode, so a listed resolution is only
shown after verification on the active camera. The camera's current resolution
is restored after probing, and resolution changes are disabled during recording.

The index scan is an initial fallback and does not guarantee discovery of every
Windows camera. Windows capability discovery reports device IDs and advertised
profiles when the driver exposes them, but it does not claim that a Windows ID
matches an OpenCV numeric index. The active OpenCV stream therefore verifies
resolution changes from actual frames.

On Windows, the discovery worker also queries PyWinRT's
`DeviceInformation.FindAllAsync(DeviceClass.VideoCapture)` and, when supported,
`MediaCapture.FindAllVideoProfiles`. These results contain Windows device IDs
and advertised media descriptions. They are deliberately not matched to
OpenCV numeric indexes yet, so the UI continues using actual frame verification
for resolution choices rather than presenting another device's advertised modes.
The fixed OpenCV candidate list is therefore only a fallback for unresolved
identity, not the authoritative Windows capability list. FPS and zoom controls
remain unavailable unless support is exposed by the device/backend and verified
in the active stream. A reported FPS value is not treated as a guaranteed
control mode, and an unavailable zoom property remains unknown rather than
being declared unsupported hardware.

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
- Live preview through OpenCV MSMF on the test machine.
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