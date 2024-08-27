#!/usr/bin/env python3
import paho.mqtt.client as mqtt
import json, yaml
from collections import namedtuple
from multiprocessing import Process, Manager
from time import sleep

from lib.I_intent_receiver import Intent
from lib.I_intent_receiver import Reply
from lib import receiver_shield
from lib import receiver_conversation
from lib import receiver_system
from lib import receiver_timer
from lib import receiver_zigbee
from lib import receiver_sonos
from lib import module_speaker as speaker
from lib import module_neopixel as neopixel
from lib import alias_converter
from lib import scheduler

receivers = {
	'Conversation': receiver_conversation.Conversation(),
	'System': receiver_system.System(),
	'Shield': receiver_shield.Shield(),
	'Timer': receiver_timer.Timer(),
	'Zigbee': receiver_zigbee.Zigbee(),
	'Sonos': receiver_sonos.Sonos(),
}

enable_debug = True

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
	if enable_debug:
		print("TOPIC: ", msg.topic)
		print("PAYLOAD: ", payload)

	try:
		reply = handle_message(client, msg.topic, payload)
	except:
		reply = Reply(glados_path='command_failed', neopixel_color=[0b11111111, 40, 0, 0, 0, 30])

	handle_reply(reply, True, False)

	if enable_debug:
		print("\nREPLY: ", reply)

def on_scheduled(intent, command):
	print("running scheduled job: ", intent, command)
	reply = handle_message(client,'',json.loads('{"input": "' + command + '", "intent": {"intentName": "' + intent + '"}, "slots": []}'))
	handle_reply(reply, reply.override_silent, True)

def handle_reply(reply, do_vocal_reply, is_scheduled):
	if reply:
		if do_vocal_reply:
			speaker.aplay_given_path(reply.glados_path, config_GeneralSettings["SoundPack"])
			if reply.neopixel_color:
				neopixel.send_rgb_command(*reply.neopixel_color)
			if reply.tts_reply and reply.tts_reply != '':
				client.publish("hermes/tts/say", json.dumps({"text": reply.tts_reply}))
		publish(reply, is_scheduled)

ReplyHistory = namedtuple('ReplyHistory', ['payload', 'deny_scheduled'])
last_reply_for_topics = {}

def publish(reply, is_scheduled):
	global last_reply_for_topics
	if reply.mqtt_topic != '' and reply.mqtt_payload != '':
		for i in range(len(reply.mqtt_topic)):
			print("REPLY; topic: ", reply.mqtt_topic[i])
			last_reply = last_reply_for_topics[reply.mqtt_topic[i]] if reply.mqtt_topic[i] in last_reply_for_topics else None
			print("REPLY; history: ", last_reply)
			if reply.mqtt_payload[i] == "<restore>":
				client.publish(reply.mqtt_topic[i], last_reply_for_topics[reply.mqtt_topic[i]].payload)
				last_reply_for_topics[reply.mqtt_topic[i]] = last_reply._replace(deny_scheduled = False)
				print("RESTORE; topic state: ", last_reply_for_topics[reply.mqtt_topic[i]])
				continue

			if not is_scheduled or last_reply is None or not last_reply.deny_scheduled:
				print("SANITY CHECK: ", not is_scheduled, last_reply is None, last_reply is not None and not last_reply.deny_scheduled)
				client.publish(reply.mqtt_topic[i], reply.mqtt_payload[i])
				if not reply.deny_scheduled or last_reply is None:
					last_reply_for_topics[reply.mqtt_topic[i]] = ReplyHistory(reply.mqtt_payload[i], reply.deny_scheduled)
				else:
					last_reply_for_topics[reply.mqtt_topic[i]] = last_reply._replace(deny_scheduled = reply.deny_scheduled)
				print("PUBLISH; topic state: ", last_reply_for_topics[reply.mqtt_topic[i]])
			else:
				last_reply_for_topics[reply.mqtt_topic[i]] = last_reply._replace(payload = reply.mqtt_payload[i])
				print("HIDE; topic state: ", last_reply_for_topics[reply.mqtt_topic[i]])

def handle_message(client, topic, payload):

	if topic.startswith('hermes/hotword/') and topic.endswith('/detected'):
		neopixel.send_rgb_command(0b11111111, 9, 4, 0, 0, 255)
		speaker.aplay_given_path("wake", config_GeneralSettings["SoundPack"])
		client.publish("hermes/asr/startListening", json.dumps({"stopOnSilence": "true"}))
		return

	if topic == "hermes/asr/textCaptured":
		client.publish("hermes/asr/stopListening", json.dumps({"siteId": "default", "sessionId": ""}))
		if float(payload['likelihood']) > 0.9:
			client.publish("hermes/nlu/query", json.dumps({"input": payload["text"]}))
			return Reply(neopixel_color=[0b11111111, 4, 2, 0, 0, 255])
		else:
			return Reply(glados_path = 'command_unknown')

	if 'intent' not in payload:
		return Reply(glados_path='command_unknown')

	reply: Reply
	intent = payload_to_intent(payload)

	if intent.intent == "Reload-Config":
		load_config()
		return Reply(glados_path='command_success')

	if intent.intent == "Alias":
		intent = alias_converter.convert_alias(intent, payload['input'])

	if intent.intent not in config_IntentRouting:
		return Reply(glados_path='command_unknown')

	for receiver in config_IntentRouting[intent.intent]:
		reply = receivers[receiver].receive_intent(intent, config_HandlerSettings.get(receiver))
		if(reply):
			break

	if not reply:
		return Reply(glados_path='command_unknown')
	else:
		return reply

def payload_to_intent(payload):
	intent = payload["intent"]["intentName"]
	text = payload["input"]
	slots = {}
	for slot in payload["slots"]:
		slots[slot["slotName"]] = slot["value"]["value"]
	return Intent(intent, slots, text)

def get_slot_by_entity(json, entity):
	for slot in json["slots"]:
		if slot["entity"] == entity:
			return slot
	raise Exception('No such entity slot')

config_IntentRouting = {}
config_HandlerSettings = {}
config_GeneralSettings = {}
proc = Process()

def load_config():
	print("Reloading config file.")
	global config_IntentRouting
	global config_HandlerSettings
	global config_GeneralSettings
	config_IntentRouting = {}
	config_HandlerSettings = {}
	config_GeneralSettings = {}
	with open("config.yaml", 'r') as stream:
		yaml_config = yaml.safe_load(stream)
		for receiver in yaml_config['IntentRouting']:
			for topic in yaml_config['IntentRouting'][receiver]:
				if topic in config_IntentRouting:
					config_IntentRouting[topic].add(receiver)
				else:
					config_IntentRouting[topic] = [receiver]
		config_HandlerSettings = yaml_config['HandlerSettings']
		config_SchedulerSettings = yaml_config['SchedulerSettings']
		config_GeneralSettings = yaml_config['GeneralSettings']

		global proc
		if proc and proc.is_alive():
			proc.terminate()
		scheduler.setup(on_scheduled, config_SchedulerSettings)

		global last_reply_for_topics
		with Manager() as manager:
			last_reply_for_topics = manager.dict()
			proc = Process(target=scheduler.run)
			proc.start()

		print('Intent Routing:', config_IntentRouting)
		print('Handler Settings:', config_HandlerSettings)
		print('Scheduler Settings:', config_SchedulerSettings)

def setup_process(shared_topic_dict):
	global last_reply_for_topics
	last_reply_for_topics = shared_topic_dict
	scheduler.run()

# Create MQTT client and connect to broker

client = mqtt.Client()
client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.on_message = on_message
client.connect("localhost", 1883)

load_config()

for receiver in receivers:
    receivers[receiver].setup(config_HandlerSettings.get(receiver))

try:
	client.loop_forever()
except KeyboardInterrupt:
	pass
print("Stopping...")
proc.terminate()
