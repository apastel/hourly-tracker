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
    * Testing on Windows and it's now installing this version on it's own without custom changes?
  * It copies my requirements file into the container, and then fails when the pip install in the vm can't find the fbs_pro.tar.gz file because it's not copied into the container
    * Workaround: change `fbs_pro-1.1.3.tar.gz` to just `fbs` in base.txt before running `buildvm`
    * On ubuntu and fedora this works. But on arch the fbs commands say that they only work with < Python 3.6 (arch Dockerfile uses Python 3.9.6)
  * Running `fbs release 0.1.0` inside Ubuntu container on my windows host
    * `boto3` module not found; had to add it to my base.txt
    * `urllib.error.URLError: <urlopen error [Errno 111] Connection refused>`
      * Tried again and now working
      ```
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
  * Running `fbs release 0.1.0` inside fedora container
    * `Critical: Cannot rename ./.repodata/ -> ./repodata/: Permission denied`
  * Linux host only: Uses python 3.6 which is old and /fbs/freeze/__init__.py uses subprocess.run() params not in 3.6
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
