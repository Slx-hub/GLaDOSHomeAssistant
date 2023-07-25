from time import sleep
import schedule as sched

def setup(callback, settings):
    sched.clear()
    if settings["daily"]:
        for key, value in settings["daily"].items():
            schedule(sched.every().day.at(key), callback, value)
    if settings["hourly"]:
        for key, value in settings["hourly"].items():
            schedule(sched.every().hour.at(key), callback, value)
    if settings["minutely"]:
        for key, value in settings["minutely"].items():
            schedule(sched.every().minute.at(key), callback, value)
    print("JOBS:", sched.get_jobs())

def schedule(scheduler, callback, config_val):
    elements = config_val.split(">")
    intent = elements[0]
    command = elements[1].strip()
    scheduler.do(callback, intent, command)

def run():
    while True:
        sched.run_pending()
        sleep(30)