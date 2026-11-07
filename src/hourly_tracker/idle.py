"""Idle time from the operating system, in seconds since the last input."""

from __future__ import annotations

import ctypes
import logging
import re
import subprocess
import sys

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def get_idle_seconds() -> float:
    """Return how long the keyboard and mouse have been idle.

    The value comes from the OS input timer. Sleep and hibernate do not
    advance it, so a powered-off gap is not reported as idle.
    """
    if sys.platform == "win32":
        return _windows_idle_seconds()
    if sys.platform == "darwin":
        return _macos_idle_seconds()
    return _linux_idle_seconds()


def _windows_idle_seconds() -> float:
    class LastInputInfo(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    info = LastInputInfo()
    info.cbSize = ctypes.sizeof(LastInputInfo)
    user32 = ctypes.windll.user32
    user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LastInputInfo)]
    user32.GetLastInputInfo.restype = ctypes.c_int
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        raise OSError("GetLastInputInfo failed")

    kernel32 = ctypes.windll.kernel32
    try:
        kernel32.GetTickCount64.restype = ctypes.c_ulonglong
        tick64 = int(kernel32.GetTickCount64())
    except AttributeError:
        kernel32.GetTickCount.restype = ctypes.c_uint
        tick64 = int(kernel32.GetTickCount())
    tick32 = tick64 & 0xFFFFFFFF
    # dwTime is the low 32 bits of the tick at the last input, so mask both
    # sides. A plain 64-bit subtraction is wrong after 49.7 days of uptime.
    idle_ms = (tick32 - int(info.dwTime)) & 0xFFFFFFFF
    return idle_ms / 1000


def _macos_idle_seconds() -> float:
    output = subprocess.run(
        ["ioreg", "-c", "IOHIDSystem"],
        capture_output=True,
        text=True,
        timeout=2,
        check=False,
    )
    if output.returncode != 0:
        raise OSError(output.stderr.strip() or "ioreg failed")
    match = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', output.stdout)
    if match is None:
        raise OSError("HIDIdleTime was not in the ioreg output")
    return int(match.group(1)) / 1_000_000_000


def _linux_idle_seconds() -> float:
    dbus_cmd = (
        "dbus-send --print-reply --dest=org.gnome.Mutter.IdleMonitor "
        "/org/gnome/Mutter/IdleMonitor/Core "
        "org.gnome.Mutter.IdleMonitor.GetIdletime"
    )
    mutter = _run_text(["bash", "-c", dbus_cmd])
    if mutter is not None:
        token = mutter.strip().rsplit(None, 1)[-1]
        try:
            return int(token) / 1000
        except ValueError:
            logging.debug("Unexpected Mutter idle reply: %s", mutter.strip())

    xprintidle = _run_text(["xprintidle"])
    if xprintidle is not None:
        try:
            return int(xprintidle.strip()) / 1000
        except ValueError:
            logging.debug("Unexpected xprintidle reply: %s", xprintidle.strip())

    raise OSError("No supported Linux idle source (Mutter IdleMonitor or xprintidle)")


def _run_text(command: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logging.debug("Idle command failed: %s", exc)
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout
