import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any, Callable

from .classification import deduplicate_devices, device_from_mapping
from .models import PeripheralDevice


PowerShellRunner = Callable[[str], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class PeripheralDiscoveryReport:
    devices: tuple[PeripheralDevice, ...]
    errors: tuple[str, ...] = ()


class PeripheralDiscovery:
    """Read-only discovery through Windows' built-in PnP device provider."""

    _SCRIPT = (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "Get-PnpDevice -ErrorAction Stop | "
        "Select-Object Status,Class,InstanceId,FriendlyName,Manufacturer,"
        "Present,DriverProviderName,DriverVersion,LocationInfo,Service,HardwareID | "
        "ConvertTo-Json -Depth 4 -Compress"
    )

    def __init__(self, runner: PowerShellRunner | None = None) -> None:
        self._uses_platform_runner = runner is None
        self._runner = runner or self._run_powershell
        self._platform_supported = os.name == "nt"

    def discover(self) -> PeripheralDiscoveryReport:
        if not self._platform_supported and self._uses_platform_runner:
            return PeripheralDiscoveryReport(
                devices=(),
                errors=("Windows peripheral discovery is only available on Windows.",),
            )
        try:
            completed = self._runner(self._SCRIPT)
        except subprocess.TimeoutExpired:
            return PeripheralDiscoveryReport(
                (),
                ("Windows device discovery timed out. Try refreshing again.",),
            )
        except PermissionError:
            return PeripheralDiscoveryReport(
                (),
                ("Windows denied access to device discovery.",),
            )
        except OSError as exc:
            return PeripheralDiscoveryReport((), (f"Could not start Windows device discovery: {exc}",))
        except subprocess.SubprocessError as exc:
            return PeripheralDiscoveryReport((), (f"Windows device discovery failed: {exc}",))
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        if completed.returncode != 0:
            error = stderr.strip()
            if "get-pnpdevice" in error.lower() and "not recognized" in error.lower():
                message = "Windows PowerShell cannot access Get-PnpDevice on this system."
            else:
                message = error or "Windows device discovery failed."
            return PeripheralDiscoveryReport((), (message,))
        try:
            payload: Any = json.loads(stdout) if stdout.strip() else []
        except json.JSONDecodeError as exc:
            return PeripheralDiscoveryReport((), (f"Windows device discovery returned invalid data: {exc}",))
        rows = payload if isinstance(payload, list) else [payload]
        devices = [device_from_mapping(row) for row in rows if isinstance(row, dict)]
        valid_devices = [device for device in devices if device is not None]
        skipped = len(rows) - len(valid_devices)
        errors = (f"Skipped {skipped} device record(s) without an instance ID.",) if skipped else ()
        return PeripheralDiscoveryReport(deduplicate_devices(valid_devices), errors)

    @staticmethod
    def _run_powershell(script: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
            # The packaged app has no console; keep PowerShell from opening one.
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
