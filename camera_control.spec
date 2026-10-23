# PyInstaller configuration for the Windows Camera Control desktop app.
from pathlib import Path

project_root = Path(SPEC).parent

a = Analysis(
    [str(project_root / "run_camera_control.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "winrt.windows.devices.enumeration",
        "winrt.windows.foundation",
        "winrt.windows.foundation.collections",
        "winrt.windows.graphics.imaging",
        "winrt.windows.media",
        "winrt.windows.media.capture",
        "winrt.windows.media.capture.frames",
        "winrt.windows.media.devices",
        "winrt.windows.storage.streams",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "unittest"],
    noarchive=False,
)

# The widget-based UI does not use Qt's software OpenGL renderer.
a.binaries = [
    entry for entry in a.binaries
    if Path(entry[0]).name.lower() != "opengl32sw.dll"
]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="WindowsCameraControl",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)