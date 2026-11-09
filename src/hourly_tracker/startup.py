"""Windows sign-in startup registration."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Hourly Tracker"


def is_supported() -> bool:
    return sys.platform == "win32"


def is_enabled() -> bool:
    if not is_supported():
        raise RuntimeError("Windows startup settings are only available on Windows.")

    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_QUERY_VALUE
        ) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
    except FileNotFoundError:
        return False
    return True


def set_enabled(enabled: bool) -> None:
    if not is_supported():
        raise RuntimeError("Windows startup settings are only available on Windows.")

    import winreg

    if enabled:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(
                key,
                VALUE_NAME,
                0,
                winreg.REG_SZ,
                _startup_command(),
            )
        return

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        pass


def _startup_command() -> str:
    if getattr(sys, "frozen", False):
        return subprocess.list2cmdline([sys.executable])

    launcher = Path(sys.argv[0])
    if not launcher.is_absolute():
        launcher = Path.cwd() / launcher
    launcher = launcher.resolve()

    if launcher.suffix.lower() == ".py":
        python = Path(sys.executable)
        pythonw = python.with_name("pythonw.exe")
        executable = pythonw if pythonw.exists() else python
        arguments = [str(executable), str(launcher)]
    else:
        arguments = [str(launcher)]

    return subprocess.list2cmdline(arguments)
