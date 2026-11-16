# Space Apps Submission: Orbit & Co (copy each block into the matching form field)

**Deadline: Sunday Nov 15, 11:59 PM local time. "Save Progress" does NOT submit; click "Submit for Judging".**

---
## Project Name
AstroGuard

## Summary *(50-200 words, max 1500 characters)*
AstroGuard is health monitoring software for astronauts on long missions, where Earth can be 22 minutes away and unreachable for weeks. It runs onboard as two synced apps: a spacecraft app for the crew and a ground app for the flight surgeon and mission control, linked by a delayed, store-and-forward space link. Each astronaut signs in to see their own vitals, check-ins, trends and a clickable body map, with plain-language guidance on how to measure each indicator in space, why it matters and what to do. An AI chat assistant answers health questions using the astronaut's real data and NASA guidance, and only sees what the asker is allowed to see. Five monitoring agents detect problems, a coordinator separates cabin issues from personal ones, and emergency mode guides the crew step by step while an AI writes a report for the ground. Access follows NASA medical-privacy practice. Real astronaut blood data from NASA's Open Science Data Repository (Inspiration4, OSD-575) gives every reading a real spaceflight reference.

## Project Demonstration *(public link: up to 7 slides OR a video of 30 s or less)*
`<link to slides or video>`

## Project *(public link)*
`<GitHub repository URL>` (live demo: `<Render URL>`, optional)

## Project Details
**What it does**
- **Astronaut app:** personal sign-in; color-coded status and fit-for-duty; live wearable data plus daily check-ins (blood pressure, blood sugar, temperature, sleep, mood); 14-day trends; a clickable body map; routine reminders with points, streaks and badges.
- **Built for non-doctors:** every indicator explains how to measure it in space, why it matters (linked to NASA's five hazards of human spaceflight), the normal range and what to do. Recommendations are tiered: self-care, crew medical officer or flight surgeon.
- **AI assistant (✨ Ask AstroGuard):** docked on every screen. It checks the asker's vitals, trends and cabin air, searches a NASA-based knowledge base and cites sources. Its tools run with the asker's own permissions (privacy-aware AI). Red-flag symptoms are caught by fixed code, not the AI. Without AI it falls back to a rule-based assistant.
- **Emergency mode:** step-by-step protocols (chest pain/collapse, low oxygen, radiation storm, fainting) and live patient vitals; an AI agent writes an SBAR situation report for the flight surgeon.
- **Two apps, one mission:** the spacecraft app (master database) and the ground app (replica) sync in store-and-forward batches with real light-time delay. The design is inspired by NASA's Delay/Disruption Tolerant Networking, and nothing is lost during a solar-conjunction blackout.
- **Real NASA data:** the Inspiration4 crew's blood chemistry (NASA OSDR OSD-575) is shown next to each astronaut's own values and drives knowledge-base passages the AI cites.
- **Device ingestion:** an API for smart shirts (Astroskin-type), fitness bands, glucometers and BP cuffs, live or batch, validated and de-duplicated.
- **Privacy following NASA practice:** medical data stays between the astronaut and the flight surgeon (Privacy Act, private medical conferences); there are two crew medical officers, as NASA requires; the commander and mission control see fit-for-duty only; an emergency unlocks vitals; astronauts see who viewed their data.
- **Multi-agent monitoring:** cardio, respiratory, sleep, radiation and environment agents plus a coordinator (root cause: cabin vs. person) and a self-healing supervisor, with an observability dashboard.

**Benefits and impact:** earlier detection, guidance without medical training, faster emergency response when the ground is minutes away, and privacy that encourages honest reporting. It's designed for Earth-independent operations, and the same offline, guided design could serve remote communities on Earth.

**How it's creative:** onboard-first instead of ground-dependent; AI that follows the same need-to-know rules as humans; a delayed-link architecture you can see in the demo; real NASA flight data as a personal reference.

**Tools:** Python 3 (standard library), SQLite, HTML/CSS/JavaScript, Canvas, SVG, the Anthropic Claude API, GitHub and Render.

**Factors considered:** communication delay and blackouts; safety (rule-based detection, AI only advises); NASA medical privacy; astronauts aren't doctors; limited bandwidth; and the limits of a prototype (synthetic crew data, demo thresholds, not a medical device).

## Use of Super Intelligence (SI)
*(Select the options that apply. Judges see the disclosures in the project itself.)* We used Claude Code (Anthropic) to help write the code, documentation, knowledge-base text, synthetic data generators and slide content. The app itself optionally calls the Anthropic Claude API for its AI assistant and reports, and all AI output is labelled in the app. Every source file carries an SI-disclosure header, and SI_DISCLOSURE.md describes it in full. No SI-generated images are used, and no NASA branding is used.

## NASA Data *(Link Text → Link URL)*
| Link Text | Link URL |
|---|---|
| NASA OSDR OSD-575: Inspiration4 Comprehensive Metabolic Panel (dataset used in the app) | https://osdr.nasa.gov/bio/repo/data/studies/OSD-575 |
| NASA Open Science Data Repository | https://osdr.nasa.gov |
| NASA SOMA / Inspiration4 data release | https://www.nasa.gov/osdr-latest-news-soma-publications |
| NASA Human Research Program | https://www.nasa.gov/hrp/ |
| NASA-STD-3001 / HIDH 3.0 Health and Medical Care | https://www.nasa.gov/reference/3-0-health-and-medical-care/ |
| NASA-STD-3001 / HIDH 5.0 Training (two Crew Medical Officers) | https://www.nasa.gov/reference/5-0-training/ |
| NASA Lifetime Surveillance of Astronaut Health (medical privacy) | https://nlsp.nasa.gov/explore/lsdahome/lsahhome |

## Space Agency Partner & Other Data *(Link Text → Link URL)*
| Link Text | Link URL |
|---|---|
| Canadian Space Agency: Bio-Monitor (Astroskin) wearable | https://www.asc-csa.gc.ca/eng/sciences/astroskin.asp |
| Challenge by the Brazilian Space Agency (AEB) | https://www.spaceappschallenge.org/2026/challenges/health-monitoring-software/ |
| National Academies: Safe Passage, astronaut medical confidentiality | https://www.nationalacademies.org/read/10218/chapter/8 |
| Inspiration4 data access guide (npj Microgravity) | https://pmc.ncbi.nlm.nih.gov/articles/PMC11094041 |
| Anthropic Claude API and Python SDK (AI assistant) | https://docs.anthropic.com |
| Claude Code (SI coding assistant) | https://www.anthropic.com/claude-code |
| Python (standard library, SQLite) | https://www.python.org |
| Render (hosting of the public demo) | https://render.com |

## Project Submission Verification
- [ ] Agree to Terms and Conditions
- [ ] Confirm all work is original, with all external resources listed above. Edit SI_DISCLOSURE.md "Human contributions" first.
