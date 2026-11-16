# SI disclosure: developed with assistance from Claude Code (Anthropic SI). See SI_DISCLOSURE.md.
"""All-in-one demo: every role on one server (http://127.0.0.1:8000), ground delay simulated.

    python run_demo.py --reset
"""
from astroguard.server.app import main

if __name__ == "__main__":
    main(node="standalone", port=8000)
