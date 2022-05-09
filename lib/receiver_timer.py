
import time
import multiprocessing
import datetime
import time
from lib.I_intent_receiver import Receiver
from lib import module_speaker

class Timer(Receiver):
	timer_dict = dict()

	def receive_intent(self, intent):
		if intent.intent == "SetTimer":
			seconds = int(intent.slots["amount"]) * get_scale(intent.slots["scale"])
			if seconds < 10 or seconds > 43200: # > 12 hours
				return "command_failed"
			self.add_timer(seconds)

		if intent.intent == "RemoveTimer":
			if intent.slots["index"] == "all":
				for key in self.timer_dict.keys():
					self.remove_timer(key)
			else:
				index = intent.slots["index"]

				for i, key in enumerate(self.timer_dict.keys()):
					if i == index - 1:
						key_to_delete = key
				if key_to_delete and key_to_delete in self.timer_dict: 
					self.remove_timer(key_to_delete)
				else:
					return "command_failed"

		return "command_success"

	def add_timer(self, seconds):
		id = generate_timer_id(seconds)
		proc = multiprocessing.Process(target=self.init_timer_task, args=(seconds, id,))
		self.timer_dict[id] = proc
		proc.start()
		print("timer set: ", id)

	def remove_timer(self, id):
		self.timer_dict[id].terminate()
		del self.timer_dict[id]
		print("deleted timer ", id)

	def timer_ring(self, id):
		del self.timer_dict[id]
		print("done with timer ", id)
		module_speaker.aplay_random_file("special/timer/ring")
	
	def init_timer_task(self, seconds, id):
		time.sleep(seconds)
		self.timer_ring(id)

def generate_timer_id(seconds):
	e = datetime.datetime.now()
	return "Timer{0}:{1}:{2}with{3}".format(e.hour, e.minute, e.second, seconds)

def get_scale(word):
	if word == "seconds":
		return 1
	if word == "minutes":
		return 60
	if word == "hours":
		return 3600