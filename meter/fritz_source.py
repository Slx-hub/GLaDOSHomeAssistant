"""FRITZ!Box access: SID session handling and the AHA HTTP read path.

Login follows the AVM documentation for /login_sid.lua?version=2 (PBKDF2
challenge, MD5 fallback for FritzOS < 7.24). Implemented directly instead of
via fritzconnection: both read paths only need the SID, which fritzconnection
does not expose for custom endpoints like home_auto_query.lua, and
fritzconnection's setup path requires TR-064 — which the spec explicitly
de-prioritizes for the Energy 250.

Read paths, in spec priority:
  1. AHA HTTP API: /webservices/homeautoswitch.lua?switchcmd=getdevicelistinfos
  2. /net/home_auto_query.lua — undocumented Web-UI endpoint, only exposed
     here as a raw dump for commissioning (spec section 1, Weg 2). Value
     extraction is deliberately not implemented until real hardware shows
     whether path 1 is sufficient.
"""

from __future__ import annotations

import hashlib
import logging
import time
import xml.etree.ElementTree as ET
from typing import Optional

import requests

from common import MeterReading, SourceError, jlog

INVALID_SID = "0000000000000000"


class FritzError(SourceError):
    pass


class LoginBlocked(FritzError):
    """Login backoff is active — do not hammer the box (it escalates its own
    delays and temporarily locks the account)."""


class FritzSession:
    def __init__(self, host: str, user: str, password: str,
                 use_https: bool = False, verify_tls: bool = False,
                 timeout_s: float = 10.0,
                 backoff_initial_s: float = 10.0, backoff_max_s: float = 900.0):
        self.host = host
        self.user = user
        self.password = password
        self.timeout_s = timeout_s
        self.verify_tls = verify_tls
        self.base_url = f"{'https' if use_https else 'http'}://{host}"
        self.backoff_initial_s = backoff_initial_s
        self.backoff_max_s = backoff_max_s
        self.login_failures = 0          # exposed as diag metric (spec section 1)
        self._sid: Optional[str] = None
        self._not_before = 0.0           # monotonic time before which no login attempt is made
        self._http = requests.Session()

    # ---- public API ----------------------------------------------------

    def request(self, path: str, params: Optional[dict] = None) -> str:
        """GET with a valid SID; on 403 (SID expired, e.g. after box reboot)
        relogin exactly once and retry."""
        sid = self._sid or self.login()
        params = dict(params or {})
        params["sid"] = sid
        resp = self._get(path, params)
        if resp.status_code == 403:
            jlog(logging.INFO, "sid_expired", detail="relogin after HTTP 403")
            self._sid = None
            params["sid"] = self.login()
            resp = self._get(path, params)
        resp.raise_for_status()
        return resp.text

    def login(self) -> str:
        remaining = self._not_before - time.monotonic()
        if remaining > 0:
            raise LoginBlocked(f"login backoff active for another {remaining:.0f}s")

        info = self._session_info()
        block_time = int(info.findtext("BlockTime") or 0)
        if block_time > 0:
            # The box itself is delaying after previous failed attempts.
            self._defer(block_time)
            raise LoginBlocked(f"box reports BlockTime={block_time}s")

        challenge = info.findtext("Challenge") or ""
        response = self._challenge_response(challenge)
        resp = self._http.post(
            f"{self.base_url}/login_sid.lua?version=2",
            data={"username": self.user, "response": response},
            timeout=self.timeout_s, verify=self.verify_tls,
        )
        resp.raise_for_status()
        result = ET.fromstring(resp.text)
        sid = result.findtext("SID") or INVALID_SID

        # An invalid SID is the failure signal — not an HTTP error (spec section 1).
        if sid == INVALID_SID:
            self.login_failures += 1
            backoff = min(self.backoff_initial_s * 2 ** (self.login_failures - 1),
                          self.backoff_max_s)
            block_time = int(result.findtext("BlockTime") or 0)
            self._defer(max(backoff, block_time))
            jlog(logging.ERROR, "login_failed",
                 login_failures=self.login_failures, backoff_s=max(backoff, block_time))
            raise FritzError("login rejected — check credentials and the "
                             "'Smart Home' permission of the user account")

        self.login_failures = 0
        self._sid = sid
        jlog(logging.INFO, "login_ok", user=self.user)
        return sid

    @property
    def backoff_remaining_s(self) -> float:
        return max(0.0, self._not_before - time.monotonic())

    # ---- internals -----------------------------------------------------

    def _get(self, path: str, params: dict) -> requests.Response:
        try:
            return self._http.get(f"{self.base_url}{path}", params=params,
                                  timeout=self.timeout_s, verify=self.verify_tls)
        except requests.RequestException as e:
            # Network trouble (box rebooting etc.) is not a credential problem:
            # no login backoff escalation, the poll loop simply retries.
            raise SourceError(f"HTTP request to box failed: {e}") from e

    def _session_info(self) -> ET.Element:
        try:
            resp = self._http.get(f"{self.base_url}/login_sid.lua",
                                  params={"version": 2},
                                  timeout=self.timeout_s, verify=self.verify_tls)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise SourceError(f"could not reach box for login: {e}") from e
        return ET.fromstring(resp.text)

    def _challenge_response(self, challenge: str) -> str:
        if challenge.startswith("2$"):
            # PBKDF2 (FritzOS >= 7.24): "2$<iter1>$<salt1>$<iter2>$<salt2>"
            _, iter1, salt1, iter2, salt2 = challenge.split("$")
            hash1 = hashlib.pbkdf2_hmac("sha256", self.password.encode("utf-8"),
                                        bytes.fromhex(salt1), int(iter1))
            hash2 = hashlib.pbkdf2_hmac("sha256", hash1,
                                        bytes.fromhex(salt2), int(iter2))
            return f"{salt2}${hash2.hex()}"
        # Legacy MD5 fallback (AVM doc: response = challenge-md5(challenge-password) in UTF-16LE)
        md5 = hashlib.md5(f"{challenge}-{self.password}".encode("utf-16-le")).hexdigest()
        return f"{challenge}-{md5}"

    def _defer(self, seconds: float):
        self._not_before = time.monotonic() + seconds


# -------------------------------------------------------------------------

def parse_devicelist(xml_text: str, *, ain: Optional[str],
                     power_scale: float, energy_scale: float,
                     invert_sign: bool, export_element: Optional[str]) -> MeterReading:
    """Extract the meter reading from a getdevicelistinfos response.

    Scaling defaults come from the FRITZ!DECT 200 (power in mW, energy in Wh)
    and are UNVERIFIED for the Energy 250 — see spec section 2. Both factors
    are config values, not constants, for exactly that reason.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise SourceError(f"devicelist XML unparseable: {e}") from e

    device = _select_device(root, ain)
    if device.findtext("present") == "0":
        raise SourceError("device not present (DECT connection to the box is down)")

    pm = device.find("powermeter")
    if pm is None:
        raise SourceError("selected device has no <powermeter> element — "
                          "run --dump-raw and work through spec section 2")

    power_raw = _int_or_none(pm.findtext("power"))
    if power_raw is None:
        raise SourceError("no <power> value in the XML — instantaneous power "
                          "missing (acceptance criterion 1 fails, cf. ISKRA MT631 case)")

    # Two's-complement guard: if the box encodes feed-in as an unsigned 32-bit
    # value, it would show up here as an absurdly large positive number.
    if power_raw >= 2 ** 31:
        power_raw -= 2 ** 32
        jlog(logging.DEBUG, "power_twos_complement_decoded", power_raw=power_raw)

    watt = power_raw * power_scale
    if invert_sign:
        watt = -watt

    energy_raw = _int_or_none(pm.findtext("energy"))
    import_kwh = energy_raw * energy_scale if energy_raw is not None else None

    export_raw = _int_or_none(pm.findtext(export_element)) if export_element else None
    export_kwh = export_raw * energy_scale if export_raw is not None else None

    return MeterReading(
        watt=watt,
        import_kwh=import_kwh,
        export_kwh=export_kwh,
        raw_signature=(power_raw, energy_raw, export_raw),
        source="aha",
        # No measurement timestamp is known in the AHA XML so far (spec
        # section 2) — change detection therefore runs on the raw values.
        ts_device=None,
    )


def _select_device(root: ET.Element, ain: Optional[str]) -> ET.Element:
    devices = root.findall(".//device")
    if ain:
        wanted = ain.replace(" ", "")
        for d in devices:
            if (d.get("identifier") or "").replace(" ", "") == wanted:
                return d
        found = [d.get("identifier") for d in devices]
        raise SourceError(f"AIN {ain!r} not in devicelist; found: {found}")
    for d in devices:
        if d.find("powermeter") is not None:
            return d
    raise SourceError("no device with <powermeter> capability in devicelist")


def _int_or_none(text: Optional[str]) -> Optional[int]:
    if text is None or text.strip() in ("", "-"):
        return None
    try:
        return int(text.strip())
    except ValueError:
        return None


# -------------------------------------------------------------------------

class FritzSource:
    """Primary source: AHA HTTP API (spec section 1, Weg 1)."""

    name = "aha"

    def __init__(self, session: FritzSession, *, ain: Optional[str],
                 power_scale: float, energy_scale: float,
                 invert_sign: bool, export_element: Optional[str]):
        self.session = session
        self.ain = ain
        self.power_scale = power_scale
        self.energy_scale = energy_scale
        self.invert_sign = invert_sign
        self.export_element = export_element

    def poll(self) -> MeterReading:
        xml_text = self.fetch_devicelist()
        reading = self.parse(xml_text)
        reading.raw_xml = xml_text
        return reading

    def parse(self, xml_text: str) -> MeterReading:
        return parse_devicelist(
            xml_text, ain=self.ain,
            power_scale=self.power_scale, energy_scale=self.energy_scale,
            invert_sign=self.invert_sign, export_element=self.export_element,
        )

    def fetch_devicelist(self) -> str:
        return self.session.request("/webservices/homeautoswitch.lua",
                                    {"switchcmd": "getdevicelistinfos"})

    def fetch_fallback_raw(self) -> str:
        """Raw dump of the undocumented home_auto_query.lua endpoint (Weg 2).

        Commissioning tool only — used by --dump-raw to answer whether the
        Momentanwerte live here when Weg 1 does not carry them.
        """
        xml_text = self.fetch_devicelist()
        device = _select_device(ET.fromstring(xml_text), self.ain)
        device_id = device.get("id")
        if device_id is None:
            raise SourceError("devicelist entry has no internal id attribute")
        return self.session.request("/net/home_auto_query.lua",
                                    {"command": "EnergyStats_10",
                                     "id": device_id, "xhr": 1})
