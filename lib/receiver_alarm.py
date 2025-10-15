from lib.I_intent_receiver import Receiver, Reply
import time, os, psutil
from threading import Thread

class System(Receiver):
	def receive_intent(self, intent, settings):
		if(intent.intent == "example"):
			doStuff()

def doStuff():
	time.sleep(10)
