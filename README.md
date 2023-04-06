# Hourly Tracker

### Install packages
```
(inside venv)
pip install -r requirements/linux.txt
```

### Install pre-commit
```
pre-commit install
```

### Generate `ui_form.py`:
```
pyside6-uic -o src/main/python/ui_form.py src/main/resources/main_window.ui
```

### Test
```
fbs run
```

### Build package:
```
fbs freeze
fbs installer
```

### Release:

```
fbs gengpgkey
fbs register       # or `login` if you already have an account
fbs buildvm ubuntu # or `arch` / `fedora`
fbs runvm ubuntu
# In the Ubuntu virtual machine:
fbs release
  Done! Your users can now install your app via the following commands:
      sudo apt-get install apt-transport-https
      wget -qO - https://fbs.sh/apastel/HourlyTracker/public-key.gpg | sudo apt-key add -
      echo 'deb [arch=amd64] https://fbs.sh/apastel/HourlyTracker/deb stable main' | sudo tee /etc/apt/sources.list.d/hourlytracker.list
      sudo apt-get update
      sudo apt-get install hourlytracker
  If they already have your app installed, they can force an immediate update via:
      sudo apt-get update -o Dir::Etc::sourcelist="/etc/apt/sources.list.d/hourlytracker.list" -o Dir::Etc::sourceparts="-" -o APT::Get::List-Cleanup="0"
      sudo apt-get install --only-upgrade hourlytracker
  Finally, your users can also install without automatic updates by downloading:
      https://fbs.sh/apastel/HourlyTracker/HourlyTracker.deb
  Also, src/build/settings/base.json was updated with the new version.
```
Getting this issue running after installing
```
$ /opt/HourlyTracker/HourlyTracker
qt.qpa.plugin: Could not load the Qt platform plugin "xcb" in "" even though it was found.
This application failed to start because no Qt platform plugin could be initialized. Reinstalling the application may fix this problem.

Available platform plugins are: linuxfb, wayland-egl, vkkhrdisplay, offscreen, wayland, vnc, xcb, minimal, minimalegl, eglfs.

Aborted (core dumped)
```

## Todo
* Bug: App closes sometimes when right-clicking system tray icon
* Bug: Occasionally the app initializes with the start time hours digit being 1 instead of what it actually is
* Keep tracking idle time after workday finishes so that if you extend hours, it still tracked
* Windows: actually track idle time
* Problem: idle time resets on linux when music playing in browser tab
* Persist console log for the day so that when user closes/re-opens app, the console so far for the day is shown instead of starting over.
* ~~When workday completes, then user increases workday hours to resume idle checking, then decreases hours back to completion, need to stop timer again~~
* ~~Notification when workday completes~~
* ~~Save "workday hours" and "idle threshold" to settings~~
