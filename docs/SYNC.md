# How the spacecraft and ground stay in sync

## One database design, two copies
The spacecraft and the ground station are 3–22 light-minutes apart, so they can't share one live
database. They share **one database module and schema** (`astroguard/db/database.py`). Each node
runs its **own copy**:

| Node | Database file | Role |
|---|---|---|
| Spacecraft (onboard) | `data/onboard.db` | **Source of truth** for crew data. It works with no Earth link at all. |
| Ground station | `data/ground.db` | **Replica**, always as of the last delivered message. |

## Live or batch? Batch, store-and-forward
Sync is **batched, not live streaming**. Every 2 seconds the spacecraft packs a **bundle** and hands
it to the space link (`astroguard/sync/link.py`). The link holds each bundle for the current
**one-way light-time**, then delivers bundles **in order**.

Why batches:
- **Bandwidth is scarce.** Deep-space links are shared with science and spacecraft operations. Bundles carry only what changed.
- **The link is disrupted.** A live stream breaks whenever the link drops; bundles simply wait.
- **That's how deep-space networking works.** NASA's Delay/Disruption Tolerant Networking (DTN) stores data at each hop and forwards it when a path exists. Our link imitates that behavior.

| Mission | Real one-way delay | Demo delay |
|---|---|---|
| Space station | < 1 s | 0.5 s |
| Lunar base | ~1.3 s | 1.3 s |
| Mars transit | 3–22 min | **20 s** (compressed for the demo) |

## What's in a downlink bundle (spacecraft → ground)
| Content | How it's sent |
|---|---|
| New telemetry frames (vitals, cabin, radiation) | **Incremental**: only frames newer than the last sent |
| Check-ins, routine tasks, audit log, **device readings** | **Incremental**: rows with `id >` the last sent id (append-only tables) |
| Preferences, flight-surgeon notes, emergencies (incl. AI situation report) | **Full copy** (small tables whose rows change) |
| Alerts, agent health, traces, events | Latest snapshot |
| Mission environment | Current value |

## Uplink (ground → spacecraft)
| Message | Effect onboard |
|---|---|
| Flight-surgeon note | Inserted into the onboard database, then comes back down in the next bundles |
| Mission Control command (scenario, environment, pause) | Executed onboard |
| Ground audit entries ("Dr. Nair viewed PLT") | Added to the astronaut's "who viewed my data" log |
| `resync` (sent when the ground node starts) | The spacecraft resets its cursors and resends everything |

## Conflicts: each record has one owner
- **The spacecraft owns crew data** (check-ins, readings, emergencies, audit). The ground never edits it directly.
- **The ground owns** notes and commands. These are **sent up as requests** and become real only when the spacecraft applies them. Then they replicate back down.
- With a single owner per record, the two copies can't disagree. The ground can only be *behind*.

## Blackouts (solar conjunction)
When the link is down, the onboard node keeps working normally: alerts, emergencies and the AI
assistant all still run. Bundles **queue up**. When the link returns, the queue is delivered in
order. **Nothing is lost.** Undeliverable messages (for example, the peer is down) are retried.

## Privacy in transit
The ground replica holds what the flight surgeon is entitled to see. The **same need-to-know
rules** are applied when ground users view it, so Mission Control sees status only.
*A flight system would also encrypt bundles and send summaries rather than raw data to Mission
Control's area.*

## What a flight system would add
DTN Bundle Protocol (BPv7) instead of HTTP, encryption and signing of bundles, compression,
priority classes (emergency first; partly modelled with a `priority` flag), and bandwidth budgets per pass.
