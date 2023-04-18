from lib.I_intent_receiver import Receiver, Reply
import soco

class Sonos(Receiver):

    sonos: soco.SoCo
    sonos_running = False

    def setup(self, settings):
        self.sonos = soco.discovery.by_name(settings["default-device"])
        #self.sonos.play_uri("x-sonos-spotify:spotify:playlist:37i9dQZF1DXb57FjYWz00c")

    def receive_intent(self, intent, settings):

        if intent.intent == "StartPlaylist":
            return Reply(glados_path='command_success')
