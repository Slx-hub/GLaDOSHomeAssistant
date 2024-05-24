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
        'scheduled_alarm_ring': Intent(intent='Scheduled', text='scheduled_alarm_ring')}

def convert_alias(intent, text):
    if dict[text]:
        return dict[text]
    return intent