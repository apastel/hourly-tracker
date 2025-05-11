import datetime
import subprocess


def get_today_str():
    return datetime.date.today().isoformat()


def get_current_session_login_time():
    try:
        output = subprocess.check_output("quser", shell=True, text=True)
        lines = output.strip().split("\n")
        for line in lines[1:]:
            parts = line.split()
            if "Active" in parts:
                # Usually the last 2 parts are date and time
                time_str = " ".join(parts[-2:])
                try:
                    login_time = datetime.datetime.strptime(
                        time_str, "%m/%d/%Y %I:%M %p"
                    )
                    return login_time
                except ValueError:
                    continue
    except subprocess.CalledProcessError as e:
        print("Failed to run quser:", e)
    return None


def get_or_update_first_login_today(self):
    today = get_today_str()
    current_session_login_time = (
        get_current_session_login_time() or datetime.datetime.now()
    )

    recorded_time = self.settings.value("today/login_time")
    recorded_date = self.settings.value("today/date")
    if recorded_time and recorded_date == today:
        recorded_time = datetime.datetime.fromisoformat(recorded_time)
        return min(recorded_time, current_session_login_time)

    # Save as today's first login
    self.settings.setValue("today/login_time", current_session_login_time.isoformat())
    self.settings.setValue("today/date", today)
    return current_session_login_time
