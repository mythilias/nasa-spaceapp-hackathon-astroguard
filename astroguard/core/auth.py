# SI disclosure: developed with assistance from Claude Code (Anthropic SI). See SI_DISCLOSURE.md.
"""Demo authentication + role-based, need-to-know access control.

Access codes are for the DEMO only. A real system would use multi-factor authentication,
hardware tokens, encryption at rest/in transit and agency security standards.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

SECRET = os.environ.get("HMS_SECRET", secrets.token_hex(16)).encode()
SESSION_TTL = 12 * 3600

# Fictional crew. Any resemblance to real astronauts is unintended.
USERS = {
    "4821": {"id": "CDR", "name": "Ana Ribeiro", "title": "Commander", "crew_id": "CDR", "roles": ["astronaut", "commander"]},
    "7316": {"id": "PLT", "name": "Kenji Watanabe", "title": "Pilot", "crew_id": "PLT", "roles": ["astronaut"]},
    "2094": {"id": "MS1", "name": "Leila Haddad", "title": "Mission Specialist · Crew Medical Officer", "crew_id": "MS1", "roles": ["astronaut", "cmo"]},
    # NASA requires at least two crew trained as Crew Medical Officers per vehicle (NASA-STD-3001 / HIDH 5.0 Training)
    "5583": {"id": "MS2", "name": "Tom Becker", "title": "Mission Specialist · Backup CMO", "crew_id": "MS2", "roles": ["astronaut", "cmo"]},
    "9001": {"id": "SURG", "name": "Dr. Priya Nair", "title": "Flight Surgeon (ground)", "crew_id": None, "roles": ["flight_surgeon"]},
    "3000": {"id": "MCC", "name": "Flight Director", "title": "Mission Control (ground)", "crew_id": None, "roles": ["mission_control"]},
}
BY_ID = {u["id"]: u for u in USERS.values()}
CREW_IDS = [u["crew_id"] for u in USERS.values() if u["crew_id"]]
GROUND_ROLES = {"flight_surgeon", "mission_control"}


def login(code: str) -> tuple[str, dict] | None:
    user = USERS.get((code or "").strip())
    if not user:
        return None
    exp = int(time.time()) + SESSION_TTL
    payload = f"{user['id']}.{exp}"
    sig = hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{payload}.{sig}", user


def verify(token: str | None) -> dict | None:
    try:
        uid, exp, sig = (token or "").split(".")
        good = hmac.new(SECRET, f"{uid}.{exp}".encode(), hashlib.sha256).hexdigest()[:32]
        if hmac.compare_digest(sig, good) and int(exp) > time.time():
            return BY_ID.get(uid)
    except ValueError:
        pass
    return None


def is_ground(user) -> bool:
    return bool(GROUND_ROLES & set(user["roles"]))


def access_level(viewer: dict, subject: str, emergency_patients: set[str],
                 subject_needs_attention: bool = False, shared_with_cmo: bool = False) -> tuple[str, str]:
    """Returns (level, reason). Levels: full > medical (vitals; mood only if shared) > status.

    Based on NASA practice: medical information is private between the astronaut and the flight
    surgeon (private medical conferences; Privacy Act of 1974). Others get the minimum necessary:
      - Flight surgeon: full (the crew's physician).
      - Medical emergency: anyone on the crew gets vitals (not mood) to treat the patient.
      - Crew Medical Officer: vitals only when the crewmate has a health warning or has chosen to share.
      - Commander / Mission Control: operational status (fit-for-duty, task restrictions). This rule is
        our design assumption; we found no public NASA document specifying it.
    """
    if viewer.get("crew_id") == subject:
        return "full", "own data"
    if "flight_surgeon" in viewer["roles"]:
        return "full", "flight surgeon"
    if subject in emergency_patients:
        return "medical", "medical emergency"
    if "cmo" in viewer["roles"]:
        if subject_needs_attention:
            return "medical", "crew medical officer: health warning"
        if shared_with_cmo:
            return "medical", "crew medical officer: shared by crew member"
    return "status", "need-to-know (operational status only)"
