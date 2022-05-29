from lib.I_intent_receiver import Intent

dict = {'noodle time': Intent(intent='SetTimer', slots={'amount': 8, 'scale': 'minutes'}),
        'breakfast time': Intent(intent='SetTimer', slots={'amount': 30, 'scale': 'minutes'})}

def convert_alias(intent, text):
    if dict[text]:
        return dict[text]
    return intent