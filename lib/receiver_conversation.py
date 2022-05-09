from lib.I_intent_receiver import Receiver

replies = {
 "Greet": "special/greet",
 "Ping": "special/ping"
}

class Conversation(Receiver):
	def receive_intent(self, intent):
		return replies.get(intent.intent, "")
