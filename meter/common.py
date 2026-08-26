"""Shared types and structured logging for the meter service."""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Tuple


class SourceError(Exception):
    """Polling the data source failed; the main loop logs it and carries on."""


class ReplayDone(Exception):
    """The replay file is exhausted; the service shuts down cleanly."""


@dataclass
class MeterReading:
    # Sign convention (fixed across all services): positive = Netzbezug, negative = Einspeisung
    watt: float
    import_kwh: Optional[float]          # counter 1.8.0
    export_kwh: Optional[float]          # counter 2.8.0, None until the XML element is known (spec section 2)
    raw_signature: Tuple                 # raw source values, used for change detection (spec section 3)
    source: str                          # "aha" | "simulate" | "replay"
    ts_device: Optional[datetime] = None  # measurement timestamp from the device, if the XML carries one
    raw_xml: Optional[str] = None        # untouched response, for --record / --dump-raw


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_logger = logging.getLogger("meter")


def setup_logging(verbose: bool = False):
    # Logs go to stderr so --dump-raw output on stdout stays clean.
    # journald captures both.
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(handler)
    _logger.setLevel(logging.DEBUG if verbose else logging.INFO)


def jlog(level: int, event: str, **fields):
    """One JSON object per line, so the send period of the sensor can be
    extracted from the logs later (spec section 5)."""
    record = {
        "ts": utcnow().isoformat(timespec="milliseconds"),
        "level": logging.getLevelName(level),
        "event": event,
    }
    record.update(fields)
    _logger.log(level, json.dumps(record, default=str))
