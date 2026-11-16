# SI disclosure: developed with assistance from Claude Code (Anthropic SI). See SI_DISCLOSURE.md.
"""Astronaut-facing content: indicator guides, body systems, emergency protocols, routine, environments.

"Astronauts are not doctors." For every indicator the tool explains HOW to measure it, WHY it
matters in spaceflight, what NORMAL looks like, and WHAT TO DO when a value is abnormal.

Thresholds are demo values chosen for this prototype. They are NOT clinical limits.
"""
from __future__ import annotations

HAZARDS = {
    "R": "Space radiation",
    "I": "Isolation & confinement",
    "D": "Distance from Earth",
    "G": "Altered gravity fields",
    "E": "Hostile closed environment",
}

# status rules: list of (status, predicate-as-(op, value)) evaluated crit first.
INDICATORS: dict[str, dict] = {
    "heart_rate": {
        "name": "Heart rate", "unit": "bpm", "source": "sensor", "system": "heart", "hazards": ["G", "E"],
        "how": [
            "Read automatically from your chest strap or watch.",
            "Manual check: rest seated (feet restrained) for 5 minutes, find the pulse on the thumb side of your wrist, count for 30 seconds and double it.",
        ],
        "why": "Without gravity, body fluid shifts toward the head and the heart adapts. Over time this can change heart size and rhythm, and some astronauts have had rhythm disturbances in flight.",
        "normal": "Resting: about 50-90 bpm",
        "warn": [(">", 100), ("<", 45)], "crit": [(">", 130), ("<", 40)],
        "actions": {
            "warn": ["Stop strenuous activity and rest for 10 minutes, then re-measure", "Hydrate", "If it stays high, tell the Crew Medical Officer"],
            "crit": ["Stop all activity and rest restrained", "Take an ECG with the onboard medical kit", "Contact the flight surgeon; if you have chest pain or feel faint, start EMERGENCY mode"],
        },
    },
    "blood_pressure": {
        "name": "Blood pressure", "unit": "mmHg", "source": "manual", "system": "heart", "hazards": ["G"],
        "how": [
            "Use the automated cuff on your bare upper arm, level with your heart.",
            "Rest 5 minutes first. Restrain your feet so you are not floating and tensing muscles. Don't talk.",
            "Take 2 readings 1 minute apart and enter the average.",
        ],
        "why": "Fluid shifts in microgravity change blood pressure regulation. On return to gravity (landing, or a Moon or Mars surface) this can cause dizziness or fainting, called orthostatic intolerance.",
        "normal": "Below about 130/85 mmHg",
        "warn": [(">", 135), ("<", 90)], "crit": [(">", 160), ("<", 85)],
        "actions": {
            "warn": ["Re-measure after 15 minutes of rest", "Reduce salt and keep hydrated", "Keep up your daily exercise; log it in Routine"],
            "crit": ["Re-measure immediately with the second cuff to rule out an equipment error", "Tell the Crew Medical Officer", "Contact the flight surgeon with both readings"],
        },
    },
    "spo2": {
        "name": "Oxygen saturation", "unit": "%", "source": "sensor", "system": "lungs", "hazards": ["E"],
        "how": [
            "Read automatically from your fingertip or ear sensor.",
            "Manual check: clip the pulse oximeter on a warm finger, keep still for 30 seconds, read the steady value.",
        ],
        "why": "A closed cabin depends on life-support systems. A pressure leak or air problem lowers the oxygen available. Hypoxia impairs judgement before you notice symptoms.",
        "normal": "95-100%",
        "warn": [("<", 94)], "crit": [("<", 90)],
        "actions": {
            "warn": ["Re-seat the sensor and warm your hands, then re-measure", "Check the cabin pressure and O2 display", "If others are low too, it is likely the cabin. Alert the crew"],
            "crit": ["Put on an oxygen mask now", "Alert the crew and check cabin pressure", "Start EMERGENCY mode (low oxygen) if it does not recover"],
        },
    },
    "blood_glucose": {
        "name": "Blood sugar", "unit": "mg/dL", "source": "manual", "system": "metabolic", "hazards": ["G", "I"],
        "how": [
            "Use the fingerstick glucometer. Clean the finger and lance the side of the fingertip.",
            "In microgravity the drop beads up on your finger, so touch the strip to it rather than letting it drip.",
            "Note the hours since your last meal.",
        ],
        "why": "Research suggests spaceflight and inactivity can reduce insulin sensitivity. Nutrition is limited on long missions, and both low and high blood sugar impair performance.",
        "normal": "Fasting about 70-99 mg/dL; under 140 two hours after a meal",
        "warn": [(">", 180), ("<", 70)], "crit": [(">", 250), ("<", 60)],
        "actions": {
            "warn": ["If low: eat 15 g of fast carbohydrate (juice pouch), re-check in 15 minutes", "If high: hydrate, light exercise, re-check in 2 hours", "Log your meals for the flight surgeon"],
            "crit": ["If low and confused or shaky: take fast carbohydrate now and tell a crewmate", "Contact the flight surgeon", "Do not perform safety-critical tasks until normal"],
        },
    },
    "body_temp": {
        "name": "Body temperature", "unit": "°C", "source": "manual", "system": "immune", "hazards": ["R", "I", "E"],
        "how": [
            "Use the digital thermometer under your tongue and wait for the beep.",
            "Don't eat or drink for 15 minutes before measuring.",
        ],
        "why": "The immune system changes in spaceflight, and dormant viruses can reactivate. A fever can be an early sign of infection. Research has also found that core temperature can run higher on long missions.",
        "normal": "About 36.1-37.2 °C",
        "warn": [(">", 37.5), ("<", 35.8)], "crit": [(">", 38.5), ("<", 35.0)],
        "actions": {
            "warn": ["Rest and hydrate; re-measure in 1 hour", "Note any symptoms (sore throat, cough, rash)", "Limit close contact in shared modules"],
            "crit": ["Tell the Crew Medical Officer", "Contact the flight surgeon about medication from the onboard kit", "Isolate in your crew quarters if possible"],
        },
    },
    "sleep_hours": {
        "name": "Sleep", "unit": "h", "source": "sensor", "system": "brain", "hazards": ["I", "D"],
        "how": [
            "Measured by your wrist actigraphy watch overnight.",
            "If the watch was off, enter your best estimate at the morning check-in.",
        ],
        "why": "Noise, light, workload and the lack of a normal day/night cycle cut sleep in space. Sleep loss slows reaction time and raises the risk of errors in spacewalks, docking and robotics.",
        "normal": "Target 7-9 h",
        "warn": [("<", 6)], "crit": [("<", 5)],
        "actions": {
            "warn": ["Protect your next sleep window: eye mask, earplugs, dimmed blue light", "Avoid caffeine within 8 hours of sleep", "Ask the commander to move non-urgent tasks"],
            "crit": ["No spacewalks, docking or robotic operations until rested", "Tell the commander (task reassignment)", "Discuss sleep medication with the flight surgeon"],
        },
    },
    "mood": {
        "name": "Mood", "unit": "/5", "source": "manual", "system": "brain", "hazards": ["I", "D"],
        "how": [
            "Rate your mood honestly from 1 (very low) to 5 (great). Add a note if you want.",
            "Your mood entries are private. Only you and the flight surgeon see them unless you choose to share.",
        ],
        "why": "Months of isolation, confinement and distance from family affect everyone. Catching low mood early lets you get support before it affects health or teamwork.",
        "normal": "3-5 most days",
        "warn": [("<", 3)], "crit": [("<", 2)],
        "actions": {
            "warn": ["Schedule a call with family or friends", "Take a break: music, a window view, or time with the crew", "Keep regular sleep and exercise"],
            "crit": ["Request a private conference with the flight surgeon or psychologist", "You are not alone. Talk to a trusted crewmate", "Use the support resources in your personal kit"],
        },
    },
    "exercise_min": {
        "name": "Exercise", "unit": "min", "source": "routine", "system": "bones", "hazards": ["G"],
        "how": [
            "Log each session in Routine: resistance device plus treadmill or cycle.",
            "ISS crews exercise about 2 hours a day.",
        ],
        "why": "Without gravity, bones lose mineral density and muscles weaken, especially in the hips, spine and legs. Daily resistance exercise is the main countermeasure.",
        "normal": "About 120 min/day",
        "warn": [("<", 60)], "crit": [("<", 0)],
        "actions": {
            "warn": ["Complete today's resistance session", "Split into two shorter sessions if your schedule is tight"],
            "crit": [],
        },
    },
}

BODY_SYSTEMS = {
    "brain": {"name": "Brain & behavior", "function": "Thinking, sleep, mood and decision making.",
              "spaceflight": "Isolation, confinement and disrupted sleep affect mood, attention and teamwork.",
              "indicators": ["sleep_hours", "mood"]},
    "eyes": {"name": "Eyes", "function": "Vision.",
             "spaceflight": "Many long-duration astronauts develop changes to the eye and optic nerve (Spaceflight Associated Neuro-ocular Syndrome, SANS), linked to the headward fluid shift.",
             "indicators": [], "note": "Do the weekly Amsler-grid vision check in Routine and report any blurring."},
    "heart": {"name": "Heart & circulation", "function": "Pumps blood and oxygen to the body.",
              "spaceflight": "Fluid shifts and less work against gravity change the heart and blood pressure control.",
              "indicators": ["heart_rate", "blood_pressure"]},
    "lungs": {"name": "Lungs", "function": "Brings oxygen in and removes carbon dioxide.",
              "spaceflight": "The cabin atmosphere (CO2, pressure, O2) directly affects breathing and oxygen levels.",
              "indicators": ["spo2"]},
    "metabolic": {"name": "Metabolism", "function": "Turns food into energy and keeps blood sugar stable.",
                  "spaceflight": "Inactivity and limited nutrition can affect insulin sensitivity and energy.",
                  "indicators": ["blood_glucose"]},
    "immune": {"name": "Immune system", "function": "Fights infection.",
               "spaceflight": "Radiation, stress and confinement alter immune function; dormant viruses can reactivate.",
               "indicators": ["body_temp"]},
    "bones": {"name": "Bones & muscles", "function": "Support, movement and strength.",
              "spaceflight": "Bone density and muscle mass decline without gravity loading; daily exercise is the countermeasure.",
              "indicators": ["exercise_min"]},
}

EMERGENCY_PROTOCOLS = {
    "chest_pain": {
        "title": "Chest pain / crewmate collapsed",
        "steps": [
            "Call out \"MEDICAL EMERGENCY\" to all crew. The Crew Medical Officer leads; one crewmate handles comms.",
            "Check responsiveness: tap the shoulders and ask loudly \"Are you OK?\"",
            "Check breathing for up to 10 seconds: look at the chest, listen and feel.",
            "NOT breathing normally: restrain the patient on the rigid medical restraint, brace yourself against the opposite surface, and start chest compressions.",
            "Attach the defibrillator from the medical kit and follow its voice prompts.",
            "Breathing: give oxygen by mask, attach the ECG and pulse oximeter, and keep the patient restrained and calm.",
            "Follow the onboard chest-pain checklist; give medication only as the checklist or flight surgeon directs.",
            "Send vitals to the flight surgeon. Log vitals every 5 minutes; this tool records them automatically.",
        ],
    },
    "low_oxygen": {
        "title": "Low oxygen / cabin pressure loss",
        "steps": [
            "Put on your oxygen mask first, then help others.",
            "Call out \"PRESSURE\" / \"LOW O2\" to all crew.",
            "Check every crew member's SpO2 on the Crew screen.",
            "Gather in the designated safe module and close the hatches as trained.",
            "Run the leak-isolation checklist with mission control.",
            "Prepare the crew vehicle in case evacuation is needed.",
        ],
    },
    "radiation": {
        "title": "Radiation storm (solar particle event)",
        "steps": [
            "Stop spacewalks and outdoor surface activities. Return inside now.",
            "Move to the storm shelter (most shielded area, surrounded by water and supplies).",
            "Wear your personal dosimeter and record the reading.",
            "Stay sheltered until the dose rate on the Habitat display returns to normal.",
            "Report your exposure to the flight surgeon.",
        ],
    },
    "fainting": {
        "title": "Dizziness / fainting",
        "steps": [
            "In gravity (Moon, Mars, after landing): lie down flat and raise the legs.",
            "In microgravity: restrain the crewmate and loosen tight clothing.",
            "Check responsiveness, breathing, heart rate and blood pressure.",
            "Give fluids by mouth once fully awake.",
            "If they do not recover within 1 minute, switch to the Chest pain / collapsed protocol.",
            "Report to the flight surgeon.",
        ],
    },
}

ROUTINE = [
    {"id": "checkin", "title": "Morning health check-in", "due": "08:00", "points": 10, "detail": "BP, blood sugar, temperature, mood"},
    {"id": "exercise", "title": "Exercise session (~2 h)", "due": "11:00", "points": 15, "detail": "Resistance + treadmill/cycle. Protects bone and muscle", "minutes": 120},
    {"id": "hydration", "title": "Hydration: 2+ liters", "due": "15:00", "points": 5, "detail": "Fluid shift makes thirst less reliable"},
    {"id": "vision", "title": "Amsler-grid vision check", "due": "17:00", "points": 5, "detail": "Weekly SANS screening"},
    {"id": "mood_pm", "title": "Evening mood & stress check", "due": "20:00", "points": 5, "detail": "Private by default"},
    {"id": "sleep_prep", "title": "Sleep prep: dim lights, 8 h window", "due": "22:00", "points": 5, "detail": "Eye mask, earplugs, no screens"},
]

ENVIRONMENTS = {
    # demo_delay_s: one-way link delay used by the two-node demo (Mars compressed so a video can show it)
    "iss": {"name": "Space station (low Earth orbit)", "gravity": "Microgravity", "delay_s": 0.5,
            "delay_label": "under 1 s", "rad_mult": 1.0, "lag_ticks": 0, "demo_delay_s": 0.5},
    "lunar": {"name": "Lunar surface base", "gravity": "1/6 g", "delay_s": 1.3,
              "delay_label": "~1.3 s one way", "rad_mult": 2.5, "lag_ticks": 2, "demo_delay_s": 1.3},
    "mars": {"name": "Mars transit vehicle", "gravity": "Microgravity", "delay_s": 720,
             "delay_label": "~12 min one way (varies 3-22 min)", "rad_mult": 3.0, "lag_ticks": 20, "demo_delay_s": 20},
}


def status_of(indicator: str, value) -> str:
    if value is None:
        return "none"
    spec = INDICATORS[indicator]
    for level in ("crit", "warn"):
        for op, th in spec[level]:
            if (op == ">" and value > th) or (op == "<" and value < th):
                return level
    return "ok"
