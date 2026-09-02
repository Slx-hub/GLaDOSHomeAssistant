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
import time
from typing import Optional

import paho.mqtt.client as mqtt
import yaml

from common import (MeterReading, ReplayDone, SourceError,
                    iso_z, jlog, setup_logging, utcnow)
from fritz_source import FritzSession, FritzSource, LoginBlocked, parse_devicelist
from history import HistoryRecorder
from notify import Notifier, PRIO_HIGH, PRIO_URGENT, PRIO_DEFAULT
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
    # Keep-awake poke: the Energy 250 transmits every 120s on battery, but
    # holds a 10s rate while something reads getbasicdevicestats. Off by
    # default — 120s is fine for plain data collection, and holding the device
    # awake costs battery. The battery manager turns it on over MQTT.
    "keep_awake": {
        "enabled": False,             # fallback only; the persisted state wins
        "interval_s": 60.0,           # hold expires ~126s after the last poke (measured)
        "allow_mqtt_toggle": True,    # honour <prefix>/cmd/keep_awake
        # Survives the nightly reboot without depending on broker persistence.
        "state_path": "/home/pi/GLaDOSHomeAssistant/meter/data/keep_awake.json"
    },
    # 5-minute power history recorded from the box's own 1-hour statistics
    # buffer (see history.py). Polling every 30 min gives 2x overlap, so gaps
    # while this service was down are recovered.
    "history": {
        "enabled": True,
        "interval_s": 1800.0,         # 30 min against a 60 min buffer
        "retry_s": 60.0,              # after a FAILED poll — must not burn the interval
        "db_path": "/home/pi/GLaDOSHomeAssistant/meter/data/history.db",
    },
    # Failure notifications to ntfy. The URL contains the topic name, which is
    # itself the access credential -> it comes from the NTFY_URL env var
    # (/etc/meter.env, mode 0600), never from this file.
    "notify": {
        "enabled": True,
        "url": None,                  # None => NTFY_URL env var
        "min_duration_s": 60.0,       # a failure must persist this long ...
        "min_count": 5,               # ... or recur this often, before alerting
        "timeout_s": 10.0,
        "max_per_hour": 12,           # backstop against a notification storm
        "notify_recovery": True,
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


def resolve_ntfy_url(notify_cfg: dict) -> Optional[str]:
    # Same rule as the box password: the secret lives outside the repo.
    return notify_cfg.get("url") or os.environ.get("NTFY_URL")


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


class KeepAwake:
    """Holds the Energy 250 in its 10s transmit mode by periodically reading
    getbasicdevicestats (see FritzSource.fetch_basic_stats).

    On battery the device transmits every 120s to save power. Reading the
    stats endpoint makes the box query it, which raises the rate to 10s; the
    hold expires ~126s after the last read. So the poke interval must stay
    comfortably under that, and switching off needs no command at all — the
    device falls back on its own within ~2 minutes.

    Rides on the main poll loop rather than a thread of its own: the loop
    already ticks every interval_s, which is far finer than this cadence.
    """

    def __init__(self, cfg: dict):
        self.interval_s = cfg["interval_s"]
        self.allow_mqtt_toggle = cfg["allow_mqtt_toggle"]
        self.state_path = cfg.get("state_path")
        # Event, not a bare bool: set from the paho network thread via MQTT.
        self._enabled = threading.Event()
        # Precedence: config default < locally persisted state < live/retained
        # MQTT command. The local file exists because a retained command is NOT
        # a durable store: this broker runs without `persistence`, so the pi's
        # nightly reboot restarts the container and wipes every retained
        # message before we ever subscribe.
        self._last_poke = 0.0
        self.pokes = 0
        self.last_error: Optional[str] = None
        restored = self._load_state()
        if cfg["enabled"] if restored is None else restored:
            self._enabled.set()
        if restored is not None and restored != cfg["enabled"]:
            jlog(logging.INFO, "keep_awake_restored", enabled=restored)

    def _load_state(self) -> Optional[bool]:
        if not self.state_path:
            return None
        try:
            with open(self.state_path, encoding="utf-8") as f:
                return bool(json.load(f)["keep_awake"])
        except FileNotFoundError:
            return None
        except Exception as e:
            jlog(logging.WARNING, "keep_awake_state_unreadable", error=str(e))
            return None

    def _save_state(self, on: bool):
        if not self.state_path:
            return
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.state_path)), exist_ok=True)
            tmp = f"{self.state_path}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"keep_awake": on}, f)
            os.replace(tmp, self.state_path)   # atomic: never a half-written file
        except Exception as e:
            jlog(logging.WARNING, "keep_awake_state_unwritable", error=str(e))

    @property
    def enabled(self) -> bool:
        return self._enabled.is_set()

    def set_enabled(self, on: bool) -> bool:
        """Returns True if the state actually changed."""
        if on == self.enabled:
            return False
        if on:
            self._enabled.set()
            # Poke on the next loop tick rather than waiting out the interval.
            self._last_poke = 0.0
        else:
            self._enabled.clear()
        self._save_state(on)
        jlog(logging.INFO, "keep_awake_changed", enabled=on)
        return True

    def tick(self, source) -> bool:
        """Poke if enabled and due. Returns True if a poke was attempted."""
        if not self.enabled:
            return False
        if not hasattr(source, "fetch_basic_stats"):
            return False          # --simulate / --replay have nothing to keep awake
        now = time.monotonic()
        if now - self._last_poke < self.interval_s:
            return False
        self._last_poke = now
        try:
            source.fetch_basic_stats()
            self.pokes += 1
            self.last_error = None
            jlog(logging.DEBUG, "keep_awake_poke", pokes=self.pokes)
        except Exception as e:
            # Never let the poke break the measurement path — it is an
            # optimisation, not a dependency.
            self.last_error = f"{type(e).__name__}: {e}"
            jlog(logging.WARNING, "keep_awake_poke_failed", error=self.last_error)
        return True


class MqttPublisher:
    def __init__(self, cfg: dict):
        prefix = cfg["topic_prefix"]
        self.topic_power = f"{prefix}/data/power"
        self.topic_energy = f"{prefix}/data/energy"
        self.topic_status = f"{prefix}/health/status"
        self.topic_diag = f"{prefix}/health/diag"
        self.topic_keep_awake = f"{prefix}/health/keep_awake"
        self.topic_cmd_keep_awake = f"{prefix}/cmd/keep_awake"

        # Set by main() before connecting; called from the paho network thread.
        self.on_keep_awake_cmd = None
        self.notifier = None

        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                   client_id=cfg["client_id"])
        # LWT before connect: broker flips us to offline within the keepalive
        # window after a hard kill (acceptance criterion 5).
        self._client.will_set(self.topic_status, "offline", qos=1, retain=True)
        self._client.reconnect_delay_set(min_delay=1, max_delay=60)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._host = cfg["host"]
        self._port = cfg["port"]
        self._keepalive_s = cfg["keepalive_s"]

    def start(self):
        """Connect and start the network loop.

        Deliberately separate from __init__ so callers can install
        on_keep_awake_cmd first: a retained command is delivered the instant we
        subscribe, and would be dropped if the handler were not yet in place.

        connect_async + loop_start: a broker that is down at service start
        (or restarts later) is retried with backoff (acceptance criterion 6).
        """
        self._client.connect_async(self._host, self._port,
                                   keepalive=self._keepalive_s)
        self._client.loop_start()

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        jlog(logging.INFO, "mqtt_connected", reason=str(reason_code))
        client.publish(self.topic_status, "online", qos=1, retain=True)
        if self.notifier is not None:
            self.notifier.resolved("mqtt", title="meter: MQTT broker reconnected")
        # Re-subscribe on every (re)connect. A retained command is redelivered
        # here, so the desired state survives a restart of this service without
        # the battery manager having to republish.
        client.subscribe(self.topic_cmd_keep_awake, qos=1)

    TRUTHY = {"on", "1", "true", "yes", "enable", "enabled"}
    FALSY = {"off", "0", "false", "no", "disable", "disabled"}

    def _on_message(self, client, userdata, msg):
        if msg.topic != self.topic_cmd_keep_awake or self.on_keep_awake_cmd is None:
            return
        raw = msg.payload.decode("utf-8", "replace").strip().strip('"').lower()
        if raw in self.TRUTHY:
            self.on_keep_awake_cmd(True)
        elif raw in self.FALSY:
            self.on_keep_awake_cmd(False)
        else:
            jlog(logging.WARNING, "keep_awake_cmd_invalid", payload=raw[:40])

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        jlog(logging.WARNING, "mqtt_disconnected", reason=str(reason_code))
        # Reportable because notifications go over HTTP, not through the broker.
        if self.notifier is not None:
            self.notifier.failure("mqtt", "meter: MQTT broker disconnected",
                                  f"reason: {reason_code}", tags="electric_plug")

    def publish_power(self, payload: dict):
        self._client.publish(self.topic_power, json.dumps(payload), qos=0, retain=True)

    def publish_energy(self, payload: dict):
        self._client.publish(self.topic_energy, json.dumps(payload), qos=1, retain=True)

    def publish_keep_awake(self, enabled: bool):
        self._client.publish(self.topic_keep_awake, "on" if enabled else "off",
                             qos=1, retain=True)

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
             record_path: Optional[str], interval_s: float,
             keep_awake: Optional["KeepAwake"] = None,
             history: Optional[HistoryRecorder] = None,
             notifier: Optional[Notifier] = None):
    tracker = FreshnessTracker(cfg["poll"]["stale_after_s"])
    login_failures = lambda: getattr(getattr(source, "session", None), "login_failures", 0)
    backoff_s = lambda: getattr(getattr(source, "session", None), "backoff_remaining_s", 0.0)
    last_energy_signature = None
    record_file = open(record_path, "a", encoding="utf-8") if record_path else None

    while not stop.is_set():
        started = utcnow()
        if keep_awake is not None:
            keep_awake.tick(source)
        if history is not None:
            history.tick(source)
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
            if notifier is not None:
                notifier.resolved("poll", title="meter: box reachable again")
                # stale needs a longer fuse than a poll error: the device
                # legitimately goes quiet for ~120s in power saving, and holds
                # of ~240s have been observed at mode transitions.
                if stale:
                    notifier.failure(
                        "stale", "meter: no fresh measurement",
                        f"last change {int((now - tracker.ts_measured).total_seconds())}s ago "
                        f"(stale_after_s={cfg['poll']['stale_after_s']:.0f}); "
                        "the I share should be frozen",
                        priority=PRIO_HIGH, tags="hourglass",
                        min_duration_s=300.0)
                else:
                    notifier.resolved("stale", title="meter: measurements fresh again")
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
            if notifier is not None:
                # Credential problems are separated out: they never fix
                # themselves and need a human, so they go out at urgent.
                if "login rejected" in (error or "") or login_failures() > 0:
                    notifier.failure("login", "meter: FRITZ!Box login rejected",
                                     f"{error}\ncheck FRITZBOX_PASSWORD and the "
                                     f"'Smart Home' permission "
                                     f"(login_failures={login_failures()})",
                                     priority=PRIO_URGENT, tags="rotating_light")
                else:
                    notifier.failure("poll", "meter: poll failing", error or "unknown",
                                     priority=PRIO_HIGH, tags="warning")
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
        if keep_awake is not None:
            diag["keep_awake"] = keep_awake.enabled
            if keep_awake.last_error is not None:
                diag["keep_awake_error"] = keep_awake.last_error
            if notifier is not None:
                if keep_awake.last_error is not None:
                    notifier.failure("keep_awake", "meter: keep-awake poke failing",
                                     keep_awake.last_error, priority=PRIO_DEFAULT,
                                     tags="warning")
                elif keep_awake.enabled:
                    notifier.resolved("keep_awake")
        if history is not None:
            if history.last_error is not None:
                diag["history_error"] = history.last_error
            if notifier is not None:
                if history.last_error is not None:
                    notifier.failure("history", "meter: history recording failing",
                                     history.last_error, priority=PRIO_HIGH,
                                     tags="floppy_disk")
                else:
                    notifier.resolved("history", title="meter: history recording OK")
        if notifier is not None and notifier.dropped:
            diag["notify_dropped"] = notifier.dropped
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
    parser.add_argument("--test-notify", action="store_true",
                        help="send one test notification to ntfy and exit")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    setup_logging(args.verbose)
    cfg = load_config(args.config)

    if args.dump_raw:
        return dump_raw(cfg)

    if args.test_notify:
        url = resolve_ntfy_url(cfg["notify"])
        if not url:
            print("NTFY_URL not set (and notify.url is null) — nothing to test")
            return 1
        print(f"posting to {url.rsplit('/', 1)[0]}/<topic>")
        n = Notifier({**cfg["notify"], "enabled": True}, url)
        n.event("meter: test notification",
                "If you can read this, failure notifications work.",
                priority=PRIO_DEFAULT, tags="white_check_mark")
        n.shutdown()
        print(f"sent={n.sent} dropped={n.dropped}")
        return 0 if n.sent else 1

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
    keep_awake = KeepAwake(cfg["keep_awake"])
    history = HistoryRecorder(cfg["history"])
    ntfy_url = resolve_ntfy_url(cfg["notify"])
    notifier = Notifier(cfg["notify"], ntfy_url)
    if cfg["notify"]["enabled"] and not ntfy_url:
        jlog(logging.WARNING, "notify_disabled",
             detail="NTFY_URL not set — failures will only appear in the journal")
    history.notifier = notifier

    publisher = MqttPublisher(cfg["mqtt"])

    def handle_keep_awake_cmd(on: bool):
        if keep_awake.set_enabled(on):
            publisher.publish_keep_awake(on)

    publisher.notifier = notifier
    if keep_awake.allow_mqtt_toggle:
        publisher.on_keep_awake_cmd = handle_keep_awake_cmd
    # Publish the configured default first; a retained command arriving on
    # subscribe then overrides it, which is the intended precedence.
    publisher.publish_keep_awake(keep_awake.enabled)
    publisher.start()

    try:
        run_loop(source, publisher, cfg, stop, args.record, interval_s,
                 keep_awake, history, notifier)
    finally:
        history.close()
        publisher.shutdown()
        notifier.shutdown()
        jlog(logging.INFO, "service_stop")
    return 0


if __name__ == "__main__":
    sys.exit(main())
