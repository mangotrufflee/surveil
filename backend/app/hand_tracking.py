"""Persistent hand identity + customer/session ids.

The document requires tracking "customer/session IDs across frames". With a
laptop camera we cannot do face recognition reliably, so a *session* is a
shopping episode: it starts when a hand appears in frame and ends when that hand
has been gone for ``idle_seconds``. Each hand gets a stable ``hand_id`` and a
``customer_id`` derived from it, and every interaction event carries the
``session_id`` of the hand that caused it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .geometry import BBox, greedy_match, intersection_over_union
from .hands import HandBox

MATCH_IOU = 0.3
IDLE_SECONDS = 8.0


@dataclass
class HandIdentity:
    hand_id: int
    customer_id: str
    session_id: str
    box: BBox
    score: float
    last_seen: float
    first_seen: float
    hits: int = 1
    frames_seen: int = 1


@dataclass
class TrackedHand:
    hand_id: int
    customer_id: str
    session_id: str
    box: BBox
    score: float
    first_seen: float
    last_seen: float
    boxes: list[BBox] = field(default_factory=list)

    @property
    def center(self) -> tuple[float, float]:
        return self.box.center


class HandIdentityTracker:
    def __init__(self, session_id: str, idle_seconds: float = IDLE_SECONDS) -> None:
        self.session_id = session_id
        self.idle_seconds = idle_seconds
        self.active: dict[int, HandIdentity] = {}
        self._next_id = 1
        self.sessions: dict[str, float] = {}

    def update(self, hands: list[HandBox], ts: float) -> list[TrackedHand]:
        boxes = [h.bbox for h in hands]
        out: list[TrackedHand] = []

        ids = list(self.active.keys())
        pairs: list[tuple[int, int, float]] = []
        for hi, hbox in enumerate(boxes):
            for ii, hid in enumerate(ids):
                pairs.append((hi, ii, intersection_over_union(hbox, self.active[hid].box)))
        matches, used_hands, used_ids = greedy_match(pairs, MATCH_IOU)

        for hi, ii in matches:
            hand, hid = hands[hi], ids[ii]
            identity = self.active[hid]
            identity.box = hand.bbox
            identity.score = hand.score
            identity.last_seen = ts
            identity.hits += 1
            identity.frames_seen += 1
            out.append(self._wrap(identity, ts))
        for hi, hand in enumerate(hands):
            if hi in used_hands:
                continue
            hid = self._next_id
            self._next_id += 1
            identity = HandIdentity(
                hand_id=hid,
                customer_id=f"C{hid:02d}",
                session_id=self.session_id,
                box=hand.bbox,
                score=hand.score,
                last_seen=ts,
                first_seen=ts,
            )
            self.active[hid] = identity
            out.append(self._wrap(identity, ts))

        for hid in list(self.active.keys()):
            if (ts - self.active[hid].last_seen) > self.idle_seconds:
                self.sessions[f"C{hid:02d}"] = self.active.pop(hid).last_seen

        return out

    def _wrap(self, identity: HandIdentity, ts: float) -> TrackedHand:
        return TrackedHand(
            hand_id=identity.hand_id,
            customer_id=identity.customer_id,
            session_id=self.session_id,
            box=identity.box,
            score=identity.score,
            first_seen=identity.first_seen,
            last_seen=identity.last_seen,
        )

    def expire(self, ts: float | None = None) -> None:
        ts = ts or time.time()
        for hid in list(self.active.keys()):
            if (ts - self.active[hid].last_seen) > self.idle_seconds:
                self.sessions[f"C{hid:02d}"] = self.active.pop(hid).last_seen

    def snapshot(self) -> list[dict]:
        return [
            {
                "hand_id": h.hand_id,
                "customer_id": h.customer_id,
                "session_id": h.session_id,
                "box": h.box.as_list(),
                "score": round(h.score, 3),
                "hits": h.hits,
                "age_s": round(h.last_seen - h.first_seen, 2),
            }
            for h in self.active.values()
        ]