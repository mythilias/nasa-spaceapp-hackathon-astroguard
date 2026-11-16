# SI disclosure: developed with assistance from Claude Code (Anthropic SI). See SI_DISCLOSURE.md.
"""Ground station node: flight surgeon + mission control, replica of the spacecraft's data.

Usually started by `python run_mission.py`. Standalone:
    set HMS_LINK_KEY=<same value as spacecraft>
    python ground_app.py --peer http://127.0.0.1:8000
"""
from astroguard.server.app import main

if __name__ == "__main__":
    main(node="ground", port=8001, peer="http://127.0.0.1:8000")
