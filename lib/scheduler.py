from time import sleep
import schedule

def setup(callback):
    schedule.every().day.at("18:00").do(callback, 'scheduled_evening_light')
    schedule.every().day.at("00:00").do(callback, 'scheduled_night_light')
    schedule.every().day.at("01:00").do(callback, 'scheduled_light_off')
    #schedule.every().minute.do(callback, 'scheduled_showcase_on')

def run():
    while True:
        schedule.run_pending()
        sleep(60)

def debug(t):
    print("I'm working... ", t)
    return