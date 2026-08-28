"""meter.service — polls the FRITZ!Smart Energy 250 through the FRITZ!Box
and publishes grid power to MQTT.

Role in the system: slow correction path (I share) for the power controller.
The fast path comes from the Shelly plugs. This service may fail without the
control loop stopping — it only gets less accurate.

The MQTT contract (topics and payloads below) is the stable part; the data
source is the exchangeable part. See --simulate / --replay / --dump-raw.

Topics (prefix configurable, default "powermeter"):
    powermeter/data/power       retain, QoS 0   power JSON (see build_power_payload)
    powermeter/data/energy      retain, QoS 1   import_kwh / export_kwh
    powermeter/health/status    retain, QoS 1   online / offline (LWT)
    powermeter/health/diag      no retain, QoS 0  poll timings, login failures, backoff
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import signal
import sys
import threading
from typing import Optional

import paho.mqtt.client as mqtt
import yaml

from common import (MeterReading, ReplayDone, SourceError,
                    iso_z, jlog, setup_logging, utcnow)
from fritz_source import FritzSession, FritzSource, LoginBlocked, parse_devicelist
from sim_source import ReplaySource, SimulateSource

DEFAULTS = {
    "fritzbox": {
        "host": "192.168.178.1",      # IP on purpose — never assume fritz.box resolves
        "user": "meter",
        "password_file": None,        # alternative to the FRITZBOX_PASSWORD env var
        "ain": None,                  # None = first device with powermeter capability
        "use_https": False,
        "verify_tls": False,
        "timeout_s": 10.0,
        "login_backoff_initial_s": 10.0,
        "login_backoff_max_s": 900.0,
        # Scaling is UNVERIFIED for the Energy 250 (spec section 2) — defaults
        # are the FRITZ!DECT 200 units (power mW, energy Wh).
        "power_scale": 0.001,         # raw -> W
        "energy_scale": 0.001,        # raw -> kWh
        "invert_sign": False,         # flip if feed-in shows the wrong sign during commissioning
        "export_element": None,       # XML element carrying 2.8.0, once known
    },
    "poll": {
        "interval_s": 10.0,
        "stale_after_s": 180.0,
    },
    "mqtt": {
        "host": "localhost",
        "port": 1883,
        "keepalive_s": 30,            # bounds how fast the LWT fires after kill -9
        "topic_prefix": "powermeter",
        "client_id": "meter-service",
    },
    "simulate": {
        "send_period_s": 60.0,
        "base_load_w": 180.0,
        "pv_peak_w": 2500.0,
        "seed": None,
    },
}


def load_config(path: str) -> dict:
    config = copy.deepcopy(DEFAULTS)
    with open(path, encoding="utf-8") as f:
        loaded = yaml.safe_load(f) or {}
    for section, values in loaded.items():
        if section in config and isinstance(values, dict):
            config[section].update(values)
        else:
            config[section] = values
    return config


def resolve_password(fritz_cfg: dict) -> str:
    # Never in the repo: either systemd EnvironmentFile (mode 0600) sets
    # FRITZBOX_PASSWORD, or password_file points outside the project dir.
    password_file = fritz_cfg.get("password_file")
    if password_file:
        with open(password_file, encoding="utf-8") as f:
            return f.read().strip()
    password = os.environ.get("FRITZBOX_PASSWORD")
    if not password:
        raise SystemExit("FRITZBOX_PASSWORD not set and no password_file configured — "
                         "refusing to start (see setup_files/meter.env.example)")
    return password


class FreshnessTracker:
    """Tells real new measurements apart from re-polled repeats (spec section 3).

    The device sends slower than we poll; the controller must not integrate
    the same measurement multiple times, and must freeze its I share once the
    value goes stale.
    """

    def __init__(self, stale_after_s: float):
        self.stale_after_s = stale_after_s
        self.ts_measured = None
        self.last_reading: Optional[MeterReading] = None
        self._last_signature = None
        self._last_ts_device = None

    def update(self, reading: MeterReading, now) -> bool:
        if reading.ts_device is not None:
            fresh = reading.ts_device != self._last_ts_device
            self._last_ts_device = reading.ts_device
            if fresh:
                self.ts_measured = reading.ts_device
        else:
            fresh = reading.raw_signature != self._last_signature
            self._last_signature = reading.raw_signature
            if fresh:
                self.ts_measured = now
        self.last_reading = reading
        return fresh

    def is_stale(self, now) -> bool:
        if self.ts_measured is None:
            return False
        return (now - self.ts_measured).total_seconds() > self.stale_after_s


class MqttPublisher:
    def __init__(self, cfg: dict):
        prefix = cfg["topic_prefix"]
        self.topic_power = f"{prefix}/data/power"
        self.topic_energy = f"{prefix}/data/energy"
        self.topic_status = f"{prefix}/health/status"
        self.topic_diag = f"{prefix}/health/diag"

        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                   client_id=cfg["client_id"])
        # LWT before connect: broker flips us to offline within the keepalive
        # window after a hard kill (acceptance criterion 5).
        self._client.will_set(self.topic_status, "offline", qos=1, retain=True)
        self._client.reconnect_delay_set(min_delay=1, max_delay=60)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        # connect_async + loop_start: a broker that is down at service start
        # (or restarts later) is retried with backoff (acceptance criterion 6).
        self._client.connect_async(cfg["host"], cfg["port"],
                                   keepalive=cfg["keepalive_s"])
        self._client.loop_start()

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        jlog(logging.INFO, "mqtt_connected", reason=str(reason_code))
        client.publish(self.topic_status, "online", qos=1, retain=True)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        jlog(logging.WARNING, "mqtt_disconnected", reason=str(reason_code))

    def publish_power(self, payload: dict):
        self._client.publish(self.topic_power, json.dumps(payload), qos=0, retain=True)

    def publish_energy(self, payload: dict):
        self._client.publish(self.topic_energy, json.dumps(payload), qos=1, retain=True)

    def publish_diag(self, payload: dict):
        self._client.publish(self.topic_diag, json.dumps(payload), qos=0, retain=False)

    def shutdown(self):
        # Orderly exit: status explicitly offline, then disconnect so the
        # broker does not additionally fire the LWT.
        info = self._client.publish(self.topic_status, "offline", qos=1, retain=True)
        try:
            info.wait_for_publish(timeout=5)
        except (ValueError, RuntimeError):
            pass
        self._client.disconnect()
        self._client.loop_stop()


def build_power_payload(reading: MeterReading, fresh: bool, stale: bool,
                        ts_measured, ts_polled) -> dict:
    return {
        # positive = Netzbezug, negative = Einspeisung — fixed across all services
        "watt": round(reading.watt, 1),
        "ts_measured": iso_z(ts_measured),
        "ts_polled": iso_z(ts_polled),
        "fresh": fresh,
        "stale": stale,
        "source": reading.source,
    }


def run_loop(source, publisher: MqttPublisher, cfg: dict, stop: threading.Event,
             record_path: Optional[str], interval_s: float):
    tracker = FreshnessTracker(cfg["poll"]["stale_after_s"])
    login_failures = lambda: getattr(getattr(source, "session", None), "login_failures", 0)
    backoff_s = lambda: getattr(getattr(source, "session", None), "backoff_remaining_s", 0.0)
    last_energy_signature = None
    record_file = open(record_path, "a", encoding="utf-8") if record_path else None

    while not stop.is_set():
        started = utcnow()
        reading = None
        error = None
        try:
            reading = source.poll()
        except ReplayDone:
            jlog(logging.INFO, "replay_done")
            break
        except LoginBlocked as e:
            error = str(e)
        except SourceError as e:
            error = str(e)
        except Exception as e:  # never let one bad poll kill the service
            error = f"{type(e).__name__}: {e}"

        now = utcnow()
        if reading is not None:
            fresh = tracker.update(reading, now)
            stale = tracker.is_stale(now)
            publisher.publish_power(
                build_power_payload(reading, fresh, stale, tracker.ts_measured, now))
            if fresh:
                jlog(logging.INFO, "measurement", watt=round(reading.watt, 1),
                     source=reading.source)

            energy_signature = (reading.import_kwh, reading.export_kwh)
            if reading.import_kwh is not None and energy_signature != last_energy_signature:
                last_energy_signature = energy_signature
                publisher.publish_energy({
                    "import_kwh": reading.import_kwh,
                    "export_kwh": reading.export_kwh,
                    "ts_measured": iso_z(tracker.ts_measured),
                    "source": reading.source,
                })

            if record_file is not None and reading.raw_xml is not None:
                record_file.write(json.dumps({"ts_polled": iso_z(now),
                                              "raw_xml": reading.raw_xml}) + "\n")
                record_file.flush()
        else:
            jlog(logging.ERROR, "poll_error", error=error)
            # Re-publish the last known value with an updated stale flag so
            # the controller can freeze its I share even while the box is away.
            last = tracker.last_reading
            if last is not None:
                publisher.publish_power(
                    build_power_payload(last, False, tracker.is_stale(now),
                                        tracker.ts_measured, now))

        poll_ms = int((utcnow() - started).total_seconds() * 1000)
        diag = {"ok": error is None, "poll_ms": poll_ms,
                "login_failures": login_failures()}
        if error is not None:
            diag["error"] = error
        if backoff_s() > 0:
            diag["login_backoff_s"] = round(backoff_s())
        publisher.publish_diag({"event": "poll", **diag})
        jlog(logging.DEBUG, "poll", **diag)

        elapsed = (utcnow() - started).total_seconds()
        stop.wait(max(0.0, interval_s - elapsed))

    if record_file is not None:
        record_file.close()


def make_fritz_source(cfg: dict) -> FritzSource:
    fritz_cfg = cfg["fritzbox"]
    session = FritzSession(
        host=fritz_cfg["host"], user=fritz_cfg["user"],
        password=resolve_password(fritz_cfg),
        use_https=fritz_cfg["use_https"], verify_tls=fritz_cfg["verify_tls"],
        timeout_s=fritz_cfg["timeout_s"],
        backoff_initial_s=fritz_cfg["login_backoff_initial_s"],
        backoff_max_s=fritz_cfg["login_backoff_max_s"],
    )
    return FritzSource(
        session,
        ain=fritz_cfg["ain"],
        power_scale=fritz_cfg["power_scale"],
        energy_scale=fritz_cfg["energy_scale"],
        invert_sign=fritz_cfg["invert_sign"],
        export_element=fritz_cfg["export_element"],
    )


def dump_raw(cfg: dict) -> int:
    """First commissioning tool (spec section 6): raw responses to stdout,
    no MQTT. Answers the open questions from spec section 2."""
    source = make_fritz_source(cfg)
    print("### AHA getdevicelistinfos (Weg 1) " + "#" * 40)
    print(source.fetch_devicelist())
    print()
    print("### home_auto_query.lua EnergyStats_10 (Weg 2, undokumentiert) " + "#" * 12)
    try:
        print(source.fetch_fallback_raw())
    except Exception as e:
        print(f"(fallback query failed: {e})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="FRITZ!Smart Energy 250 -> MQTT poller")
    parser.add_argument("--config",
                        default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                             "config.yaml"))
    parser.add_argument("--simulate", action="store_true",
                        help="synthetic data instead of the FRITZ!Box; same topics, same payloads")
    parser.add_argument("--replay", metavar="LOGFILE",
                        help="replay a JSONL file written by --record")
    parser.add_argument("--replay-speed", type=float, default=1.0,
                        help="pacing factor for --replay, 0 = as fast as possible")
    parser.add_argument("--record", metavar="LOGFILE",
                        help="append raw XML responses as JSONL while polling")
    parser.add_argument("--dump-raw", action="store_true",
                        help="fetch raw responses once, print to stdout, no MQTT")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    setup_logging(args.verbose)
    cfg = load_config(args.config)

    if args.dump_raw:
        return dump_raw(cfg)

    interval_s = cfg["poll"]["interval_s"]
    if args.simulate:
        sim_cfg = cfg["simulate"]
        source = SimulateSource(send_period_s=sim_cfg["send_period_s"],
                                base_load_w=sim_cfg["base_load_w"],
                                pv_peak_w=sim_cfg["pv_peak_w"],
                                seed=sim_cfg["seed"])
    elif args.replay:
        fritz_cfg = cfg["fritzbox"]
        source = ReplaySource(
            args.replay,
            parse=lambda xml_text: parse_devicelist(
                xml_text,
                ain=fritz_cfg["ain"],
                power_scale=fritz_cfg["power_scale"],
                energy_scale=fritz_cfg["energy_scale"],
                invert_sign=fritz_cfg["invert_sign"],
                export_element=fritz_cfg["export_element"],
            ),
            speed=args.replay_speed,
        )
        interval_s = 0.0  # the replay source paces itself from the recorded timestamps
    else:
        source = make_fritz_source(cfg)

    stop = threading.Event()

    def handle_signal(signum, frame):
        jlog(logging.INFO, "shutdown_signal", signal=signal.Signals(signum).name)
        stop.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    jlog(logging.INFO, "service_start", mode=source.name,
         interval_s=interval_s, stale_after_s=cfg["poll"]["stale_after_s"])
    publisher = MqttPublisher(cfg["mqtt"])
    try:
        run_loop(source, publisher, cfg, stop, args.record, interval_s)
    finally:
        publisher.shutdown()
        jlog(logging.INFO, "service_stop")
    return 0


if __name__ == "__main__":
    sys.exit(main())
