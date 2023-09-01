from lib.I_intent_receiver import Receiver, Reply

class Conversation(Receiver):
	def receive_intent(self, intent, settings):
		return Reply(glados_path=Receiver.get_reply_from_settings(intent, settings, 'command_unknown'))
