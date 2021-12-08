# Hourly Tracker

Generate `ui_form.py`: 
`pyuic5 -o src/main/python/ui_form.py src/main/resources/main_window.ui`

## Todo
* Notification when workday completes
* Save "workday hours" and "idle threshold" to settings
* App icon
* Windows: actually track idle time
* Bug: idle time resets on linux when music playing in browser tab
* When workday completes, then user increases workday hours to resume idle checking, then decreases hours back to completion, need to stop timer again