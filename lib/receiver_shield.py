import lib.module_apa102 as module_apa102
import time
from lib.I_intent_receiver import Receiver
from gpiozero import LED

color_strings = ["off","white","red","green","blue","yellow","magenta","cyan"]
color_to_rgb = [[0,0,0],[1,1,1],[1,0,0],[0,1,0],[0,0,1],[1,1,0],[1,0,1],[0,1,1]]

class Shield(Receiver):
	PX_COUNT = 12
	def __init__(self):
		self.dev = module_apa102.APA102(num_led=self.PX_COUNT)
		self.power = LED(5)
		self.power.on()
		# self.set_pixels(1,1,1,1)

	def receive_intent(self, intent):
		if intent.intent == "ChangeLightState":
			self.set_color("weiss" if intent.slots["state"] == "on" else "off")
		if intent.intent == "ChangeLightColor":
			self.set_color(intent.slots["color"])
		return "command_success"

	def set_pixels(self, r, g, b, a=100):
		for led in range(self.PX_COUNT):
			self.dev.set_pixel(led, r, g, b, a)
		self.dev.show()

	def set_color_index(self, index):
		rgbval = color_to_rgb[index]
		self.set_pixels(rgbval[0], rgbval[1], rgbval[2])

	def set_color(self, color):
		self.set_color_index(color_strings.index(color))

if __name__ == "__main__":
	px = Shield()
	while True:
		for color in range(len(color_to_rgb)):
			px.set_color_index(color)
			time.sleep(3)
