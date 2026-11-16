# SI disclosure: developed with assistance from Claude Code (Anthropic SI). See SI_DISCLOSURE.md.
"""Pretend to be crew devices and push data into the ONBOARD node's ingestion API.

    python tools/device_simulator.py                 # PLT: band batch + glucometer + BP cuff + 30 s of live shirt data
    python tools/device_simulator.py --crew MS1 --live 0
    python tools/device_simulator.py --stress        # live shirt stream with elevated heart rate

Shows both ingestion styles:
  * BATCH: a fitness band that buffered 7 nights of sleep and resting heart rate, synced when docked
           (send it twice: duplicates are detected and ignored)
  * LIVE:  a smart shirt streaming heart rate / SpO2 / breathing rate every second
"""
import argparse
import json
import random
import time
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8000/api/ingest"
KEY = "demo-device-key"


def push(device_id, readings):
    req = urllib.request.Request(URL, data=json.dumps({"device_id": device_id, "readings": readings}).encode(),
                                 headers={"Content-Type": "application/json", "X-Device-Key": KEY}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "detail": json.loads(e.read() or b"{}")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--crew", default="PLT", choices=["CDR", "PLT", "MS1", "MS2"])
    ap.add_argument("--live", type=int, default=30, help="seconds of live smart-shirt streaming (0 = none)")
    ap.add_argument("--stress", action="store_true", help="stream an elevated heart rate")
    a = ap.parse_args()
    now = time.time()

    band = f"band-{a.crew}" if a.crew in ("PLT", "MS1", "CDR") else None
    if band:
        nights = [{"ts": now - d * 86400 + 6 * 3600 - (now % 86400), "sleep_hours": round(random.uniform(5.4, 7.2), 1),
                   "heart_rate": random.randint(55, 66), "hrv_ms": random.randint(40, 70)} for d in range(7, 0, -1)]
        print("BATCH  fitness band, 7 nights   ->", push(band, nights))
        print("BATCH  same batch re-sent        ->", push(band, nights), "(duplicates ignored)")

    print("SINGLE glucometer                ->", push("glucometer-1", [{"crew_id": a.crew, "glucose_mg_dl": random.randint(88, 110)}]))
    print("SINGLE BP cuff                   ->", push("bpcuff-1", [{"crew_id": a.crew, "systolic": random.randint(114, 126), "diastolic": random.randint(72, 82)}]))
    print("BAD    out-of-range reading      ->", push("bpcuff-1", [{"crew_id": a.crew, "systolic": 400, "diastolic": 80}])["rejected"])

    shirt = f"shirt-{a.crew}" if a.crew in ("PLT", "MS2") else None
    if shirt and a.live:
        print(f"LIVE   {shirt} streaming for {a.live}s (watch the heart-rate tile say 'Smart shirt (live)')...")
        for i in range(a.live):
            hr = (128 + random.randint(-4, 6)) if a.stress else (72 + random.randint(-3, 3))
            r = push(shirt, [{"hr": hr, "spo2": round(random.uniform(96.5, 98.5), 1), "breathing_rate": random.randint(13, 17)}])
            if i % 10 == 0:
                print(f"       t={i:>2}s hr={hr} -> stored={r.get('stored')} live={r.get('routed_live')}")
            time.sleep(1)
    print("done")


if __name__ == "__main__":
    main()
