
import time
from multiprocessing import Process
import datetime
import time
from lib.I_intent_receiver import Receiver, Reply
from lib import module_speaker
from lib import module_neopixel as neopixel

class Timer(Receiver):
	timer_dict = dict()

	def receive_intent(self, intent):
		# because threads cant FUCKING clean up after themselves...
		clean_timers(self.timer_dict)

		if intent.intent == "SetTimer":
			seconds = int(intent.slots["amount"]) * get_scale(intent.slots["scale"])
			if seconds < 10 or seconds > 43200: # > 12 hours
				return Reply(glados_path='command_failed')
			self.add_timer(seconds)
			replytext = str(intent.slots["amount"]) + intent.slots["scale"]
			return Reply(glados_path='special/timer/create', tts_reply=replytext)

		if intent.intent == "RemoveTimer":
			if intent.slots["index"] == "all":
				for key in list(self.timer_dict):
					self.remove_timer(key)
			else:
				index = intent.slots["index"]
				key_to_delete = ''
				for i, key in enumerate(self.timer_dict.keys()):
					if i == index - 1:
						key_to_delete = key
				if key_to_delete in self.timer_dict: 
					self.remove_timer(key_to_delete)
				else:
					return Reply(glados_path='command_failed')
			return Reply(glados_path='command_success')

		if intent.intent == "QueryTimer":
			index = int(intent.slots["index"])
			result = ""
			for i, key in enumerate(self.timer_dict.keys()):
				if i == index - 1:
					result = key
			if result in self.timer_dict: 
				time = secs_to_time_string(get_secs_till_done(result))
				return Reply(glados_path='special/timer/query', tts_reply=time)
			else:
				return Reply(glados_path='command_failed')

	def add_timer(self, seconds):
		id = generate_timer_id(seconds)
		self.timer_dict[id] = Process(target=self.init_timer_task, args=(seconds, id,))
		self.timer_dict[id].start()
		print("timer set: ", id)

	def remove_timer(self, id):
		self.timer_dict[id].terminate()
		del self.timer_dict[id]
		print("deleted timer ", id)

	def timer_ring(self, id):
		print("done with timer ", id)
		neopixel.send_rgb_command(0b11111111, 5, 0, 0, 0, 50)
		module_speaker.aplay_random_file("special/timer/ring")
	
	def init_timer_task(self, seconds, id):
		time.sleep(seconds)
		self.timer_ring(id)

def clean_timers(dict):
	for key in list(dict):
		print("Cleaning timer " + key + " ?")
		if get_secs_till_done(key) < 0:
			print("YES!")
			del dict[key]

def get_secs_till_done(id):
	return int(id.split("UNTIL_",1)[1]) - int(time.time())

def secs_to_time_string(seconds):
	hours = seconds // 3600
	seconds %= 3600
	minutes = seconds // 60
	seconds %= 60
	time_string = " "
	time_string += str(hours) + " hours" if hours != 0 else ""
	time_string += str(minutes) + " minutes" if minutes != 0 else ""
	time_string += str(seconds) + " seconds" if seconds != 0 else ""
	return time_string

def generate_timer_id(seconds):
	e = datetime.datetime.now()
	return "Timer_AT_{0}:{1}:{2}_WITH_{3}_UNTIL_{4}".format(e.hour, e.minute, e.second, seconds, int(time.time() + seconds))

def get_scale(word):
	if word == "seconds" or word == "second":
		return 1
	if word == "minutes" or word == "minute":
		return 60
	if word == "hours" or word == "hour":
		return 3600