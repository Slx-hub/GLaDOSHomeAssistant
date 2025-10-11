import paho.mqtt.client as mqtt
from flask import Flask, request
import json
import os
import threading
import random
import requests
import xmltodict
from datetime import datetime, timedelta
from dotenv import load_dotenv

from lib import picture_frame_util

kvv_request = """
<?xml version="1.0" encoding="UTF-8"?>
<Trias version="1.1" xmlns="http://www.vdv.de/trias" xmlns:siri="http://www.siri.org.uk/siri" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.vdv.de/trias file:///C:/development/HEAD/extras/TRIAS/TRIAS_1.1/Trias.xsd">
    <ServiceRequest>
        <siri:RequestorRef><<trias_token>></siri:RequestorRef>
        <RequestPayload>
            <TripRequest>
                <Origin>
                    <LocationRef>
                        <StopPlaceRef>de:08216:1844</StopPlaceRef>
                    </LocationRef>
                    <DepArrTime><<date>>T08:00:00</DepArrTime>
                </Origin>
                <Destination>
                    <LocationRef>
                        <StopPlaceRef>de:08212:403</StopPlaceRef>
                    </LocationRef>
                </Destination>
                <Params>
                    <NumberOfResultsGroup>
                      <NumberOfResultsBefore>0</NumberOfResultsBefore>
                      <NumberOfResultsAfter>3</NumberOfResultsAfter>
                    </NumberOfResultsGroup>
                </Params>
            </TripRequest>
        </RequestPayload>
    </ServiceRequest>
</Trias>
"""

weather_request = "https://api.openweathermap.org/data/3.0/onecall?lat=48.86241181349633&lon=8.204346854848135&exclude=current,minutely,daily,alerts&units=metric&lang=de&appid=<<weather_token>>"

import logging
import sys
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

load_dotenv()
app = Flask(__name__)

def slots_to_json(data: dict) -> str:
    slots = []
    for key, value in data.items():
        slots.append({
            "slotName": key,
            "value": {"value": value}
        })
    return json.dumps({"input": "", "slots": slots})

@app.route("/picture_frame_display_image")
def picture_frame_display_image():
    threading.Thread(target=picture_frame_send_image, daemon=True).start()
    return "OK"

@app.route("/picture_frame_display_info_screen")
def picture_frame_display_info_screen():
    threading.Thread(target=picture_frame_send_info_screen, daemon=True).start()
    return "OK"


@app.route("/picture_frame_clear_display")
def get_picture_frame_clear_display():
    threading.Thread(target=picture_frame_clear_display, daemon=True).start()
    return "OK"

@app.route("/intent/<intent>")
def turn_on_livingroom(intent):
    slots = dict(request.args)
    mqtt_client.publish(f"hermes/intent/{intent}", slots_to_json(slots))
    return "OK"

@app.route("/query/<message>")
def custom(message):
    mqtt_client.publish("hermes/nlu/query", json.dumps({"input": message, "siteId": "default"}))
    return "OK"

#####################################################################################

def picture_frame_send_info_screen():

    parsed = {}

    try:
        resp = requests.post(
            "https://projekte.kvv-efa.de/schneidertrias/trias",
            headers={"Content-Type": "text/xml"},
            data=fill_variables(kvv_request)
        )
        resp.raise_for_status()
        try:
            parsed["kvv"] = xmltodict.parse(resp.text)
        except Exception as e:
            parsed["kvv"] = f"error: {resp.text}"
            logger.info("Failed to parse XML: %s" % e)
    except Exception as e:
        parsed["kvv"] = f"error: Status code not OK: {resp.status_code}"
        logger.info("Failed to request KVV: %s" % e)

    try:
        resp = requests.get(fill_variables(weather_request))
        resp.raise_for_status()
        try:
            parsed["weather"] = resp.json()
        except Exception as e:
            parsed["weather"] = f"error: {resp.text}"
            logger.info("Failed to parse JSON: %s" % e)
    except Exception as e:
        parsed["weather"] = f"error: Status code not OK: {resp.status_code}"
        logger.info("Failed to request Weather: %s" % e)

    logger.info(f"Received API data")
    image_bytes = picture_frame_util.draw_info_screen(parsed)
    logger.info(f"Generated info screen")
    try:
        resp = requests.post(
            "http://192.168.178.42/image",
            headers={"Content-Type": "application/octet-stream"},
            data=image_bytes
        )
        logger.info("Displayed info screen, response %s" % resp.status_code)
    except Exception as e:
        logger.info("Failed to post info screen: %s" % e)

def fill_variables(content: str) -> str:
    # Get the token securely
    trias_token = os.getenv("TRIAS_TOKEN")
    if not trias_token:
        raise RuntimeError("TRIAS_TOKEN not found in environment variables")
    weather_token = os.getenv("WEATHER_TOKEN")
    if not weather_token:
        raise RuntimeError("WEATHER_TOKEN not found in environment variables")

    # Replace placeholders
    filled = (
        content
        .replace("<<date>>", datetime.now().strftime("%Y-%m-%d"))
        .replace("<<trias_token>>", trias_token)
        .replace("<<weather_token>>", weather_token)
    )

    return filled


def picture_frame_send_image():
    try:
        resp = requests.post(
            "http://192.168.178.42/image",
            headers={"Content-Type": "application/octet-stream"},
            data=picture_frame_util.load_random_glds_image()
        )
        logger.info("Displayed image, response %s" % resp.status_code)
    except Exception as e:
        logger.info("Failed to post image: %s" % e)
        
def picture_frame_clear_display():
    try:
        resp = requests.get("http://192.168.178.42/clear?color=1")
        logger.info("Cleared Display, response %s" % resp.status_code)
    except Exception as e:
        logger.info("Failed to post image: %s" % e)

# --- dispatch table ---
actions = {
    "pf_display_image": picture_frame_send_image,
    "pf_display_info_screen": picture_frame_send_info_screen,
    "pf_clear_display": picture_frame_clear_display,
}

#####################################################################################

def on_connect(client, userdata, flags, rc):
    """Called when connected to MQTT broker."""
    client.subscribe("hermes/http/#")
    logger.info("Connected!!")


def on_disconnect(client, userdata, flags, rc):
    """Called when disconnected from MQTT broker."""
    client.reconnect()


def on_message(client, userdata, msg):
    """Called each time a message is received on a subscribed topic."""
    topic = msg.topic
    payload = json.loads(msg.payload)

# --- MQTT on_message handler ---
def on_message(client, userdata, msg):
    """Called each time a message is received on a subscribed topic."""
    topic = msg.topic

    if topic == "hermes/http/PictureFrame":
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except json.JSONDecodeError:
            logger.info("Invalid JSON payload")
            return

        if "input" in payload:
            command = payload["input"]
            func = actions.get(command)
            if func:
                logger.info("Executing action for input: %s" % command)
                func()
            else:
                logger.info("No action defined for input: %s" % command)

# --- MQTT Setup ---
mqtt_client = mqtt.Client()
mqtt_client.on_connect = on_connect
mqtt_client.on_disconnect = on_disconnect
mqtt_client.on_message = on_message
mqtt_client.connect("localhost", 1883)
mqtt_client.loop_start()  # runs network loop in background

# --- Start HTTP server ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5123)