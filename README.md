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
  * Running the resulting app installed via the package manager crashes with:
  ```
  apastel@apastel-laptop:~/dev/hourlyTracker$ /opt/HourlyTracker/HourlyTracker
  Traceback (most recent call last):
    File "main.py", line 14, in <module>
  ModuleNotFoundError: No module named 'fbs_runtime.application_context'
  [56473] Failed to execute script main
  ```
  * Asked the developer for help and he says you have to get the fbs pro tarball installed inside the VM "somehow". He said the manual "should" have a solution but if not then I'm on my own because I only have the Hobbyist license. Fucking b.s.
    * https://github.com/mherrmann/fbs/issues/294
    * Trying to do install via a URL like the other guy suggested
      * `fbs @ https://drive.google.com/uc?export=download&id=1YtW5VYfmc-esB2JwycbQeOnynX5LdDXW`
      * But got this error when doing `fbs release 0.1.0`:
  ```
  Traceback (most recent call last):
  File "/root/.pyenv/versions/3.6.12/bin/fbs", line 11, in <module>
    load_entry_point('fbs==1.1.3', 'console_scripts', 'fbs')()
  File "/root/.pyenv/versions/3.6.12/lib/python3.6/site-packages/fbs/__main__.py", line 17, in _main
    fbs.cmdline.main()
  File "/root/.pyenv/versions/3.6.12/lib/python3.6/site-packages/fbs/cmdline.py", line 32, in main
    fn(*args)
  File "/root/.pyenv/versions/3.6.12/lib/python3.6/site-packages/fbs/builtin_commands/__init__.py", line 478, in release
    freeze()
  File "/root/.pyenv/versions/3.6.12/lib/python3.6/site-packages/fbs/builtin_commands/__init__.py", line 165, in freeze
    freeze_ubuntu(debug=debug)
  File "/root/.pyenv/versions/3.6.12/lib/python3.6/site-packages/fbs/freeze/ubuntu.py", line 4, in freeze_ubuntu
    freeze_linux(debug)
  File "/root/.pyenv/versions/3.6.12/lib/python3.6/site-packages/fbs/freeze/linux.py", line 8, in freeze_linux
    run_pyinstaller(debug=debug)
  File "/root/.pyenv/versions/3.6.12/lib/python3.6/site-packages/fbs/freeze/__init__.py", line 48, in run_pyinstaller
    cp = run(args, capture_output=True, text=True)
  File "/root/.pyenv/versions/3.6.12/lib/python3.6/subprocess.py", line 423, in run
    with Popen(*popenargs, **kwargs) as process:
  TypeError: __init__() got an unexpected keyword argument 'capture_output'
  ```
  * Fixed this by editing the ubuntu Dockerfile to use Python 3.7.0 (can't use 3.10 or else get error with ssl mentioned above)
  * Figured if I'm already editing the Dockerfile might as well modify it to copy in the tarball instead of pulling from URL
  * Finally got the VM to build again and installed the release package, but app fails to start with:
```
Traceback (most recent call last):
  File "main.py", line 14, in <module>
  File "PyInstaller/loader/pyimod02_importers.py", line 352, in exec_module
  File "fbs_runtime/application_context/PySide6.py", line 2, in <module>
ImportError: /opt/HourlyTracker/libz.so.1: version `ZLIB_1.2.9' not found (required by /opt/HourlyTracker/libQt6Gui.so.6)
[106662] Failed to execute script 'main' due to unhandled exception!
```
 * Got past that issue with this https://stackoverflow.com/a/50097275/1186464
 * But then next issue running is this:
 ```
 qt.qpa.plugin: Could not find the Qt platform plugin "xcb" in ""
 This application failed to start because no Qt platform plugin could be initialized. Reinstalling the application may fix this problem.
 Aborted (core dumped)
 ```
 * This is seeming less and less worth it, esp. if other people are gonna have these problems running it.
 * Tried installing a bunch of random Qt shit but didn't fix it. I'm done.

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
