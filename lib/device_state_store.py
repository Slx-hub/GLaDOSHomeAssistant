import json
import fcntl
import os
import logging

logger = logging.getLogger(__name__)

STATE_FILE = '/tmp/glados_device_state.json'


class DeviceStateStore:
    """Cross-process two-layer state store for MQTT device topics.

    Maintains two layers per topic:
      - base:     The state that scheduled events want the device in.
                  Always written, but only published when no override is active.
      - override: The state a user-initiated mode (VR, Cinema, …) has set.
                  Takes precedence over base while active.

    Backed by a JSON file with fcntl file-level locking so the main
    process and the scheduler child process stay in sync.
    """

    def __init__(self, filepath=STATE_FILE):
        self.filepath = filepath
        if not os.path.exists(filepath):
            with open(filepath, 'w') as f:
                json.dump({}, f)

    # ── atomic read-modify-write ─────────────────────────────────────

    def _transact(self, func):
        """Run *func(data)* inside an exclusive file lock.

        *func* may mutate *data* (the full state dict) and return an
        arbitrary value that is forwarded to the caller.
        """
        with open(self.filepath, 'r+') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                data = json.load(f)
            except (json.JSONDecodeError, ValueError):
                data = {}
            result = func(data)
            f.seek(0)
            f.truncate()
            json.dump(data, f, indent=2)
        return result

    # ── public API ───────────────────────────────────────────────────

    def update_base(self, topic, payload):
        """Store *payload* as the base (scheduled) state for *topic*.

        Returns ``True`` when no override is active and the caller
        should publish the payload to MQTT.  Returns ``False`` when an
        override is active (the base is still recorded for later).
        """
        def _update(data):
            entry = data.setdefault(topic, {})
            entry['base'] = payload
            return entry.get('override') is None

        should_publish = self._transact(_update)
        if not should_publish:
            logger.info("Base updated but suppressed (override active): %s", topic)
        return should_publish

    def set_override(self, topic, payload):
        """Set a user override for *topic*.  The caller should always
        publish the payload afterwards."""
        def _update(data):
            data.setdefault(topic, {})['override'] = payload

        self._transact(_update)
        logger.info("User override set: %s", topic)

    def clear_override(self, topic):
        """Remove the user override for *topic*.

        Returns the current base payload (which the caller should
        publish to restore the scheduled state), or ``None`` if no
        base state has been recorded yet.
        """
        def _update(data):
            entry = data.get(topic)
            if entry:
                entry['override'] = None
                return entry.get('base')
            return None

        base = self._transact(_update)
        logger.info("Override cleared for %s – base %s",
                     topic, "restored" if base else "empty")
        return base

    def reset(self):
        """Wipe all state (useful on startup / tests)."""
        with open(self.filepath, 'w') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            json.dump({}, f)
        logger.info("Device state store reset.")
