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
			return healthCheck()
		
def healthCheck():
	print(psutil.virtual_memory().percent)
	if psutil.virtual_memory().percent > 80.0:
		Thread(target=reboot).start()
		return Reply(glados_path='special/shutdown/good night.wav')
	return Reply(neopixel_color=[0b00101010, 30, 0, 0, 0, 2])

def shutdown():
	time.sleep(10)
	os.system("sudo shutdown -h now")


def reboot():
	time.sleep(10)
	os.system("sudo reboot")
