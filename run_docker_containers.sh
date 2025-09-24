docker stop mosquitto
docker stop gladosrhasspy
docker stop zigbee2mqtt

docker rm mosquitto
docker rm gladosrhasspy
docker rm zigbee2mqtt

docker network rm smart-home
docker network create smart-home

docker run -d --restart=unless-stopped --network smart-home -p 1883:1883 --name mosquitto -v $(pwd)/setup_files/mosquitto.conf:/mosquitto/config/mosquitto.conf eclipse-mosquitto
docker run -d --restart=unless-stopped --network smart-home -p 12101:12101 --name gladosrhasspy gladosrhasspy:latest
docker run -d --restart=unless-stopped --network smart-home -p 8080:8080 --name zigbee2mqtt --device=/dev/ttyACM0 -v $(pwd)/setup_files/z2mdata:/app/data -v /run/udev:/run/udev:ro -e TZ=Europe/Berlin ghcr.io/koenkk/zigbee2mqtt
