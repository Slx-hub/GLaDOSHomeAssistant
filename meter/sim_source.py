"""Synthetic and replay data sources.

SimulateSource makes the full MQTT contract testable without hardware
(spec section 6): base load + fridge compressor cycle + occasional big
loads + a midday PV curve so the sign path (negative = Einspeisung) gets
exercised too. The simulated device only updates its value every
send_period_s — repeated polls in between return the identical value, so
the freshness logic sees the same picture the real sensor will produce.

ReplaySource re-feeds a JSONL file written by --record through the real
XML parser, for regression tests on the controller.
"""

from __future__ import annotations

import json
import math
import random
import time
from datetime import datetime, timezone
from typing import Callable, List, Optional

from common import MeterReading, ReplayDone, SourceError


class SimulateSource:
    name = "simulate"

    def __init__(self, send_period_s: float = 60.0, base_load_w: float = 180.0,
                 pv_peak_w: float = 2500.0, seed: Optional[int] = None):
        self.send_period_s = send_period_s
        self.base_load_w = base_load_w
        self.pv_peak_w = pv_peak_w
        self._rng = random.Random(seed)
        self._watt: Optional[float] = None
        self._value_ts = 0.0
        self._import_kwh = 4321.0   # non-zero start so the counters look like counters
        self._export_kwh = 123.0
        self._big_load_until = 0.0
        self._big_load_w = 0.0
        self._cloud = 0.8

    def poll(self) -> MeterReading:
        now = time.time()
        if self._watt is None or now - self._value_ts >= self.send_period_s:
            self._advance(now)
        return MeterReading(
            watt=self._watt,
            import_kwh=round(self._import_kwh, 3),
            export_kwh=round(self._export_kwh, 3),
            raw_signature=(round(self._watt, 1),
                           round(self._import_kwh, 3),
                           round(self._export_kwh, 3)),
            source=self.name,
            ts_device=None,   # worst case: no device timestamp, like spec section 3 assumes
        )

    def _advance(self, now: float):
        # Integrate the previous value into the counters before replacing it.
        if self._watt is not None:
            kwh = self._watt * (now - self._value_ts) / 3_600_000.0
            if kwh >= 0:
                self._import_kwh += kwh
            else:
                self._export_kwh += -kwh

        fridge_w = 75.0 if (now % 2400.0) < 700.0 else 0.0

        if now >= self._big_load_until:
            self._big_load_w = 0.0
            # roughly one big load per half hour of simulated time
            if self._rng.random() < self.send_period_s / 1800.0:
                self._big_load_until = now + self._rng.uniform(120, 600)
                self._big_load_w = self._rng.choice([800.0, 1200.0, 2000.0, 2400.0])

        hour = datetime.now().hour + datetime.now().minute / 60.0
        pv_w = 0.0
        if 8.0 < hour < 18.0 and self.pv_peak_w > 0:
            self._cloud = min(1.0, max(0.3, self._cloud + self._rng.uniform(-0.15, 0.15)))
            pv_w = self.pv_peak_w * math.sin(math.pi * (hour - 8.0) / 10.0) * self._cloud

        noise = self._rng.gauss(0.0, 8.0)
        self._watt = round(self.base_load_w + fridge_w + self._big_load_w - pv_w + noise, 1)
        self._value_ts = now


class ReplaySource:
    name = "replay"

    def __init__(self, path: str, parse: Callable[[str], MeterReading],
                 speed: float = 1.0):
        """speed=1.0 replays with the recorded pacing, higher is faster,
        0 disables pacing entirely."""
        self._parse = parse
        self._speed = speed
        self._records: List[dict] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    self._records.append(json.loads(line))
        if not self._records:
            raise SourceError(f"replay file {path} contains no records")
        self._idx = 0
        self._wall_start: Optional[float] = None
        self._rec_start = self._rec_ts(self._records[0])

    def poll(self) -> MeterReading:
        if self._idx >= len(self._records):
            raise ReplayDone()
        record = self._records[self._idx]
        self._idx += 1

        if self._speed > 0 and self._rec_start is not None:
            if self._wall_start is None:
                self._wall_start = time.monotonic()
            rec_ts = self._rec_ts(record)
            if rec_ts is not None:
                due = self._wall_start + (rec_ts - self._rec_start) / self._speed
                delay = due - time.monotonic()
                if delay > 0:
                    time.sleep(delay)

        if "raw_xml" in record:
            reading = self._parse(record["raw_xml"])
        else:
            # hand-written test records: plain values instead of raw XML
            reading = MeterReading(
                watt=float(record["watt"]),
                import_kwh=record.get("import_kwh"),
                export_kwh=record.get("export_kwh"),
                raw_signature=(record["watt"], record.get("import_kwh"),
                               record.get("export_kwh")),
                source=self.name,
            )
        reading.source = self.name
        return reading

    @staticmethod
    def _rec_ts(record: dict) -> Optional[float]:
        raw = record.get("ts_polled")
        if not raw:
            return None
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
