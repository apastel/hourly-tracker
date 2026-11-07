"""Best-effort time of the current OS login session."""

from __future__ import annotations

import ctypes
import datetime as dt
import getpass
import logging
import os
import subprocess
import sys
from pathlib import Path

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_LOGIN_FORMATS = (
    "%m/%d/%Y %I:%M %p",
    "%m/%d/%Y %H:%M",
    "%d/%m/%Y %I:%M %p",
    "%d/%m/%Y %H:%M",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %I:%M %p",
)


def get_login_time() -> dt.datetime | None:
    """Return the current session's logon time, or None if it can't be read."""
    try:
        if sys.platform == "win32":
            return _windows_login_time()
        if sys.platform == "darwin":
            return _posix_login_time(["who", "-q"])
        return _posix_login_time(["last", "-R", "-F", getpass.getuser()])
    except (OSError, subprocess.TimeoutExpired):
        logging.exception("Could not read the OS login time")
        return None


def _windows_login_time() -> dt.datetime | None:
    logon = _windows_logon_time_from_wts()
    if logon is not None:
        return logon
    return _windows_logon_time_from_quser()


class _WTSInfoW(ctypes.Structure):
    """Layout of WTSINFOW. 216 bytes, checked against the live API."""

    _fields_ = [
        ("state", ctypes.c_int),
        ("session_id", ctypes.c_uint),
        ("incoming_bytes", ctypes.c_uint),
        ("outgoing_bytes", ctypes.c_uint),
        ("incoming_frames", ctypes.c_uint),
        ("outgoing_frames", ctypes.c_uint),
        ("incoming_compressed_bytes", ctypes.c_uint),
        ("outgoing_compressed_bytes", ctypes.c_uint),
        ("win_station_name", ctypes.c_wchar * 32),
        ("domain", ctypes.c_wchar * 17),
        ("user_name", ctypes.c_wchar * 21),
        ("_pad", ctypes.c_uint),
        ("connect_time", ctypes.c_longlong),
        ("disconnect_time", ctypes.c_longlong),
        ("last_input_time", ctypes.c_longlong),
        ("logon_time", ctypes.c_longlong),
        ("current_time", ctypes.c_longlong),
    ]


def _windows_logon_time_from_wts() -> dt.datetime | None:
    """Read this session's logon time from wtsapi32.

    WTSLogonTime is not supported on this Windows build. WTSSessionInfo carries
    the same FILETIME, and `quser.exe` is not installed everywhere.
    """
    try:
        kernel = ctypes.windll.kernel32
        wts = ctypes.windll.wtsapi32
    except (AttributeError, OSError):
        return None

    session = ctypes.c_ulong()
    kernel.ProcessIdToSessionId.argtypes = [
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    kernel.ProcessIdToSessionId.restype = ctypes.c_int
    kernel.GetCurrentProcessId.restype = ctypes.c_ulong
    if not kernel.ProcessIdToSessionId(kernel.GetCurrentProcessId(), ctypes.byref(session)):
        return None

    buffer = ctypes.c_void_p()
    returned = ctypes.c_ulong()
    wts.WTSQuerySessionInformationW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_ulong),
    ]
    wts.WTSQuerySessionInformationW.restype = ctypes.c_int
    # WTSSessionInfo == 24.
    ok = wts.WTSQuerySessionInformationW(
        None,
        session.value,
        24,
        ctypes.byref(buffer),
        ctypes.byref(returned),
    )
    if not ok or not buffer:
        return None
    try:
        if returned.value < ctypes.sizeof(_WTSInfoW):
            return None
        info = ctypes.cast(buffer, ctypes.POINTER(_WTSInfoW)).contents
        ticks = int(info.logon_time)
    finally:
        wts.WTSFreeMemory.argtypes = [ctypes.c_void_p]
        wts.WTSFreeMemory(buffer)
    if ticks <= 0:
        return None
    seconds = ticks / 10_000_000 - 11_644_473_600
    return dt.datetime.fromtimestamp(seconds).replace(microsecond=0)


def _windows_logon_time_from_quser() -> dt.datetime | None:
    command = _quser_command()
    if not Path(command[0]).exists():
        return None
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
        errors="replace",
        creationflags=_NO_WINDOW,
    )
    if completed.returncode != 0 and not completed.stdout.strip():
        logging.info("quser failed: %s", completed.stderr.strip())
        return None

    username = getpass.getuser().lower()
    active: dt.datetime | None = None
    fallback: dt.datetime | None = None
    for line in completed.stdout.splitlines()[1:]:
        parsed = _parse_login_tail(line)
        if parsed is None:
            continue
        lowered = line.lower()
        if username and username in lowered:
            fallback = fallback or parsed
        if "active" in lowered:
            active = parsed
            break
    return active or fallback


def _quser_command() -> list[str]:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = Path(system_root) / "System32" / "quser.exe"
    if candidate.exists():
        return [str(candidate)]
    return ["quser"]


def _parse_login_tail(line: str) -> dt.datetime | None:
    parts = line.split()
    if len(parts) < 2:
        return None
    for length in (3, 2):
        if len(parts) < length:
            continue
        parsed = _parse_login_text(" ".join(parts[-length:]))
        if parsed is not None:
            return parsed
    return None


def _parse_login_text(text: str) -> dt.datetime | None:
    for fmt in _LOGIN_FORMATS:
        try:
            return dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _posix_login_time(command: list[str]) -> dt.datetime | None:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
        errors="replace",
    )
    if completed.returncode != 0 and not completed.stdout.strip():
        return None
    for line in completed.stdout.splitlines():
        parsed = _parse_last_line(line)
        if parsed is not None:
            return parsed
    return None


def _parse_last_line(line: str) -> dt.datetime | None:
    # `last -F` looks like: user tty Tue Nov  6 08:30:00 2026   still logged in
    for fmt in ("%a %b %d %H:%M:%S %Y", "%b %d %H:%M"):
        tokens = line.split()
        width = 5 if fmt.startswith("%a") else 3
        for index in range(len(tokens) - width + 1):
            candidate = " ".join(tokens[index : index + width])
            try:
                parsed = dt.datetime.strptime(candidate, fmt)
            except ValueError:
                continue
            if fmt == "%b %d %H:%M":
                return parsed.replace(year=dt.date.today().year)
            return parsed
    return None
