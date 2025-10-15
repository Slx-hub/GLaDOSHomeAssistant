from lib.I_intent_receiver import Intent

dict = {'noodle time': Intent(intent='SetTimer', slots={'amount': 8, 'scale': 'minutes'}),
        'lunch time': Intent(intent='SetTimer', slots={'amount': 30, 'scale': 'minutes'}),
        'scheduled_evening_light': Intent(intent='ChangeLightState', slots={'state': 'on', 'source': 'livingroom'}),
        'scheduled_night_light': Intent(intent='ChangeLightState', slots={'state': 'on', 'mode': 'dim', 'source': 'livingroom'}),
        'scheduled_light_off': Intent(intent='ChangeLightState', slots={'state': 'off', 'source': 'livingroom'}),
        'scheduled_alarm_off': Intent(intent='ChangeLightState', slots={'state': 'off', 'source': 'bedroom'}),
        'scheduled_alarm_low': Intent(intent='ChangeLightState', slots={'state': 'on', 'mode': 'dim', 'source': 'bedroom'}),
        'scheduled_alarm_medium': Intent(intent='ChangeLightState', slots={'state': 'on', 'mode': 'default', 'source': 'bedroom'}),
        'scheduled_alarm_full': Intent(intent='ChangeLightState', slots={'state': 'on', 'mode': 'full', 'source': 'bedroom'}),
        'scheduled_alarm_ring': Intent(intent='Conversation', text='scheduled_alarm_ring'),
        'scheduled_lavalamp_on': Intent(intent='ChangeSocketState', slots={'state': 'on', 'source': 'lavalamp'}),
        'scheduled_lavalamp_off': Intent(intent='ChangeSocketState', slots={'state': 'off', 'source': 'lavalamp'})}

def convert_alias(intent):
    if dict[intent.text]:
        return dict[intent.text]
    return intent