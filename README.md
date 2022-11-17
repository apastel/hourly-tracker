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
```
* Having to make several changes to get release to work
  * Ubuntu Dockerfile: `fpm -v 1.15.0`, `COPY *.tar.gz /tmp/requirements`
  * Uses python 3.6 which is old and /fbs/freeze/__init__.py uses subprocess.run() params not in 3.6
    * Attempting to use python 3.10.8 instead but python ssl extension error

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
