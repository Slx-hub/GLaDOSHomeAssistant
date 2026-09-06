# GLaDOSHomeAssistant

This piece of code replaces the Dialog Management, Intent Handling and TTS Module of a [Rhasspy](https://rhasspy.readthedocs.io/en/latest/) Voice Assistant instance.

TTS consists of canned audio samples generated with [elevenlabs](https://elevenlabs.io), to sound like GlaDOS from Portal.

All the functions it can execute are tailored to my exact needs, so this repo won't be of any use for anyone else.

## Hardware

After forgetting which type of Arduino controlled the leds, along with a wrong guess wasting an entire day (and some braincells) i guess i gotta write it down:

- Led control is Seeeduino XIAO M0
- Led array is NeoPixel Jewel 7
- Led libary is Adafruit NeoPixel (1.12.3)

## Energy

The grid power meter poller lives in [meter/](meter/) — standalone service
(own venv, own systemd unit, `powermeter/` MQTT namespace), see its README.

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

Turns out i have to do this more often than i would like to, so this time ima write down all the steps while im at it.

Everything except a handful of files lives in this repo. Before the old pi dies, copy these somewhere safe:

- `/etc/meter.env` (FRITZ!Box password, ntfy topic url)
- `~/.ssh/git` (github deploy key, only needed for pushing)
- `.env` in the repo root (TRIAS and weather api tokens, gitignored)
- optional: `meter/data/history.db` (power history, gitignored, restore starts from zero without it)

On the new pi:

1. `sudo apt update && sudo apt upgrade`
2. install docker as instructed <https://docs.docker.com/engine/install/debian>, then `sudo usermod -aG docker pi` and re-login
3. checkout straight into home, path must be `/home/pi/GLaDOSHomeAssistant/` (the systemd units use absolute paths)
4. restore the files listed above (`sudo chmod 600 /etc/meter.env`)
5. run `complete_setup.sh` (python deps, systemd units, meter venv, bash aliases)
6. plug in ConBee II, XIAO and the USB speaker, check `ls -la /dev/serial/by-id/` matches the paths in `run_docker_containers.sh` and `lib/module_neopixel.py`
7. run `run_docker_containers.sh`. It pulls the pinned images, the Rhasspy profile is bind-mounted from `setup_files/rhasspy-profiles/`, no manual profile setup needed
8. open <http://raspberrypi:12101>, hit **Train** once (the intent graph is gitignored)
9. everything should run now. The ConBee keeps the zigbee network on the stick and `setup_files/z2mdata/` has the pairings, so no re-pairing

No docker commit/save/load anymore: the old `gladosrhasspy:latest` image was the stock `rhasspy/rhasspy:2.5.11` plus a layer of cache junk, so the 1.6 GB tar is not needed.

- !(no longer works, probs too old. voicecard will be removed for now) checkout <https://github.com/respeaker/seeed-voicecard> into home follow readme
    !might be on the wooden path here, maybe <https://github.com/respeaker/4mics_hat> is the correct thing to do?
