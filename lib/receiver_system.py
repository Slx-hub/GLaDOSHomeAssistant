from lib.I_intent_receiver import Receiver
import time, os
from threading import Thread

class System(Receiver):
	def receive_intent(self, intent):
		if(intent.intent == "Shutdown"):
			Thread(target=shutdown).start()
			return "Gute Nacht"

def shutdown():
	time.sleep(5)
	os.system("sudo shutdown -h now")
