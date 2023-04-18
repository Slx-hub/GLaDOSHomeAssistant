from dataclasses import dataclass, field
from typing import List

class Receiver:
	def setup(self, settings):
		return

	def receive_intent(self, intent, settings):
		print("Override receive_intent!")

@dataclass
class Reply:
	glados_path: str = ""
	neopixel_color: List = field(default_factory=lambda: [0b11111111, 0, 0, 0, 0, 0])
	tts_reply: str = ""
	mqtt_topic: List = field(default_factory=lambda: [])
	mqtt_payload: List = field(default_factory=lambda: [])
	override_state: bool = True

class Intent:
	def __init__(self, intent, slots, text = ""):
		self.intent = intent
		self.slots = slots
		self.text = text
