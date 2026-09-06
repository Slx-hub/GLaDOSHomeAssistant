#!/bin/bash
# Recreates the three containers from scratch. Run from the repo root.
# All state lives in bind mounts under setup_files/, so stop+rm loses nothing.
#
# Image tags are pinned to the versions this setup was verified with. Bump them
# deliberately, not by accident on a fresh install.
#
# USB devices are addressed via /dev/serial/by-id so the order in which the
# ConBee and the XIAO enumerate at boot does not matter. The names contain the
# device serial numbers: a replacement stick needs a new entry here
# (ls -la /dev/serial/by-id/).
CONBEE=/dev/serial/by-id/usb-dresden_elektronik_ingenieurtechnik_GmbH_ConBee_II_DE2672256-if00

docker stop mosquitto
docker stop gladosrhasspy
docker stop zigbee2mqtt

docker rm mosquitto
docker rm gladosrhasspy
docker rm zigbee2mqtt

docker network rm smart-home
docker network create smart-home

docker run -d --restart=unless-stopped --network smart-home -p 1883:1883 --name mosquitto -v $(pwd)/setup_files/mosquitto.conf:/mosquitto/config/mosquitto.conf eclipse-mosquitto:2.0.22
# Stock Rhasspy image: the profile is bind-mounted, nothing is baked in. The
# image ships without a CMD, so the profile arguments have to be passed here.
docker run -d --restart=unless-stopped --network smart-home -p 12101:12101 --name gladosrhasspy -v $(pwd)/setup_files/rhasspy-profiles:/profiles rhasspy/rhasspy:2.5.11 --user-profiles /profiles --profile en
# The ConBee is mapped to /dev/ttyACM0 inside the container, which is what
# setup_files/z2mdata/configuration.yaml expects.
docker run -d --restart=unless-stopped --network smart-home -p 8080:8080 --name zigbee2mqtt --device=$CONBEE:/dev/ttyACM0 -v $(pwd)/setup_files/z2mdata:/app/data -v /run/udev:/run/udev:ro -e TZ=Europe/Berlin ghcr.io/koenkk/zigbee2mqtt:2.6.1
