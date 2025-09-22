import paho.mqtt.client as mqtt
from flask import Flask
import json
import os
import random
import requests

def on_connect(client, userdata, flags, rc):
	"""Called when connected to MQTT broker."""
	client.subscribe("hermes/http/#")
	print("Connected!!")


def on_disconnect(client, userdata, flags, rc):
	"""Called when disconnected from MQTT broker."""
	client.reconnect()


def on_message(client, userdata, msg):
	"""Called each time a message is received on a subscribed topic."""
    topic = msg.topic
	payload = json.loads(msg.payload)

# --- dispatch table ---
actions = {
    "display_image": picture_frame_display_image,
    # later you can add more mappings here
}

# --- MQTT on_message handler ---
def on_message(client, userdata, msg):
    """Called each time a message is received on a subscribed topic."""
    topic = msg.topic

    if topic == "hermes/http/PictureFrame":
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except json.JSONDecodeError:
            print("Invalid JSON payload")
            return

        if "input" in payload:
            command = payload["input"]
            func = actions.get(command)
            if func:
                print(f"Executing action for input: {command}")
                func()
            else:
                print(f"No action defined for input: {command}")

#####################################################################################

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
    folder = "./lib/pic_frame_images/"
    files = [f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f))]
    if not files:
        print("No images found in", folder)
        return "not OK"

    chosen_file = random.choice(files)
    file_path = os.path.join(folder, chosen_file)

    with open(file_path, "rb") as f:
        data = f.read()

    try:
        resp = requests.post(
            "http://192.168.178.42/image",
            headers={"Content-Type": "application/octet-stream"},
            data=data
        )
        print(f"Posted {chosen_file}, response {resp.status_code}")
    except Exception as e:
        print("Failed to post image:", e)
        return "not OK"
    return "OK"

# Example endpoints
@app.route("/turn_on_livingroom")
def turn_on_livingroom():
    mqtt_client.publish("hermes/intent/ChangeLightState", slots_to_json({"source": "livingroom", "state": "on"}))
    return "OK"

@app.route("/turn_off_livingroom")
def turn_off_livingroom():
    mqtt_client.publish("hermes/intent/ChangeLightState", slots_to_json({"source": "livingroom", "state": "off"}))
    return "OK"

@app.route("/custom/<message>")
def custom(message):
    mqtt_client.publish("hermes/nlu/query", json.dumps({"input": message, "siteId": "default"}))
    return "OK"


# --- MQTT Setup ---
mqtt_client = mqtt.Client()
client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.on_message = on_message
mqtt_client.connect("localhost", 1883)
mqtt_client.loop_start()  # runs network loop in background

# --- Flask Setup ---
app = Flask(__name__)

# --- Start HTTP server ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5123)
