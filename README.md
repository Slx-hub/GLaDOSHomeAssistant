# GLaDOSHomeAssistant

This piece of code replaces the Dialog Management, Intent Handling and TTS Module of a [Rhasspy](https://rhasspy.readthedocs.io/en/latest/) Voice Assistant instance.

TTS consists of canned audio samples generated with [15.ai](https://15.ai) (rip), to sound like GlaDOS from Portal.

All the functions it can execute are tailored to my exact needs, so this repo won't be of any use for anyone else.

## Manual

This section is not a setup guide but rather acts as a reference for when i have once again no clue of what i've done 4 months ago

Bash shortcuts:
- defined in ~/.bashrc
- rhstart, rhstop, rhrestart -> calls respective docker functions
- glrestart -> restarts GlaDOS Module
- glados -> shows active GlaDOS Log

Linux command to convert mp3 to wav:
```for i in *.mp3; do ffmpeg -i "$i" "${i%.*}.wav"; done ```
