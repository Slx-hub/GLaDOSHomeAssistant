# GLaDOSHomeAssistant

This piece of code replaces the Dialog Management, Intent Handling and TTS Module of a [Rhasspy](https://rhasspy.readthedocs.io/en/latest/) Voice Assistant instance.

TTS consists of canned audio samples generated with [15.ai](https://15.ai) (rip), to sound like GlaDOS from Portal.

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
