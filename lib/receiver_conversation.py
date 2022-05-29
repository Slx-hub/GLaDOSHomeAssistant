from lib.I_intent_receiver import Receiver, Reply

replies = {
 "Greet": "special/greet",
 "Ping": "special/ping"
}

class Conversation(Receiver):
	def receive_intent(self, intent):
		replytext = replies.get(intent.intent, "")
		return Reply(glados_path=replytext)
