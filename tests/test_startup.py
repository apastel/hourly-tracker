"""Windows sign-in startup registration tests."""

from __future__ import annotations

import sys
import subprocess
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hourly_tracker import startup


class StartupTest(unittest.TestCase):
    def test_python_script_launch_uses_pythonw_when_available(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "run tracker.py"
            python = Path(directory) / "python.exe"
            pythonw = Path(directory) / "pythonw.exe"
            with (
                mock.patch.object(sys, "argv", [str(script)]),
                mock.patch.object(sys, "executable", str(python)),
                mock.patch.object(Path, "exists", return_value=True),
            ):
                command = startup._startup_command()
        self.assertEqual(command, subprocess.list2cmdline([str(pythonw), str(script)]))

    def test_console_launcher_is_registered_directly(self):
        with tempfile.TemporaryDirectory() as directory:
            launcher = Path(directory) / "hourly-tracker.exe"
            with mock.patch.object(sys, "argv", [str(launcher)]):
                command = startup._startup_command()
        self.assertEqual(command, subprocess.list2cmdline([str(launcher)]))

    def test_frozen_app_launch_uses_executable_path(self):
        executable = r"C:\Program Files\Hourly Tracker\HourlyTracker.exe"
        with (
            mock.patch.object(sys, "frozen", True, create=True),
            mock.patch.object(sys, "executable", executable),
            mock.patch.object(sys, "argv", ["unrelated.py"]),
        ):
            command = startup._startup_command()
        self.assertEqual(command, subprocess.list2cmdline([executable]))

    def test_registry_setting_can_be_enabled_and_disabled(self):
        winreg = SimpleNamespace(
            HKEY_CURRENT_USER=object(),
            KEY_QUERY_VALUE=1,
            KEY_SET_VALUE=2,
            REG_SZ=3,
            OpenKey=mock.Mock(return_value=nullcontext("key")),
            CreateKeyEx=mock.Mock(return_value=nullcontext("key")),
            QueryValueEx=mock.Mock(return_value=("command", 3)),
            SetValueEx=mock.Mock(),
            DeleteValue=mock.Mock(),
        )
        with (
            mock.patch.object(startup.sys, "platform", "win32"),
            mock.patch.dict(sys.modules, {"winreg": winreg}),
            mock.patch.object(startup, "_startup_command", return_value="command"),
        ):
            self.assertTrue(startup.is_enabled())
            startup.set_enabled(True)
            startup.set_enabled(False)

        winreg.SetValueEx.assert_called_once_with(
            "key",
            startup.VALUE_NAME,
            0,
            winreg.REG_SZ,
            "command",
        )
        winreg.DeleteValue.assert_called_once_with("key", startup.VALUE_NAME)

    def test_missing_registry_value_means_disabled(self):
        winreg = SimpleNamespace(
            HKEY_CURRENT_USER=object(),
            KEY_QUERY_VALUE=1,
            OpenKey=mock.Mock(return_value=nullcontext("key")),
            QueryValueEx=mock.Mock(side_effect=FileNotFoundError),
        )
        with (
            mock.patch.object(startup.sys, "platform", "win32"),
            mock.patch.dict(sys.modules, {"winreg": winreg}),
        ):
            self.assertFalse(startup.is_enabled())


if __name__ == "__main__":
    unittest.main()
