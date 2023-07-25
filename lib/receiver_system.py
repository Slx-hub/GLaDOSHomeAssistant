from lib.I_intent_receiver import Receiver, Reply
import time, os
from threading import Thread

class System(Receiver):
	def receive_intent(self, intent, settings):
		if(intent.intent == "Shutdown"):
			Thread(target=shutdown).start()
			return Reply(glados_path='special/shutdown')
		if(intent.intent == "Reboot"):
			Thread(target=reboot).start()
			return Reply(glados_path='special/shutdown')

def shutdown():
	time.sleep(10)
	os.system("sudo shutdown -h now")


def reboot():
	time.sleep(10)
	os.system("sudo reboot")
