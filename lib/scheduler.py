from time import sleep
import schedule

def setup(callback, settings):
    schedule.clear()
    if settings["daily"]:
        for key, value in settings["daily"].items():
            schedule.every().day.at(key).do(callback, value)
    if settings["hourly"]:
        for key, value in settings["hourly"].items():
            schedule.every().hour.at(key).do(callback, value)
    if settings["minutely"]:
        for key, value in settings["minutely"].items():
            schedule.every().minute.at(key).do(callback, value)
    print("JOBS:", schedule.get_jobs())

def run():
    while True:
        schedule.run_pending()
        sleep(30)