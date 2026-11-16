# SI disclosure: developed with assistance from Claude Code (Anthropic SI). See SI_DISCLOSURE.md.
"""Device data ingestion: smart shirts, fitness bands, glucometers, BP cuffs.

Devices push readings to the ONBOARD node at POST /api/ingest, either live (a reading every
few seconds) or as an offline BATCH (e.g. a fitness band that buffered a week of sleep and
syncs when docked). Every reading is:
  1. authenticated (device key; demo-grade),
  2. mapped to the device's owner (or an explicit crew code for shared devices),
  3. validated against plausible ranges,
  4. de-duplicated (device + metric + timestamp is unique, so re-sending a batch is safe),
  5. stored in the `readings` table (raw history, replicated to the ground), then ROUTED:
       live vitals  -> the live telemetry stream (agents analyse them within a second)
       clinical     -> a device-sourced check-in (trends, alerts, recommendations)

Adding a new device type = one entry in DEVICE_TYPES (field names -> AstroGuard metrics).
"""
from __future__ import annotations

import os
import time

DEVICE_KEY = os.environ.get("HMS_DEVICE_KEY", "demo-device-key")  # demo only
LIVE_WINDOW_S = 120  # a live reading older than this is treated as history

# canonical metric -> (min, max) plausibility
RANGES = {
    "heart_rate": (25, 230), "spo2": (50, 100), "resp_rate": (4, 60), "skin_temp": (25, 40), "hrv": (3, 250),
    "systolic": (50, 260), "diastolic": (30, 160), "glucose": (20, 600), "body_temp": (30, 43),
    "sleep_hours": (0, 24), "steps": (0, 100000),
}
LIVE_METRICS = {"heart_rate", "spo2", "resp_rate", "skin_temp", "hrv"}      # feed the live stream
CLINICAL_METRICS = {"systolic", "diastolic", "glucose", "body_temp", "sleep_hours"}  # become check-ins

DEVICE_TYPES = {
    # type: {"label", "fields": {payload field -> canonical metric}}
    "smart_shirt": {"label": "Smart shirt (Astroskin-type)",
                    "fields": {"hr": "heart_rate", "spo2": "spo2", "breathing_rate": "resp_rate",
                               "skin_temp": "skin_temp", "systolic": "systolic", "diastolic": "diastolic"}},
    "fitness_band": {"label": "Fitness band (Fitbit-type)",
                     "fields": {"heart_rate": "heart_rate", "hrv_ms": "hrv", "sleep_hours": "sleep_hours", "steps": "steps"}},
    "glucometer": {"label": "Glucometer", "fields": {"glucose_mg_dl": "glucose"}},
    "bp_cuff": {"label": "Blood pressure cuff", "fields": {"systolic": "systolic", "diastolic": "diastolic"}},
    "thermometer": {"label": "Digital thermometer", "fields": {"temp_c": "body_temp"}},
}

# Registered devices (a real system would provision these with per-device credentials)
DEVICES = {
    "shirt-PLT": {"type": "smart_shirt", "crew_id": "PLT"},
    "shirt-MS2": {"type": "smart_shirt", "crew_id": "MS2"},
    "band-PLT": {"type": "fitness_band", "crew_id": "PLT"},
    "band-MS1": {"type": "fitness_band", "crew_id": "MS1"},
    "band-CDR": {"type": "fitness_band", "crew_id": "CDR"},
    "glucometer-1": {"type": "glucometer", "crew_id": None},   # shared: reading must name the crew member
    "bpcuff-1": {"type": "bp_cuff", "crew_id": None},
    "thermo-1": {"type": "thermometer", "crew_id": None},
}


class DeviceHub:
    def __init__(self, system):
        self.system = system

    def registry(self):
        return {d: {**v, "label": DEVICE_TYPES[v["type"]]["label"]} for d, v in DEVICES.items()}

    def ingest(self, payload: dict) -> dict:
        dev_id = payload.get("device_id")
        dev = DEVICES.get(dev_id)
        if not dev:
            raise ValueError(f"unknown device '{dev_id}'")
        spec = DEVICE_TYPES[dev["type"]]
        readings = payload.get("readings") or []
        if not isinstance(readings, list) or len(readings) > 5000:
            raise ValueError("readings must be a list (max 5000 per batch)")
        from ..core.auth import CREW_IDS

        now = time.time()
        rows, rejected, live, clinical = [], [], 0, {}
        for i, r in enumerate(readings):
            crew = dev["crew_id"] or r.get("crew_id")
            if crew not in CREW_IDS:
                rejected.append({"index": i, "reason": "unknown or missing crew_id"})
                continue
            ts = float(r.get("ts") or now)
            if ts > now + 60:
                rejected.append({"index": i, "reason": "timestamp in the future"})
                continue
            # validate the whole reading first: one bad field rejects it (keeps BP pairs consistent)
            vals, problem = {}, None
            for field, metric in spec["fields"].items():
                if field not in r or r[field] is None:
                    continue
                try:
                    v = float(r[field])
                except (TypeError, ValueError):
                    problem = {"index": i, "field": field, "reason": "not a number"}
                    break
                lo, hi = RANGES[metric]
                if not lo <= v <= hi:
                    problem = {"index": i, "field": field, "reason": f"outside plausible range {lo}-{hi}"}
                    break
                vals[metric] = v
            if problem or not vals:
                rejected.append(problem or {"index": i, "reason": "no recognised fields for this device type"})
                continue
            for metric, v in vals.items():
                rows.append((dev_id, crew, metric, v, ts, now))
                if metric in LIVE_METRICS and now - ts <= LIVE_WINDOW_S:
                    self.system.sim.set_live(crew, metric, v, ts, dev_id)
                    live += 1
                if metric in CLINICAL_METRICS:
                    clinical.setdefault((crew, round(ts)), {})[metric] = v

        stored = self.system.db.insert_readings(rows)
        duplicates = len(rows) - stored
        # clinical readings -> device-sourced check-ins (only if this batch actually added new rows)
        checkins = 0
        if stored:
            for (crew, ts), vals in sorted(clinical.items(), key=lambda kv: kv[0][1]):
                self.system.device_checkin(crew, vals, ts, dev_id)
                checkins += 1
        self.system.store.log("info", "ingest", f"{dev_id}: {stored} new reading(s), {duplicates} duplicate(s), "
                                                f"{len(rejected)} rejected, {live} live, {checkins} check-in(s)")
        return {"device": dev_id, "type": dev["type"], "received": len(readings), "stored": stored,
                "duplicates": duplicates, "rejected": rejected[:20], "routed_live": live, "routed_checkins": checkins}
