# SI disclosure: developed with assistance from Claude Code (Anthropic SI). See SI_DISCLOSURE.md.
"""Simulated deep-space link between the ONBOARD node and the GROUND node.

Store-and-forward, in the spirit of NASA's Delay/Disruption Tolerant Networking (DTN):
every message is queued, held for the one-way light-time of the current mission
environment, then delivered in order. During a blackout (e.g. Mars solar conjunction)
messages stay queued and are delivered when the link returns. Nothing is lost.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from collections import deque


class SpaceLink:
    def __init__(self, name: str, peer_url: str, link_key: str, delay_fn, on_log=None):
        self.name = name                # "downlink" (onboard -> ground) or "uplink" (ground -> onboard)
        self.peer_url = peer_url.rstrip("/")
        self.link_key = link_key
        self.delay_fn = delay_fn        # returns current one-way delay in seconds
        self.on_log = on_log or (lambda *a: None)
        self.queue: deque = deque()
        self.lock = threading.Lock()
        self.seq = 0
        self.blackout = False
        self.sent = 0
        self.delivered = 0
        self.failures = 0
        self.last_delivered_ts: float | None = None
        self.last_rx_ts: float | None = None   # last message received FROM the peer
        self.rx_count = 0

    def start(self):
        threading.Thread(target=self._run, name=f"link-{self.name}", daemon=True).start()

    def send(self, kind: str, payload: dict, priority: bool = False):
        with self.lock:
            self.seq += 1
            msg = {"seq": self.seq, "kind": kind, "created": time.time(), "payload": payload, "priority": priority}
            self.queue.append(msg)
            self.sent += 1
        return msg

    def received(self):
        self.last_rx_ts = time.time()
        self.rx_count += 1

    def _post(self, path, body):
        req = urllib.request.Request(self.peer_url + path, data=json.dumps(body, default=str).encode(),
                                     headers={"Content-Type": "application/json", "X-Link-Key": self.link_key},
                                     method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status

    def _run(self):
        while True:
            time.sleep(0.25)
            if self.blackout:
                continue
            now, delay = time.time(), self.delay_fn()
            while True:
                with self.lock:
                    if not self.queue or self.queue[0]["created"] + delay > now:
                        break
                    msg = self.queue[0]
                try:
                    self._post("/api/link/rx", msg)
                    with self.lock:
                        self.queue.popleft()
                    self.delivered += 1
                    self.last_delivered_ts = time.time()
                except (urllib.error.URLError, OSError, TimeoutError):
                    self.failures += 1  # peer unreachable: keep the message and retry (store-and-forward)
                    break

    def control_peer(self, body):
        """Out-of-band demo control channel (not a real space link): toggles blackout on both nodes."""
        try:
            self._post("/api/link/control-peer", body)
        except (urllib.error.URLError, OSError, TimeoutError):
            pass

    def status(self):
        with self.lock:
            queued = len(self.queue)
            oldest = self.queue[0]["created"] if self.queue else None
        now = time.time()
        return {"name": self.name, "delay_s": self.delay_fn(), "blackout": self.blackout, "queued": queued,
                "oldest_queued_age_s": round(now - oldest, 1) if oldest else None,
                "sent": self.sent, "delivered": self.delivered,
                "last_rx_age_s": round(now - self.last_rx_ts, 1) if self.last_rx_ts else None,
                "rx_count": self.rx_count}
