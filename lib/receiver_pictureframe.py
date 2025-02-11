from lib.I_intent_receiver import Receiver, Reply

class PictureFrame(Receiver):

    def receive_intent(self, intent, settings):
        if settings["url"] and intent.intent == "PictureFrame":
            return Reply(glados_path='command_success')
