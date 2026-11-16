# SI disclosure: developed with assistance from Claude Code (Anthropic SI). See SI_DISCLOSURE.md.
"""AI agents (Claude) for AstroGuard.

1. Medical Assistant: a chat agent for each signed-in user. Its tools are created PER REQUEST
   and run with THAT user's permissions, so the AI can never see more than the person asking.
2. Ground Briefing agent: writes an SBAR situation report for the flight surgeon when an
   emergency is declared, so one delayed message carries everything the ground needs.

Safety design (Anthropic high-risk use requirements and NASA practice):
  * Clearly labelled AI; not a doctor; no medication dosing.
  * Red-flag symptoms are detected by deterministic code, NOT the model, and always surface
    the emergency protocol with a human-confirmed "Start emergency" button.
  * The AI suggests; decisions go to the Crew Medical Officer / flight surgeon.
  * Minimum necessary data: crew codes instead of names; private data only for the asker.
  * If the model is unavailable (no key, no link, blackout) everything falls back to the
    rule-based knowledge base. The demo uses a cloud model as a stand-in for an onboard model.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time

from .guides import EMERGENCY_PROTOCOLS, INDICATORS
from .knowledge import Retriever

MODEL = os.environ.get("HMS_MODEL", "claude-opus-5-5")
MAX_TOOL_ROUNDS = 6
MAX_TURNS = 12  # then the conversation restarts (we never edit history; append-only)

RED_FLAGS = [
    (re.compile(r"chest (pain|tight|pressure)|heart attack|collaps|unconscious|not breathing|no pulse|unresponsive", re.I), "chest_pain"),
    (re.compile(r"can'?t breathe|cannot breathe|short(ness)? of breath|choking|low oxygen|pressure (drop|loss|leak)", re.I), "low_oxygen"),
    (re.compile(r"faint|pass(ed)? out|dizz(y|iness) and|blacking out", re.I), "fainting"),
    (re.compile(r"radiation (alarm|storm|spike)|solar (flare|particle)", re.I), "radiation"),
]
SELF_HARM = re.compile(r"suicid|kill myself|end my life|self[- ]harm|hurt myself", re.I)

SYSTEM_PROMPT = """You are the AstroGuard Medical Assistant, an AI aboard a crewed spacecraft. You help astronauts \
(who are not doctors) understand their health data and follow approved guidance when the flight surgeon on Earth \
may be minutes away.

How to work:
- Before advising, use your tools to check the asker's actual data (health summary, trends, cabin environment). \
Base advice on the knowledge-base guidance and measurement guides your tools return, and cite passage ids like [env-co2-2].
- Consider whether the cause is environmental (cabin CO2, pressure, radiation) or personal.
- Give a short, plain answer: what is likely going on, why it matters in spaceflight, and 2-4 concrete next steps. \
Label each step's tier: Self-care, Crew Medical Officer, or Flight surgeon.
- Keep answers under about 150 words unless the person asks for step-by-step instructions.

Limits you must keep:
- You are an AI assistant, not a doctor. Never give medication names with doses or diagnose definitively; \
route those decisions to the Crew Medical Officer or flight surgeon.
- If anything suggests an emergency (chest pain, collapse, breathing trouble, confusion, severe bleeding), \
tell them to start EMERGENCY mode immediately and call the suggest_emergency_protocol tool.
- Respect privacy. Tools only return what this user is allowed to see. If data about a crewmate is restricted, \
say so plainly and do not guess. Never ask the person to reveal a crewmate's private information.
- Only call request_cmo_review if the user has clearly agreed to share their concern with the Crew Medical Officer.
- If the person mentions low mood or distress, respond with warmth, and remind them a private conference with the \
flight surgeon or psychologist is available any time."""


class MedicalAssistant:
    def __init__(self, system):
        self.system = system
        self.retriever = Retriever()
        self.client = None
        self.status_text = "offline (no API key): rule-based guidance"
        self.conversations: dict[str, list] = {}
        self.lock = threading.Lock()
        self.calls = 0
        self.errors = 0
        if os.environ.get("HMS_DISABLE_LLM") != "1" and (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            try:
                import anthropic

                self._anthropic = anthropic
                self.client = anthropic.Anthropic(timeout=90.0, max_retries=2)
                self.status_text = f"online: {MODEL} (cloud model, demo stand-in for an onboard model)"
            except ImportError:
                self.status_text = "offline (anthropic package not installed): rule-based guidance"

    @property
    def online(self):
        # The cloud model stands in for an ONBOARD model, so a link blackout does not take it offline.
        return self.client is not None and os.environ.get("HMS_SIMULATE_AI_OFFLINE") != "1"

    # ---------------------------------------------------------------- tools (bound to one user)
    def _tools_for(self, user):
        S = self.system
        tools, impl = [], {}

        def add(name, desc, props, required, fn):
            tools.append({"name": name, "description": desc,
                          "input_schema": {"type": "object", "properties": props, "required": required,
                                           "additionalProperties": False}})
            impl[name] = fn

        if user.get("crew_id"):
            cid = user["crew_id"]

            def my_summary(_):
                v = S.member_view(user, cid)
                return {"crew_code": cid,
                        "overall": v["overall"], "duty": v["duty"], "restrictions": v["restrictions"],
                        "indicators": {k: {"value": i["display"], "unit": i["unit"], "status": i["status"], "source": i["source"]}
                                       for k, i in v["indicators"].items()},
                        "recommendations": [{"tier": r["tier"], "title": r["title"]} for r in v["recommendations"]],
                        "active_alerts": [{"severity": a["severity"], "title": a["title"], "root_cause": a.get("root_cause")}
                                          for a in v.get("alerts", [])]}
            add("get_my_health_summary", "Get the asking astronaut's own current indicators, status, restrictions, "
                "recommendations and active alerts.", {}, [], my_summary)

            def my_trend(inp):
                metric = inp["metric"]
                field = {"blood_pressure": "systolic", "blood_glucose": "glucose", "body_temp": "body_temp",
                         "sleep_hours": "sleep_hours", "mood": "mood"}[metric]
                t = S.member_view(user, cid)["trends"]
                pts = [{"date": time.strftime("%m-%d", time.localtime(ts)), "value": v}
                       for ts, v in zip(t["ts"], t.get(field, [])) if v is not None]
                return {"metric": metric, "last_14_days": pts}
            add("get_my_trend", "Get the asking astronaut's 14-day history for one check-in metric.",
                {"metric": {"type": "string", "enum": ["blood_pressure", "blood_glucose", "body_temp", "sleep_hours", "mood"]}},
                ["metric"], my_trend)

            def cmo_review(inp):
                if not inp.get("user_consented"):
                    return {"error": "Not sent: the user must agree first."}
                S.coordinator.raise_external(
                    f"checkin_{cid}_cmo_request", "warning", f"{cid} requested a Crew Medical Officer review",
                    "Requested by the crew member through the AI assistant", [cid], [inp["summary"][:300]],
                    ["CMO: contact the crew member and review their data"], "crew medical officer review", agent="assistant")
                return {"sent": True, "note": "The Crew Medical Officers can now see this request and the crew member's vitals."}
            add("request_cmo_review", "Ask the Crew Medical Officers to check on the asking astronaut. ONLY with explicit user consent.",
                {"summary": {"type": "string", "description": "One-sentence reason, no private details beyond what the user agreed to share"},
                 "user_consented": {"type": "boolean"}}, ["summary", "user_consented"], cmo_review)

        def cabin(_):
            f = S.frame_for(user) or {}
            alerts = [a for a in S.alerts_for(user) if a["state"] == "active" and a["key"].startswith(("co2", "depress", "pressure", "spe"))]
            return {"mission_environment": S.env["name"], "gravity": S.env["gravity"], "earth_link_delay": S.env["delay_label"],
                    "cabin": f.get("cabin"), "radiation": f.get("radiation"),
                    "cabin_alerts": [{"severity": a["severity"], "title": a["title"]} for a in alerts]}
        add("get_cabin_environment", "Get current cabin CO2, pressure, O2, temperature, radiation dose rate, "
            "mission environment and active habitat alerts.", {}, [], cabin)

        def guidance(inp):
            docs = self.retriever.search(inp["query"], k=3)
            return [{"id": d["id"], "title": d["title"], "source": d["source"], "text": d["text"]} for d in docs]
        add("search_health_guidance", "Search the AstroGuard knowledge base (summaries of NASA Human Research Program "
            "and NASA-STD-3001 health guidance). Returns passages with ids to cite.",
            {"query": {"type": "string"}}, ["query"], guidance)

        def measure(inp):
            g = INDICATORS[inp["indicator"]]
            return {k: g[k] for k in ("name", "unit", "how", "why", "normal", "actions")}
        add("get_measurement_guide", "How to measure an indicator in space, why it matters, normal range and what to do if abnormal.",
            {"indicator": {"type": "string", "enum": list(INDICATORS)}}, ["indicator"], measure)

        if user["roles"] != ["astronaut"]:
            def crewmate(inp):
                from .auth import CREW_IDS
                c = inp["crew_code"]
                if c not in CREW_IDS:
                    return {"error": "unknown crew code"}
                v = S.member_view(user, c)
                out = {"crew_code": c, "access_level": v["access"], "access_reason": v["access_reason"],
                       "overall": v["overall"], "duty": v["duty"], "restrictions": v["restrictions"],
                       "alerts": [{"severity": a["severity"], "title": a["title"]} for a in v.get("alerts", [])]}
                if "indicators" in v:
                    out["indicators"] = {k: {"value": i["display"], "unit": i["unit"], "status": i["status"]}
                                         for k, i in v["indicators"].items()}
                    out["trend_notes"] = [r["title"] for r in v.get("recommendations", []) if r["tier"] == "Improve"]
                    tr = v.get("trends", {})
                    summary = {}
                    for f in ("systolic", "glucose", "body_temp", "sleep_hours", "mood"):
                        vals = [x for x in tr.get(f, []) if x is not None]
                        if len(vals) >= 4:
                            h = len(vals) // 2
                            summary[f] = {"first_week_avg": round(sum(vals[:h]) / h, 1),
                                          "second_week_avg": round(sum(vals[h:]) / (len(vals) - h), 1), "latest": vals[-1]}
                    out["two_week_trends"] = summary
                else:
                    out["note"] = "Medical details are restricted for your role (need-to-know)"
                return out
            add("get_crewmate_status", "Get a crewmate's status, filtered by YOUR access level (commanders get "
                "operational status only; CMOs get vitals only on a health warning, sharing or emergency).",
                {"crew_code": {"type": "string", "enum": ["CDR", "PLT", "MS1", "MS2"]}}, ["crew_code"], crewmate)

        def spaceflight_ref(inp):
            from . import nasa_data
            s = nasa_data.summary(inp["analyte"])
            return s or {"error": "no reference data for that analyte"}
        add("get_spaceflight_reference", "Real astronaut blood-chemistry data from NASA's open Inspiration4 dataset "
            "(OSDR OSD-575): pre-flight, return-day and recovery values plus lab reference range. Cite it as [osdr-575-<analyte>].",
            {"analyte": {"type": "string", "enum": ["glucose", "calcium", "alk_phos", "potassium", "sodium", "creatinine", "bun", "albumin"]}},
            ["analyte"], spaceflight_ref)

        def suggest_emergency(inp):
            p = EMERGENCY_PROTOCOLS.get(inp["protocol"])
            return {"protocol": inp["protocol"], "title": p["title"], "first_steps": p["steps"][:3],
                    "ui": "A 'Start emergency' button is now shown to the user."} if p else {"error": "unknown protocol"}
        add("suggest_emergency_protocol", "Show the user a button to start an emergency protocol (they confirm).",
            {"protocol": {"type": "string", "enum": list(EMERGENCY_PROTOCOLS)}}, ["protocol"], suggest_emergency)
        return tools, impl

    # ---------------------------------------------------------------- chat
    def reset(self, user):
        with self.lock:
            self.conversations.pop(user["id"], None)

    def chat(self, user, text: str, context: dict | None = None) -> dict:
        text = text.strip()[:2000]
        red = next((proto for rx, proto in RED_FLAGS if rx.search(text)), None)
        selfharm = bool(SELF_HARM.search(text))
        result = {"red_flag": red, "self_harm": selfharm, "tools_used": [], "citations": [], "suggested_protocol": red}

        if not self.online:
            result.update(self._fallback(user, text))
            return result

        tools, impl = self._tools_for(user)
        with self.lock:
            convo = self.conversations.setdefault(user["id"], [])
            if sum(1 for m in convo if m["role"] == "user" and isinstance(m["content"], str)) >= MAX_TURNS:
                convo.clear()
            convo.append({"role": "user", "content": text})
            messages = list(convo)
        who = f"Signed-in user: crew code {user.get('crew_id') or user['id']}, roles {', '.join(user['roles'])}."
        ctx = context or {}
        screens = {"health": "My Health dashboard", "checkin": "daily check-in form", "body": "body map",
                   "routine": "mission routine", "crew": "crew board", "privacy": "privacy settings"}
        if ctx.get("view") in screens:
            who += f" They are currently looking at the {screens[ctx['view']]}"
            if ctx.get("view") == "body" and str(ctx.get("body_system", "")).isalpha():
                who += f" (selected body system: {ctx['body_system']})"
            who += "."
        try:
            response = None
            for _ in range(MAX_TOOL_ROUNDS):
                self.calls += 1
                response = self.client.beta.messages.create(
                    model=MODEL, max_tokens=4096, system=SYSTEM_PROMPT + "\n\n" + who,
                    output_config={"effort": "low"}, tools=tools, messages=messages,
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                )
                messages.append({"role": "assistant", "content": response.content})
                if response.stop_reason == "refusal":
                    break
                uses = [b for b in response.content if b.type == "tool_use"]
                if response.stop_reason != "tool_use" or not uses:
                    break
                results = []
                for b in uses:
                    try:
                        out = impl[b.name](b.input or {})
                        if b.name == "suggest_emergency_protocol" and isinstance(out, dict) and "title" in out:
                            result["suggested_protocol"] = out["protocol"]
                        if b.name == "search_health_guidance":
                            result["citations"] += [{"id": d["id"], "title": d["title"], "source": d["source"]} for d in out]
                        content, is_err = json.dumps(out, default=str), False
                    except Exception as e:  # noqa: BLE001 - report tool failure to the model
                        content, is_err = f"Error: {e}", True
                    result["tools_used"].append(b.name)
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": content, "is_error": is_err})
                messages.append({"role": "user", "content": results})
            if response is None or response.stop_reason == "refusal":
                reply = "I can't help with that request. Please contact your Crew Medical Officer or flight surgeon."
            else:
                reply = "".join(b.text for b in response.content if b.type == "text").strip() or "(no answer)"
            with self.lock:
                self.conversations[user["id"]] = messages
            result.update({"reply": reply, "mode": "ai", "model": getattr(response, "model", MODEL)})
        except Exception as e:  # noqa: BLE001 - any API failure falls back to rule-based guidance
            self.errors += 1
            with self.lock:
                self.conversations.pop(user["id"], None)
            self.system.store.log("warn", "assistant", f"AI unavailable, using rule-based fallback: {type(e).__name__}")
            result.update(self._fallback(user, text, error=type(e).__name__))
        return result

    # ------------------------------------------------------------ rule-based assistant (no AI available)
    INDICATOR_WORDS = [
        (r"blood pressure|\bbp\b|systolic|diastolic", "blood_pressure"), (r"sugar|glucose", "blood_glucose"),
        (r"temperature|fever|\btemp\b", "body_temp"), (r"sleep|insomnia", "sleep_hours"),
        (r"heart|pulse|\bhr\b", "heart_rate"), (r"oxygen|spo2|saturation", "spo2"), (r"mood|sad|down|lonely|stress", "mood"),
        (r"exercise|workout|bone|muscle", "exercise_min"),
    ]
    CREW_WORDS = {"CDR": r"\bcdr\b|commander|ana\b", "PLT": r"\bplt\b|pilot|kenji", "MS1": r"\bms1\b|leila", "MS2": r"\bms2\b|tom\b"}
    STATUS_WORD = {"ok": "normal", "warn": "needs watching", "crit": "out of range", "none": "no data"}

    def _fallback(self, user, text, error=None):
        """Intent-based answers from the user's real data (same permission-bound tools as the AI)."""
        t = text.lower()
        tools, impl = self._tools_for(user)
        used, cites, out = [], [], []

        def call(name, inp=None):
            used.append(name)
            return impl[name](inp or {})

        def kb(query, n=1):
            docs = call("search_health_guidance", {"query": query})[:n]
            for d in docs:
                cites.append({"id": d["id"], "title": d["title"], "source": d["source"]})
            return docs

        def first_sentences(d, n=1, cap=150):
            s = '. '.join(d['text'].split('. ')[:n]).rstrip('.')
            if len(s) > cap:
                s = s[:cap].rsplit(' ', 1)[0].rstrip(',;:') + '…'
            return f"{s}{'' if s.endswith('…') else '.'} [{d['id']}]"

        ind = next((k for rx, k in self.INDICATOR_WORDS if re.search(rx, t)), None)
        crew = [c for c, rx in self.CREW_WORDS.items() if re.search(rx, t) and c != user.get("crew_id")]
        has_crew_tool = "get_crewmate_status" in impl
        mine = "get_my_health_summary" in impl
        red = next((proto for rx, proto in RED_FLAGS if rx.search(text)), None)

        if red:
            p = EMERGENCY_PROTOCOLS[red]
            out.append(f"⚠ **Possible emergency: start EMERGENCY mode now ({p['title']}).**")
            out += [f"{i}. {s}" for i, s in enumerate(p["steps"][:3], 1)]
            out.append("The flight surgeon gets an automatic situation report.")
        elif crew and not has_crew_tool:
            out.append(f"🔒 I can't share {', '.join(crew)}'s health data: it stays between them and the flight surgeon.")
            out.append("Worried about a crewmate? Tell the Crew Medical Officer, or press ⚠ EMERGENCY if urgent.")
        elif re.search(r"how (do|to|should) i (measure|take|check|use)|how to measure|measur", t) and ind:
            g = call("get_measurement_guide", {"indicator": ind})
            out.append(f"**How to measure {g['name'].lower()} in space:**")
            out += [f"{i}. {s}" for i, s in enumerate(g["how"], 1)]
            out.append(f"**Normal:** {g['normal']}.")
        elif re.search(r"cabin|air|co2|carbon|radiation|habitat|pressure (in|of) the|leak", t) and ind != "blood_pressure":
            c = call("get_cabin_environment")
            cab, rad = c.get("cabin") or {}, c.get("radiation") or {}
            if not cab:
                return {"reply": "📡 No data from the spacecraft yet. Try again in a few seconds.",
                        "mode": "rule-based", "tools_used": used, "citations": []}
            out.append(f"**Cabin now:** CO₂ {cab.get('co2_mmHg', '?')} mmHg · pressure {cab.get('pressure_kPa', '?')} kPa · "
                       f"O₂ {cab.get('o2_pct', '?')}% · radiation {round(rad.get('dose_rate_uSv_h', 0))} µSv/h.")
            if c["cabin_alerts"]:
                out.append("⚠ " + "; ".join(a["title"] for a in c["cabin_alerts"]) + ".")
            else:
                ok = (cab.get("co2_mmHg", 0) <= 4 and cab.get("pressure_kPa", 101) >= 97)
                out.append("✅ All within limits." if ok else "⚠ Some readings are high: check the Habitat panel.")
        elif crew and has_crew_tool:
            for c in crew[:2]:
                v = call("get_crewmate_status", {"crew_code": c})
                line = f"**{c}:** {v['duty']} ({self.STATUS_WORD.get(v['overall'], v['overall'])})"
                if "indicators" in v:
                    flagged = [f"{k.replace('_', ' ')} {i['value']} {i['unit']}" for k, i in v["indicators"].items()
                               if i["status"] in ("warn", "crit") and k != "exercise_min"]
                    line += ". " + ("Flagged: " + ", ".join(flagged) if flagged else "All normal")
                    out.append(line + ".")
                    if re.search(r"summar|trend|week|history|doing", t) and v.get("two_week_trends"):
                        names = {"systolic": "BP", "glucose": "Sugar", "body_temp": "Temp", "sleep_hours": "Sleep", "mood": "Mood"}
                        out.append(" · ".join(f"{names[f]} {s['first_week_avg']}→{s['second_week_avg']}" for f, s in v["two_week_trends"].items()))
                else:
                    out.append(line + ". 🔒 Medical details restricted for your role.")
        elif has_crew_tool and re.search(r"who needs|attention first|which crew|everyone|whole crew|all crew|fit for", t):
            rank = {"crit": 0, "warn": 1, "ok": 2}
            rows = sorted((call("get_crewmate_status", {"crew_code": c}) for c in ("CDR", "PLT", "MS1", "MS2")),
                          key=lambda v: rank.get(v["overall"], 3))
            out.append("**Most urgent first:**")
            for v in rows:
                why = ""
                if "indicators" in v:
                    flagged = [f"{k.replace('_', ' ')} {i['value']} {i['unit']}" for k, i in v["indicators"].items()
                               if i["status"] in ("warn", "crit") and k != "exercise_min"]
                    why = (": " + ", ".join(flagged)) if flagged else ""
                out.append(f"- **{v['crew_code']}** {v['duty']}{why}")
            if any("indicators" not in v for v in rows):
                out.append("🔒 Medical reasons are visible to the flight surgeon only.")
        elif mine and re.search(r"trend|going up|going down|rising|increas|decreas|worse|why is my|last (week|two weeks)|history", t):
            metric = ind if ind in ("blood_pressure", "blood_glucose", "body_temp", "sleep_hours", "mood") else "blood_pressure"
            tr = call("get_my_trend", {"metric": metric})["last_14_days"]
            vals = [p["value"] for p in tr]
            if len(vals) >= 4:
                a, b = sum(vals[:len(vals) // 2]) / (len(vals) // 2), sum(vals[len(vals) // 2:]) / (len(vals) - len(vals) // 2)
                word = "rising" if b > a * 1.02 else "falling" if b < a * 0.98 else "steady"
                out.append(f"**Your {metric.replace('_', ' ')} is {word}:** {a:.0f} → {b:.0f} over 14 days (last {vals[-1]:g}).")
            s = call("get_my_health_summary")
            recs = [r for r in s["recommendations"] if metric.split("_")[-1] in r["title"].lower()]
            if recs:
                out.append(f"{recs[0]['title']} ({recs[0]['tier']}).")
            d = kb(f"{metric.replace('_', ' ')} spaceflight")
            if d:
                out.append(first_sentences(d[0], 1, 110))
            out.append("Tip: measure at the same time each morning (Self-care).")
        elif mine and (ind or re.search(r"headache|tired|fatigue|dizzy|nause|sick|unwell|feel|pain|ache|how am i|my health|status|ok\?", t)):
            s = call("get_my_health_summary")
            flagged = {k: i for k, i in s["indicators"].items() if i["status"] in ("warn", "crit") and k != "exercise_min"}
            if ind and ind in s["indicators"]:
                i = s["indicators"][ind]
                out.append(f"**Your {ind.replace('_', ' ')}: {i['value']} {i['unit']}** ({self.STATUS_WORD.get(i['status'])}).")
                if ind == "blood_glucose":
                    from . import nasa_data
                    try:
                        ref = nasa_data.summary("glucose")
                        pre = ref["phases"]["pre_flight"]
                        used.append("get_spaceflight_reference")
                        cites.append({"id": "osdr-575-glucose", "title": "Real flight data: blood sugar (Inspiration4)", "source": nasa_data.DATASET_TITLE})
                        out.append(f"🛰 Inspiration4 crew before launch: {pre['min']:g}–{pre['max']:g} mg/dL (NASA OSDR). [osdr-575-glucose]")
                    except (TypeError, ValueError, KeyError):
                        pass
            if re.search(r"headache|tired|fatigue|dizzy|nause", t):
                c = call("get_cabin_environment")
                co2 = (c.get("cabin") or {}).get("co2_mmHg")
                sleep = s["indicators"].get("sleep_hours", {}).get("value")
                causes = []
                if co2 and co2 > 3.5:
                    causes.append(f"cabin CO₂ is high ({co2} mmHg)")
                if sleep and float(sleep) < 6.5:
                    causes.append(f"your sleep was short ({sleep} h)")
                out.append("**Likely:** " + ("; ".join(causes) if causes else f"cabin CO₂ ({co2} mmHg) and sleep ({sleep} h) look fine") + ".")
                out.append("**Next:** hydrate and rest 20 min (Self-care). If it persists, tell the Crew Medical Officer.")
            elif not ind:
                out.append(f"**Overall:** {s['duty']}." + (" Flagged: " + ", ".join(f"{k.replace('_', ' ')} {i['value']} {i['unit']}" for k, i in flagged.items()) + "." if flagged else " Nothing out of range."))
        else:
            d = kb(text, n=1)
            if d:
                out.append(first_sentences(d[0], 1, 140))
            out.append("Tap any tile on My Health for measuring and what-to-do guidance.")

        why = f" ({error})" if error else ""
        uniq = list({c["id"]: c for c in cites}.values())
        return {"reply": "\n".join(out), "mode": "rule-based", "tools_used": used, "citations": uniq}

    # ---------------------------------------------------------------- ground briefing (SBAR)
    def briefing(self, patient_view: dict, protocol: str, declared_by: str, env: dict) -> tuple[str, str]:
        """Returns (text, author). Template if the model is unavailable."""
        ind = patient_view.get("indicators", {})
        vit = "; ".join(f"{i['name']} {i['display']} {i['unit']} ({i['status']})" for i in ind.values()
                        if i.get("display") is not None and i["key"] != "mood")
        alerts = "; ".join(a["title"] for a in patient_view.get("alerts", []))
        p = EMERGENCY_PROTOCOLS[protocol]
        facts = (f"Patient {patient_view['crew_id']}. Protocol: {p['title']}, declared by {declared_by} at "
                 f"{time.strftime('%H:%M:%S')}. Mission: {env['name']}, Earth link {env['delay_label']}. "
                 f"Vitals: {vit or 'n/a'}. Active alerts: {alerts or 'none'}. Recent trends: "
                 f"{'; '.join(r['title'] for r in patient_view.get('recommendations', []) if r['tier'] == 'Improve') or 'none'}.")
        template = (f"S: {p['title']} declared for {patient_view['crew_id']} by {declared_by}.\n"
                    f"B: {env['name']}; Earth link {env['delay_label']}.\n"
                    f"A: {vit or 'vitals unavailable'}. Alerts: {alerts or 'none'}.\n"
                    f"R: Crew following onboard protocol. Flight surgeon review of vitals and protocol requested.")
        if not self.online:
            return template, "template (AI unavailable)"
        try:
            self.calls += 1
            r = self.client.beta.messages.create(
                model=MODEL, max_tokens=2048, output_config={"effort": "low"},
                system=("You write SBAR situation reports for a NASA flight surgeon on Earth during a spaceflight medical "
                        "emergency. The message will arrive after a long light-time delay, so it must be complete and "
                        "self-contained. Use exactly four labelled lines: S (situation), B (background), A (assessment of the "
                        "data, no definitive diagnosis), R (what the crew is doing and the specific decisions needed from the "
                        "surgeon). Max 110 words. Use only the facts given; do not invent values."),
                messages=[{"role": "user", "content": facts}],
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            )
            if r.stop_reason == "refusal":
                return template, "template"
            text = "".join(b.text for b in r.content if b.type == "text").strip()
            return (text or template), (f"AI ({r.model})" if text else "template")
        except Exception as e:  # noqa: BLE001
            self.errors += 1
            self.system.store.log("warn", "assistant", f"Briefing AI unavailable: {type(e).__name__}")
            return template, "template (AI unavailable)"
