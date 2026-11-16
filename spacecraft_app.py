# SI disclosure: developed with assistance from Claude Code (Anthropic SI). See SI_DISCLOSURE.md.
"""Spacecraft (ONBOARD) node: crew app, agents, AI, device ingestion, master database.

Usually started by `python run_mission.py`. Standalone:
    set HMS_LINK_KEY=<same value as ground>
    python spacecraft_app.py --peer http://127.0.0.1:8001
"""
from astroguard.server.app import main

if __name__ == "__main__":
    main(node="onboard", port=8000, peer="http://127.0.0.1:8001")
