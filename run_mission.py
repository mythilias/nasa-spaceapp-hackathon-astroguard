# SI disclosure: developed with assistance from Claude Code (Anthropic SI). See SI_DISCLOSURE.md.
"""Start the two-node AstroGuard mission: ONBOARD (spacecraft) + GROUND (Earth), linked by a delayed space link.

    python run_mission.py           # onboard  http://127.0.0.1:8000  (crew)
                                    # ground   http://127.0.0.1:8001  (flight surgeon, mission control)
    python run_mission.py --reset   # fresh demo data on both nodes

Ctrl+C stops both.
"""
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent


def main():
    reset = ["--reset"] if "--reset" in sys.argv else []
    env = dict(os.environ, HMS_LINK_KEY=os.environ.get("HMS_LINK_KEY") or secrets.token_hex(16))
    py = sys.executable
    onboard = subprocess.Popen([py, "spacecraft_app.py", *reset], cwd=ROOT, env=env)
    time.sleep(1.0)
    ground = subprocess.Popen([py, "ground_app.py", *reset], cwd=ROOT, env=env)
    print("\n  ONBOARD (crew):          http://127.0.0.1:8000")
    print("  GROUND  (surgeon, MCC):  http://127.0.0.1:8001\n  Ctrl+C to stop.\n")
    try:
        while onboard.poll() is None and ground.poll() is None:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for p in (onboard, ground):
            if p.poll() is None:
                p.terminate()


if __name__ == "__main__":
    main()
