# PyInstaller configuration for the Device Control desktop app.
import re
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

project_root = Path(SPEC).parent

# Single source of truth for the version: camera_control/__init__.py.
version = re.search(
    r'__version__ = "([^"]+)"', (project_root / "camera_control" / "__init__.py").read_text()
).group(1)
version_tuple = tuple(int(part) for part in version.split(".")) + (0,)

version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=version_tuple, prodvers=version_tuple),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "040904B0",
                    [
                        StringStruct("CompanyName", "BOUAZZA Karim"),
                        StringStruct("FileDescription", "Device Control - camera and peripherals"),
                        StringStruct("FileVersion", version),
                        StringStruct("InternalName", "DeviceControl"),
                        StringStruct("OriginalFilename", f"DeviceControl-{version}.exe"),
                        StringStruct("ProductName", "Device Control"),
                        StringStruct("ProductVersion", version),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)

a = Analysis(
    [str(project_root / "run_camera_control.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "winrt.windows.devices.enumeration",
        "winrt.windows.foundation",
        "winrt.windows.foundation.collections",
        "winrt.windows.media.capture",
        "winrt.windows.media.devices",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "unittest"],
    noarchive=False,
)

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=f"DeviceControl-{version}",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    version=version_info,
)
