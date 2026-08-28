# meter.service

Polls the FRITZ!Smart Energy 250 through the FRITZ!Box and publishes grid
power to MQTT. Slow correction path (I share) for the power controller — the
fast path comes from the Shelly plugs. May fail without stopping the control
loop.

Standalone: own venv, own systemd unit, no dependency on the Rhasspy stack.

## MQTT contract (stable — changes break `control` and `watchdog`)

| Topic | Retain | QoS | Content |
|---|---|---|---|
| `powermeter/data/power` | yes | 0 | `{watt, ts_measured, ts_polled, fresh, stale, source}` |
| `powermeter/data/energy` | yes | 1 | `{import_kwh, export_kwh, ts_measured, source}` |
| `powermeter/health/status` | yes | 1 | `online` / `offline` (LWT) |
| `powermeter/health/diag` | no | 0 | poll timings, login failures, backoff state |
| `powermeter/health/keep_awake` | yes | 1 | `on` / `off` — current fast-sampling state |
| `powermeter/cmd/keep_awake` | — | 1 | **subscribed**: `on` / `off` (publish retained) |

Sign: **positive = Netzbezug, negative = Einspeisung.**

Consumers must evaluate `ts_measured` — a retained value is a start value,
not necessarily a fresh one. `fresh: false` means the poll returned the same
measurement again (the device sends slower than we poll); `stale: true`
after `stale_after_s` without change means: freeze the I share.

## Modes

```bash
python meter_service.py                     # real polling (needs FRITZBOX_PASSWORD)
python meter_service.py --simulate          # synthetic data, same topics/payloads
python meter_service.py --dump-raw          # raw box responses to stdout, no MQTT
python meter_service.py --record raw.jsonl  # record raw XML while polling
python meter_service.py --replay raw.jsonl  # re-feed a recording through the parser
```

## Setup on the pi

Runs as part of `complete_setup.sh`, or standalone:

```bash
./setup_meter.sh              # idempotent, safe to re-run
sudo nano /etc/meter.env      # FRITZBOX_PASSWORD, mode 0600
nano config.yaml              # box IP, user, AIN
./setup_meter.sh              # re-run starts the service once the password is set
```

Box prerequisites: FRITZ!OS 8+, a user account with the **Smart Home**
permission. Nothing here needs "FRITZ!Box Einstellungen" (BoxAdmin) — that is
only required for the undocumented `home_auto_query.lua` endpoints, which are
used by `--dump-raw` for commissioning and are otherwise unnecessary.

`setup_meter.sh` enables two units: `meter.service` (polling + history
recording) and `meter-history.service` (the web UI on port 8086).

## The device, as measured

Commissioned 2026-08-28 against a FRITZ!Box 7590 on FritzOS 8.25. Everything
here is empirical — AVM documents almost none of it.

**Two device entries, and the powermeter is on the sub-unit.** `getdevicelistinfos`
returns the SE 250 twice:

| identifier | id | functionbitmask | carries |
|---|---|---|---|
| `15282 0921804` | 16 | 1 | `battery`, `batterylow` — **no** `<powermeter>` |
| `15282 0921804-1` | 2000 | 8322 | `<powermeter>` |

`ain: null` picks the first entry that has a `<powermeter>`, which happens to
work, but the AIN is pinned in `config.yaml` so it does not depend on ordering.

**Units differ between the two endpoints.** This is the easiest way to be wrong
by 100x:

| Source | Element | Unit |
|---|---|---|
| `getdevicelistinfos` | `<power>` | mW (`294000` = 294.0 W) |
| `getdevicelistinfos` | `<energy>` | Wh (`8245442` = 8245.442 kWh) |
| `getbasicdevicestats` | `power/stats` | **0.01 W** (`23900` = 239.0 W) |

Scaling was cross-checked by comparing the energy counter's growth against
time-weighted mean power over 8 minutes: 41 Wh observed vs 39.2 Wh expected,
and the 4.6% excess is fully explained by a transmit pause during which the
frozen power value understated the truth. `power_scale`/`energy_scale` of
0.001 are correct.

**No measurement timestamp** anywhere in the XML, so `ts_device` stays `None`
and change detection runs on the raw signature. **No 2.8.0 export element** —
`<powermeter>` carries only `voltage` (always empty), `power`, `energy`, so
`export_element` stays `null` and `export_kwh` is always `None`.

### Transmit rate — the 120s power saving mode

On battery the device transmits **every 120s**. It goes to **10s** while
something is actively reading it, and falls back afterwards. Measured
behaviour:

| Event | Trigger | Latency |
|---|---|---|
| asleep → 10s | a `getbasicdevicestats` read arrives | fast from its next scheduled transmit, so up to ~2 min |
| 10s → asleep | ~126s after the last read | (two runs: 126s, 131s — likely a 120s timer) |

Consequences:

* Polling `getdevicelistinfos` (the main measurement loop) does **not** affect
  the rate, no matter how fast. Only the stats endpoint does.
* Reading the stats endpoint needs only the **Smart Home** permission.
* Turning it off requires no command — the hold simply lapses, so a crash or
  reboot cannot leave the device stuck awake.
* There is **no setting** for this: not in the AHA API (the device exposes no
  config elements at all), not in the manual, not in the firmware changelog.
* **USB-C power does not disable it** — tested with a continuous supply, still
  120s. Several reviews claim otherwise; they are wrong.

During power saving the box fills its statistics buffer by *repeating* the last
value in blocks of 12, so the frozen `<power>` value can be badly wrong mid-gap
— in one measured case it read 270 W while the true mean from the energy
counter was 360 W. Consumers wanting accuracy across a gap should prefer
`dE/dt` over the instantaneous value.

## Keep-awake (fast sampling on demand)

`keep_awake` in `config.yaml`, off by default. When enabled the service pokes
`getbasicdevicestats` every `interval_s` (60s, comfortably inside the ~126s
hold) to hold 10s transmission.

Meant to be driven at runtime by the battery manager, not by config:

```bash
mosquitto_pub -t powermeter/cmd/keep_awake -m on  -q 1 -r   # fast sampling
mosquitto_pub -t powermeter/cmd/keep_awake -m off -q 1 -r   # back to 120s
```

Publish it **retained**: the command is redelivered when this service
subscribes, so the desired state survives a restart here without the battery
manager noticing. Current state is mirrored on
`powermeter/health/keep_awake` and in every `diag` payload.

Holding the device awake costs battery — 12x the radio duty cycle — which is
why it is opt-in and self-releasing.

## History (5-minute averages)

Recorded from the box's **own** 1-hour statistics buffer, not from our MQTT
stream: polling every 30 min against a 60 min buffer gives 2x overlap, so data
recorded while this service was down is still recovered. `history` in
`config.yaml`.

Stored in SQLite (`data/history.db`, WAL, gitignored) as 5-minute means:

```sql
power_5min(ts INTEGER PRIMARY KEY, watt REAL, n INTEGER)
```

`ts` is the UTC epoch of the bucket start; `n` is how many 10s samples went
into it (30 = complete). A bucket is only overwritten by one built from
strictly more samples, so re-reading a partial trailing bucket never degrades
a complete one. A `0` in the stats array is treated as *no data* rather than
0 W — the box pads unreported series with zeros (the voltage array is all
zeros) and a whole-house meter never reads 0.

**Note:** the history poll and the keep-awake poke are the same request, so
recording wakes the device for ~2 min every 30 min (~7% duty cycle) even with
`keep_awake` off.

### Surviving the nightly reboot

The pi reboots at 02:00 and is back in ~20s. Nothing is lost, by construction:

* **The first tick after start always polls** (`_next_poll` starts at 0), so
  collection resumes immediately instead of waiting out the interval.
* The box buffer holds **60 min** and we poll every **30 min**, so the last
  read is at most 30 min old when the outage begins — leaving ~30 min of slack
  before anything falls out of the buffer. A 20-second reboot is nowhere near it.
* **Only a successful poll consumes the full interval.** A failure retries
  after `retry_s` (60s). This matters precisely at boot: the box can be briefly
  unreachable while the network comes up, and burning 30 min on that could push
  the next read past the buffer.
* The last successful poll is persisted in `meta.last_success_ts` (**wall
  clock**, so it survives the reboot). Each poll logs
  `since_last_success_s`, and if the gap exceeded the buffer it logs a
  `history_gap` **warning** — data lost that way is unrecoverable, so it is
  worth seeing rather than silently missing.

Bucket timestamps come from the box's `datatime`, not the pi's clock, so an
unsynced clock at boot cannot misplace data.

The hard limit: if the pi is offline for **more than an hour**, the box has
already overwritten that part of its buffer and the data is gone for good.

### Web UI — `meter-history.service`, port 8086

Separate process from `meter.service` on purpose: the measurement path must not
share a process with a web server. Opens the database read-only.

Day navigation, per-day chart, and period averages defaulting to all available
data. Days are local calendar days (Europe/Berlin); storage stays UTC.

| Endpoint | Returns |
|---|---|
| `GET /` | the page |
| `GET /api/days` | one row per local day with data |
| `GET /api/day?date=YYYY-MM-DD` | 5-min series + summary + the local-day window |
| `GET /api/summary[?from=&to=]` | averages; **no range = all data** |

## Failure notifications (ntfy)

Failures go to a self-hosted ntfy topic over **HTTP** — deliberately not through
MQTT, so a dead broker is still reportable. `notify` in `config.yaml`.

The URL contains the topic name, which **is** the access credential (anyone
holding it can read and post), so it lives in `/etc/meter.env` as `NTFY_URL`
and never in this repo. Unset it to disable notifications; failures still go to
the journal either way.

```bash
python meter_service.py --test-notify    # send one test message and exit
```

### What gets reported

| Key | Condition | Priority |
|---|---|---|
| `login` | box login rejected — needs a human, never self-heals | urgent |
| `poll` | box unreachable / device absent / unparseable | high |
| `stale` | no fresh measurement (fuse: 300s, above normal power saving) | high |
| `history` | history recording failing | high |
| `mqtt` | broker disconnected | high |
| `keep_awake` | keep-awake poke failing | default |
| — | history gap: data lost for good (one-shot `event`) | default |

### Why you will not get spammed

The poll loop runs every 5s, so a box outage would otherwise produce ~720
messages an hour. Alerts are **edge-triggered per key**:

* A condition must persist `min_duration_s` (60s) **or** recur `min_count` (5)
  times before anything is sent — so a SID expiry or a WiFi blip stays silent.
* Exactly **one** message per outage, however long it lasts.
* Exactly **one** recovery message, and only if a failure was actually
  announced. A condition that never alerted never sends an "all clear".
* `max_per_hour` (12) is a hard backstop; drops are counted in `diag`.

Verified against a blackholed box IP: 9 consecutive poll errors produced 1
notification.

Sending runs on a daemon thread behind a bounded queue. A full queue drops
rather than blocks, and every transport error is swallowed — a broken notifier
must never become a measurement outage.

## Commissioning checklist

Worked through on 2026-08-28 — kept for the next device/meter.

1. ~~`--dump-raw` must show an instantaneous power value.~~ **Pass** —
   `<power>` present alongside `<energy>`.
2. ~~Verify `power_scale` / `energy_scale`.~~ **Pass** — cross-checked against
   counter growth (see above). A glance at the meter display would make it
   absolute rather than relative.
3. **OPEN — sign during feed-in.** No negative and no >=2^31 value has been
   observed yet, so `invert_sign` is unverified. With no 2.8.0 element there is
   no counter-growth fallback, so if the raw value turns out to be unsigned
   this needs code, not config.
4. ~~Measure the send period and set `poll.interval_s` / `stale_after_s`.~~
   **Done** — 10s active / 120s power saving; `interval_s: 5.0`,
   `stale_after_s: 180.0`.
5. ~~Check for a measurement timestamp in the XML.~~ **None** — change
   detection stays on the raw signature.
6. ~~Check whether 2.8.0 appears.~~ **It does not** — `export_element` stays
   `null`.
