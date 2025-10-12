from lib.I_intent_receiver import Receiver, Reply
import time, os, psutil
from threading import Thread

class System(Receiver):
	def receive_intent(self, intent, settings):
		if(intent.intent == "Shutdown"):
			Thread(target=shutdown).start()
			return Reply(glados_path='special/shutdown')
		if(intent.intent == "Reboot"):
			Thread(target=reboot).start()
			return Reply(glados_path='special/shutdown')
		if(intent.intent == "HealthCheck"):
			return healthCheck(settings)
		
def healthCheck(settings):
	threshold = settings.get("ram-threshold", 80.0)
	if psutil.virtual_memory().percent > threshold:
		Thread(target=reboot).start()
		return Reply(glados_path='special/healthcheck/better restart.wav')
	return Reply(glados_path='special/healthcheck/all good.wav', neopixel_color=[0b11111111, 8, 30, 0, 0, 3])

def shutdown():
	time.sleep(10)
	os.system("sudo shutdown -h now")


def reboot():
	time.sleep(10)
	os.system("sudo reboot")
