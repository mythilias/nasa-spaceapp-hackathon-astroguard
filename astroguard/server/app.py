# SI disclosure: developed with assistance from Claude Code (Anthropic SI). See SI_DISCLOSURE.md.
"""AstroGuard HTTP server and node logic (shared by the spacecraft and ground apps).

Entry points (project root):
    python run_demo.py         all-in-one demo (one process, ground delay simulated)
    python spacecraft_app.py   onboard node   (normally started by run_mission.py)
    python ground_app.py       ground node    (normally started by run_mission.py)
    python run_mission.py      both nodes + delayed space link

Standard library only. Optional: `pip install anthropic` + ANTHROPIC_API_KEY for the AI agents.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import secrets
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from astroguard.core import auth
from astroguard.core.agents import SPECIALISTS, Coordinator, Store, Supervisor
from astroguard.core.assistant import MedicalAssistant
from astroguard.core.explainer import Explainer
from astroguard.core.guides import BODY_SYSTEMS, EMERGENCY_PROTOCOLS, ENVIRONMENTS, HAZARDS, INDICATORS, ROUTINE, status_of
from astroguard.core.health import assess, project, routine
from astroguard.core.knowledge import KB
from astroguard.db.database import DB
from astroguard.ingest.devices import DeviceHub
from astroguard.sim.telemetry import CREW, SCENARIOS, TelemetrySimulator
from astroguard.sync.link import SpaceLink

ROOT = Path(__file__).resolve().parents[2]   # project root
STATIC = ROOT / "ui"

# Optional local secrets file (never committed): ANTHROPIC_API_KEY=...
_env_file = ROOT / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8-sig").splitlines():
        if "=" in _line and not _line.strip().startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))
SENSITIVE = {"full", "medical"}


class Forbidden(Exception):
    pass


class System:
    """mode: 'standalone' (everything in one process, ground delay simulated),
             'onboard' (spacecraft node: source of truth, crew logins),
             'ground'  (Earth node: replica fed over the delayed link, ground logins)."""

    def __init__(self, tick_s: float = 1.0, db_path: Path = ROOT / "data" / "astroguard.db",
                 mode: str = "standalone", peer: str | None = None, link_key: str = ""):
        self.mode = mode
        self.tick_s = tick_s
        self.store = Store()
        self.db = DB(db_path, seed=(mode != "ground"))
        self.link = None
        self.remote_ops: dict = {}
        self._cursors = {t: 0 for t in DB.REPLICATED_INCREMENTAL}
        self._sent_tick = 0
        if mode in ("onboard", "ground"):
            self.link = SpaceLink("downlink" if mode == "onboard" else "uplink", peer, link_key,
                                  lambda: ENVIRONMENTS[self.env_key]["demo_delay_s"])
        self.sim = TelemetrySimulator(seed=7)
        self.findings: queue.Queue = queue.Queue()
        self.explainer = Explainer(self.store)
        self.agents = [cls(self.store, self.findings) for cls in SPECIALISTS]
        self.coordinator = Coordinator(self.store, self.findings, self.explainer)
        self.supervisor = Supervisor(self.store, self.agents)
        self.paused = False
        self.started = time.time()
        self.env_key = "iss"
        self._audit_seen: dict[tuple, float] = {}
        self.assistant = MedicalAssistant(self)
        self.devices = DeviceHub(self)

    def start(self):
        if self.mode == "ground":
            self.link.start()
            self.link.send("resync", {})  # ask the spacecraft to resend everything
            self.store.log("info", "system", "Ground node online: waiting for downlink from the spacecraft")
            return
        for a in self.agents:
            a.start()
        self.coordinator.start()
        self.supervisor.start()
        threading.Thread(target=self._loop, name="simulator", daemon=True).start()
        if self.mode == "onboard":
            self.link.start()
            threading.Thread(target=self._downlink_loop, name="downlink", daemon=True).start()
        self.store.log("info", "system", f"AstroGuard {self.mode} node online: {len(self.agents)} agents, explainer: {self.explainer.mode}")

    # ---- two-node replication ------------------------------------------------------
    def _downlink_loop(self):
        while True:
            time.sleep(2.0)
            self.link.send("snapshot", self._snapshot())

    def _ops_local(self):
        return {"agents": [a.health() for a in self.agents] + [self.coordinator.health()],
                "explainer": self.explainer.status(), "active_scenarios": self.sim.active_scenarios(),
                "paused": self.paused, "uptime_s": round(time.time() - self.started)}

    def _snapshot(self):
        with self.store.lock:
            frames = [f for f in self.store.history if f["tick"] > self._sent_tick]
            alerts = [dict(a) for a in self.store.alerts][:60]
            spans = list(self.store.spans)[-60:]
            events = list(self.store.events)[-80:]
        if frames:
            self._sent_tick = frames[-1]["tick"]
        rows = {}
        for t in DB.REPLICATED_INCREMENTAL:
            r = self.db.rows_since(t, self._cursors[t])
            if r:
                self._cursors[t] = r[-1]["id"]
            rows[t] = r
        for t in DB.REPLICATED_FULL:
            rows[t] = self.db.all_rows(t)
        return {"frames": frames, "alerts": alerts, "spans": spans, "events": events, "db": rows,
                "ops": self._ops_local(), "env": self.env_key}

    def on_link_message(self, msg):
        kind, p = msg["kind"], msg["payload"]
        self.link.received()
        if self.mode == "ground" and kind == "snapshot":
            with self.store.lock:
                for f in p["frames"]:
                    self.store.history.append(f)
                if p["frames"]:
                    self.store.latest_frame = p["frames"][-1]
                self.store.alerts = deque(p["alerts"], maxlen=200)
                self.store.spans = deque(p["spans"], maxlen=600)
                self.store.events = deque(p["events"], maxlen=200)
            for t in DB.REPLICATED_INCREMENTAL:
                self.db.upsert(t, p["db"].get(t, []))
            for t in DB.REPLICATED_FULL:
                self.db.replace_all(t, p["db"].get(t, []))
            self.remote_ops = p["ops"]
            self.env_key = p["env"]
        elif self.mode == "onboard":
            if kind == "resync":
                self._cursors = {t: 0 for t in DB.REPLICATED_INCREMENTAL}
                self._sent_tick = 0
            elif kind == "note":
                self.db.add_note(p["from_user"], p["to"], p["text"])
                self.store.log("info", "uplink", f"Message from {p['from_user']} received for {p['to']}")
            elif kind == "audit":
                self.db.audit(p["viewer"], p["role"], p["subject"], p["level"], p["reason"])
            elif kind == "command":
                self.exec_command(p, via="uplink")

    def exec_command(self, c, via="local"):
        t = c.get("type")
        if t == "scenario":
            if c["name"] == "clear":
                self.sim.clear()
            else:
                self.sim.inject(c["name"])
            self.store.log("info", via, f"Scenario command: {c['name']}")
        elif t == "environment":
            self.set_env(c["env"])
        elif t == "chaos":
            self.chaos(c["agent"], c["kind"])
        elif t == "pause":
            self.paused = not self.paused
        elif t == "emergency_update":
            self.db.update_emergency(int(c["id"]), c.get("steps_done"), bool(c.get("resolve")))
            if c.get("resolve"):
                self.coordinator.resolve(f"emerg_{c['id']}", f"resolved by {c.get('by', '?')}")

    def node_info(self):
        return {"mode": self.mode, "link": self.link.status() if self.link else None,
                "env_delay_label": self.env["delay_label"], "assistant": self.assistant.status_text,
                "assistant_online": self.assistant.online}

    def _loop(self):
        while True:
            if not self.paused:
                frame = self.sim.step()
                with self.store.lock:
                    self.store.latest_frame = frame
                    self.store.history.append(frame)
                for a in self.agents:
                    a.submit(frame)
            time.sleep(self.tick_s)

    # ---- helpers -----------------------------------------------------------------
    @property
    def env(self):
        return {"key": self.env_key, **ENVIRONMENTS[self.env_key]}

    def frame_for(self, user):
        """Ground users see data delayed by the (demo-compressed) light-time."""
        with self.store.lock:
            hist = list(self.store.history)
        if not hist:
            return None
        # two-node mode: the delay is real (the link); standalone: simulate it
        lag = self.env["lag_ticks"] if auth.is_ground(user) and self.mode == "standalone" else 0
        return hist[max(0, len(hist) - 1 - lag)]

    def alerts_for(self, user):
        with self.store.lock:
            alerts = [dict(a) for a in self.store.alerts]
        if auth.is_ground(user) and self.mode == "standalone":
            cutoff = time.time() - self.env["lag_ticks"] * self.tick_s
            alerts = [a for a in alerts if a["ts"] <= cutoff]
        return alerts

    def emergency_patients(self):
        return {e["patient"] for e in self.db.active_emergencies()}

    def audit(self, viewer, subject, level, reason):
        if viewer.get("crew_id") == subject or level not in SENSITIVE:
            return
        key = (viewer["id"], subject, level)
        if time.time() - self._audit_seen.get(key, 0) > 60:
            self._audit_seen[key] = time.time()
            if self.mode == "ground":  # the spacecraft holds the master record: send the audit entry up
                self.link.send("audit", {"viewer": viewer["id"], "role": viewer["title"], "subject": subject,
                                         "level": level, "reason": reason})
            else:
                self.db.audit(viewer["id"], viewer["title"], subject, level, reason)

    def member_view(self, viewer, cid, alerts=None, frame=None):
        a = assess(cid, frame or self.frame_for(viewer), self.db)
        level, reason = auth.access_level(viewer, cid, self.emergency_patients(),
                                          subject_needs_attention=a["overall_physical"] != "ok",
                                          shared_with_cmo=self.db.share_vitals(cid))
        view = project(a, level, self.db.share_mood(cid), alerts if alerts is not None else self.alerts_for(viewer))
        view["access_reason"] = reason
        self.audit(viewer, cid, level, reason)
        return view

    # ---- API: astronaut ------------------------------------------------------------
    def home(self, user):
        cid = user["crew_id"]
        if not cid:
            raise Forbidden("ground users have no personal health record")
        names = {u["id"]: u["name"] for u in auth.USERS.values()}
        return {
            "me": self.member_view(user, cid),
            "routine": routine(cid, self.db),
            "notes": [dict(n, from_name=names.get(n["from_user"], n["from_user"])) for n in self.db.notes_for(cid)],
            "audit": [dict(a, viewer_name=names.get(a["viewer"], a["viewer"])) for a in self.db.audit_for(cid)],
            "share_mood_cmo": self.db.share_mood(cid),
            "share_vitals_cmo": self.db.share_vitals(cid),
            "devices": [dict(d, **self.devices.registry().get(d["device_id"], {})) for d in self.db.devices_for(cid)],
        }

    def checkin(self, user, data):
        cid = user["crew_id"]
        if not cid:
            raise Forbidden("only crew members submit check-ins")

        def num(k, lo, hi):
            v = data.get(k)
            if v in (None, ""):
                return None
            v = float(v)
            if not lo <= v <= hi:
                raise ValueError(f"{k} out of plausible range ({lo}-{hi})")
            return v

        clean = {"systolic": num("systolic", 50, 260), "diastolic": num("diastolic", 30, 160),
                 "glucose": num("glucose", 20, 600), "body_temp": num("body_temp", 30, 43),
                 "sleep_hours": num("sleep_hours", 0, 24), "mood": num("mood", 1, 5),
                 "symptoms": str(data.get("symptoms", ""))[:300], "note": str(data.get("note", ""))[:500]}
        if clean["mood"] is not None:
            clean["mood"] = int(clean["mood"])
        self.db.add_checkin(cid, clean)
        self._alert_checks(cid, clean)
        self.store.log("info", "checkin", f"{cid} submitted a health check-in")
        return self.home(user)

    def device_checkin(self, cid, vals: dict, ts: float, device_id: str):
        """Clinical readings from a device (BP cuff, glucometer, band sleep...) become a device-sourced check-in."""
        clean = {"systolic": vals.get("systolic"), "diastolic": vals.get("diastolic"), "glucose": vals.get("glucose"),
                 "body_temp": vals.get("body_temp"), "sleep_hours": vals.get("sleep_hours"), "mood": None,
                 "symptoms": "", "note": f"device:{device_id}"}
        self.db.add_checkin(cid, clean, ts=ts, routine_credit=False)
        if time.time() - ts < 6 * 3600:  # only recent readings raise alerts; old batch history just fills trends
            self._alert_checks(cid, clean)

    def _alert_checks(self, cid, clean):
        # Out-of-range values become alerts (mood stays private, so no alert for it)
        checks = [("blood_pressure", clean["systolic"], f"Blood pressure {clean['systolic']:.0f}/{(clean['diastolic'] or 0):.0f} mmHg" if clean["systolic"] else ""),
                  ("blood_glucose", clean["glucose"], f"Blood sugar {clean['glucose']:.0f} mg/dL" if clean["glucose"] else ""),
                  ("body_temp", clean["body_temp"], f"Body temperature {clean['body_temp']:.1f} °C" if clean["body_temp"] else "")]
        for ind, val, msg in checks:
            if val is None:
                continue
            st = status_of(ind, val)
            key = f"checkin_{cid}_{ind}"
            if st == "crit":
                spec = INDICATORS[ind]
                self.coordinator.raise_external(
                    key, "critical", f"{cid}: {spec['name'].lower()} out of range (check-in)",
                    f"Self-reported check-in: {msg} is outside the safe range", [cid], [msg],
                    spec["actions"]["crit"], f"{spec['name']} {spec['why']}")
            else:
                self.coordinator.resolve(key, "normal on re-check")

    def task(self, user, task_id):
        if not user["crew_id"] or task_id not in {t["id"] for t in ROUTINE}:
            raise Forbidden("invalid task")
        self.db.task_done(user["crew_id"], task_id)
        return routine(user["crew_id"], self.db)

    # ---- API: crew / ground ------------------------------------------------------------
    def team(self, user):
        alerts = self.alerts_for(user)
        frame = self.frame_for(user)
        cabin_alerts = [a for a in alerts if a["state"] == "active" and not a["key"].startswith(
            ("hypox_", "arrhythmia_", "fatigue_", "checkin_"))]
        return {
            "crew": [self.member_view(user, cid, alerts, frame) for cid in auth.CREW_IDS],
            "habitat": frame and {"cabin": frame["cabin"], "radiation": frame["radiation"], "tick": frame["tick"]},
            "cabin_alerts": cabin_alerts,
            "data_age_s": round(time.time() - frame["ts"], 1) if frame else None,
            "simulated_delay": self.env["delay_label"] if auth.is_ground(user) else None,
        }

    # ---- API: emergency ------------------------------------------------------------------
    def start_emergency(self, user, patient, protocol):
        if not user["crew_id"]:
            raise Forbidden("emergencies are started onboard")
        if patient not in auth.CREW_IDS or protocol not in EMERGENCY_PROTOCOLS:
            raise ValueError("unknown patient or protocol")
        eid = self.db.start_emergency(patient, protocol, user["id"])
        p = EMERGENCY_PROTOCOLS[protocol]
        self.coordinator.raise_external(
            f"emerg_{eid}", "critical", f"EMERGENCY: {p['title']} ({patient})",
            f"Emergency declared by {user['name']}. Full medical access is unlocked for the crew and flight surgeon.",
            [patient], [f"{user['id']} declared emergency for {patient}: {p['title']}"], p["steps"][:3],
            p["title"] + " emergency " + protocol.replace("_", " "), agent="emergency")
        self.store.log("alert", "emergency", f"EMERGENCY declared by {user['id']} for {patient}: {p['title']}")

        def write_briefing():  # AI ground-briefing agent: SBAR report for the flight surgeon (sent down the link)
            a = assess(patient, self.frame_for(user), self.db)
            view = project(a, "medical", False, self.alerts_for(user))  # minimum necessary: no mood
            text, by = self.assistant.briefing(view, protocol, user["id"], self.env)
            self.db.set_briefing(eid, text, by)
            self.store.log("info", "assistant", f"Situation report for emergency #{eid} written ({by}) and queued for the flight surgeon")
        threading.Thread(target=write_briefing, daemon=True).start()
        return {"id": eid}

    def update_emergency(self, user, eid, steps_done=None, resolve=False):
        if not user["crew_id"] and "flight_surgeon" not in user["roles"]:
            raise Forbidden("not permitted")
        self.db.update_emergency(int(eid), steps_done, resolve)
        if resolve:
            self.coordinator.resolve(f"emerg_{eid}", f"resolved by {user['id']}")
            self.store.log("info", "emergency", f"Emergency #{eid} resolved by {user['id']}")
        return {"ok": True}

    def emergencies(self, user):
        out = []
        for e in self.db.active_emergencies():
            e["protocol_detail"] = EMERGENCY_PROTOCOLS[e["protocol"]]
            e["patient_view"] = self.member_view(user, e["patient"])
            out.append(e)
        return out

    # ---- API: ops dashboard (mission control / flight surgeon) ------------------------------
    def state(self, user) -> dict:
        frame = self.frame_for(user)
        with self.store.lock:
            history = list(self.store.history)
            spans = list(self.store.spans)
            events = list(self.store.events)[-80:]
        alerts = self.alerts_for(user)[:60]
        ops = self.remote_ops if self.mode == "ground" else self._ops_local()
        ops_agents = ops.get("agents", [])
        live_agents = len([a for a in ops_agents if a["status"] != "DOWN" and a["name"] != "coordinator"]) or 1
        by_trace: dict[str, list] = {}
        for s in spans:
            by_trace.setdefault(s["trace_id"], []).append(s)
        trace = None
        for tid in reversed(list(by_trace)):
            if len(by_trace[tid]) >= live_agents:
                trace = {"trace_id": tid, "spans": by_trace[tid]}
                break
        medical = "flight_surgeon" in user["roles"]
        series = {
            "t": [f["tick"] for f in history],
            "crew": {cid: {m: [f["crew"][cid][m] for f in history] for m in ("heart_rate", "spo2", "resp_rate", "hrv")}
                     for cid in CREW} if medical else {},
            "cabin": {m: [f["cabin"][m] for f in history] for m in ("co2_mmHg", "pressure_kPa")},
            "radiation": [f["radiation"]["dose_rate_uSv_h"] for f in history],
        }
        if not medical:  # need-to-know: mission control sees cabin data, not individual vitals
            if frame:
                frame = dict(frame, crew=None)
            medical_keys = ("hypox_", "arrhythmia_", "fatigue_", "checkin_")
            alerts = [dict(a, title="Medical: under review by flight surgeon", root_cause="Restricted (need-to-know)",
                           evidence=[], actions=["Flight surgeon is handling this; check the crew board for task restrictions"],
                           agents=["restricted"], explanation="Details are restricted to the crew member, the flight surgeon and the crew medical officer.",
                           citations=[], explained_by="access policy")
                      if a["key"].startswith(medical_keys) else a for a in alerts]
            personal_agents = {"cardio", "respiratory", "sleep"}
            spans = [dict(s, findings=[f"{len(s['findings'])} finding(s), restricted"] if s["findings"] else [])
                     if s["agent"] in personal_agents else s for s in spans]
            events = [dict(e, message="Medical alert for a crew member (restricted)")
                      if e["source"] in ("coordinator", "checkin") and any(c in e["message"] for c in CREW)
                      and not any(w in e["message"] for w in ("CO2", "depressurization", "Solar", "radiation", "Cabin"))
                      else e for e in events]
        return {
            "now": time.time(), "uptime_s": ops.get("uptime_s", 0), "paused": ops.get("paused", False),
            "frame": frame, "series": series, "crew_names": CREW, "viewer": user, "env": self.env,
            "environments": {k: v["name"] for k, v in ENVIRONMENTS.items()},
            "scenarios": {k: v[0] for k, v in SCENARIOS.items()}, "active_scenarios": ops.get("active_scenarios", []),
            "alerts": alerts, "events": events[::-1], "agents": ops_agents,
            "trace": trace, "recent_spans": spans[-40:][::-1],
            "explainer": ops.get("explainer", {"mode": "waiting for downlink", "kb_passages": 0}),
            "node": self.node_info(),
        }

    def set_env(self, key):
        if key not in ENVIRONMENTS:
            raise ValueError("unknown environment")
        self.env_key = key
        self.sim.rad_mult = ENVIRONMENTS[key]["rad_mult"]
        self.store.log("info", "operator", f"Mission environment set to {ENVIRONMENTS[key]['name']}")

    def chaos(self, agent: str, kind: str) -> bool:
        for a in self.agents:
            if a.name == agent:
                if kind == "crash":
                    a.crashed = True
                    self.store.log("warn", "chaos", f"Injected crash into agent '{agent}'")
                elif kind == "slow":
                    a.slow_ms = 0 if a.slow_ms else 400
                    self.store.log("warn", "chaos", f"{'Injected' if a.slow_ms else 'Removed'} 400 ms latency on '{agent}'")
                return True
        return False


SYSTEM: System


def guides_payload():
    from astroguard.core import nasa_data
    return {"nasa_reference": {k: nasa_data.summary(k) for k in nasa_data.REFERENCE},
            "nasa_indicator_map": nasa_data.INDICATOR_TO_ANALYTE,
            "indicators": INDICATORS, "systems": BODY_SYSTEMS, "protocols": EMERGENCY_PROTOCOLS,
            "hazards": HAZARDS, "environments": ENVIRONMENTS, "routine": ROUTINE,
            "crew": {u["crew_id"]: {"name": u["name"], "title": u["title"]} for u in auth.USERS.values() if u["crew_id"]}}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, default=str).encode())

    def _user(self, *roles):
        user = auth.verify(self.headers.get("X-Session"))
        if not user:
            raise PermissionError("login required")
        if roles and not set(roles) & set(user["roles"]):
            raise Forbidden(f"requires role: {', '.join(roles)}")
        return user

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def _dispatch(self, method):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        p = url.path
        try:
            if method == "GET":
                if p in ("/", "/index.html"):
                    return self._send(200, (STATIC / "app.html").read_bytes(), "text/html; charset=utf-8")
                if p == "/ops":
                    return self._send(200, (STATIC / "ops.html").read_bytes(), "text/html; charset=utf-8")
                if p == "/api/guides":
                    return self._json(guides_payload())
                if p == "/api/node":
                    return self._json({"mode": SYSTEM.mode})
                if p == "/api/knowledge":
                    return self._json(KB)
                user = self._user()
                if p == "/api/me":
                    return self._json({"user": user, "env": SYSTEM.env, "emergencies": SYSTEM.emergencies(user),
                                       "node": SYSTEM.node_info()})
                if p == "/api/home":
                    return self._json(SYSTEM.home(user))
                if p == "/api/team":
                    if user["roles"] == ["astronaut"]:
                        raise Forbidden("crew board is for the commander, CMO and ground team")
                    return self._json(SYSTEM.team(user))
                if p == "/api/state":
                    self._user("mission_control", "flight_surgeon")
                    return self._json(SYSTEM.state(user))
            else:
                body = self._body()
                if p == "/api/login":
                    res = auth.login(body.get("code", ""))
                    if not res:
                        return self._json({"error": "Invalid access code"}, 401)
                    ground_user = auth.is_ground(res[1])
                    if SYSTEM.mode == "onboard" and ground_user:
                        return self._json({"error": "This is the spacecraft's onboard system. Ground team: sign in at the ground station (port 8001)."}, 403)
                    if SYSTEM.mode == "ground" and not ground_user:
                        return self._json({"error": "This is the ground station. Crew: sign in on the onboard system (port 8000)."}, 403)
                    return self._json({"token": res[0], "user": res[1]})
                # ---- device ingestion (wearables & medical devices -> onboard node) ----
                if p == "/api/ingest":
                    if SYSTEM.mode == "ground":
                        raise Forbidden("devices connect to the spacecraft's onboard node, not the ground station")
                    from astroguard.ingest.devices import DEVICE_KEY
                    if not secrets.compare_digest(self.headers.get("X-Device-Key", ""), DEVICE_KEY):
                        raise PermissionError("bad device key")
                    return self._json(SYSTEM.devices.ingest(body))
                # ---- deep-space link endpoints (node to node, shared key) ----
                if p in ("/api/link/rx", "/api/link/control-peer"):
                    if not SYSTEM.link or not secrets.compare_digest(self.headers.get("X-Link-Key", ""), SYSTEM.link.link_key):
                        raise Forbidden("bad link key")
                    if p == "/api/link/rx":
                        SYSTEM.on_link_message(body)
                    else:
                        SYSTEM.link.blackout = bool(body.get("blackout"))
                        SYSTEM.store.log("warn" if SYSTEM.link.blackout else "info", "link",
                                         "Link BLACKOUT (solar conjunction): messages are being stored" if SYSTEM.link.blackout
                                         else "Link restored: delivering stored messages")
                    return self._json({"ok": True})
                user = self._user()
                if p == "/api/assistant":
                    if not str(body.get("text", "")).strip():
                        raise ValueError("message required")
                    ctx = body.get("context") if isinstance(body.get("context"), dict) else {}
                    return self._json(SYSTEM.assistant.chat(user, str(body["text"]), ctx))
                if p == "/api/assistant/reset":
                    SYSTEM.assistant.reset(user)
                    return self._json({"ok": True})
                if p == "/api/link/control":
                    self._user("mission_control")
                    if not SYSTEM.link:
                        raise ValueError("two-node mode only")
                    on = bool(body.get("blackout"))
                    SYSTEM.link.blackout = on
                    SYSTEM.link.control_peer({"blackout": on})
                    SYSTEM.store.log("warn" if on else "info", "link", "Simulated solar conjunction BLACKOUT" if on else "Link restored")
                    return self._json({"ok": True, "blackout": on})
                # ---- on the ground node, operations become commands sent up the delayed link ----
                if SYSTEM.mode == "ground" and p in ("/api/environment", "/api/scenario", "/api/chaos", "/api/pause", "/api/emergency/update", "/api/note"):
                    if p == "/api/note":
                        self._user("flight_surgeon")
                        if body.get("to") not in auth.CREW_IDS or not str(body.get("text", "")).strip():
                            raise ValueError("recipient and text required")
                        SYSTEM.link.send("note", {"from_user": user["id"], "to": body["to"], "text": str(body["text"])[:1000]})
                    elif p == "/api/emergency/update":
                        self._user("flight_surgeon")
                        SYSTEM.link.send("command", {"type": "emergency_update", "id": body.get("id"), "steps_done": body.get("steps_done"),
                                                     "resolve": bool(body.get("resolve")), "by": user["id"]}, priority=True)
                    else:
                        self._user("mission_control")
                        cmd = {"/api/environment": {"type": "environment", "env": body.get("env") or q.get("env")},
                               "/api/scenario": {"type": "scenario", "name": body.get("name") or q.get("name", "")},
                               "/api/chaos": {"type": "chaos", "agent": body.get("agent") or q.get("agent", ""), "kind": body.get("kind") or q.get("kind", "crash")},
                               "/api/pause": {"type": "pause"}}[p]
                        SYSTEM.link.send("command", cmd)
                        SYSTEM.store.log("info", "uplink", f"Command queued for spacecraft: {cmd['type']} {cmd.get('name') or cmd.get('env') or cmd.get('agent') or ''}")
                    return self._json({"ok": True, "queued": True, "arrives_in_s": SYSTEM.link.delay_fn(),
                                       "blackout": SYSTEM.link.blackout})
                if p == "/api/checkin":
                    return self._json(SYSTEM.checkin(user, body))
                if p == "/api/task":
                    return self._json(SYSTEM.task(user, body.get("task_id")))
                if p == "/api/share":
                    if not user["crew_id"]:
                        raise Forbidden("crew only")
                    if body.get("what") == "vitals":
                        SYSTEM.db.set_share_vitals(user["crew_id"], bool(body.get("on")))
                    else:
                        SYSTEM.db.set_share_mood(user["crew_id"], bool(body.get("on")))
                    return self._json({"ok": True})
                if p == "/api/note":
                    self._user("flight_surgeon")
                    if body.get("to") not in auth.CREW_IDS or not str(body.get("text", "")).strip():
                        raise ValueError("recipient and text required")
                    SYSTEM.db.add_note(user["id"], body["to"], str(body["text"])[:1000])
                    return self._json({"ok": True})
                if p == "/api/emergency":
                    return self._json(SYSTEM.start_emergency(user, body.get("patient"), body.get("protocol")))
                if p == "/api/emergency/update":
                    return self._json(SYSTEM.update_emergency(user, body.get("id"), body.get("steps_done"), bool(body.get("resolve"))))
                if p == "/api/environment":
                    self._user("mission_control")
                    SYSTEM.set_env(body.get("env") or q.get("env"))
                    return self._json({"ok": True})
                if p == "/api/scenario":
                    self._user("mission_control")
                    name = body.get("name") or q.get("name", "")
                    if name == "clear":
                        SYSTEM.sim.clear()
                        SYSTEM.store.log("info", "operator", "Cleared all scenarios")
                        return self._json({"ok": True})
                    ok = SYSTEM.sim.inject(name)
                    if ok:
                        SYSTEM.store.log("info", "operator", f"Injected scenario: {name}")
                    return self._json({"ok": ok}, 200 if ok else 400)
                if p == "/api/chaos":
                    self._user("mission_control")
                    return self._json({"ok": SYSTEM.chaos(body.get("agent") or q.get("agent", ""), body.get("kind") or q.get("kind", "crash"))})
                if p == "/api/pause":
                    self._user("mission_control")
                    SYSTEM.paused = not SYSTEM.paused
                    return self._json({"paused": SYSTEM.paused})
            self._json({"error": "not found"}, 404)
        except PermissionError as e:
            self._json({"error": str(e)}, 401)
        except Forbidden as e:
            self._json({"error": str(e)}, 403)
        except (ValueError, TypeError) as e:
            self._json({"error": str(e)}, 400)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")


def main(node: str = "standalone", port: int = 8000, peer: str | None = None):
    global SYSTEM
    ap = argparse.ArgumentParser()
    # cloud hosts (e.g. Render) provide PORT and need 0.0.0.0; locally we stay on 127.0.0.1
    cloud = node == "standalone" and "PORT" in os.environ
    ap.add_argument("--port", type=int, default=int(os.environ["PORT"]) if cloud else port)
    ap.add_argument("--host", default="0.0.0.0" if cloud else "127.0.0.1")
    ap.add_argument("--tick", type=float, default=1.0, help="seconds per telemetry frame")
    ap.add_argument("--reset", action="store_true", help="wipe and re-seed the demo database")
    ap.add_argument("--node", choices=["standalone", "onboard", "ground"], default=node)
    ap.add_argument("--peer", default=peer, help="URL of the other node (two-node mode)")
    args = ap.parse_args()
    db_name = {"standalone": "astroguard.db", "onboard": "onboard.db", "ground": "ground.db"}[args.node]
    db_path = ROOT / "data" / db_name
    if args.reset and db_path.exists():
        db_path.unlink()
    if args.node != "standalone" and not args.peer:
        ap.error("--peer is required for onboard/ground nodes (or use run_mission.py)")
    link_key = os.environ.get("HMS_LINK_KEY", "")
    if args.node != "standalone" and not link_key:
        ap.error("set HMS_LINK_KEY (the same value on both nodes), or use run_mission.py")
    SYSTEM = System(tick_s=args.tick, db_path=db_path, mode=args.node, peer=args.peer, link_key=link_key)
    SYSTEM.start()
    print(f"AstroGuard [{args.node}] running at http://{args.host}:{args.port}  (explainer: {SYSTEM.explainer.mode})")
    if args.node != "ground":
        print("Crew codes: CDR 4821 · PLT 7316 · MS1/CMO 2094 · MS2/CMO 5583")
    if args.node != "onboard":
        print("Ground codes: Flight Surgeon 9001 · Mission Control 3000")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
