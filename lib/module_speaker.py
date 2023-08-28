import os, random
from subprocess import call

def aplay_given_path(path, soundpack):
    if not path or path == "":
        return 

    if path.endswith(".wav"):
        aplay_file(path, soundpack)
    else:
        aplay_random_file(path, soundpack)

def aplay_file(file, soundpack):
    aplay_wav("lib/replies/" + soundpack + "/" + file)

def aplay_random_file(path, soundpack):
    filepath = "lib/replies/" + soundpack + "/" + path + "/"
    if not os.path.isdir(filepath):
        filepath = "lib/replies/error/"
    file = random.choice(os.listdir(filepath))
    aplay_wav(filepath + file)

def aplay_wav(file):
    call(["aplay", "-Dsysdefault:CARD=BR21", file])
