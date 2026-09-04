"""Failure notifications to ntfy.

Design constraints, in order of importance:

1. Never block or break the measurement path. Sending happens on a daemon
   thread behind a bounded queue; a full queue drops rather than waits, and any
   transport error is logged and swallowed.
2. Never spam. The poll loop runs every 5s, so a box outage would otherwise
   produce ~720 notifications an hour. Alerts are edge-triggered per key: one
   message when a condition has persisted long enough to be real, one when it
   clears, nothing in between.
3. Never cry wolf. A single failed poll is usually transient (a SID expiry, a
   WiFi blip). A condition must persist for min_duration_s OR min_count
   consecutive reports before anything is sent, so blips stay silent.

Deliberately over HTTP, not MQTT: that way a dead broker is still reportable.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import unicodedata
from typing import Dict, Optional

import requests

from common import jlog

# ntfy carries title/tags in HTTP headers, and requests encodes headers as
# latin-1. A single em dash in a title used to raise UnicodeEncodeError inside
# the worker -- swallowed, so the alert simply never arrived. Fold the exotic
# punctuation this codebase likes down to ASCII before it reaches a header.
_HEADER_SUBS = str.maketrans({
    "\u2014": "-", "\u2013": "-", "\u2026": "...",
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
})


def _header_safe(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.translate(_HEADER_SUBS))
    return folded.encode("ascii", "replace").decode("ascii")


# ntfy priorities
PRIO_LOW = "low"
PRIO_DEFAULT = "default"
PRIO_HIGH = "high"
PRIO_URGENT = "urgent"


class _Alert:
    __slots__ = ("first_seen", "count", "notified", "last_detail")

    def __init__(self, now: float, detail: str):
        self.first_seen = now
        self.count = 1
        self.notified = False
        self.last_detail = detail


class Notifier:
    def __init__(self, cfg: dict, url: Optional[str], token: Optional[str] = None):
        self.enabled = bool(cfg["enabled"]) and bool(url)
        self.url = url
        self.token = token
        self.min_duration_s = float(cfg["min_duration_s"])
        self.min_count = int(cfg["min_count"])
        self.timeout_s = float(cfg["timeout_s"])
        self.max_per_hour = int(cfg["max_per_hour"])
        self.notify_recovery = bool(cfg["notify_recovery"])

        self._alerts: Dict[str, _Alert] = {}
        self._sent_times: list = []          # for the hourly rate cap
        self.sent = 0
        self.dropped = 0
        self._q: "queue.Queue[tuple]" = queue.Queue(maxsize=64)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        if self.enabled:
            self._thread = threading.Thread(target=self._worker, name="notify",
                                            daemon=True)
            self._thread.start()

    # ---- public API ------------------------------------------------------

    def failure(self, key: str, title: str, detail: str,
                priority: str = PRIO_HIGH, tags: str = "warning",
                min_duration_s: Optional[float] = None):
        """Report that `key` is currently failing. Edge-triggered: sends at most
        once per outage, and only once the condition has proven persistent."""
        if not self.enabled:
            return
        now = time.monotonic()
        a = self._alerts.get(key)
        if a is None:
            self._alerts[key] = _Alert(now, detail)
            return                      # first sighting is never worth waking anyone
        a.count += 1
        a.last_detail = detail
        if a.notified:
            return
        threshold = self.min_duration_s if min_duration_s is None else min_duration_s
        if (now - a.first_seen) >= threshold or a.count >= self.min_count:
            a.notified = True
            held = int(now - a.first_seen)
            self._enqueue(title,
                          f"{detail}\n\nfailing for {held}s ({a.count} occurrences)",
                          priority, tags)

    def resolved(self, key: str, title: str = None, tags: str = "white_check_mark"):
        """Report that `key` is healthy. Only sends if a failure was announced,
        so conditions that never alerted also never produce a recovery message."""
        if not self.enabled:
            return
        a = self._alerts.pop(key, None)
        if a is None or not a.notified:
            return
        if not self.notify_recovery:
            return
        held = int(time.monotonic() - a.first_seen)
        self._enqueue(title or f"recovered: {key}",
                      f"back to normal after {held}s ({a.count} occurrences)",
                      PRIO_LOW, tags)

    def event(self, title: str, detail: str,
              priority: str = PRIO_DEFAULT, tags: str = "warning"):
        """One-shot notification for something that is not a state (e.g. data
        lost for good). No dedupe — callers must only fire these rarely."""
        if not self.enabled:
            return
        self._enqueue(title, detail, priority, tags)

    def shutdown(self):
        if self._thread is None:
            return
        self._stop.set()
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass
        self._thread.join(timeout=5)

    # ---- internals -------------------------------------------------------

    def _enqueue(self, title: str, body: str, priority: str, tags: str):
        if not self._rate_ok():
            self.dropped += 1
            jlog(logging.WARNING, "notify_rate_limited", title=title,
                 max_per_hour=self.max_per_hour)
            return
        try:
            self._q.put_nowait((title, body, priority, tags))
        except queue.Full:
            self.dropped += 1
            jlog(logging.WARNING, "notify_queue_full", title=title)

    def _rate_ok(self) -> bool:
        cutoff = time.monotonic() - 3600
        self._sent_times = [t for t in self._sent_times if t > cutoff]
        if len(self._sent_times) >= self.max_per_hour:
            return False
        self._sent_times.append(time.monotonic())
        return True

    def _worker(self):
        session = requests.Session()
        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=1.0)
            except queue.Empty:
                continue
            if item is None:
                break
            title, body, priority, tags = item
            headers = {"Title": _header_safe(title),
                       "Priority": priority, "Tags": _header_safe(tags)}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            try:
                r = session.post(self.url, data=body.encode("utf-8"),
                                 headers=headers, timeout=self.timeout_s)
                r.raise_for_status()
                self.sent += 1
                jlog(logging.INFO, "notify_sent", title=title, priority=priority)
            except Exception as e:
                # A failing notifier must never escalate into a service problem.
                self.dropped += 1
                jlog(logging.WARNING, "notify_failed", title=title,
                     error=f"{type(e).__name__}: {e}")
