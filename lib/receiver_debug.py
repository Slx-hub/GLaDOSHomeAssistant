from lib.I_intent_receiver import Receiver

class Debug(Receiver):
	def receive_intent(self, intent):
		print("Debug:")
		print("Intent:",intent.intent)
		for k,v in intent.slots.items():
			print(k, v)
		return ""
