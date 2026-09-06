sudo apt update
# python-is-python3: the systemd units call `python`, not `python3`.
# Docker itself is NOT installed here. The Debian `docker` package is an
# unrelated transitional package. Install docker-ce from the official repo:
# https://docs.docker.com/engine/install/debian
sudo apt install python-is-python3 python3-paho-mqtt python3-requests python3-flask python3-schedule python3-pil python3-pip python3-yaml python3-psutil python3-serial python3-xmltodict python3-dotenv python3-gpiozero python3-spidev
