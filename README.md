# GLaDOSHomeAssistant

This piece of code replaces the Dialog Management, Intent Handling and TTS Module of a [Rhasspy](https://rhasspy.readthedocs.io/en/latest/) Voice Assistant instance.

TTS consists of canned audio samples generated with [elevenlabs](https://elevenlabs.io), to sound like GlaDOS from Portal.

All the functions it can execute are tailored to my exact needs, so this repo won't be of any use for anyone else.

## Hardware

After forgetting which type of Arduino controlled the leds, along with a wrong guess wasting an entire day (and some braincells) i guess i gotta write it down:

- Led control is Seeeduino XIAO M0
- Led array is NeoPixel Jewel 7
- Led libary is Adafruit NeoPixel (1.12.3)

## Manual

This section is not a setup guide but rather acts as a reference for when i have once again no clue of what i've done 4 months ago

Bash shortcuts:
- defined in ~/.bashrc
- rhstart, rhstop, rhrestart -> starts and stops Rhasspy Container
- glstart, glstop, glrestart -> starts and stops GlaDOS Module
- glados -> shows active GlaDOS Log

Linux command to convert mp3 to wav:
```for i in *.mp3; do ffmpeg -i "$i" "${i%.*}.wav"; done ```

## How to migrate

Turns out i have to do this more often than i would like to, so this time ima write down all the steps while im at it

- on the old pie: create docker image with `docker commit <container_id_or_name> gladosrhasspy:latest`
-	`docker save -o ./setup_files/gladosrhasspy.tar gladosrhasspy:latest`
- copy tar to temporary space
- on the new pie: `sudo apt update` and `sudo apt upgrade` cant hurt
- checkout straight into home, path should be `home/pi/GLaDOSHomeAssistant/`
- run complete_setup.sh
- move `gladosrhasspy.tar` from temp to new pie
- install docker as instructed <https://docs.docker.com/engine/install/debian>
- run `docker load -i gladosrhasspy.tar`
- edit `run_docker_containers.sh` to align with <https://www.zigbee2mqtt.io/guide/installation/02_docker.html>
- execute `run_docker_containers.sh`
- setup rhasspy as shown in `./setup_files/rhasspy-profile.json` (weirdly enough there is an export but no import)
- copy rhasspy sentences from `./setup_files/rhasspy-sentences.txt`
- everything should run now

- !(no longer works, probs too old. voicecard will be removed for now) checkout <https://github.com/respeaker/seeed-voicecard> into home follow readme
    !might be on the wooden path here, maybe <https://github.com/respeaker/4mics_hat> is the correct thing to do?