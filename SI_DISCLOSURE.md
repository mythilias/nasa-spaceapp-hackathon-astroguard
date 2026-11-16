# Use of Super Intelligence (SI) / AI tools

As the NASA Space Apps Challenge requires, here is where and how SI tools were used in AstroGuard.

## SI tools used
| Tool | Used for |
|---|---|
| **Claude Code** (Anthropic coding assistant, model Claude Opus 5.5) | Writing most of the **source code** (Python backend, HTML/CSS/JavaScript UI), **documentation** (README, docs/), the **knowledge-base text** (paraphrased summaries of NASA guidance), the **synthetic crew data generators**, the demo script and submission text, and the slide content. |
| **Anthropic Claude API** (`claude-opus-5-5`), *inside the product* | Runtime AI features: the AstroGuard Medical Assistant chat, emergency situation reports (SBAR) and alert explanations. Optional: without an API key the app uses rule-based logic. Every AI output in the app is labelled "AI-generated". |

## Where SI-generated content appears
- **Code:** every source file starts with an SI-disclosure header comment (Python) or a `generator` meta tag and comment (HTML).
- **Data:** `astroguard/sim/telemetry.py` and the seed data in `astroguard/db/database.py` generate **synthetic** crew data; no real person's data is used. The real NASA dataset in `datasets/osdr/` was **downloaded unchanged** from NASA OSDR and is not SI-generated.
- **Text:** README, docs and knowledge-base passages were drafted with SI and reviewed by the team.
- **Images/video:** no SI-generated images are used. Screenshots in our slides are captures of the running app. Slides carry a visible "SI-assisted" note.
- **No NASA branding:** no NASA logos, flags, insignia or mission identifiers were generated or used.

## Human contributions (team Orbit & Co)
*Edit before submitting:* describe your own work, for example: choosing the challenge and concept, product and privacy decisions (NASA-aligned need-to-know rules, two CMOs, onboard-first design), directing and reviewing the SI-generated code, testing every feature, selecting NASA resources and datasets, and preparing the demo.
