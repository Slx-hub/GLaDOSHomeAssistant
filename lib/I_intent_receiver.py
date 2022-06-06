from dataclasses import dataclass, field
from typing import List

class Receiver:
	def receive_intent(self, intent):
		print("Override receive_intent!")

@dataclass
class Reply:
	glados_path: str = ""
	neopixel_color: List = field(default_factory=lambda: [0b11111111, 0, 0, 0, 0, 0])
	tts_reply: str = ""

class Intent:
	def __init__(self, intent, slots, text = ""):
		self.intent = intent
		self.slots = slots
		self.text = text
