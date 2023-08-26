from lib.I_intent_receiver import Receiver, Reply

class Conversation(Receiver):
	def receive_intent(self, intent, settings):
		replytext = settings.get(intent.intent)
		if not replytext:
			replytext = settings.get(intent.text, "")
		return Reply(glados_path=replytext)
