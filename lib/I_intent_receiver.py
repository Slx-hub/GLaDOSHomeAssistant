class Receiver:
	def receive_intent(self, intent):
		print("Override receive_intent!")

class Intent:
	def __init__(self, intent, slots):
		self.intent = intent
		self.slots = slots
