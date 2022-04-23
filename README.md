# Hourly Tracker

### Install packages
`$ pip install -r requirements/base.txt`

### Install pre-commit
`$ pre-commit install`

### Generate `ui_form.py`:
`$ pyuic5 -o src/main/python/ui_form.py src/main/resources/main_window.ui`

### Test
`$ fbs run`

### Build package:
```
fbs freeze
fbs installer
```
Free version of fbs does not support Linux without downgrading to PyQt5 (which requires Python 3.5/3.6)
## Todo
* Bug: App closes sometimes when right-clicking system tray icon
* Windows: actually track idle time
* Bug: idle time resets on linux when music playing in browser tab
* ~~When workday completes, then user increases workday hours to resume idle checking, then decreases hours back to completion, need to stop timer again~~
* ~~Notification when workday completes~~
* ~~Save "workday hours" and "idle threshold" to settings~~
