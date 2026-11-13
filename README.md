# Hourly Tracker

Hourly Tracker projects when your workday is done from three things: when you started, how long you meant to work, and how long you were away. Away time is split into two kinds:

- **Idle** — the keyboard and mouse were still while the computer was awake and this app was running. The idle timer comes from the operating system (`GetLastInputInfo` on Windows, Mutter IdleMonitor or `xprintidle` on Linux, `IOHIDSystem` on macOS).
- **Offline** — the app could not observe the machine, because it was asleep, powered off, or this window was closed. That gap is measured from the last heartbeat, not from the input timer. Sleep does not advance the OS idle timer, so it is not mistaken for idle time.

A break shorter than the away threshold (20 minutes by default, same idea as the original app) stays part of the workday. The original default workday length is 9 hours. The projected end is:

`start + workday length + idle + offline`

## Correcting a bad away event

Idle and offline periods are rows in the away table. **Extends day** is the part of a row after your start time, and that is the part that pushes your finish later. Edit a row to fix its type or its start and end. Delete a row to put that time back into hours worked. The projected end moves earlier by the same amount.

Minimizing the window keeps it on the taskbar while idle tracking keeps running. The **X** button minimizes to the system tray by default; change it to quit in **Settings**. Double-click the tray icon to reopen the app, or use the tray menu to reopen or quit. Quitting stops tracking and the next launch records the time in between as offline once it passes the threshold.

When the projected workday ends, Windows displays a desktop notification. If work continues past the end time, the notification repeats every 20 minutes.

Open **Settings** from the main window to choose **System**, **Light**, or **Dark** appearance. System is the default and follows the operating system's appearance. The Windows startup option in the same dialog enables or disables starting Hourly Tracker when you sign in; it is available only on Windows.

## Build a Windows installer

Build on Windows with the same architecture as the desired installer. Install the Inno Setup compiler, then run:

```powershell
python -m pip install -e ".[build]"
python -m PyInstaller --clean --noconfirm packaging\windows\hourly_tracker.spec
$buildRef = git branch --show-current
if (-not $buildRef) { $buildRef = git describe --tags --exact-match HEAD 2>$null }
if (-not $buildRef) { $buildRef = "detached" }
$buildRef = ($buildRef -replace '[^A-Za-z0-9.-]', '-') -replace '^[.-]+|[.-]+$', ''
$commit = git rev-parse --short=12 HEAD
if ($LASTEXITCODE -ne 0) { throw "Could not determine the checked-out commit." }
$appVersion = "$buildRef-$commit"
ISCC.exe "/DAppVersion=$appVersion" packaging\windows\hourly-tracker.iss
```

The installer is written to `dist\HourlyTracker-Setup-<ref>-<commit>.exe`. Its displayed version and filename identify the selected branch or tag and the checked-out commit (for example, `HourlyTracker-Setup-feature-timeout-a1b2c3d4e5f6.exe`). Both the “start when I sign in” task and the “start now” post-install option are checked by default. The uninstaller removes the installed program, its startup registry value, and all per-user Hourly Tracker data, including the database and logs.

## Build and release with GitHub Actions

The **Build Windows installer** workflow can be run manually with a branch or tag ref. It builds the versioned installer and uploads it as the `hourly-tracker-installer` workflow artifact. GitHub Actions wraps workflow artifacts in a ZIP; the tag-and-release workflow extracts that artifact and attaches the `.exe` directly to the draft release, so release users can download the installer without extracting a ZIP.

To prepare a release, run **Tag and draft release**, providing a new `v`-prefixed tag and the branch to tag (default `main`). It creates or reuses that tag, dispatches the installer build on the tag, waits for the build to succeed, and creates a draft GitHub release with the installer attached. Publishing the draft release remains a manual step.

The frozen app is built without UPX packing, which can reduce false antivirus detections. As with other unsigned Windows executables, this cannot guarantee that Chrome or SmartScreen will not warn; Authenticode signing with a trusted code-signing certificate is the standard next step for improving publisher identity and reputation.

The database is separate from the original Hourly Tracker settings:

- Windows: `%APPDATA%\HourlyTrackerV2\hourly_tracker.db`
- macOS: `~/Library/Application Support/HourlyTrackerV2/hourly_tracker.db`
- Linux: `$XDG_DATA_HOME/HourlyTrackerV2/hourly_tracker.db` or `~/.local/share/HourlyTrackerV2/hourly_tracker.db`

## Run

The window uses Tk, which ships with Python. System tray support uses Pillow and pystray, installed from the project dependencies.

```powershell
python run.py
```

Or, after `python -m pip install -e .`:

```powershell
hourly-tracker
```

On the first launch, the start time is the current OS login and is displayed read-only in the main window. A clock time that is still later today is read as the most recent time it occurred, so 11:57 PM just after midnight means 11:57 PM yesterday, not later tonight.

## Tests

```powershell
python -m unittest discover -s tests -v
```

## Layout

```
pyproject.toml          project metadata; no runtime dependencies
run.py                  launch without installing
src/hourly_tracker/
  app.py                Tk window and away table
  tracker.py            idle / offline rules and workday math
  storage.py            SQLite settings and away events
  idle.py               OS idle probe
  login_time.py         OS login time
  formatting.py         durations and timestamps
  paths.py              per-user data directory
tests/                  rule tests and a window smoke test
packaging/windows/      PyInstaller frozen-app and Inno Setup installer definitions
```
