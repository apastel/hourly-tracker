from PyQt5.QtCore import QTime
from fbs_runtime.application_context.PyQt5 import ApplicationContext
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget
from ui_form import Ui_MainWindow

import sys
import platform
from datetime import datetime
import subprocess

def get_login_time():
    os_name = platform.uname()[0].lower()
    if os_name == "windows":
        user = win32net.NetUserGetInfo(None,win32api.GetUserName(),2)
        print(user["last_logon"])
    elif os_name.endswith("linux"):
        cmd = "last -R $USER -s 00:00 | perl -ne 'print unless /wtmp\sbegins/ || /^$/' | awk 'END {print $6}'"
        first_login_time = subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.partition('\n')[0]
        first_login_time = datetime.strptime(first_login_time, '%H:%M')
        return QTime(first_login_time.hour, first_login_time.minute)
        

if __name__ == "__main__":
    app = QApplication(sys.argv)
    ex = Ui_MainWindow()
    w = QMainWindow()
    ex.setupUi(w)
    ex.startTime.setTime(get_login_time())
    w.show()
    sys.exit(app.exec_())
