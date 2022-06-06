from lib.I_intent_receiver import Receiver, Reply

replies = {
 "Greet": "special/greet",
 "Howareyou": "special/howareyou",
 "ping": "special/conversation/pong.wav",
 "hello there": "special/conversation/kenobi.wav"
}

class Conversation(Receiver):
	def receive_intent(self, intent):
		replytext = replies.get(intent.intent)
		if not replytext:
			replytext = replies.get(intent.text, "")
		return Reply(glados_path=replytext)
