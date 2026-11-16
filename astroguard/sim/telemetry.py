# SI disclosure: developed with assistance from Claude Code (Anthropic SI). See SI_DISCLOSURE.md.
"""Simulated crew + cabin telemetry with injectable anomaly scenarios.

Every tick produces one frame:
    {
      "trace_id": str, "ts": float, "tick": int,
      "crew": {crew_id: {heart_rate, hr_irregularity, spo2, resp_rate, systolic_bp,
                         skin_temp, hrv, sleep_hours}},
      "cabin": {co2_mmHg, o2_pct, pressure_kPa, temp_c, humidity_pct},
      "radiation": {dose_rate_uSv_h, mission_dose_mSv},
    }
Values are synthetic and only loosely realistic. They are for demonstration.
"""
from __future__ import annotations

import math
import random
import time
import uuid

CREW = {
    "CDR": "Commander",
    "PLT": "Pilot",
    "MS1": "Mission Specialist 1",
    "MS2": "Mission Specialist 2",
}

# Per-crew physiological baselines (resting, in-flight).
BASELINES = {
    "CDR": dict(heart_rate=64, spo2=98.0, resp_rate=14, systolic_bp=118, skin_temp=33.8, hrv=58, sleep_hours=6.6),
    "PLT": dict(heart_rate=70, spo2=97.6, resp_rate=15, systolic_bp=122, skin_temp=34.0, hrv=49, sleep_hours=6.2),
    "MS1": dict(heart_rate=60, spo2=98.2, resp_rate=13, systolic_bp=112, skin_temp=33.6, hrv=66, sleep_hours=5.7),
    "MS2": dict(heart_rate=67, spo2=97.9, resp_rate=14, systolic_bp=116, skin_temp=33.9, hrv=55, sleep_hours=6.4),
}

CABIN_BASE = dict(co2_mmHg=2.4, o2_pct=21.0, pressure_kPa=101.3, temp_c=22.5, humidity_pct=45.0)
DOSE_RATE_BASE = 15.0  # uSv/h, roughly the order of magnitude seen in low Earth orbit

# name -> (description, duration_ticks, target crew or None for cabin-wide)
SCENARIOS = {
    "co2_buildup": ("CO2 scrubber degradation: cabin CO2 rises, crew respiration and heart rate respond", 90, None),
    "solar_particle_event": ("Solar particle event: radiation dose rate spikes", 60, None),
    "depressurization": ("Slow cabin leak: pressure falls, all crew desaturate", 70, None),
    "hypoxemia": ("Individual hypoxemia: one crew member's SpO2 drops", 60, "PLT"),
    "arrhythmia": ("Cardiac arrhythmia: irregular, elevated heart rate in one crew member", 50, "MS2"),
    "sleep_deprivation": ("Accumulated sleep debt: low sleep, suppressed HRV", 120, "MS1"),
}


def _ramp(elapsed: int, duration: int, rise: float = 0.35) -> float:
    """0 -> 1 envelope: ramps up over the first `rise` fraction of the scenario, holds, then eases off at the end."""
    if elapsed < 0 or elapsed >= duration:
        return 0.0
    p = elapsed / duration
    if p < rise:
        return p / rise
    if p > 0.85:
        return max(0.0, (1.0 - p) / 0.15)
    return 1.0


class TelemetrySimulator:
    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)
        self.tick = 0
        self.active: dict[str, int] = {}  # scenario -> start tick
        self.mission_dose_mSv = 42.0
        self.rad_mult = 1.0  # set by the mission environment (ISS / Moon / Mars)
        self.live: dict[tuple, tuple] = {}  # (crew, metric) -> (value, ts, device) from real devices

    def set_live(self, crew, metric, value, ts, device):
        """A real device reading replaces the simulated value for ~2 minutes."""
        self.live[(crew, metric)] = (value, ts, device)
        self._state = {cid: dict(b) for cid, b in BASELINES.items()}
        self._cabin = dict(CABIN_BASE)

    # ---- scenario control -------------------------------------------------
    def inject(self, name: str) -> bool:
        if name not in SCENARIOS:
            return False
        self.active[name] = self.tick
        return True

    def clear(self):
        self.active.clear()

    def active_scenarios(self) -> list[dict]:
        out = []
        for name, start in self.active.items():
            desc, dur, target = SCENARIOS[name]
            out.append({"name": name, "description": desc, "target": target,
                        "progress": round(min(1.0, (self.tick - start) / dur), 2)})
        return out

    def _level(self, name: str) -> float:
        if name not in self.active:
            return 0.0
        return _ramp(self.tick - self.active[name], SCENARIOS[name][1])

    # ---- frame generation -------------------------------------------------
    def _noise(self, sd: float) -> float:
        return self.rng.gauss(0, sd)

    def step(self) -> dict:
        self.tick += 1
        # expire finished scenarios
        for name in [n for n, s in self.active.items() if self.tick - s >= SCENARIOS[n][1]]:
            del self.active[name]

        co2 = self._level("co2_buildup")
        spe = self._level("solar_particle_event")
        leak = self._level("depressurization")
        circadian = math.sin(self.tick / 60.0)  # slow drift so charts are not flat

        cabin = {
            "co2_mmHg": CABIN_BASE["co2_mmHg"] + 6.2 * co2 + self._noise(0.08),
            "o2_pct": CABIN_BASE["o2_pct"] - 0.6 * leak + self._noise(0.05),
            "pressure_kPa": CABIN_BASE["pressure_kPa"] - 16.0 * leak + self._noise(0.1),
            "temp_c": CABIN_BASE["temp_c"] + 0.4 * circadian + 0.8 * co2 + self._noise(0.05),
            "humidity_pct": CABIN_BASE["humidity_pct"] + 1.5 * circadian + self._noise(0.4),
        }

        baseline = DOSE_RATE_BASE * self.rad_mult
        dose_rate = baseline * (1 + 0.1 * circadian) * (1 + 59.0 * spe) + abs(self._noise(1.0))
        self.mission_dose_mSv += dose_rate / 1000.0 / 3600.0 * 60.0  # 1 tick ~ 1 simulated minute
        radiation = {"dose_rate_uSv_h": dose_rate, "mission_dose_mSv": self.mission_dose_mSv, "baseline_uSv_h": baseline}

        crew = {}
        for cid, base in BASELINES.items():
            hyp = self._level("hypoxemia") if SCENARIOS["hypoxemia"][2] == cid else 0.0
            arr = self._level("arrhythmia") if SCENARIOS["arrhythmia"][2] == cid else 0.0
            slp = self._level("sleep_deprivation") if SCENARIOS["sleep_deprivation"][2] == cid else 0.0

            hr_irreg = 2.0 + 28.0 * arr
            hr = (base["heart_rate"] + 3 * circadian
                  + 22 * co2 + 30 * leak + 28 * hyp + 70 * arr + 8 * slp
                  + self._noise(1.5) + self.rng.uniform(-hr_irreg, hr_irreg) * (1 if arr else 0.3))
            spo2 = base["spo2"] - 1.2 * co2 - 11.5 * leak - 12.0 * hyp + self._noise(0.3)
            rr = base["resp_rate"] + 9 * co2 + 8 * leak + 9 * hyp + self._noise(0.5)
            sbp = base["systolic_bp"] + 10 * co2 + 18 * arr + 6 * slp + self._noise(2.0)
            hrv = base["hrv"] - 6 * co2 - 25 * arr - 28 * slp + self._noise(2.0)
            sleep = base["sleep_hours"] - 2.8 * slp + self._noise(0.05)

            crew[cid] = {
                "heart_rate": round(hr, 1),
                "hr_irregularity": round(hr_irreg + abs(self._noise(0.5)), 1),
                "spo2": round(min(100.0, spo2), 1),
                "resp_rate": round(rr, 1),
                "systolic_bp": round(sbp, 1),
                "skin_temp": round(base["skin_temp"] + 0.2 * circadian + self._noise(0.05), 2),
                "hrv": round(max(5.0, hrv), 1),
                "sleep_hours": round(max(0.0, sleep), 2),
            }

        device_live: dict[str, dict] = {}
        now = time.time()
        for (cid, metric), (val, ts, dev) in list(self.live.items()):
            if now - ts > 120:
                del self.live[(cid, metric)]
            elif cid in crew and metric in crew[cid]:
                crew[cid][metric] = round(val, 1)
                device_live.setdefault(cid, {})[metric] = dev

        return {
            "device_live": device_live,
            "trace_id": uuid.uuid4().hex[:12],
            "ts": time.time(),
            "tick": self.tick,
            "crew": crew,
            "cabin": {k: round(v, 2) for k, v in cabin.items()},
            "radiation": {k: round(v, 3) for k, v in radiation.items()},
        }
