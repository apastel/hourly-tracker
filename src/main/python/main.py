import math
import platform
import subprocess
import sys
from datetime import date
from datetime import datetime
from datetime import timedelta

from fbs_runtime.application_context.PyQt5 import ApplicationContext
from PyQt5.QtCore import QSettings
from PyQt5.QtCore import QTime
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QAction
from PyQt5.QtWidgets import QMainWindow
from PyQt5.QtWidgets import QMenu
from PyQt5.QtWidgets import QSystemTrayIcon
from ui_form import Ui_MainWindow

os_name = platform.uname()[0].lower()
# if os_name == "windows":
#     import win32net
#     import win32api


class MainWindow(QMainWindow, Ui_MainWindow):
    def __init__(self):
        super().__init__()

        self.settings = QSettings("Axlecorp", "HourlyTracker")
        try:
            self.resize(self.settings.value("mainwindow/size"))
            self.move(self.settings.value("mainwindow/pos"))
        except Exception:
            pass

        self._callbacks = []
        self._cur_minutes_idle = 0
        self.total_minutes_idle = 0
        if self.settings.value("today/date", date.today()) == date.today():
            self.total_minutes_idle = int(
                self.settings.value("today/total_minutes_idle", 0)
            )
        idle_str = str(timedelta(minutes=self.total_minutes_idle))[:-3]
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
        tray.showMessage(
            "Tray Program",
            "Application was minimized to Tray",
            QSystemTrayIcon.Information,
            2000,
        )

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
        if os_name == "windows":
            system_startup_time = " ".join(
                subprocess.run(
                    'net statistics workstation | FINDSTR "statistics since"',
                    shell=True,
                    capture_output=True,
                    text=True,
                ).stdout.split(" ")[-2:]
            ).strip()
            first_login_time = datetime.strptime(system_startup_time, "%I:%M:%S %p")
        elif os_name.endswith("linux"):
            last_cmd = "last -R $USER -s 00:00"
            perl_cmd = r"perl -ne 'print unless /wtmp\sbegins/ || /^$/'"
            awk_cmd = "awk 'END {print $6}'"
            cmd = f"{last_cmd} | {perl_cmd} | {awk_cmd}"
            first_login_time = subprocess.getoutput(cmd).partition("\n")[0]
            first_login_time = datetime.strptime(first_login_time, "%H:%M")

        return QTime(first_login_time.hour, first_login_time.minute)

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
        if os_name.endswith("linux"):
            seconds_idle = int(int(subprocess.getoutput("xprintidle")) / 1000)
            minutes_idle = math.floor(seconds_idle / 60)
            self.current_minutes_idle = minutes_idle
            if self.current_minutes_idle == 0 and self.is_idle:
                self.consoleTextArea.appendPlainText(
                    f"User returned from idle at {datetime.now().strftime('%I:%M %p')}"
                )
                self.is_idle = False
            idle_str = str(timedelta(seconds=seconds_idle))
            self.curIdleTime.setTime(QTime.fromString(idle_str, "h:mm:ss"))
        else:
            print("Not yet implemented")

    def increment_idle_time(self):
        if self.current_minutes_idle >= self.idleThreshold.value():
            if not self.is_idle:
                minutes_since_idle = datetime.now() - timedelta(
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
            idle_str = str(timedelta(minutes=self.total_minutes_idle))[:-3]
            self.totalIdleTime.setTime(QTime.fromString(idle_str, "h:mm"))
            self.settings.setValue("today/date", date.today())
            self.settings.setValue("today/total_minutes_idle", self.total_minutes_idle)

    def check_workday_complete(self):
        now = QTime().currentTime()
        if now >= self.endTime.time():
            self.consoleTextArea.appendPlainText(
                f"Workday completed at "
                f"{self.endTime.time().toString('h:mm AP')}, go relax!"
            )
            tray.showMessage(
                "Hourly Tracker",
                f"Workday completed at "
                f"{self.endTime.time().toString('h:mm AP')}, go relax!",
                QSystemTrayIcon.Information,
                15000,
            )
            idle_timer.stop()
            finished_timer.stop()
            self.curIdleTime.setTime(QTime(0, 0))

    def maybe_restart_timer(self):
        if not idle_timer.isActive():
            idle_timer.start(1000)
        if not finished_timer.isActive():
            finished_timer.start(1000)
            self.consoleTextArea.appendPlainText("Restarted workday tracking...")

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


if __name__ == "__main__":
    appctxt = ApplicationContext()
    window = MainWindow()
    window.register_callback(window.increment_idle_time)
    idle_timer = QTimer()
    finished_timer = QTimer()
    idle_timer.timeout.connect(window.check_idle_time)
    finished_timer.timeout.connect(window.check_workday_complete)
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
    sys.exit(appctxt.app.exec_())
