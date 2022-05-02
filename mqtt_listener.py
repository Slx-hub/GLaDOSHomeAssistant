#!/usr/bin/env python3
import paho.mqtt.client as mqtt
import json, yaml, os, time
from threading import Thread

from lib.I_intent_receiver import Intent
from lib import receiver_shield
from lib import receiver_debug
from lib import receiver_conversation
from lib import receiver_system

receivers = {
	'Debug': receiver_debug.Debug(),
	'Conversation': receiver_conversation.Conversation(),
	'System': receiver_system.System(),
	'Shield': receiver_shield.Shield()
}

config = {}

def on_connect(client, userdata, flags, rc):
	"""Called when connected to MQTT broker."""
	client.subscribe("hermes/hotword/#")
	client.subscribe("hermes/asr/textCaptured")
	client.subscribe("hermes/intent/#")
	client.subscribe("hermes/nlu/intentNotRecognized")
	print("Connected. Waiting for intents.")


def on_disconnect(client, userdata, flags, rc):
	"""Called when disconnected from MQTT broker."""
	client.reconnect()


def on_message(client, userdata, msg):
	"""Called each time a message is received on a subscribed topic."""
	payload = json.loads(msg.payload)
	print("TOPIC: ", msg.topic)
	print("PAYLOAD: ", payload)

	if msg.topic == "hermes/hotword/porcupine_raspberry-pi/detected":
		client.publish("hermes/tts/say", json.dumps({"text": "was"}))
		client.publish("hermes/asr/startListening", json.dumps({"stopOnSilence": "true"}))
		return

	if msg.topic == "hermes/asr/textCaptured":
		client.publish("hermes/nlu/query", json.dumps({"input": payload["text"]}))

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
		reply = "error"
		print("Recognition failure")
	
	client.publish("hermes/tts/say", json.dumps({"text": reply}))

def payload_to_intent(payload):
	intent = payload["intent"]["intentName"]
	slots = {}
	for slot in payload["slots"]:
		slots[slot["entity"]] = slot["rawValue"]
	return Intent(intent,slots)

def get_slot_by_entity(json, entity):
	for slot in json["slots"]:
		if slot["entity"] == entity:
			return slot
	raise Exception('No such entity slot')

# Read Config
with open("config.yaml", 'r') as stream:
	config = yaml.safe_load(stream)

# Create MQTT client and connect to broker

client = mqtt.Client()
client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.on_message = on_message

client.connect("localhost", 1883)
client.loop_forever()
