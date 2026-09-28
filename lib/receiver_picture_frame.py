from lib.I_intent_receiver import Receiver
from lib.I_intent_receiver import Reply

# Actions http_bridge.py knows. It listens on hermes/http/PictureFrame, the
# same topic the scheduler uses for the timed frame updates.
ACTIONS = ('pf_display_image', 'pf_display_info_screen', 'pf_clear_display', 'pf_special_action')

class PictureFrame(Receiver):
	def receive_intent(self, intent, settings):
		action = intent.slots.get('action')
		if action not in ACTIONS:
			return None
		# "pf_display_image japan_cats" shows that image instead of a random one
		image = intent.slots.get('image')
		command = f'{action} {image}' if image else action
		return Reply(next_intent=f'hermes/http/PictureFrame> {command}')
