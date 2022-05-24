#!/usr/bin/env python3
import paho.mqtt.client as mqtt
import json, yaml

from lib.I_intent_receiver import Intent
from lib import receiver_shield
from lib import receiver_debug
from lib import receiver_conversation
from lib import receiver_system
from lib import receiver_timer
from lib import module_speaker as speaker
from lib import module_neopixel as neopixel

receivers = {
	'Debug': receiver_debug.Debug(),
	'Conversation': receiver_conversation.Conversation(),
	'System': receiver_system.System(),
	'Shield': receiver_shield.Shield(),
	'Timer': receiver_timer.Timer(),
}

config = {}

def on_connect(client, userdata, flags, rc):
	"""Called when connected to MQTT broker."""
	client.subscribe("hermes/hotword/#")
	client.subscribe("hermes/asr/textCaptured")
	client.subscribe("hermes/intent/#")
	client.subscribe("hermes/nlu/intentNotRecognized")
	print("Connected!!")


def on_disconnect(client, userdata, flags, rc):
	"""Called when disconnected from MQTT broker."""
	client.reconnect()


def on_message(client, userdata, msg):
	"""Called each time a message is received on a subscribed topic."""
	payload = json.loads(msg.payload)
	print("TOPIC: ", msg.topic)
	print("PAYLOAD: ", payload)

	if msg.topic.startswith('hermes/hotword/') and msg.topic.endswith('/detected'):
		neopixel.send_rgb_command(0b11111111, 9, 4, 0, 0, 255)
		speaker.aplay_random_file("wake")
		client.publish("hermes/asr/startListening", json.dumps({"stopOnSilence": "true"}))
		return

	if msg.topic == "hermes/asr/textCaptured":
		neopixel.send_rgb_command(0b11111111, 4, 2, 0, 0, 255)
		client.publish("hermes/nlu/query", json.dumps({"input": payload["text"]}))
		return

	if 'intent' not in payload:
		return

	intent = payload_to_intent(payload)

	list = config["registration"]["All"]
	list += config["registration"][intent.intent]
	reply = ""

	for receiver in config["registration"]["All"]:
		reply = receivers[receiver].receive_intent(intent)
		if(reply != ""):
			break

	if reply == "":
		speaker.aplay_random_file("command_unknown")
		return

	speaker.aplay_random_file(reply)
	neopixel.send_rgb_command(0b11111111, 0, 0, 0, 0, 0)

def payload_to_intent(payload):
	intent = payload["intent"]["intentName"]
	slots = {}
	for slot in payload["slots"]:
		slots[slot["slotName"]] = slot["value"]["value"]
	return Intent(intent,slots)

def get_slot_by_entity(json, entity):
	for slot in json["slots"]:
		if slot["entity"] == entity:
			return slot
	raise Exception('No such entity slot')

with open("config.yaml", 'r') as stream:
	config = yaml.safe_load(stream)

# Create MQTT client and connect to broker

client = mqtt.Client()
client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.on_message = on_message

client.connect("localhost", 1883)
client.loop_forever()
