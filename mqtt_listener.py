#!/usr/bin/env python3
import paho.mqtt.client as mqtt
import json, yaml

from lib.I_intent_receiver import Intent
from lib.I_intent_receiver import Reply
from lib import receiver_shield
from lib import receiver_debug
from lib import receiver_conversation
from lib import receiver_system
from lib import receiver_timer
from lib import module_speaker as speaker
from lib import module_neopixel as neopixel
from lib import alias_converter

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

	reply = handle_message(client, msg.topic, payload)
	if reply:
		speaker.aplay_random_file(reply.glados_path)
		if reply.neopixel_color:
			neopixel.send_rgb_command(*reply.neopixel_color)
		if reply.tts_reply and reply.tts_reply != '':
			client.publish("hermes/tts/say", json.dumps({"text": reply.tts_reply}))

def handle_message(client, topic, payload):

	if topic.startswith('hermes/hotword/') and topic.endswith('/detected'):
		neopixel.send_rgb_command(0b11111111, 9, 4, 0, 0, 255)
		speaker.aplay_random_file("wake")
		client.publish("hermes/asr/startListening", json.dumps({"stopOnSilence": "true"}))
		return

	if topic == "hermes/asr/textCaptured":
		if float(payload['likelihood']) > 0.9:
			client.publish("hermes/nlu/query", json.dumps({"input": payload["text"]}))
			return Reply(neopixel_color=[0b11111111, 4, 2, 0, 0, 255])
		else:
			return Reply(glados_path = 'command_unknown')

	if 'intent' not in payload:
		return Reply(glados_path='command_unknown')

	reply: Reply
	intent = payload_to_intent(payload)

	if intent.intent == "Alias":
		intent = alias_converter.convert_alias(intent, payload['input'])

	for receiver in config["registration"][intent.intent]:
		reply = receivers[receiver].receive_intent(intent)
		if(reply):
			break

	if not reply:
		return Reply(glados_path='command_unknown')
	else:
		return reply

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
