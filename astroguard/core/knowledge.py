# SI disclosure: developed with assistance from Claude Code (Anthropic SI). See SI_DISCLOSURE.md.
"""Knowledge base + BM25 retriever (pure Python, no dependencies).

The passages are short paraphrased summaries of themes in NASA human-spaceflight health
guidance: NASA-STD-3001 (Space Flight Human-System Standard) and the NASA Human Research
Program (HRP) risk evidence. They are written for this demo. Numeric thresholds marked
"demo threshold" are chosen for the simulation and are NOT authoritative. Check every
value against the primary sources listed in `source` before any real use.
"""
from __future__ import annotations

import math
import re
from collections import Counter

KB: list[dict] = [
    {
        "id": "env-co2-1",
        "title": "Cabin carbon dioxide exposure",
        "source": "NASA-STD-3001 Vol. 2 (atmosphere: CO2); HRP evidence on CO2 exposure",
        "text": "Carbon dioxide builds up in closed spacecraft cabins and is removed by scrubbers such as the "
                "ISS Carbon Dioxide Removal Assembly. Spacecraft CO2 levels are routinely far higher than on Earth. "
                "Crew have reported headache, lethargy, irritability and reduced concentration at elevated partial "
                "pressures. Microgravity reduces air convection, so local CO2 pockets can form near a sleeping or "
                "working crew member. NASA has progressively tightened its CO2 limits, and ISS operations aim to keep "
                "average ppCO2 low, around a few mmHg.",
    },
    {
        "id": "env-co2-2",
        "title": "Physiological response to elevated CO2",
        "source": "General respiratory physiology; NASA-STD-3001 Vol. 2",
        "text": "Elevated inspired CO2 raises respiration rate and minute ventilation, and can increase heart rate "
                "and blood pressure. When several crew members show rising respiration and heart rate at the same "
                "time, that points to a shared environmental cause such as CO2 buildup rather than an individual "
                "medical problem. Response: verify scrubber operation, increase ventilation and air flow, check "
                "portable CO2 monitors, and move crew to a well-ventilated module if needed. Demo threshold: warn "
                "at 4 mmHg, critical at 6 mmHg.",
    },
    {
        "id": "env-pressure-1",
        "title": "Cabin pressure loss and hypoxia",
        "source": "NASA-STD-3001 Vol. 2 (atmosphere: total pressure and ppO2)",
        "text": "A fall in cabin total pressure lowers the partial pressure of oxygen, which can cause hypoxia and "
                "falling oxygen saturation in every crew member at once. Hypoxia impairs judgement and can come on "
                "without obvious symptoms. A cabin-wide pressure drop together with crew-wide desaturation calls "
                "for emergency leak procedures: locate and isolate the leak, prepare oxygen masks, and be ready to "
                "shelter in or evacuate to the crew vehicle. Demo threshold: warn below 97 kPa, critical below "
                "90 kPa.",
    },
    {
        "id": "med-spo2-1",
        "title": "Oxygen saturation monitoring",
        "source": "General clinical guidance; NASA-STD-3001 Vol. 1 (crew health)",
        "text": "Peripheral oxygen saturation (SpO2) in healthy adults is normally about 95-100 percent. Readings "
                "below about 90 percent indicate significant hypoxemia. An individual desaturation while cabin "
                "atmosphere is normal points to a personal cause: sensor placement, respiratory illness, or a "
                "cardiopulmonary event. Response: re-seat the sensor, assess symptoms, give supplemental oxygen, "
                "and consult the flight surgeon. Demo threshold: warn below 94 percent, critical below 90 percent.",
    },
    {
        "id": "med-cardio-1",
        "title": "Cardiovascular adaptation and arrhythmia risk",
        "source": "NASA HRP Risk of Cardiovascular Adaptations Contributing to Adverse Mission Performance and Health Outcomes",
        "text": "Microgravity shifts body fluid toward the head, reduces plasma volume and changes heart structure "
                "and function over time. Heart rhythm disturbances have been seen in some astronauts. A sustained "
                "high or highly irregular heart rate at rest is a medical concern. It calls for an ECG check, rest, "
                "hydration review and a private medical conference with the flight surgeon. Demo threshold: warn "
                "above 110 bpm or irregularity above 15 bpm, critical above 140 bpm.",
    },
    {
        "id": "med-cardio-2",
        "title": "Orthostatic intolerance and blood pressure",
        "source": "NASA HRP cardiovascular evidence",
        "text": "After adapting to microgravity, astronauts can have orthostatic intolerance, meaning dizziness or "
                "fainting when gravity loads return during landing or on planetary surfaces. Monitoring blood "
                "pressure and heart rate trends in flight supports countermeasures such as fluid loading, "
                "compression garments and exercise.",
    },
    {
        "id": "beh-sleep-1",
        "title": "Sleep loss and circadian desynchronization",
        "source": "NASA HRP Risk of Performance Decrements and Adverse Health Outcomes from Sleep Loss, Circadian Desynchronization and Work Overload",
        "text": "Astronauts often sleep less in flight than on Earth, frequently around six hours a night, because of "
                "noise, light, workload, shifted schedules and lack of a normal day-night cycle. Sleep loss "
                "degrades attention, reaction time and decision making, and raises error risk during critical "
                "tasks such as spacewalks, docking and robotic operations. Countermeasures include protected "
                "sleep periods, lighting tuned to the circadian cycle, workload rescheduling and, if needed, sleep "
                "medication. Demo threshold: warn below 6 hours, critical below 5 hours.",
    },
    {
        "id": "beh-hrv-1",
        "title": "Heart rate variability as a stress and fatigue marker",
        "source": "Physiology literature; HRP behavioral health evidence",
        "text": "Low heart rate variability (HRV) is linked to physiological stress, fatigue and poor recovery. A "
                "sustained HRV fall alongside short sleep strengthens the case for fatigue-related performance "
                "risk. Fatigue together with environmental stressors such as elevated CO2 can compound cognitive "
                "impairment.",
    },
    {
        "id": "rad-1",
        "title": "Space radiation exposure and career limits",
        "source": "NASA-STD-3001 Vol. 1 (radiation); NASA HRP Risk of Radiation Carcinogenesis",
        "text": "Outside Earth's protective atmosphere, crew are exposed to galactic cosmic rays and occasional solar "
                "particle events (SPEs). NASA manages exposure with dosimetry, operational limits and an effective "
                "dose career limit; NASA's updated standard sets a career limit of 600 mSv. Mission dose should be "
                "tracked continuously against the crew member's remaining budget.",
    },
    {
        "id": "rad-spe-1",
        "title": "Solar particle event response",
        "source": "NASA space radiation operations; NASA-STD-3001 Vol. 1",
        "text": "A solar particle event can raise dose rates by orders of magnitude within hours, which risks acute "
                "effects and large additions to career dose. Response: on space weather alerts or a sharp rise in "
                "onboard dose rate, crew move to the most shielded area (a storm shelter or a module lined with "
                "water and stores), postpone spacewalks, and stay there until dose rates return to normal. Demo "
                "threshold: warn at 3x baseline dose rate, critical at 20x.",
    },
    {
        "id": "ops-1",
        "title": "Distinguishing environmental from individual causes",
        "source": "Operational practice; NASA-STD-3001 Vol. 2 (environmental monitoring)",
        "text": "Correlating crew physiology with cabin environment is key to root-cause analysis. If abnormal "
                "readings appear in several crew at once and line up with an environmental change, the "
                "environment is the likely cause and fixing it protects the whole crew. If only one crew member is "
                "affected while the environment is normal, treat it as an individual medical event. Sensor faults "
                "should be ruled out by cross-checking redundant sensors.",
    },
    {
        "id": "ops-autonomy-1",
        "title": "Crew medical autonomy on deep space missions",
        "source": "NASA HRP Risk of Adverse Outcomes Due to Inflight Medical Conditions; Exploration Medical Capability",
        "text": "On missions beyond low Earth orbit, communication delays and the lack of quick return mean crews "
                "must detect and manage medical issues more autonomously. Onboard decision support that fuses "
                "biomedical and environmental data, explains its reasoning and recommends actions helps the crew "
                "act without real-time ground support.",
    },
    {
        "id": "hrp-hazards",
        "title": "The five hazards of human spaceflight",
        "source": "NASA Human Research Program: Five Hazards of Human Spaceflight",
        "text": "NASA's Human Research Program groups spaceflight risks into five hazards: space radiation, "
                "isolation and confinement, distance from Earth, gravity fields, and hostile closed environments. "
                "These hazards contribute to immune changes, bone loss, cardiovascular changes, inadequate "
                "nutrition and behavioral health conditions. Monitoring indicators tied to each hazard lets "
                "astronauts spot changes early.",
    },
    {
        "id": "met-glucose-1",
        "title": "Blood sugar and metabolism in spaceflight",
        "source": "NASA HRP nutrition and metabolism evidence; general clinical guidance",
        "text": "Studies suggest spaceflight and physical inactivity can reduce insulin sensitivity, and long "
                "missions depend on a limited food system. Low blood sugar causes shakiness, confusion and poor "
                "performance; it is treated with about 15 g of fast carbohydrate and a re-check after 15 minutes. "
                "Persistently high readings should be reviewed by the flight surgeon. Demo threshold: warn "
                "outside 70-180 mg/dL, critical below 60 or above 250 mg/dL.",
    },
    {
        "id": "imm-temp-1",
        "title": "Immune changes, fever and body temperature",
        "source": "NASA HRP Risk of Adverse Health Event Due to Altered Immune Response",
        "text": "Spaceflight alters immune function, and latent viruses such as herpesviruses can reactivate during "
                "missions. A fever may be an early sign of infection in a closed habitat where illness can spread. "
                "Research has also found that core body temperature can run higher on long-duration missions. "
                "Response to fever: rest, fluids, symptom log, limit contact, and consult the flight surgeon about "
                "onboard medication. Demo threshold: warn above 37.5 °C, critical above 38.5 °C.",
    },
    {
        "id": "beh-mood-1",
        "title": "Isolation, confinement and behavioral health",
        "source": "NASA HRP Risk of Adverse Cognitive or Behavioral Conditions and Psychiatric Disorders",
        "text": "Long periods of isolation, confinement, monotony and distance from family raise the risk of low mood, "
                "stress and team conflict. Regular self-rating of mood helps catch problems early. Support includes "
                "private psychological conferences, family contact, meaningful work and crew social time. Behavioral "
                "health data is sensitive and should stay private unless the astronaut chooses to share it.",
    },
    {
        "id": "bone-1",
        "title": "Bone and muscle loss",
        "source": "NASA HRP Risk of Bone Fracture due to Spaceflight-induced Changes to Bone",
        "text": "Without gravity loading, astronauts lose bone mineral density, especially in the hips and spine, and "
                "muscle strength declines. Daily exercise on resistance devices, treadmill and cycle (about two hours "
                "per day on the ISS) is the main countermeasure, along with adequate nutrition and vitamin D.",
    },
    {
        "id": "eye-sans-1",
        "title": "Spaceflight Associated Neuro-ocular Syndrome (SANS)",
        "source": "NASA HRP Risk of Spaceflight Associated Neuro-ocular Syndrome",
        "text": "Many long-duration astronauts develop changes such as optic disc swelling and shifts in vision, linked "
                "to the headward fluid shift. Regular vision checks (for example an Amsler grid) and onboard eye "
                "imaging help detect changes.",
    },
    {
        "id": "emerg-cardiac-1",
        "title": "Cardiac emergency and CPR in microgravity",
        "source": "Spaceflight medicine literature; onboard medical checklists (generalized)",
        "text": "Treating a collapsed crew member in microgravity is hard because rescuers and patients float. Crews "
                "train to restrain the patient on a rigid surface and brace themselves to give effective chest "
                "compressions; researchers have studied several microgravity CPR methods. A defibrillator and "
                "cardiac medications are in the onboard medical kit. With communication delays to Mars, the crew "
                "must begin treatment before the flight surgeon can respond.",
    },
    {
        "id": "data-osdr-1",
        "title": "NASA Open Science Data Repository",
        "source": "NASA Open Science Data Repository (OSDR), osdr.nasa.gov",
        "text": "NASA's Open Science Data Repository collects spaceflight biology and health datasets from missions "
                "and ground studies. It can inform which indicators change in spaceflight, help set realistic ranges, "
                "and test monitoring approaches before they fly.",
    },
]

# Passages computed from REAL NASA flight data (OSDR OSD-575, Inspiration4 blood chemistry)
try:
    from .nasa_data import kb_passages as _osdr_passages
    KB.extend(_osdr_passages())
except Exception:  # noqa: BLE001 - the app still works without the dataset file
    pass

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = set("a an and are as at be by can for from has have in is it its of on or such that the this to with".split())


def _tok(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


class Retriever:
    """Okapi BM25 over title + text."""

    def __init__(self, docs: list[dict] = KB, k1: float = 1.4, b: float = 0.75):
        self.docs = docs
        self.k1, self.b = k1, b
        self.tf = [Counter(_tok(d["title"] + " " + d["title"] + " " + d["text"])) for d in docs]
        self.len = [sum(c.values()) for c in self.tf]
        self.avg = sum(self.len) / len(self.len)
        df = Counter(t for c in self.tf for t in c)
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, k: int = 3) -> list[dict]:
        q = _tok(query)
        scored = []
        for i, tf in enumerate(self.tf):
            s = 0.0
            for t in q:
                if t in tf:
                    f = tf[t]
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg))
            if s > 0:
                scored.append((s, i))
        scored.sort(reverse=True)
        return [dict(self.docs[i], score=round(s, 2)) for s, i in scored[:k]]
