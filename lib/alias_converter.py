from lib.I_intent_receiver import Intent

dict = {'noodle time': Intent(intent='SetTimer', slots={'amount': 8, 'scale': 'minutes'}),
        'lunch time': Intent(intent='SetTimer', slots={'amount': 30, 'scale': 'minutes'}),
        'scheduled_evening_light': Intent(intent='ChangeLightState', slots={'state': 'on', 'source': 'livingroom'}),
        'scheduled_night_light': Intent(intent='ChangeLightState', slots={'state': 'on', 'mode': 'dim', 'source': 'livingroom'}),
        'scheduled_light_off': Intent(intent='ChangeLightState', slots={'state': 'off', 'source': 'livingroom'})}

def convert_alias(intent, text):
    if dict[text]:
        return dict[text]
    return intent