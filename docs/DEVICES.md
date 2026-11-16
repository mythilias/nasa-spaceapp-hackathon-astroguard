# Connecting wearables and medical devices

Devices send data to the **spacecraft's onboard node**. They never send it to the ground: the crew's
devices are onboard, and the data reaches Earth through the normal sync (see [SYNC.md](SYNC.md)).

```
 Smart shirt (Astroskin-type) ─┐  live, every few seconds
 Fitness band (Fitbit-type) ───┤  batch: buffered offline, synced when docked
 Glucometer · BP cuff · thermometer ─┤  single readings
                                     ▼
                     POST /api/ingest   (onboard node, port 8000)
     authenticate → map to crew → validate → de-duplicate → store → route
                                     │
           live vitals ──────────────┼──► live telemetry stream ──► agents, alerts, My Health (within ~1 s)
           clinical values ──────────┴──► device-sourced check-in ──► trends, recommendations, alerts
           every reading ────────────────► `readings` table ──► replicated to the ground
```

## API
```http
POST /api/ingest
X-Device-Key: demo-device-key
Content-Type: application/json

{ "device_id": "band-PLT",
  "readings": [ { "ts": 1763190000, "sleep_hours": 6.4, "heart_rate": 58, "hrv_ms": 52 },
                { "ts": 1763276400, "sleep_hours": 5.9, "heart_rate": 61, "hrv_ms": 47 } ] }
```
Response: `received`, `stored`, `duplicates`, `rejected` (each with a reason), `routed_live`, `routed_checkins`.

- **Live vs batch:** the same endpoint handles both. A reading less than 2 minutes old with a live vital (HR, SpO2, breathing, skin temperature, HRV) replaces the simulated value in the live stream. Older readings are history.
- **De-duplication:** `device + metric + timestamp` is unique, so a band can safely re-send its whole buffer.
- **Validation:** each field is checked against a plausible range, and **one bad field rejects the whole reading** (this keeps blood-pressure pairs consistent).
- **Shared devices** (glucometer, cuff, thermometer) must name the `crew_id` in each reading. Personal devices are bound to their owner.
- **Alerts:** recent clinical readings go through the same alert checks as manual check-ins. Old batch history only fills trends.
- **Source shown in the UI:** tiles say "Smart shirt (live)", "Blood pressure cuff", and so on.

## Registered device types
| Type | Example device | Fields → AstroGuard metric |
|---|---|---|
| `smart_shirt` | CSA Bio-Monitor / Astroskin-type | `hr`, `spo2`, `breathing_rate`, `skin_temp`, `systolic`, `diastolic` |
| `fitness_band` | Fitbit-type watch | `heart_rate`, `hrv_ms`, `sleep_hours`, `steps` |
| `glucometer` | fingerstick meter | `glucose_mg_dl` |
| `bp_cuff` | automated cuff | `systolic`, `diastolic` |
| `thermometer` | digital thermometer | `temp_c` |

**Adding a new device type is one entry** in `DEVICE_TYPES` (`astroguard/ingest/devices.py`), mapping its field names to AstroGuard metrics.

## Try it
```bash
python run_mission.py --reset
python tools/device_simulator.py            # band batch (sent twice: duplicates ignored), glucometer, cuff, 30 s live shirt
python tools/device_simulator.py --stress   # live shirt with elevated heart rate: watch the agents react
```

## Demo limitations
There's one shared demo device key. A flight system would give each device its own credentials,
sign its data, keep a device health log (battery, signal) and run calibration checks.
