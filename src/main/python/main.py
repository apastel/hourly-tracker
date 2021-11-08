from PyQt5.QtCore import QTime, QTimer
from PyQt5.QtWidgets import QApplication, QMainWindow
from ui_form import Ui_MainWindow

import sys
import platform
import math
os_name = platform.uname()[0].lower()
if os_name == "windows":
    import win32net
    import win32api
from datetime import datetime
import subprocess


class MainWindow(QMainWindow, Ui_MainWindow):
    def __init__(self):
        super().__init__()

        self._minutes_idle = 0
        self._callbacks = []
        self.setWindowTitle("Hourly Tracker")
        self.setupUi(self)
        self.total_minutes_idle = 0
        self.startTime.setTime(self.get_login_time())
        self.update_end_time()
        self.startTime.timeChanged.connect(self.update_end_time)
        self.idleTime.timeChanged.connect(self.update_end_time)
        self.workdayHours.valueChanged.connect(self.update_end_time)


    @property
    def minutes_idle(self):
        return self._minutes_idle


    @minutes_idle.setter
    def minutes_idle(self, new_value):
        if (self._minutes_idle != new_value and new_value != 0):
            self._minutes_idle = new_value
            self._notify_observers()


    def _notify_observers(self):
        for callback in self._callbacks:
            callback()


    def register_callback(self, callback):
        self._callbacks.append(callback)


    def get_login_time(self):
        if os_name == "windows":
            user = win32net.NetUserGetInfo(None,win32api.GetUserName(),2)
            first_login_time = datetime.fromtimestamp(user["last_logon"])
        elif os_name.endswith("linux"):
            cmd = "last -R $USER -s 00:00 | perl -ne 'print unless /wtmp\sbegins/ || /^$/' | awk 'END {print $6}'"
            first_login_time = subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.partition('\n')[0]
            first_login_time = datetime.strptime(first_login_time, '%H:%M')

        return QTime(first_login_time.hour, first_login_time.minute)


    def update_end_time(self):
        workHours = self.workdayHours.value()
        idle_seconds = self.idleTime.time().hour() * 3600 + self.idleTime.time().minute() * 60
        self.endTime.setTime(self.startTime.time().addSecs(workHours * 3600).addSecs(idle_seconds))


    def check_idle_time(self):
        if os_name.endswith("linux"):
            seconds_idle = int(int(subprocess.getoutput('xprintidle')) / 1000)
            self.minutes_idle = math.floor(seconds_idle / 60)
            print(f"Idle time: {self.minutes_idle}m {seconds_idle}s ")
        else:
            print(f"Idle time not yet implemented in {os_name}")


    def increment_idle_time(self):
        self.idleTime.setTime(self.idleTime.time().addSecs(60))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.register_callback(window.increment_idle_time)
    timer = QTimer()
    timer.timeout.connect(window.check_idle_time)
    timer.start(1000)
    window.show()
    sys.exit(app.exec_())
