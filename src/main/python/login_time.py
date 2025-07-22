import datetime
import logging
import subprocess


def get_current_session_login_time():
    try:
        output = subprocess.check_output("quser", shell=True, text=True)
        lines = output.strip().split("\n")
        for line in lines[1:]:
            parts = line.split()
            if "Active" in parts:
                time_str = " ".join(parts[-3:])
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
    current_session_login_time = (
        get_current_session_login_time() or datetime.datetime.now()
    )
    logging.debug(
        f"current_session_login_time: {current_session_login_time}  type: {type(current_session_login_time)}"
    )

    if self.get_date_from_recorded_login_time() == datetime.date.today():
        logging.debug("recorded_time's date matches today")
        recorded_login_time_str = self.settings.value("today/login_time")
        logging.debug(
            f"recorded_login_time_str (from settings): {recorded_login_time_str} type: {type(recorded_login_time_str)}"
        )
        recorded_time_for_min = datetime.datetime.fromisoformat(
            str(recorded_login_time_str)
        )
        logging.debug(
            f"min({recorded_time_for_min}, {current_session_login_time}) = {min(recorded_time_for_min, current_session_login_time)}"
        )
        return min(recorded_time_for_min, current_session_login_time)

    logging.debug("recorded_time != today, save new time")
    # Save as today's first login
    self.settings.setValue("today/login_time", current_session_login_time.isoformat())
    return current_session_login_time
