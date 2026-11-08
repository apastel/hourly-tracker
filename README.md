# Hourly Tracker

Hourly Tracker projects when your workday is done from three things: when you started, how long you meant to work, and how long you were away. Away time is split into two kinds:

- **Idle** — the keyboard and mouse were still while the computer was awake and this app was running. The idle timer comes from the operating system (`GetLastInputInfo` on Windows, Mutter IdleMonitor or `xprintidle` on Linux, `IOHIDSystem` on macOS).
- **Offline** — the app could not observe the machine, because it was asleep, powered off, or this window was closed. That gap is measured from the last heartbeat, not from the input timer. Sleep does not advance the OS idle timer, so it is not mistaken for idle time.

A break shorter than the away threshold (20 minutes by default, same idea as the original app) stays part of the workday. The original default workday length is 9 hours. The projected end is:

`start + workday length + idle + offline`

## Correcting a bad away event

Idle and offline periods are rows in the away table. **Extends day** is the part of a row after your start time, and that is the part that pushes your finish later. Edit a row to fix its type or its start and end. Delete a row to put that time back into hours worked. The projected end moves earlier by the same amount.

Minimizing or closing the window sends it to the system tray while idle tracking keeps running. Double-click the tray icon to reopen it. Use the tray menu to reopen or quit the app. Quitting stops tracking and the next launch records the time in between as offline once it passes the threshold.

When the projected workday ends, Windows displays a desktop notification. If work continues past the end time, the notification repeats every 20 minutes.

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

On the first launch, the start time is the current OS login. Change it in the Start field if that is not when you began working. A clock time that is still later today is read as the most recent time it occurred, so 11:57 PM just after midnight means 11:57 PM yesterday, not later tonight.

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
```
