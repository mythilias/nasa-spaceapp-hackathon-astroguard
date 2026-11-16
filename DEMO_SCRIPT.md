# AstroGuard: Demo Recording Script

## Intro walkthrough (~70 s)
Start fresh: `python run_mission.py --reset`, then open `http://127.0.0.1:8000` (signed out).

| Time | On screen | You say |
|---|---|---|
| 0:00 | Spacecraft app login (`127.0.0.1:8000`) | "Hi! This is **AstroGuard**, our answer to NASA's challenge: health monitoring software for astronauts on space missions." |
| 0:06 | Stay on login | "It's a web application with an **AI chat assistant**, built as **two apps**: one for the crew on the spacecraft, and one on the ground for mission control, kept automatically in sync." |
| 0:16 | Point at the demo code buttons | "Each crew member signs in with a **personal access code** and sees only what their role allows. These are demo codes." |
| 0:24 | Click **Kenji (7316)**, then open **✨ Ask AstroGuard** | "I'm signing in as **Kenji**, a regular astronaut. His dashboard shows his own vitals, trends, and what to do next. If he has questions, he can ask the **AstroGuard chat assistant**." |
| 0:35 | Click Check-in, Body, Routine, Privacy | "He also has daily check-ins, a body map, his mission routine, and a privacy tab. A **crew medical officer** gets one extra tab: the **crew board**." |
| 0:45 | New tab: `127.0.0.1:8001` (ground login) | "This is the second app: the **ground station** on Earth. It stays in sync with the spacecraft over a delayed space link." |
| 0:52 | Click **Dr. Priya Nair (9001)** | "I'll sign in as **Priya**, the flight surgeon." |
| 0:55 | Crew board → click a crew card | "As the crew's doctor, she sees everyone's full medical picture, and can send a private message that travels up to the spacecraft." |
| 1:03 | Click **Mission Control ↗** | "And in Mission Control, she can watch the AI agents themselves: their health, their alerts, and every data trace, in real time." |

Tips:
- Sign out is the button at the top right. In the ground tab, the link pill can say "in transit"; that's the delayed sync working.
- If the AI answer takes a few seconds, keep talking; it will appear as you finish the sentence.
- Then continue with the full scenario below (check-in, emergency, blackout), or stop here for a short video.

Target length: **about 2:45** (full), plus a **30-second cut**. Check the current Space Apps video-length rule.

## 1. Setup (3 minutes)
1. AI on: the `.env` file contains `ANTHROPIC_API_KEY=...`, and `pip install anthropic` is done.
2. Start fresh: `python run_mission.py --reset`
3. Open **4 browser tabs**. Each tab keeps its own login:

| Tab | URL | Who | Node |
|---|---|---|---|
| 1 | `http://127.0.0.1:8000/#code=7316&view=health` | Kenji (Pilot) | 🛰 Onboard |
| 2 | `http://127.0.0.1:8000/#code=4821&view=crew` | Ana (Commander) | 🛰 Onboard |
| 3 | `http://127.0.0.1:8001/#code=9001&view=crew` | Dr. Nair (Flight Surgeon) | 🌍 Ground |
| 4 | `http://127.0.0.1:8001/#code=3000&view=ops` | Mission Control | 🌍 Ground |

4. In **Tab 4**, set the environment to **Mars transit** *before* recording, and wait about 25 s for the spacecraft to confirm. The link delay becomes 20 s (standing in for ~12 min).
5. Zoom the browser to 110-125%. Record with `Win + Alt + R` (Game Bar), Clipchamp or OBS. Add the voiceover afterwards if that's easier.
6. Re-run `python run_mission.py --reset` before each new take, and set Mars again.

## 2. Scenes

| Time | Action | Voiceover |
|---|---|---|
| 0:00 | Tab 1 header (🛰 ONBOARD · Mars · 📡 link pill) | "Halfway to Mars, Earth is 12 minutes away, sometimes unreachable for weeks. Today's astronaut health monitoring relies on the ground. AstroGuard moves it onboard." |
| 0:12 | Tab 1: My Health. Click the **Blood sugar** tile | "Each astronaut sees their own status, live wearable data and check-ins. Astronauts aren't doctors, so every reading explains how to measure it in space, why it matters, and what to do." |
| 0:27 | **Check-in**: BP **168/104**, sugar **55**, submit, and status turns red | "A daily check-in. Out-of-range values are flagged straight away, with tiered actions: self-care, crew medical officer, or flight surgeon." |
| 0:40 | Click the floating **✨ Ask AstroGuard** button (bottom right); the assistant docks on the right. Tap "I have a headache and feel tired". *(Alternative: open a tile's guide and click "Ask AstroGuard about my reading".)* | "Our AI medical assistant checks Kenji's actual vitals and the cabin CO2, then answers with NASA-cited guidance. Its tools run with Kenji's own permissions, so the AI can never see more than he can." |
| 1:00 | Point to "checked: your health summary, cabin environment…" and the citations | "Every answer shows what it checked and its sources. It's labeled as AI, never prescribes, and hands decisions to humans." |
| 1:08 | **Tab 2** (Commander): Crew board | "The commander sees fit-for-duty and task restrictions. Following NASA practice, medical details stay between each astronaut and the flight surgeon." |
| 1:18 | Tab 2: **⚠ EMERGENCY**, choose Tom, then **Chest pain / collapsed**; tick steps 1-2 | "Tom collapses. A step-by-step protocol, Tom's vitals unlocked for the crew, and a warning: the surgeon is 12 minutes away, act now." |
| 1:35 | Point to the **📨 Situation report** box | "An AI agent writes a situation report for the flight surgeon, so one delayed message carries everything." |
| 1:45 | **Tab 3** (Ground, surgeon): show the link pill; the emergency appears about 20 s after it was declared | "This is the ground station: a separate system, synced over a delayed space link. The emergency and the AI report arrive after the light-time delay." |
| 2:00 | Tab 3: click Tom, then send a private message ("Give oxygen, attach ECG, I'm reviewing") | "The flight surgeon replies. The message travels up the link and reaches the crew 12 minutes later, which is why onboard guidance matters." |
| 2:12 | **Tab 4** (Mission Control): click **Simulate solar conjunction blackout** | "During solar conjunction the link goes down. The spacecraft keeps working on its own; messages are stored and forwarded when the link returns." |
| 2:22 | Tab 4: click **co2 buildup**, the coordinator alert appears; click **crash** on an agent, and the supervisor restarts it | "Underneath, five agents watch heart, lungs, sleep, radiation and the cabin; a coordinator finds the root cause, and a supervisor keeps the agents themselves healthy." |
| 2:35 | Back to Tab 1 | "AstroGuard: onboard-first, privacy-aware AI health monitoring for when Earth is too far away, and for remote communities here on Earth too. Thank you." |

Notes:
- In blackout, ground commands (like *co2 buildup*) wait in the queue. Click **Restore link** before the CO2 step, or do the CO2 step first.
- If the AI is slow, cut the wait in editing.

## 3. 30-second cut
1. (0-5 s) Hook: "Halfway to Mars, Earth is 12 minutes away."
2. (5-12 s) Ask AstroGuard: the headache answer with "checked: vitals, cabin" and citations.
3. (12-20 s) EMERGENCY: protocol plus the AI situation report.
4. (20-26 s) Ground tab: the report arrives after the delay; the blackout button.
5. (26-30 s) "AstroGuard: health guidance when Earth is too far away."

## 4. Upload
YouTube as **Unlisted** or Public. Put the link in the submission and the GitHub README.
