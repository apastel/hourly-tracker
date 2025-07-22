import ctypes
import ctypes.wintypes as wintypes
import datetime
import logging
import math
import os
import pathlib
import subprocess
import sys
import time
from pathlib import Path

import fbs.builtin_commands
import fbs_runtime.application_context.PySide6
import login_time
from generated import ui_main_window
from PySide6.QtCore import QDate
from PySide6.QtCore import QDateTime
from PySide6.QtCore import QSettings
from PySide6.QtCore import Qt
from PySide6.QtCore import QTime
from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMainWindow
from PySide6.QtWidgets import QMenu
from PySide6.QtWidgets import QSystemTrayIcon

APP_DATA_PATH: pathlib.Path = (
    pathlib.Path(os.getenv("APPDATA" if os.name == "nt" else "HOME"))
    / fbs_runtime.PUBLIC_SETTINGS["app_name"]
)
LOG_DIR = Path(APP_DATA_PATH) / "Logs"
os.makedirs(LOG_DIR, exist_ok=True)
NOTIF_INTERVAL_DEFAULT = 15  # minutes

logging.basicConfig(
    level=logging.DEBUG,
    format="[%(asctime)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(
            LOG_DIR / f"hourly-tracker_{time.strftime('%Y-%m-%d')}.log"
        ),
        logging.StreamHandler(sys.stdout),
    ],
    encoding="utf-8 ",
)


class MainWindow(QMainWindow, ui_main_window.Ui_MainWindow):
    def __init__(self):
        super().__init__()

        self.settings = QSettings(fbs_runtime.PUBLIC_SETTINGS["app_name"])
        try:
            self.resize(self.settings.value("mainwindow/size"))
            self.move(self.settings.value("mainwindow/pos"))
        except Exception:
            pass

        self._callbacks = []
        self._cur_minutes_idle = 0
        self.total_minutes_idle = 0
        if self.get_date_from_recorded_login_time() == datetime.date.today():
            self.total_minutes_idle = int(
                self.settings.value("today/total_minutes_idle", 0)
            )
        else:
            self.settings.setValue("today/total_minutes_idle", 0)

        if not self.settings.value("settings/notification_interval"):
            self.settings.setValue(
                "settings/notification_interval", NOTIF_INTERVAL_DEFAULT
            )
        idle_str = str(datetime.timedelta(minutes=self.total_minutes_idle))[:-3]
        self.is_idle = False
        self.setupUi(self)
        self.startTime.setTime(self.get_login_time())
        self.totalIdleTime.setTime(QTime.fromString(idle_str, "h:mm"))
        self.workdayHours.setValue(
            int(self.settings.value("settings/workday_hours", 9))
        )
        self.idleThreshold.setValue(
            int(self.settings.value("settings/idle_threshold", 20))
        )
        self.update_end_time()
        self.startTime.timeChanged.connect(self.update_end_time)
        self.startTime.timeChanged.connect(self.persist_updated_start_time)
        self.totalIdleTime.timeChanged.connect(self.update_end_time)
        self.workdayHours.valueChanged.connect(self.update_end_time)
        self.workdayHours.valueChanged.connect(self.save_settings)
        self.idleThreshold.valueChanged.connect(self.save_settings)
        self.endTime.timeChanged.connect(self.maybe_restart_timer)
        self.endTime.timeChanged.connect(self.update_tooltip)
        self.curIdleTime.setDisplayFormat("h'h' mm'm' ss's'")
        self.totalIdleTime.setDisplayFormat("h'h' mm'm'")

    def closeEvent(self, event):
        event.ignore()
        self.settings.setValue("mainwindow/size", self.size())
        self.settings.setValue("mainwindow/pos", self.pos())
        self.hide()

    @property
    def current_minutes_idle(self):
        return self._cur_minutes_idle

    @current_minutes_idle.setter
    def current_minutes_idle(self, new_value):
        if self._cur_minutes_idle != new_value:
            self._cur_minutes_idle = new_value
            self._notify_observers()

    def _notify_observers(self):
        for callback in self._callbacks:
            callback()

    def register_callback(self, callback):
        self._callbacks.append(callback)

    def get_login_time(self):
        if fbs.builtin_commands.is_windows():
            first_login_time = login_time.get_or_update_first_login_today(self)
        elif fbs.builtin_commands.is_linux():
            last_cmd = "last -R $USER -s 00:00"
            perl_cmd = r"perl -ne 'print unless /wtmp\sbegins/ || /^$/'"
            awk_cmd = "awk 'END {print $6}'"
            cmd = f"{last_cmd} | {perl_cmd} | {awk_cmd}"
            first_login_time = subprocess.getoutput(cmd).partition("\n")[0]
            first_login_time = datetime.datetime.strptime(first_login_time, "%H:%M")

        return QTime(first_login_time.hour, first_login_time.minute)

    def persist_updated_start_time(self):
        today = QDate.currentDate()
        datetime = QDateTime(today, self.startTime.time())
        iso_string = datetime.toString(Qt.ISODate)
        self.settings.setValue("today/login_time", iso_string)

    def update_end_time(self):
        workHours = self.workdayHours.value()
        idle_seconds = (
            self.totalIdleTime.time().hour() * 3600
            + self.totalIdleTime.time().minute() * 60
        )
        self.endTime.setTime(
            self.startTime.time().addSecs(workHours * 3600).addSecs(idle_seconds)
        )

    def check_idle_time(self):
        if fbs.builtin_commands.is_linux():
            # xprintidle doesn't work on wayland
            # seconds_idle = int(int(subprocess.getoutput("xprintidle")) / 1000)

            idle_cmd = (
                "dbus-send --print-reply --dest=org.gnome.Mutter.IdleMonitor "
                "/org/gnome/Mutter/IdleMonitor/Core org.gnome.Mutter.IdleMonitor.GetIdletime"
            )
            idle_result = subprocess.Popen(
                ["/bin/bash", "-c", idle_cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
            )
            millis_idle = int(idle_result.communicate()[0].rsplit(None, 1)[-1])
            seconds_idle = int(millis_idle / 1000)
            minutes_idle = math.floor(millis_idle / 1000 / 60)

        elif fbs.builtin_commands.is_windows():

            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)

            if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
                millis_idle = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
                seconds_idle = millis_idle // 1000
                minutes_idle = seconds_idle // 60

        self.current_minutes_idle = minutes_idle
        if self.current_minutes_idle == 0 and self.is_idle:
            self.consoleTextArea.appendPlainText(
                f"User returned from idle at {datetime.now().strftime('%I:%M %p')}"
            )
            self.is_idle = False

        idle_str = str(datetime.timedelta(seconds=seconds_idle))
        self.curIdleTime.setTime(QTime.fromString(idle_str, "h:mm:ss"))

    def increment_idle_time(self):
        if self.current_minutes_idle >= self.idleThreshold.value():
            if not self.is_idle:
                minutes_since_idle = datetime.datetime.now() - datetime.timedelta(
                    minutes=self.current_minutes_idle
                )
                self.consoleTextArea.appendPlainText(
                    f"User has been idle since "
                    f"{minutes_since_idle.strftime('%I:%M %p')}"
                )
                self.total_minutes_idle += self.current_minutes_idle
            else:
                self.total_minutes_idle += 1
            self.is_idle = True
            idle_str = str(datetime.timedelta(minutes=self.total_minutes_idle))[:-3]
            self.totalIdleTime.setTime(QTime.fromString(idle_str, "h:mm"))
            self.settings.setValue("today/date", datetime.date.today())
            self.settings.setValue("today/total_minutes_idle", self.total_minutes_idle)

    def check_workday_complete(self):
        now = QTime().currentTime()
        if now >= self.endTime.time():
            idle_timer.stop()
            finished_timer.stop()
            self.curIdleTime.setTime(QTime(0, 0))
            message = f"Workday completed at {self.endTime.time().toString('h:mm AP')}, go relax!"
            self.consoleTextArea.appendPlainText(message)
            self.show_workday_complete_notif()
            notification_timer.start(
                self.settings.value(
                    "settings/notification_interval", NOTIF_INTERVAL_DEFAULT
                )
                * 60
                * 1000
            )

    def show_workday_complete_notif(self):
        tray.showMessage(
            "Hourly Tracker",
            f"Workday completed at {self.endTime.time().toString('h:mm AP')}, go relax!",
            tray.icon(),
        )

    def maybe_restart_timer(self):
        if not idle_timer.isActive():
            idle_timer.start(1000)
        if not finished_timer.isActive():
            finished_timer.start(1000)
            self.consoleTextArea.appendPlainText("Restarted workday tracking...")
            notification_timer.stop()

    def tray_icon_clicked(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.show()

    def get_time_remaining(self):
        return self.endTime.time().toString("h:mm AP")

    def update_tooltip(self):
        tray.setToolTip(f"Hourly Tracker: End Time {self.get_time_remaining()}")

    def save_settings(self):
        self.settings.setValue("settings/workday_hours", self.workdayHours.value())
        self.settings.setValue("settings/idle_threshold", self.idleThreshold.value())

    def get_date_from_recorded_login_time(self):
        recorded_login_time_str = self.settings.value("today/login_time")
        if not recorded_login_time_str:
            logging.debug(
                "today/login_time did not exist, so get_date_from_recorded_login_time() == today"
            )
            return datetime.date.today()
        logging.debug(
            f"recorded_login_time_str (from settings): {recorded_login_time_str} type: {type(recorded_login_time_str)}"
        )

        # Try to parse recorded_time_str into a datetime object
        recorded_datetime_obj = None
        if recorded_login_time_str:
            try:
                # Ensure it's a string before parsing, in case QSettings returns something else
                recorded_datetime_obj = datetime.datetime.fromisoformat(
                    str(recorded_login_time_str)
                )
            except ValueError as e:
                logging.warning(
                    f"Failed to parse recorded_login_time_str {recorded_login_time_str!r}: {e}"
                )
                # Handle error: maybe clear the setting or treat as no recorded time
                recorded_datetime_obj = None  # Treat as if no valid time was recorded

        # Get the date portion from recorded_datetime_obj if it exists
        # This will be a datetime.date object (e.g., datetime.date(2025, 7, 21))
        recorded_date_obj = None
        if recorded_datetime_obj:
            recorded_date_obj = recorded_datetime_obj.date()
            logging.debug(
                f"recorded_date_obj: {recorded_date_obj} type: {type(recorded_date_obj)}"
            )
        return recorded_date_obj


if __name__ == "__main__":
    appctxt = fbs_runtime.application_context.PySide6.ApplicationContext()
    window = MainWindow()
    window.register_callback(window.increment_idle_time)
    idle_timer = QTimer()
    finished_timer = QTimer()
    notification_timer = QTimer()
    idle_timer.timeout.connect(window.check_idle_time)
    finished_timer.timeout.connect(window.check_workday_complete)
    notification_timer.timeout.connect(window.show_workday_complete_notif)
    idle_timer.start(1000)
    finished_timer.start(1000)

    tray = QSystemTrayIcon()

    tray.setIcon(QIcon(appctxt.get_resource("clock.png")))
    tray.activated.connect(window.tray_icon_clicked)
    quit = QAction("Quit")
    quit.triggered.connect(appctxt.app.quit)
    menu = QMenu()
    menu.addAction(quit)
    tray.setContextMenu(menu)
    tray.setToolTip(f"Hourly Tracker: End Time {window.get_time_remaining()}")
    tray.show()

    window.show()
    sys.exit(appctxt.app.exec())
