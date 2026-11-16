# SI disclosure: developed with assistance from Claude Code (Anthropic SI). See SI_DISCLOSURE.md.
"""Real spaceflight reference data from NASA's Open Science Data Repository (OSDR).

Dataset: OSD-575, Inspiration4 (SpaceX, 2021, 3-day orbital mission, 4 civilian crew)
         Comprehensive Metabolic Panel (CMP), file LSDS-8_Comprehensive_Metabolic_Panel_CMP.upload_SUBMITTED.csv
Source:  https://osdr.nasa.gov/bio/repo/data/studies/OSD-575  (open access; crew consented to data sharing)
Subjects are anonymised (C001-C004). Timepoints: L-92, L-44, L-3 (days before launch),
R+1, R+45, R+82, R+194 (days after return).

How AstroGuard uses it:
  * shows a REAL crew reference next to an astronaut's own value (blood sugar, calcium, electrolytes, kidney markers)
  * adds data-derived passages to the knowledge base, so the AI and alert explanations can cite real flight data
Limits: n = 4, a short mission, and blood drawn on Earth before and after flight. Reference only, not clinical norms.
"""
from __future__ import annotations

import csv
import statistics
from pathlib import Path

DATASET_ID = "OSD-575"
DATASET_URL = "https://osdr.nasa.gov/bio/repo/data/studies/OSD-575"
DATASET_TITLE = "NASA OSDR OSD-575: Inspiration4 crew, comprehensive metabolic panel"
CSV_PATH = Path(__file__).resolve().parents[2] / "datasets" / "osdr" / "LSDS-8_Comprehensive_Metabolic_Panel_CMP.upload_SUBMITTED.csv"

PHASES = {"pre_flight": ("L-92", "L-44", "L-3"), "return_day": ("R+1",), "recovery": ("R+45", "R+82", "R+194")}
TIMEPOINT_ORDER = ["L-92", "L-44", "L-3", "R+1", "R+45", "R+82", "R+194"]

# AstroGuard concept -> (analyte in the file, display name, related body system)
ANALYTES = {
    "glucose": ("GLUCOSE", "Blood sugar (glucose)", "metabolic"),
    "calcium": ("CALCIUM", "Calcium", "bones"),
    "alk_phos": ("ALKALINE PHOSPHATASE", "Alkaline phosphatase (bone/liver enzyme)", "bones"),
    "potassium": ("POTASSIUM", "Potassium", "heart"),
    "sodium": ("SODIUM", "Sodium", "heart"),
    "creatinine": ("CREATININE", "Creatinine (kidney)", "metabolic"),
    "bun": ("UREA NITROGEN (BUN)", "Urea nitrogen (kidney/hydration)", "metabolic"),
    "albumin": ("ALBUMIN", "Albumin (protein/nutrition)", "metabolic"),
}
INDICATOR_TO_ANALYTE = {"blood_glucose": "glucose"}


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _load():
    if not CSV_PATH.exists():
        return {}
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8-sig")))
    out = {}
    for key, (analyte, label, system) in ANALYTES.items():
        rs = [r for r in rows if r["ANALYTE"] == analyte and _num(r["VALUE"]) is not None]
        if not rs:
            continue
        by_tp = {}
        for r in rs:
            by_tp.setdefault(r["timepoint"], []).append(_num(r["VALUE"]))
        phases = {}
        for ph, tps in PHASES.items():
            vals = [v for tp in tps for v in by_tp.get(tp, [])]
            if vals:
                phases[ph] = {"mean": round(statistics.mean(vals), 2), "min": min(vals), "max": max(vals), "n": len(vals)}
        lo, hi = _num(rs[0]["RANGE_MIN"]), _num(rs[0]["RANGE_MAX"])
        out[key] = {
            "analyte": analyte, "label": label, "system": system, "unit": rs[0]["UNITS"],
            "lab_range": [lo, hi], "phases": phases,
            "timeline": [{"timepoint": tp, "mean": round(statistics.mean(by_tp[tp]), 2), "n": len(by_tp[tp])}
                         for tp in TIMEPOINT_ORDER if tp in by_tp],
            "subjects": len({r["SUBJECT_ID"] for r in rs}),
        }
    return out


REFERENCE = _load()


def summary(key: str) -> dict | None:
    r = REFERENCE.get(key)
    return dict(r, dataset=DATASET_TITLE, dataset_id=DATASET_ID, url=DATASET_URL) if r else None


def compare(key: str, value: float | None) -> str | None:
    """One plain sentence placing an astronaut's value next to the real Inspiration4 crew data."""
    r = REFERENCE.get(key)
    if not r or value is None or "pre_flight" not in r["phases"]:
        return None
    pre, ret = r["phases"]["pre_flight"], r["phases"].get("return_day")
    s = (f"Real crew reference (NASA OSDR {DATASET_ID}, Inspiration4, n={r['subjects']}): pre-flight {r['label'].split(' (')[0].lower()} "
         f"ranged {pre['min']:g}-{pre['max']:g} {r['unit']} (mean {pre['mean']:g})")
    if ret:
        s += f"; on return day, {ret['min']:g}-{ret['max']:g} (mean {ret['mean']:g})"
    lo, hi = r["lab_range"]
    if lo is not None and hi is not None:
        s += f". Lab reference range {lo:g}-{hi:g}. Your value: {value:g}"
        s += " (within the crew's pre-flight range)." if pre["min"] <= value <= pre["max"] else " (outside the crew's pre-flight range)."
    return s


def kb_passages() -> list[dict]:
    """Knowledge-base passages derived from the real data, so the AI and explanations can cite it."""
    out = []
    for key, r in REFERENCE.items():
        ph = r["phases"]
        if "pre_flight" not in ph:
            continue
        parts = [f"In NASA's open Inspiration4 dataset ({DATASET_ID}), {r['label'].lower()} for the {r['subjects']} crew members "
                 f"averaged {ph['pre_flight']['mean']:g} {r['unit']} before launch"]
        if "return_day" in ph:
            parts.append(f"{ph['return_day']['mean']:g} {r['unit']} the day after return")
        if "recovery" in ph:
            parts.append(f"{ph['recovery']['mean']:g} {r['unit']} during recovery (45-194 days)")
        lo, hi = r["lab_range"]
        text = ", ".join(parts) + f". The laboratory reference range was {lo:g}-{hi:g} {r['unit']}. " if lo is not None and hi is not None else ", ".join(parts) + ". "
        text += ("Values from four people on a three-day mission are a reference point, not a norm: they show how a real crew's "
                 "blood chemistry looked around spaceflight and why tracking each astronaut against their own pre-flight baseline matters.")
        out.append({"id": f"osdr-575-{key}", "title": f"Real flight data: {r['label']} (Inspiration4)",
                    "source": f"{DATASET_TITLE} ({DATASET_URL})", "text": text})
    return out
