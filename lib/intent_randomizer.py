import re
import random

def is_random_intent(intent):
    return '%-' in intent
    
def roll_random_intent(intent):
    m = re.match(r'(\d+)%-(\w+)', intent)
    if m:
        val = random.randint(1,100)
        return m.group(2) if val <= int(m.group(1)) else None