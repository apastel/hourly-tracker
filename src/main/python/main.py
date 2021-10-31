from PyQt5.QtCore import QTime
from fbs_runtime.application_context.PyQt5 import ApplicationContext
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget
from ui_form import Ui_MainWindow

import sys
import platform
import win32net
import win32api
import time

def get_logged_in_time():
    os_name = platform.uname()[0].lower()
    if os_name == "windows":
        user = win32net.NetUserGetInfo(None,win32api.GetUserName(),2)
        print(user["last_logon"])
    elif os_name.endswith("nix"):
        

if __name__ == "__main__":
    app = QApplication(sys.argv)
    ex = Ui_MainWindow()
    w = QMainWindow()
    ex.setupUi(w)
    get_logged_in_time()
    ex.startTime.setTime(QTime(7, 43))
    w.show()
    sys.exit(app.exec_())
