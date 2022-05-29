import os, random
from subprocess import call

def aplay_random_file(folder):
    if not folder or folder == "":
        return 
    filepath = "lib/replies/" + folder + "/"
    if not os.path.isdir(filepath):
        filepath = "lib/replies/error/"
    file = random.choice(os.listdir(filepath))
    aplay_wav(filepath + file)


def aplay_wav(file):
    call(["aplay", "-Dsysdefault:CARD=BR21", file])
