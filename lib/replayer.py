"""Re-send stored device state after a Zigbee device announces itself, and
verify that the command was actually accepted.

Bulbs behind a wall switch lose power when switched off.  When power
returns they rejoin the network and zigbee2mqtt publishes a
``device_announce`` event, and we re-send the state the bulb is supposed
to be in.  A single send is not reliable: the bulb has just booted, the
link may be weak (MacNoAck) and zigbee2mqtt does not retry failed
commands nor report the failure on MQTT.

Acknowledgement signal: zigbee2mqtt publishes the device's state topic
(``z2mq/<device>``) only after a ``/set`` command was acknowledged by the
device -- on a failed command nothing is published.  If that echo does
not arrive within ACK_TIMEOUT the command is re-sent.  About two seconds
after an announce zigbee2mqtt additionally reads the real state back from
the device and publishes it; if that report contradicts what we want, we
re-send as well.
"""
import json
import logging
import threading
import time
from queue import Queue, Empty

logger = logging.getLogger(__name__)

FIRST_SEND_DELAY = 0.2   # s between announce and first send (bulb just booted)
ACK_TIMEOUT = 0.5        # s to wait for zigbee2mqtt's state echo before re-sending
MAX_ATTEMPTS = 5
WATCH_WINDOW = 4.0       # s after announce during which a contradicting
                         # state report still triggers a re-send


def state_matches(desired, reported):
    """True when every key of *desired* that the device reports agrees.

    Keys the device does not report are ignored.  Strings (``on``/``ON``)
    compare case-insensitively.
    """
    for key, want in desired.items():
        if key not in reported:
            continue
        got = reported[key]
        if isinstance(want, str) or isinstance(got, str):
            if str(want).lower() != str(got).lower():
                return False
        elif want != got:
            return False
    return True


class Replayer:
    def __init__(self, publish):
        self._publish = publish          # callable(topic, payload_str)
        self._episodes = {}              # device_name -> (Queue, desired dict)
        self._lock = threading.Lock()

    # ── inputs ───────────────────────────────────────────────────────

    def on_announce(self, device_name, set_topic, desired_payload):
        """Start a replay episode for *device_name*."""
        try:
            desired = json.loads(desired_payload)
        except (json.JSONDecodeError, ValueError):
            desired = {}
        queue = Queue()
        with self._lock:
            if device_name in self._episodes:
                logger.info("Replay %s: already running, ignoring repeated announce", device_name)
                return
            self._episodes[device_name] = (queue, desired)
        threading.Thread(target=self._run,
                         args=(device_name, set_topic, desired_payload, queue),
                         daemon=True).start()

    def on_state(self, device_name, reported):
        """Feed a ``z2mq/<device>`` state report into a running episode."""
        with self._lock:
            episode = self._episodes.get(device_name)
        if episode is None:
            return
        queue, desired = episode
        queue.put(state_matches(desired, reported))

    # ── episode ──────────────────────────────────────────────────────

    def _run(self, device_name, set_topic, payload, queue):
        try:
            deadline = time.monotonic() + WATCH_WINDOW
            time.sleep(FIRST_SEND_DELAY)
            attempts = 0
            while attempts < MAX_ATTEMPTS:
                attempts += 1
                self._publish(set_topic, payload)
                try:
                    acked = queue.get(timeout=ACK_TIMEOUT)
                except Empty:
                    logger.info("Replay %s: no ack for attempt %d, re-sending", device_name, attempts)
                    continue
                if not acked:
                    logger.info("Replay %s: state differs after attempt %d, re-sending", device_name, attempts)
                    continue
                # Acked.  Keep listening for a contradicting report (e.g.
                # zigbee2mqtt's read-back ~2 s after the announce).
                if self._watch(queue, deadline):
                    logger.info("Replay %s: confirmed after %d attempt(s)", device_name, attempts)
                    return
                logger.info("Replay %s: late state report contradicts, re-sending", device_name)
            logger.warning("Replay %s: giving up after %d attempts", device_name, attempts)
        finally:
            with self._lock:
                self._episodes.pop(device_name, None)

    @staticmethod
    def _watch(queue, deadline):
        """Wait until *deadline*; False as soon as a mismatch is reported."""
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            try:
                if not queue.get(timeout=remaining):
                    return False
            except Empty:
                return True
