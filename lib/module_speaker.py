import os, random
from subprocess import call

def aplay_random_file(folder):
    filepath = "lib/replies/" + folder + "/"
    if not os.path.isdir(filepath):
        filepath = "lib/replies/error/"
    file = random.choice(os.listdir(filepath))
    print("Debug Path:", filepath, file)
    aplay_wav(filepath + file)


def aplay_wav(file):
    call(["aplay", file])
