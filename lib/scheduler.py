from time import sleep
import schedule as sched
import re

def setup(callback, settings):
    sched.clear()
    if settings["daily"]:
        for key, value in sanitize_config_keys(settings["daily"]):
            schedule(sched.every().day.at(key), callback, value)
    if settings["hourly"]:
        for key, value in sanitize_config_keys(settings["hourly"]):
            schedule(sched.every().hour.at(key), callback, value)
    if settings["everyXminutes"]:
        for key, value in sanitize_config_keys(settings["everyXminutes"]):
            schedule(sched.every(int(key)).minutes, callback, value)
    print("JOBS:", sched.get_jobs())

def sanitize_config_keys(settings):
    sanitized_keys = []
    for key in settings.keys():
        if key.startswith('<'):
            continue
        sanitized_keys.add((re.sub("-\d", "", key), settings[key]))
    return sanitized_keys

def schedule(scheduler, callback, config_val):
    elements = config_val.split(">")
    intent = elements[0]
    command = elements[1].strip()
    scheduler.do(callback, intent, command)

def run():
    while True:
        sched.run_pending()
        sleep(30)