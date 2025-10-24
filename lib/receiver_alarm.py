from lib.I_intent_receiver import Receiver, Reply
import yaml
from datetime import datetime, timedelta
import logging
import json

logger = logging.getLogger(__name__)

class Alarm(Receiver):

	def receive_intent(self, intent, settings):

		# Servicing functions
		if intent.intent == "ChangeAlarmState":
			return self._handle_change_alarm_state(intent, settings)
		
		if intent.intent == "ChangeAlarmTime":
			return self._handle_change_alarm_time(intent, settings)
		
		# From here, only if alarm is armed
		if not settings.get("armed", False):
			logger.info(f"Alarm ignored - not armed")
			return Reply(glados_path='command_success')

		if intent.intent == "Alarm":
			return Reply(next_intent="Alias> " + intent.text)

	def _handle_change_alarm_state(self, intent, settings):
		"""Handle ChangeAlarmState intent - enable/disable alarm"""
		state = intent.slots.get("state", "").lower()
		
		if state not in ["on", "off"]:
			return Reply(glados_path='command_failed')
		
		armed = state == "on"
		
		# Update config file
		if self._update_alarm_armed_state(armed):
			# Trigger config reload
			return Reply(next_intent="Alias> " + intent.text)
			return Reply(glados_path='Reload-Config',
						mqtt_topic=['hermes/intent/'], 
						mqtt_payload=['{"input": "reload config", "intent": {"intentName": "Reload-Config"}, "slots": []}'])
		else:
			return Reply(glados_path='command_failed')

	def _handle_change_alarm_time(self, intent, settings):
		"""Handle ChangeAlarmTime intent - update alarm schedule"""
		hours = intent.slots.get("hours")
		minutes = intent.slots.get("minutes")
		
		if hours is None or minutes is None:
			return Reply(glados_path='command_failed')
		
		try:
			# Validate time format
			alarm_time = datetime.strptime(f"{hours:02d}:{minutes:02d}", "%H:%M")
			
			# Calculate all alarm times
			alarm_times = {
				"low": (alarm_time - timedelta(minutes=30)).strftime("%H:%M"),
				"medium": (alarm_time - timedelta(minutes=15)).strftime("%H:%M"),
				"full": (alarm_time - timedelta(minutes=5)).strftime("%H:%M"),
				"ring": alarm_time.strftime("%H:%M"),
				"off": (alarm_time + timedelta(minutes=8)).strftime("%H:%M")
			}
			
			# Update config file
			if self._update_alarm_schedule(alarm_times):
				# Trigger config reload
				return Reply(glados_path='command_success',
							mqtt_topic=['hermes/intent/Reload-Config'],
							mqtt_payload=['{"input": "reload config", "intent": {"intentName": "Reload-Config"}, "slots": []}'])
			else:
				return Reply(glados_path='command_failed')
				
		except ValueError:
			return Reply(glados_path='command_failed')

	def _update_alarm_armed_state(self, armed):
		"""Update the alarm armed state in config.yaml"""
		try:
			with open("config.yaml", 'r') as file:
				config = yaml.safe_load(file)
			
			if 'HandlerSettings' not in config:
				config['HandlerSettings'] = {}
			if 'Alarm' not in config['HandlerSettings']:
				config['HandlerSettings']['Alarm'] = {}
			
			config['HandlerSettings']['Alarm']['armed'] = armed
			
			with open("config.yaml", 'w') as file:
				yaml.dump(config, file, default_flow_style=False, sort_keys=False)
			
			logger.info(f"Updated alarm armed state to: {armed}")
			return True
			
		except Exception as e:
			logger.error(f"Failed to update alarm armed state: {e}")
			return False

	def _update_alarm_schedule(self, alarm_times):
		"""Update the alarm schedule in config.yaml"""
		try:
			with open("config.yaml", 'r') as file:
				content = file.read()
			
			config = yaml.safe_load(content)
			
			# Remove existing alarm entries (those with -A suffix)
			if 'SchedulerSettings' in config and 'daily' in config['SchedulerSettings']:
				daily = config['SchedulerSettings']['daily']
				keys_to_remove = [key for key in daily.keys() if key.endswith('-A')]
				for key in keys_to_remove:
					del daily[key]
				
				# Add new alarm entries
				daily[f"{alarm_times['low']}-A"] = "Alias> scheduled_alarm_low"
				daily[f"{alarm_times['medium']}-A"] = "Alias> scheduled_alarm_medium"
				daily[f"{alarm_times['full']}-A"] = "Alias> scheduled_alarm_full"
				daily[f"{alarm_times['ring']}-A"] = "Scheduled> scheduled_alarm_ring"
				daily[f"{alarm_times['off']}-A"] = "Alias> scheduled_alarm_off"
			
			with open("config.yaml", 'w') as file:
				yaml.dump(config, file, default_flow_style=False, sort_keys=False, default_style='"')
			
			logger.info(f"Updated alarm schedule: {alarm_times}")
			return True
			
		except Exception as e:
			logger.error(f"Failed to update alarm schedule: {e}")
			return False
