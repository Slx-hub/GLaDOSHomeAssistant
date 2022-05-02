from lib.I_intent_receiver import Receiver

class x(Receiver):
	def receive_intent(self, intent):
		print(intent.intent)
		for k,v in intent.slots.items():
			print(k, v)
		return ""
