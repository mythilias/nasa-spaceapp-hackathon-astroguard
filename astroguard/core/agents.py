# SI disclosure: developed with assistance from Claude Code (Anthropic SI). See SI_DISCLOSURE.md.
"""Multi-agent monitoring pipeline.

    Simulator --frame--> [Cardio, Respiratory, Sleep, Radiation, Environment]  (one thread each)
                                   | findings
                                   v
                              Coordinator  --correlates over a sliding window--> Alerts
                                   |                                               |
                                   +--> Explainer (RAG + optional Claude) <--------+
    Supervisor: watches every agent's heartbeat, marks it DOWN when stale and restarts it.

Every agent records a span per frame (trace_id, start, duration, findings), so the
dashboard can show a trace waterfall and per-agent health.
"""
from __future__ import annotations

import queue
import statistics
import threading
import time
import uuid
from collections import defaultdict, deque

from ..sim.telemetry import CREW, DOSE_RATE_BASE

WARN, CRIT = "warning", "critical"
SEV_RANK = {"info": 0, WARN: 1, CRIT: 2}


def finding(agent, severity, metric, value, message, crew=None, trace_id=None):
    return {"agent": agent, "severity": severity, "metric": metric, "value": value,
            "message": message, "crew": crew, "trace_id": trace_id, "ts": time.time()}


class Store:
    """Shared, lock-protected state the dashboard reads."""

    def __init__(self):
        self.lock = threading.Lock()
        self.latest_frame: dict | None = None
        self.history: deque = deque(maxlen=180)  # recent frames for charts
        self.spans: deque = deque(maxlen=600)
        self.alerts: deque = deque(maxlen=200)
        self.events: deque = deque(maxlen=200)  # supervisor / system log

    def add_span(self, span):
        with self.lock:
            self.spans.append(span)

    def log(self, level, source, message):
        with self.lock:
            self.events.append({"ts": time.time(), "level": level, "source": source, "message": message})


# --------------------------------------------------------------------------------------
class Agent:
    name = "agent"
    domain = ""
    description = ""

    def __init__(self, store: Store, out: queue.Queue):
        self.store = store
        self.out = out
        self.inbox: queue.Queue = queue.Queue(maxsize=50)
        self.status = "STARTING"
        self.last_heartbeat = 0.0
        self.processed = 0
        self.findings_emitted = 0
        self.errors = 0
        self.restarts = 0
        self.latencies: deque = deque(maxlen=50)
        self.crashed = False   # set by chaos injection
        self.slow_ms = 0       # set by chaos injection
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.window: dict = defaultdict(lambda: deque(maxlen=20))  # rolling per-key history

    # lifecycle ------------------------------------------------------------
    def start(self):
        self._stop.clear()
        self.crashed = False
        self.slow_ms = 0
        self.status = "HEALTHY"
        self.last_heartbeat = time.time()
        self._thread = threading.Thread(target=self._run, name=self.name, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def submit(self, frame):
        try:
            self.inbox.put_nowait(frame)
        except queue.Full:
            self.errors += 1  # dropped frame = backpressure, shown on the dashboard

    def _run(self):
        while not self._stop.is_set():
            if self.crashed:  # simulated hard crash: thread dies silently, heartbeats stop
                return
            try:
                frame = self.inbox.get(timeout=0.5)
            except queue.Empty:
                self.last_heartbeat = time.time()
                continue
            t0 = time.perf_counter()
            start_ts = time.time()
            try:
                if self.slow_ms:
                    time.sleep(self.slow_ms / 1000)
                results = self.analyze(frame) or []
                for f in results:
                    f["trace_id"] = frame["trace_id"]
                    self.out.put(f)
                self.findings_emitted += len(results)
                ok = True
            except Exception as e:  # noqa: BLE001 - an agent must never take the pipeline down
                self.errors += 1
                results, ok = [], False
                self.store.log("error", self.name, f"analyze failed: {e!r}")
            dur = (time.perf_counter() - t0) * 1000
            self.latencies.append(dur)
            self.processed += 1
            self.last_heartbeat = time.time()
            self.store.add_span({"trace_id": frame["trace_id"], "tick": frame["tick"], "agent": self.name,
                                 "start": start_ts, "duration_ms": round(dur, 2), "ok": ok,
                                 "findings": [f"{f['severity']}: {f['message']}" for f in results]})

    def health(self):
        lat = list(self.latencies)
        return {
            "name": self.name, "domain": self.domain, "description": self.description,
            "status": self.status, "processed": self.processed, "findings": self.findings_emitted,
            "errors": self.errors, "restarts": self.restarts, "queue_depth": self.inbox.qsize(),
            "latency_ms_p50": round(statistics.median(lat), 2) if lat else None,
            "latency_ms_max": round(max(lat), 2) if lat else None,
            "heartbeat_age_s": round(time.time() - self.last_heartbeat, 1) if self.last_heartbeat else None,
        }

    # helpers ----------------------------------------------------------------
    def analyze(self, frame) -> list[dict]:
        raise NotImplementedError

    def sustained(self, key, value, predicate, n=3):
        """True only if `predicate` holds for the last n samples. This suppresses one-off sensor noise."""
        w = self.window[key]
        w.append(value)
        return len(w) >= n and all(predicate(v) for v in list(w)[-n:])


class CardioAgent(Agent):
    name, domain = "cardio", "Cardiovascular"
    description = "Heart rate, rhythm irregularity, blood pressure"

    def analyze(self, frame):
        out = []
        for cid, v in frame["crew"].items():
            hr, irr, sbp = v["heart_rate"], v["hr_irregularity"], v["systolic_bp"]
            if self.sustained((cid, "hr_crit"), hr, lambda x: x > 140):
                out.append(finding(self.name, CRIT, "heart_rate", hr, f"{cid} heart rate {hr:.0f} bpm (sustained >140)", cid))
            elif self.sustained((cid, "hr_warn"), hr, lambda x: x > 110):
                out.append(finding(self.name, WARN, "heart_rate", hr, f"{cid} heart rate {hr:.0f} bpm (sustained >110)", cid))
            if self.sustained((cid, "irr"), irr, lambda x: x > 15):
                out.append(finding(self.name, CRIT if irr > 22 else WARN, "hr_irregularity", irr,
                                   f"{cid} irregular rhythm (variability {irr:.0f} bpm)", cid))
            if self.sustained((cid, "sbp"), sbp, lambda x: x > 135):
                out.append(finding(self.name, WARN, "systolic_bp", sbp, f"{cid} systolic BP {sbp:.0f} mmHg", cid))
        return out


class RespiratoryAgent(Agent):
    name, domain = "respiratory", "Respiratory"
    description = "SpO2 and respiration rate"

    def analyze(self, frame):
        out = []
        for cid, v in frame["crew"].items():
            spo2, rr = v["spo2"], v["resp_rate"]
            if self.sustained((cid, "spo2c"), spo2, lambda x: x < 90):
                out.append(finding(self.name, CRIT, "spo2", spo2, f"{cid} SpO2 {spo2:.1f}% (<90)", cid))
            elif self.sustained((cid, "spo2w"), spo2, lambda x: x < 94):
                out.append(finding(self.name, WARN, "spo2", spo2, f"{cid} SpO2 {spo2:.1f}% (<94)", cid))
            if self.sustained((cid, "rr"), rr, lambda x: x > 20):
                out.append(finding(self.name, WARN, "resp_rate", rr, f"{cid} respiration {rr:.0f}/min (>20)", cid))
        return out


class SleepAgent(Agent):
    name, domain = "sleep", "Sleep & Fatigue"
    description = "Sleep duration and heart rate variability"

    def analyze(self, frame):
        out = []
        for cid, v in frame["crew"].items():
            s, hrv = v["sleep_hours"], v["hrv"]
            if self.sustained((cid, "slc"), s, lambda x: x < 5):
                out.append(finding(self.name, CRIT, "sleep_hours", s, f"{cid} slept {s:.1f} h (<5)", cid))
            elif self.sustained((cid, "slw"), s, lambda x: x < 6):
                out.append(finding(self.name, WARN, "sleep_hours", s, f"{cid} slept {s:.1f} h (<6)", cid))
            if self.sustained((cid, "hrv"), hrv, lambda x: x < 35):
                out.append(finding(self.name, WARN, "hrv", hrv, f"{cid} HRV {hrv:.0f} ms (fatigue/stress marker)", cid))
        return out


class RadiationAgent(Agent):
    name, domain = "radiation", "Radiation"
    description = "Dose rate vs baseline, cumulative mission dose"
    CAREER_LIMIT_MSV = 600.0

    def analyze(self, frame):
        out = []
        r = frame["radiation"]
        dr = r["dose_rate_uSv_h"]
        ratio = dr / r.get("baseline_uSv_h", DOSE_RATE_BASE)
        if self.sustained("drc", ratio, lambda x: x > 20, n=2):
            out.append(finding(self.name, CRIT, "dose_rate_uSv_h", round(dr, 1), f"Dose rate {dr:.0f} uSv/h ({ratio:.0f}x baseline)"))
        elif self.sustained("drw", ratio, lambda x: x > 3, n=2):
            out.append(finding(self.name, WARN, "dose_rate_uSv_h", round(dr, 1), f"Dose rate {dr:.0f} uSv/h ({ratio:.0f}x baseline)"))
        if r["mission_dose_mSv"] > 0.5 * self.CAREER_LIMIT_MSV:
            out.append(finding(self.name, WARN, "mission_dose_mSv", r["mission_dose_mSv"],
                               f"Mission dose {r['mission_dose_mSv']:.0f} mSv exceeds 50% of career limit"))
        return out


class EnvironmentAgent(Agent):
    name, domain = "environment", "Cabin Environment"
    description = "CO2, O2, total pressure, temperature"

    def analyze(self, frame):
        out = []
        c = frame["cabin"]
        co2, p = c["co2_mmHg"], c["pressure_kPa"]
        if self.sustained("co2c", co2, lambda x: x > 6):
            out.append(finding(self.name, CRIT, "co2_mmHg", co2, f"Cabin CO2 {co2:.1f} mmHg (>6)"))
        elif self.sustained("co2w", co2, lambda x: x > 4):
            out.append(finding(self.name, WARN, "co2_mmHg", co2, f"Cabin CO2 {co2:.1f} mmHg (>4)"))
        if self.sustained("pc", p, lambda x: x < 90):
            out.append(finding(self.name, CRIT, "pressure_kPa", p, f"Cabin pressure {p:.1f} kPa (<90)"))
        elif self.sustained("pw", p, lambda x: x < 97):
            out.append(finding(self.name, WARN, "pressure_kPa", p, f"Cabin pressure {p:.1f} kPa (<97)"))
        if self.sustained("o2", c["o2_pct"], lambda x: x < 20.0):
            out.append(finding(self.name, WARN, "o2_pct", c["o2_pct"], f"Cabin O2 {c['o2_pct']:.1f}%"))
        return out


SPECIALISTS = [CardioAgent, RespiratoryAgent, SleepAgent, RadiationAgent, EnvironmentAgent]


# --------------------------------------------------------------------------------------
class Coordinator:
    """Correlates findings across agents and crew into root-cause alerts."""

    name = "coordinator"
    WINDOW_S = 8.0
    COOLDOWN_S = 20.0

    def __init__(self, store: Store, inbox: queue.Queue, explainer):
        self.store, self.inbox, self.explainer = store, inbox, explainer
        self.recent: deque = deque()
        self.last_fired: dict[str, float] = {}
        self.active: dict[str, dict] = {}  # alert key -> alert currently open
        self.processed = 0
        self.last_heartbeat = time.time()
        self.latencies: deque = deque(maxlen=50)
        self.status = "HEALTHY"

    def start(self):
        threading.Thread(target=self._run, name=self.name, daemon=True).start()

    def _run(self):
        next_eval = time.time()
        while True:
            try:
                f = self.inbox.get(timeout=0.25)
                self.recent.append(f)
            except queue.Empty:
                pass
            now = time.time()
            self.last_heartbeat = now
            if now >= next_eval:
                t0 = time.perf_counter()
                self._evaluate(now)
                self.latencies.append((time.perf_counter() - t0) * 1000)
                self.processed += 1
                next_eval = now + 1.0

    # correlation rules ------------------------------------------------------
    def _evaluate(self, now):
        while self.recent and now - self.recent[0]["ts"] > self.WINDOW_S:
            self.recent.popleft()
        fs = list(self.recent)
        by = lambda agent, metric=None: [f for f in fs if f["agent"] == agent and (metric is None or f["metric"] == metric)]  # noqa: E731
        crew_with = lambda items: sorted({f["crew"] for f in items if f["crew"]})  # noqa: E731
        consumed: set[int] = set()
        fired_keys = set()

        def fire(key, severity, title, root_cause, crew, evidence, actions, query):
            consumed.update(id(e) for e in evidence)
            fired_keys.add(key)
            self._raise(key, severity, title, root_cause, crew, evidence, actions, query, now)

        co2 = by("environment", "co2_mmHg")
        pressure = by("environment", "pressure_kPa")
        resp_cardio = by("respiratory") + by("cardio", "heart_rate")
        spo2 = by("respiratory", "spo2")
        rad = by("radiation", "dose_rate_uSv_h")
        sleep = by("sleep")

        # R1 cabin depressurization: pressure loss + multi-crew desaturation
        if pressure and len(crew_with(spo2)) >= 2:
            fire("depress", CRIT, "Suspected cabin depressurization",
                 "Environmental: cabin pressure loss is lowering oxygen partial pressure for the whole crew",
                 crew_with(spo2), pressure + spo2,
                 ["Run emergency leak procedure: locate and isolate the leak",
                  "Prepare oxygen masks for all crew", "Prepare to shelter in or evacuate to the crew vehicle"],
                 "cabin pressure loss hypoxia oxygen saturation crew-wide leak")
        # R2 CO2 exposure affecting crew
        elif co2 and len(crew_with(resp_cardio)) >= 2:
            fire("co2_crew", CRIT if any(f["severity"] == CRIT for f in co2) else WARN,
                 "Cabin CO2 buildup affecting multiple crew",
                 "Environmental: elevated CO2 (likely scrubber degradation) is driving raised respiration and heart rate across the crew",
                 crew_with(resp_cardio), co2 + resp_cardio,
                 ["Check CO2 scrubber status", "Increase cabin ventilation and air flow",
                  "Move crew to a well-ventilated module", "Cross-check with portable CO2 monitors"],
                 "carbon dioxide CO2 scrubber respiration heart rate multiple crew environmental")
        elif co2:
            fire("co2", co2[-1]["severity"], "Cabin CO2 elevated",
                 "Environmental: CO2 above limit, crew physiology not yet affected", [], co2,
                 ["Check CO2 scrubber status", "Increase ventilation"], "carbon dioxide CO2 cabin scrubber")
        elif pressure:
            fire("pressure", pressure[-1]["severity"], "Cabin pressure falling",
                 "Environmental: pressure below nominal, crew SpO2 still holding", [], pressure,
                 ["Verify with redundant pressure sensors", "Begin leak check"], "cabin pressure loss leak")

        # R3 solar particle event
        if rad:
            sev = CRIT if any(f["severity"] == CRIT for f in rad) else WARN
            fire("spe", sev, "Solar particle event: radiation spike",
                 "Space weather: sharply raised dose rate, consistent with a solar particle event",
                 list(CREW), rad,
                 ["Move crew to the most shielded module (storm shelter)", "Postpone spacewalks",
                  "Log personal dosimeter readings"],
                 "solar particle event radiation dose rate shelter career limit")

        env_problem = bool(co2 or pressure)
        # R4 individual events (only when the environment is not the explanation)
        for cid in CREW:
            mine = [f for f in fs if f["crew"] == cid and id(f) not in consumed]
            m_spo2 = [f for f in mine if f["metric"] == "spo2"]
            m_irr = [f for f in mine if f["metric"] in ("hr_irregularity",)]
            m_hr = [f for f in mine if f["metric"] == "heart_rate"]
            # fatigue needs real sleep debt; low HRV alone (arrhythmia, CO2) is only supporting evidence
            m_sleep = ([f for f in mine if f["agent"] == "sleep"]
                       if any(f["metric"] == "sleep_hours" for f in mine) else [])
            if m_spo2 and not env_problem:
                fire(f"hypox_{cid}", max((f["severity"] for f in m_spo2), key=SEV_RANK.get),
                     f"{cid}: individual hypoxemia",
                     f"Individual medical: {cid} is desaturating while cabin atmosphere is nominal",
                     [cid], m_spo2 + m_hr + [f for f in mine if f["metric"] == "resp_rate"],
                     ["Re-seat the SpO2 sensor and confirm the reading", "Give supplemental oxygen",
                      "Private medical conference with the flight surgeon"],
                     "individual oxygen saturation SpO2 hypoxemia normal cabin atmosphere")
            if m_irr:
                fire(f"arrhythmia_{cid}", max((f["severity"] for f in m_irr + m_hr), key=SEV_RANK.get),
                     f"{cid}: possible cardiac arrhythmia",
                     f"Individual medical: irregular, elevated heart rate in {cid}",
                     [cid], m_irr + m_hr + [f for f in mine if f["metric"] == "systolic_bp"],
                     ["Take a 12-lead ECG", "Crew member rests; suspend strenuous tasks",
                      "Consult the flight surgeon"],
                     "heart rhythm arrhythmia irregular heart rate cardiovascular")
            if m_sleep:
                compounded = env_problem
                fire(f"fatigue_{cid}", CRIT if compounded else max((f["severity"] for f in m_sleep), key=SEV_RANK.get),
                     f"{cid}: fatigue risk" + (" compounded by cabin CO2" if compounded else ""),
                     f"Behavioral health: sleep debt and suppressed HRV in {cid}"
                     + ("; elevated CO2 further raises cognitive-impairment risk" if compounded else ""),
                     [cid], m_sleep,
                     ["Protect the next sleep period", "Reassign safety-critical tasks (spacewalk, docking)",
                      "Review workload and lighting schedule"],
                     "sleep loss fatigue performance heart rate variability" + (" CO2 compound" if compounded else ""))

        # an escalated alert supersedes its precursor
        for parent, child in (("co2_crew", "co2"), ("depress", "pressure")):
            if parent in fired_keys and child in self.active:
                a = self.active.pop(child)
                a["state"], a["resolved_at"] = "resolved", now
                a["root_cause"] += " (escalated, see the newer alert)"

        # resolve alerts whose conditions cleared
        for key in list(self.active):
            if key.startswith(("checkin_", "emerg_")):
                continue  # resolved explicitly (new normal check-in / emergency resolved)
            if key not in fired_keys and now - self.active[key]["updated"] > self.WINDOW_S:
                a = self.active.pop(key)
                a["state"] = "resolved"
                a["resolved_at"] = now
                self.store.log("info", self.name, f"Resolved: {a['title']}")

    def raise_external(self, key, severity, title, root_cause, crew, messages, actions, query, agent="checkin"):
        """Alerts originating outside the frame pipeline (manual check-ins, emergencies)."""
        ev = [finding(agent, severity, f"{agent}_{i}", None, m, crew[0] if crew else None, "manual")
              for i, m in enumerate(messages)]
        self.last_fired.pop(key, None)
        self._raise(key, severity, title, root_cause, crew, ev, actions, query, time.time())

    def resolve(self, key, note=""):
        with self.store.lock:
            a = self.active.pop(key, None)
            if a:
                a["state"], a["resolved_at"] = "resolved", time.time()
                if note:
                    a["root_cause"] += f" ({note})"
        if a:
            self.store.log("info", self.name, f"Resolved: {a['title']}")

    def _raise(self, key, severity, title, root_cause, crew, evidence, actions, query, now):
        ev = [{"agent": e["agent"], "metric": e["metric"], "value": e["value"], "message": e["message"],
               "severity": e["severity"], "trace_id": e["trace_id"]} for e in evidence]
        # de-duplicate evidence by message prefix (agents emit every tick)
        seen, uniq = set(), []
        for e in reversed(ev):
            k = (e["agent"], e["metric"], e["message"].split(" ")[0])
            if k not in seen:
                seen.add(k)
                uniq.append(e)
        with self.store.lock:
            existing = self.active.get(key)
            if existing:
                existing.update(severity=max(existing["severity"], severity, key=SEV_RANK.get),
                                evidence=uniq[:10], crew=crew or existing["crew"], updated=now)
                return
            if now - self.last_fired.get(key, 0) < self.COOLDOWN_S:
                return
            alert = {"id": uuid.uuid4().hex[:8], "key": key, "ts": now, "updated": now, "state": "active",
                     "severity": severity, "title": title, "root_cause": root_cause, "crew": crew,
                     "evidence": uniq[:10], "actions": actions, "agents": sorted({e["agent"] for e in ev}),
                     "explanation": None, "citations": [], "explained_by": None}
            self.active[key] = alert
            self.last_fired[key] = now
            self.store.alerts.appendleft(alert)
        self.store.log("alert" if severity == CRIT else "warn", self.name, f"{severity.upper()}: {title}")
        self.explainer.explain(alert, query)

    def health(self):
        lat = list(self.latencies)
        return {"name": self.name, "domain": "Correlation", "description": "Cross-agent root-cause correlation",
                "status": self.status, "processed": self.processed, "findings": len(self.store.alerts),
                "errors": 0, "restarts": 0, "queue_depth": self.inbox.qsize(),
                "latency_ms_p50": round(statistics.median(lat), 2) if lat else None,
                "latency_ms_max": round(max(lat), 2) if lat else None,
                "heartbeat_age_s": round(time.time() - self.last_heartbeat, 1)}


# --------------------------------------------------------------------------------------
class Supervisor:
    """Watches agent heartbeats and latency, and restarts dead agents."""

    STALE_S = 3.0
    RESTART_AFTER_S = 5.0

    def __init__(self, store: Store, agents: list[Agent]):
        self.store, self.agents = store, agents
        self.down_since: dict[str, float] = {}

    def start(self):
        threading.Thread(target=self._run, name="supervisor", daemon=True).start()

    def _run(self):
        while True:
            now = time.time()
            for a in self.agents:
                age = now - a.last_heartbeat
                p50 = statistics.median(a.latencies) if a.latencies else 0
                if age > self.STALE_S:
                    if a.status != "DOWN":
                        a.status = "DOWN"
                        self.down_since[a.name] = now
                        self.store.log("alert", "supervisor", f"Agent '{a.name}' heartbeat lost ({age:.1f}s): marked DOWN")
                    elif now - self.down_since[a.name] > self.RESTART_AFTER_S:
                        a.status = "RESTARTING"
                        a.restarts += 1
                        self.store.log("warn", "supervisor", f"Restarting agent '{a.name}' (restart #{a.restarts})")
                        a.start()
                        self.store.log("info", "supervisor", f"Agent '{a.name}' back online")
                elif a.slow_ms or p50 > 250 or a.inbox.qsize() > 5:
                    if a.status != "DEGRADED":
                        a.status = "DEGRADED"
                        self.store.log("warn", "supervisor",
                                       f"Agent '{a.name}' degraded (p50 {p50:.0f} ms, queue {a.inbox.qsize()})")
                elif a.status != "HEALTHY":
                    a.status = "HEALTHY"
                    self.store.log("info", "supervisor", f"Agent '{a.name}' healthy")
            time.sleep(0.5)
