import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Tuple, Optional
from PIL import Image, ImageDraw, ImageFont

def validate_kvv_response(data, draw):
    error = ""
    if "kvv" not in data or not data["kvv"]:
        error = "No KVV response received."
    else:
        try:
            root_element = data["kvv"]["trias:Trias"]["trias:ServiceDelivery"]["trias:DeliveryPayload"]

            warnings = root_element.get("trias:TripResponse", {}) \
                                   .get("trias:TripResponseContext", {}) \
                                   .get("trias:Situations")

            trips = root_element.get("trias:TripResponse", {}) \
                               .get("trias:TripResult")

            # 2. Validate nodes
            if warnings is None:
                error = "Missing warnings section in response."
            elif trips is None:
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
        print(f"Error: {error}")
        draw.text((20, 55), f"<!> {error}", font_size=20, fill=palette_colors[4])
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
    """
    Accepts either:
      - a dict like {"trias:Trip": { ... }} or
      - the dict representing the inner trias:Trip object
    Returns a list of tuples [(str, color_int), ...] as described.
    """
    # normalize to inner trip object
    if "trias:Trip" in trip_wrapper and isinstance(trip_wrapper["trias:Trip"], dict):
        trip_obj = trip_wrapper["trias:Trip"]
    else:
        trip_obj = trip_wrapper

    legs_raw = trip_obj.get("trias:TripLeg")
    if legs_raw is None:
        return [("No trip legs", 4)]

    # normalize legs to list
    if isinstance(legs_raw, dict):
        legs = [legs_raw]
    elif isinstance(legs_raw, list):
        legs = legs_raw
    else:
        return [("Unexpected leg structure", 4)]

    # Build a simplified sequence of leg infos
    leg_infos = []
    for leg in legs:
        if "trias:TimedLeg" in leg:
            tl = leg["trias:TimedLeg"]
            board_time_s = _get_in(tl, ["trias:LegBoard", "trias:ServiceDeparture", "trias:TimetabledTime"])
            alight_time_s = _get_in(tl, ["trias:LegAlight", "trias:ServiceArrival", "trias:TimetabledTime"])
            board_name = _first_text(_get_in(tl, ["trias:LegBoard", "trias:StopPointName"]))
            alight_name = _first_text(_get_in(tl, ["trias:LegAlight", "trias:StopPointName"]))
            line_name = _first_text(_get_in(tl, ["trias:Service", "trias:PublishedLineName"])) \
                        or _first_text(_get_in(tl, ["trias:Service", "trias:Mode", "trias:Name"]))
            leg_infos.append({
                "type": "timed",
                "board_time_utc": _parse_iso_time_to_aware(board_time_s),
                "alight_time_utc": _parse_iso_time_to_aware(alight_time_s),
                "board_name": board_name,
                "alight_name": alight_name,
                "line": (line_name or "").strip()
            })
        elif "trias:InterchangeLeg" in leg:
            il = leg["trias:InterchangeLeg"]
            dur = il.get("trias:Duration") or il.get("trias:WalkDuration")
            # also allow TimeWindowStart/End to be used if present
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
            # unknown leg type, skip but keep placeholder
            leg_infos.append({"type": "unknown"})

    # find indices of timed legs
    timed_indices = [i for i, li in enumerate(leg_infos) if li.get("type") == "timed"]
    if not timed_indices:
        return [("No timed legs found", 4)]

    # start result with first timed board time (local)
    first_idx = timed_indices[0]
    first_leg = leg_infos[first_idx]
    first_board_local = _format_time_local(first_leg.get("board_time_utc"), tz_name)
    result: List[Tuple[str, int]] = []
    if first_board_local:
        result.append((first_board_local, 2))
    else:
        result.append(("??:??", 2))

    # Helper to find next timed index after i
    def _next_timed_index(after_index: int) -> Optional[int]:
        for k in timed_indices:
            if k > after_index:
                return k
        return None

    # Iterate over each timed leg in sequence and append the requested tuples
    for ti_idx in timed_indices:
        leg = leg_infos[ti_idx]
        # arrow  >  line  >  arrow  >  alight stop
        result.append((" > ", 3))
        result.append(((leg.get("line") or ""), 6))
        result.append((" > ", 3))

        # use alight_name trimmed to 5 chars
        alight_name = leg.get("alight_name") or leg.get("board_name") or ""
        alight_trim = (alight_name.strip()[:5]) if alight_name else ""
        result.append((alight_trim, 0))

        # determine what's next: either final alight time or changeover minutes to next timed board
        next_ti = _next_timed_index(ti_idx)
        if next_ti is None:
            # last timed leg: append its alight time formatted
            final_alight_local = _format_time_local(leg.get("alight_time_utc"), tz_name)
            result.append((" > ", 3))
            result.append((final_alight_local or "??:??", 2))
        else:
            # there is a following timed leg. Check if there is an interchange between current and next
            # scan leg_infos between ti_idx and next_ti for an interchange with duration
            change_min = None
            for mid in range(ti_idx + 1, next_ti):
                mid_leg = leg_infos[mid]
                if mid_leg.get("type") == "interchange":
                    # prefer explicit duration if present
                    if mid_leg.get("duration_min") is not None:
                        change_min = mid_leg["duration_min"]
                        break
                    # otherwise, if start/end times are present use them
                    if mid_leg.get("start_utc") and mid_leg.get("end_utc"):
                        delta = mid_leg["end_utc"] - mid_leg["start_utc"]
                        change_min = int(round(delta.total_seconds() / 60.0))
                        break
            # if no explicit interchange duration, compute difference between next board and current alight
            if change_min is None:
                cur_alight_utc = leg.get("alight_time_utc")
                next_board_utc = leg_infos[next_ti].get("board_time_utc")
                if cur_alight_utc and next_board_utc:
                    # compute minutes (could be negative in malformed data — clamp to 0)
                    delta_min = int(round((next_board_utc - cur_alight_utc).total_seconds() / 60.0))
                    change_min = max(0, delta_min)
                else:
                    change_min = None

            # append change string
            result.append((" > ", 3))
            if change_min is None:
                # fallback to showing next board time if we can't compute minutes
                next_board_local = _format_time_local(leg_infos[next_ti].get("board_time_utc"), tz_name)
                result.append((next_board_local or "??:??", 2))
            else:
                result.append((f"{change_min} min", 2))

            # after adding a change entry, loop continues; next timed leg will again append  >  line  >  ...
            # so visually you'll get: ... (alight)  >  (X min)  >  (line of next leg) ...
    return result
