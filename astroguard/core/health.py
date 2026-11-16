# SI disclosure: developed with assistance from Claude Code (Anthropic SI). See SI_DISCLOSURE.md.
"""Per-astronaut health assessment, recommendations, routine/gamification and access projection."""
from __future__ import annotations

import statistics
import time
from datetime import date, datetime, timedelta

from .auth import BY_ID
from .guides import BODY_SYSTEMS, INDICATORS, ROUTINE, status_of

RANK = {"none": -1, "ok": 0, "warn": 1, "crit": 2}
TIER = {"warn": "Self-care", "crit": "Flight surgeon"}
TIER_CMO = {"blood_pressure", "body_temp", "heart_rate"}  # warn-level items worth telling the CMO about


def _latest(checkins, field):
    for c in reversed(checkins):
        if c.get(field) is not None:
            return c[field], c["ts"]
    return None, None


def _device_label(device_id):
    from ..ingest.devices import DEVICE_TYPES, DEVICES
    d = DEVICES.get(device_id)
    return DEVICE_TYPES[d["type"]]["label"] if d else device_id


def _source_of(checkins, field):
    for c in reversed(checkins):
        if c.get(field) is not None:
            note = c.get("note") or ""
            return _device_label(note[7:]) if note.startswith("device:") else "check-in"
    return "check-in"


def assess(cid: str, frame: dict | None, db) -> dict:
    """Merge live sensor data + manual check-ins into indicator statuses, duty status and recommendations."""
    ch = db.checkins(cid, days=14)
    live = (frame or {}).get("crew", {}).get(cid, {})
    fts = (frame or {}).get("ts")
    ind = {}

    def put(key, value, ts, source, display=None):
        ind[key] = {"key": key, "name": INDICATORS[key]["name"], "unit": INDICATORS[key]["unit"],
                    "value": value, "display": display if display is not None else value,
                    "status": status_of(key, value), "ts": ts, "source": source, "system": INDICATORS[key]["system"]}

    dev_live = (frame or {}).get("device_live", {}).get(cid, {})

    def live_src(metric):
        return f"{_device_label(dev_live[metric])} (live)" if metric in dev_live else "wearable sensor (simulated)"

    hr = live.get("heart_rate")
    put("heart_rate", round(hr) if hr is not None else None, fts, live_src("heart_rate"))
    put("spo2", live.get("spo2"), fts, live_src("spo2"))
    sys_v, sys_ts = _latest(ch, "systolic")
    dia_v, _ = _latest(ch, "diastolic")
    put("blood_pressure", sys_v, sys_ts, _source_of(ch, "systolic"), f"{sys_v:.0f}/{dia_v:.0f}" if sys_v and dia_v else None)
    g, gts = _latest(ch, "glucose"); put("blood_glucose", g, gts, _source_of(ch, "glucose"))
    t, tts = _latest(ch, "body_temp"); put("body_temp", t, tts, _source_of(ch, "body_temp"))
    s_live = live.get("sleep_hours")
    s, sts = _latest(ch, "sleep_hours")
    if s_live is not None:
        put("sleep_hours", round(s_live, 1), fts, "actigraphy watch")
    else:
        put("sleep_hours", s, sts, "check-in")
    m, mts = _latest(ch, "mood"); put("mood", m, mts, "check-in")
    done = db.tasks_today(cid)
    ex = 120 if "exercise" in done else 0
    put("exercise_min", ex, time.time(), "routine log")
    if ex == 0 and datetime.now().hour < 11:  # not due yet
        ind["exercise_min"]["status"] = "ok"
        ind["exercise_min"]["display"] = "due 11:00"

    # recommendations ----------------------------------------------------------
    recs = []
    for k, i in ind.items():
        if i["status"] in ("warn", "crit"):
            tier = TIER[i["status"]]
            if i["status"] == "warn" and k in TIER_CMO:
                tier = "Crew Medical Officer"
            recs.append({"indicator": k, "severity": i["status"], "tier": tier,
                         "title": f"{i['name']} {'needs attention' if i['status'] == 'warn' else 'is out of range'}: {i['display']} {i['unit']}",
                         "actions": INDICATORS[k]["actions"][i["status"]]})
    recs += _trend_recs(ch)
    recs.sort(key=lambda r: -RANK.get(r["severity"], 0))

    # a missed routine task is a nudge, not a health status
    worst = max((i["status"] for k, i in ind.items() if k != "exercise_min"), key=lambda s: RANK[s], default="ok")
    restrictions = []
    if ind["sleep_hours"]["status"] == "crit":
        restrictions.append("No spacewalk, docking or robotic operations until rested")
    if any(ind[k]["status"] == "crit" for k in ("heart_rate", "blood_pressure", "spo2")):
        restrictions.append("No strenuous or safety-critical tasks: medical review")
    if ind["blood_glucose"]["status"] == "crit":
        restrictions.append("No safety-critical tasks until blood sugar is normal")
    if ind["body_temp"]["status"] == "crit":
        restrictions.append("Limit contact in shared modules")
    # duty is visible to the commander, so it must not depend on private mood
    phys = max((i["status"] for k, i in ind.items() if k not in ("exercise_min", "mood")), key=lambda s: RANK[s], default="ok")
    duty = ("Unfit for duty: medical review" if phys == "crit" and restrictions
            else "Fit with restrictions" if restrictions or phys == "crit"
            else "Fit for duty")

    systems = {}
    for sid, sysd in BODY_SYSTEMS.items():
        sts_ = [ind[k]["status"] for k in sysd["indicators"] if k in ind]
        systems[sid] = max(sts_, key=lambda s: RANK[s]) if sts_ else "ok"

    # status others may see: excludes private mood so it cannot be inferred from a color change
    physical = max((i["status"] for k, i in ind.items() if k not in ("exercise_min", "mood")),
                   key=lambda s: RANK[s], default="ok")
    physical = physical if physical != "none" else "ok"

    return {"crew_id": cid, "indicators": ind, "overall": worst if worst != "none" else "ok",
            "overall_physical": physical, "duty": duty,
            "restrictions": restrictions, "recommendations": recs, "systems": systems,
            "trends": _trends(ch), "live": live}


def _trend_recs(ch):
    out = []
    if len(ch) < 6:
        return out
    last, prev = ch[-7:], ch[-14:-7] or ch[:1]

    def avg(rows, f):
        v = [r[f] for r in rows if r.get(f) is not None]
        return statistics.mean(v) if v else None

    s_now = avg(last, "sleep_hours")
    if s_now is not None and s_now < 7:
        out.append({"indicator": "sleep_hours", "severity": "improve", "tier": "Improve",
                    "title": f"Sleep averaging {s_now:.1f} h this week (target 7-9 h)",
                    "actions": ["Move lights-out 30 minutes earlier", "Dim screens and blue light 1 hour before sleep",
                                "Use eye mask and earplugs; secure your sleeping bag to reduce drifting"]})
    b_now, b_prev = avg(last, "systolic"), avg(prev, "systolic")
    if b_now and b_prev and b_now - b_prev > 4:
        out.append({"indicator": "blood_pressure", "severity": "improve", "tier": "Improve",
                    "title": f"Blood pressure trending up (+{b_now - b_prev:.0f} mmHg vs last week)",
                    "actions": ["Keep daily aerobic exercise", "Reduce salty snacks", "Measure at the same time each morning"]})
    m_now, m_prev = avg(last, "mood"), avg(prev, "mood")
    if m_now and m_prev and m_prev - m_now >= 0.6:
        out.append({"indicator": "mood", "severity": "improve", "tier": "Improve",
                    "title": f"Mood trending down ({m_prev:.1f} to {m_now:.1f})",
                    "actions": ["Schedule a family call this week", "Plan a shared crew meal or movie",
                                "A private conversation with the psychologist is always available"]})
    return out


def _trends(ch):
    fields = ["systolic", "diastolic", "glucose", "body_temp", "sleep_hours", "mood"]
    return {"ts": [c["ts"] for c in ch], **{f: [c[f] for c in ch] for f in fields}}


# ---- routine / gamification ---------------------------------------------------
def routine(cid, db):
    done_today = db.tasks_today(cid)
    now_hm = datetime.now().strftime("%H:%M")
    tasks = []
    for t in ROUTINE:
        state = "done" if t["id"] in done_today else ("due" if t["due"] <= now_hm else "upcoming")
        tasks.append({**t, "state": state})
    rows = db.task_days(cid)
    by_day: dict[str, set] = {}
    for r in rows:
        by_day.setdefault(r["day"], set()).add(r["task_id"])
    points = sum(next((t["points"] for t in ROUTINE if t["id"] == r["task_id"]), 0) for r in rows)
    streak, d = 0, date.today()
    if "checkin" not in by_day.get(d.isoformat(), set()):
        d -= timedelta(days=1)  # today not done yet doesn't break the streak
    while "checkin" in by_day.get(d.isoformat(), set()):
        streak += 1
        d -= timedelta(days=1)
    ex_count = sum(1 for r in rows if r["task_id"] == "exercise")
    badges = [
        {"id": "first", "name": "First Step", "desc": "Complete a check-in", "earned": any(r["task_id"] == "checkin" for r in rows)},
        {"id": "streak7", "name": "Steady Orbit", "desc": "7-day check-in streak", "earned": streak >= 7},
        {"id": "bones", "name": "Iron Bones", "desc": "10 exercise sessions", "earned": ex_count >= 10},
        {"id": "full", "name": "Full Routine", "desc": "Every task done today", "earned": all(t["state"] == "done" for t in tasks)},
    ]
    level = 1 + points // 150
    return {"tasks": tasks, "points": points, "streak": streak, "level": level,
            "next_level_at": level * 150, "badges": badges,
            "due_now": [t["title"] for t in tasks if t["state"] == "due"]}


# ---- access projection ----------------------------------------------------------
def project(assessment: dict, level: str, share_mood: bool, alerts: list[dict]) -> dict:
    """Strip data the viewer is not entitled to. The server only ever sends the projected view."""
    cid = assessment["crew_id"]
    u = BY_ID[cid]
    mood_visible = level == "full" or (level == "medical" and share_mood)
    base = {"crew_id": cid, "name": u["name"], "title": u["title"], "access": level,
            "overall": assessment["overall"] if mood_visible else assessment["overall_physical"],
            "duty": assessment["duty"], "restrictions": assessment["restrictions"]}
    my_alerts = [a for a in alerts if a["state"] == "active" and (cid in a["crew"])]
    if level == "status":
        base["alerts"] = [{"severity": a["severity"],
                           "title": a["title"] if not a["key"].startswith(("hypox_", "arrhythmia_", "fatigue_", "checkin_"))
                           else "Medical: under review by flight surgeon"} for a in my_alerts]
        return base
    out = dict(assessment, **base)
    out["alerts"] = my_alerts
    if level == "medical" and not share_mood:
        out["indicators"] = {k: v for k, v in assessment["indicators"].items() if k != "mood"}
        out["recommendations"] = [r for r in assessment["recommendations"] if r["indicator"] != "mood"]
        out["trends"] = {k: v for k, v in assessment["trends"].items() if k != "mood"}
        out["mood_private"] = True
    return out
