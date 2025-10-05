import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Tuple, Optional
from PIL import Image, ImageDraw, ImageFont

import logging
import sys
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def validate_kvv_response(data, draw):
    error = ""
    if "kvv" not in data or not data["kvv"]:
        error = "No KVV response received."
    elif isinstance(data["kvv"], str) and data["kvv"].startswith("error:"):
        if "<body>" in data["kvv"]:
            data["kvv"] = data["kvv"].split("<body>")[1]
        error = data["kvv"]
    else:
        try:
            root_element = data["kvv"]["trias:Trias"]["trias:ServiceDelivery"]["trias:DeliveryPayload"]

            trips = root_element.get("trias:TripResponse", {}) \
                               .get("trias:TripResult")

            # 2. Validate nodes
            if trips is None:
                error = "Missing trip data in response."
            # 3. Validate trip content
            elif isinstance(trips, (list, dict)) and not trips:
                error = "No trips available in response."

        except KeyError as e:
            error = f"Malformed response: missing {e}"
        except Exception as e:
            error = f"Unexpected parse error: {e}"

    # If there was an error, display it
    if error:
        logger.info("Error: %s" % error)
        draw.text((20, 55), f"<!> {error}", font_size=20, fill="#A04E4E")
        return False
    return True

def _get_in(d: Dict[str, Any], keys: List[str], default=None):
    """Safe nested dict access for xmltodict-style structures."""
    cur = d
    for k in keys:
        if cur is None:
            return default
        if isinstance(cur, list):
            # many xml > dict conversions produce lists; pick the first element by default
            cur = cur[0]
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if cur is not None else default

def _first_text(node: Any) -> Optional[str]:
    """Extract trias:Text or string from xmldict node or None."""
    if node is None:
        return None
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        # many nodes are { "trias:Text": "..." , "trias:Language": "de" }
        t = node.get("trias:Text")
        if isinstance(t, list):
            return t[0]
        return t
    if isinstance(node, list) and node:
        return _first_text(node[0])
    return None

def _parse_iso_time_to_aware(dt_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO time like '2025-09-26T05:32:00Z' into timezone-aware UTC datetime."""
    if not dt_str:
        return None
    # handle trailing Z
    s = dt_str.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except Exception:
        # fallback parsing (very permissive)
        try:
            return datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except Exception:
            return None

_ISO_DUR_RE = re.compile(r"^PT(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?$")

def _iso_duration_to_minutes(iso_dur: Optional[str]) -> Optional[int]:
    """Parse ISO 8601 duration like 'PT8M' or 'PT1H10M' into integer minutes (rounded)."""
    if not iso_dur:
        return None
    m = _ISO_DUR_RE.match(iso_dur)
    if not m:
        return None
    h = int(m.group("h") or 0)
    mm = int(m.group("m") or 0)
    s = int(m.group("s") or 0)
    total_seconds = h * 3600 + mm * 60 + s
    return int(round(total_seconds / 60.0))

def _format_time_local(dt_aware: Optional[datetime], tz_name: str = "Europe/Berlin") -> Optional[str]:
    """Convert an aware datetime to tz_name and format HH:MM."""
    if dt_aware is None:
        return None
    # ensure dt_aware is timezone-aware, assume UTC if no tzinfo
    if dt_aware.tzinfo is None:
        dt_aware = dt_aware.replace(tzinfo=timezone.utc)
    try:
        local = dt_aware.astimezone(ZoneInfo(tz_name))
    except Exception:
        local = dt_aware.astimezone()
    return local.strftime("%H:%M")

def format_trip_for_display(trip_wrapper: Dict[str, Any], tz_name: str = "Europe/Berlin") -> List[Tuple[str, int]]:
    if "trias:Trip" in trip_wrapper and isinstance(trip_wrapper["trias:Trip"], dict):
        trip_obj = trip_wrapper["trias:Trip"]
    else:
        trip_obj = trip_wrapper

    legs_raw = trip_obj.get("trias:TripLeg")
    if legs_raw is None:
        return [("No trip legs", 4)]

    legs = legs_raw if isinstance(legs_raw, list) else [legs_raw]
    leg_infos = []

    for leg in legs:
        if "trias:TimedLeg" in leg:
            tl = leg["trias:TimedLeg"]

            # board/alight times with estimates
            board_dep = tl.get("trias:LegBoard", {}).get("trias:ServiceDeparture", {})
            alight_arr = tl.get("trias:LegAlight", {}).get("trias:ServiceArrival", {})

            board_time_tt = board_dep.get("trias:TimetabledTime")
            board_time_est = board_dep.get("trias:EstimatedTime")
            alight_time_tt = alight_arr.get("trias:TimetabledTime")
            alight_time_est = alight_arr.get("trias:EstimatedTime")

            board_time_utc = _parse_iso_time_to_aware(board_time_tt)
            alight_time_utc = _parse_iso_time_to_aware(alight_time_tt)
            board_time_eff = _parse_iso_time_to_aware(board_time_est) or board_time_utc
            alight_time_eff = _parse_iso_time_to_aware(alight_time_est) or alight_time_utc

            # bays (estimated overrides planned)
            bay_text = _first_text(tl.get("trias:LegBoard", {}).get("trias:EstimatedBay")) \
                       or _first_text(tl.get("trias:LegBoard", {}).get("trias:PlannedBay"))
            if bay_text and bay_text.lower().startswith("gleis "):
                bay_text = bay_text[6:]

            board_name = _first_text(_get_in(tl, ["trias:LegBoard", "trias:StopPointName"]))
            line_name = _first_text(_get_in(tl, ["trias:Service", "trias:PublishedLineName"])) \
                        or _first_text(_get_in(tl, ["trias:Service", "trias:Mode", "trias:Name"]))

            leg_infos.append({
                "type": "timed",
                "board_name": board_name,
                "bay": bay_text,
                "line": line_name,
                "has_estimates": board_dep.get("trias:EstimatedTime") is not None,
                "board_time_tt": board_time_utc,
                "board_time_eff": board_time_eff,
                "alight_time_tt": alight_time_utc,
                "alight_time_eff": alight_time_eff
            })

        elif "trias:InterchangeLeg" in leg:
            il = leg["trias:InterchangeLeg"]
            dur = il.get("trias:Duration") or il.get("trias:WalkDuration")
            tstart = il.get("trias:TimeWindowStart")
            tend = il.get("trias:TimeWindowEnd")
            leg_infos.append({
                "type": "interchange",
                "duration_iso": dur,
                "duration_min": _iso_duration_to_minutes(dur),
                "start_utc": _parse_iso_time_to_aware(tstart),
                "end_utc": _parse_iso_time_to_aware(tend),
            })
        else:
            leg_infos.append({"type": "unknown"})

    timed_indices = [i for i, li in enumerate(leg_infos) if li["type"] == "timed"]
    if not timed_indices:
        return [("No timed legs", 4)]

    result = []

    def format_time(tt: datetime, eff: datetime, has_est: bool) -> Tuple[str, int]:
        tt_s, eff_s = _format_time_local(tt, tz_name), _format_time_local(eff, tz_name)
        diff_min = int(round((eff - tt).total_seconds() / 60.0)) if (tt and eff) else 0
        txt = eff_s if eff_s else "??:??"
        if has_est and eff and tt:
            txt += f"({diff_min:+d})"
        color = 4 if diff_min >= 5 else 2
        return (txt, color)

    for idx, ti in enumerate(timed_indices):
        leg = leg_infos[ti]

        if idx == 0:
            # board time
            result.append(format_time(leg["board_time_tt"], leg["board_time_eff"], leg["has_estimates"]))
        result.append(("-", 3))

        # board stop + bay
        board_trim = (leg["board_name"] or "")[:7]
        result.append((board_trim, 0))
        if leg["bay"]:
            result.append((f"||{leg['bay']}", 3))

        # line
        result.append((" >", 3))
        result.append(((leg["line"] or ""), 6))


        result.append(("> ", 3))
        # if last leg: add arrival time
        if idx == len(timed_indices) - 1:
            result.append(format_time(leg["alight_time_tt"], leg["alight_time_eff"], leg["has_estimates"]))
        else:
            # compute changeover
            cur_eff = leg["alight_time_eff"]
            cur_tt = leg["alight_time_tt"]
            nxt = leg_infos[timed_indices[idx + 1]]
            nxt_eff, nxt_tt = nxt["board_time_eff"], nxt["board_time_tt"]
            any_est = leg["has_estimates"] or nxt["has_estimates"]

            dur_eff = int(round((nxt_eff - cur_eff).total_seconds() / 60.0))
            dur_tt = int(round((nxt_tt - cur_tt).total_seconds() / 60.0))
            diff = dur_eff - dur_tt

            txt = f"{dur_eff}m" + (f"({diff:+d})" if any_est else "")
            color = 4 if dur_eff < 5 else 2

            result.append((txt, color))

    return result
