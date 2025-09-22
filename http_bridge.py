import paho.mqtt.client as mqtt
from flask import Flask

# --- MQTT Setup ---
mqtt_client = mqtt.Client("http_bridge")
mqtt_client.connect("localhost", 1883)
mqtt_client.loop_start()  # runs network loop in background

# --- Flask Setup ---
app = Flask(__name__)

def slots_to_json(data: dict) -> str:
    slots = []
    for key, value in data.items():
        slots.append({
            "slotName": key,
            "value": {"value": value}
        })
    return json.dumps({"slots": slots})

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
def custom(topic, message):
    mqtt_client.publish("hermes/nlu/query", json.dumps({"input": message, "siteId": "default"}))
    return "OK"

# --- Start HTTP server ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5123)
