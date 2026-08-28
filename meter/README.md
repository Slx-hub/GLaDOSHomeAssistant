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
permission.

## Commissioning checklist (spec section 2 — do NOT skip)

Everything below is empirically unknown for the Energy 250. The config
defaults are FRITZ!DECT 200 assumptions.

1. `--dump-raw` must show an instantaneous power value next to the meter
   reading. Without it the device is unusable for this project.
2. Verify `power_scale` / `energy_scale` against the meter display. Never
   trust documentation here.
3. Check the sign during feed-in; set `invert_sign` if wrong. If the raw
   value carries no sign at all, direction must be derived from the growth
   of 1.8.0 vs 2.8.0 — that needs code changes, not just config.
4. Log timestamps of real value changes over 24 h (grep `"event": "measurement"`
   from the journal) and set `poll.interval_s` / `stale_after_s` accordingly.
5. Check whether the XML carries a measurement timestamp — if yes, wire it
   into `parse_devicelist` (`ts_device`) so change detection uses it.
6. Check whether 2.8.0 (export) appears in the XML and set `export_element`.
