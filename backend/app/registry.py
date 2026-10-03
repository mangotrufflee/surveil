"""Stable product identity, separated from tracking identity.

ByteTrack's ``track_id`` is a *temporary, camera-local* label. It is minted anew
whenever a product is occluded long enough for the old track to expire, so
``cell phone #7`` becomes ``cell phone #8`` for what is physically the same
object. Writing that straight into the ledger is what produced the churn in the
event table - and the old ``product_id = f"{class}:{track_id}"`` made it worse by
minting a brand-new *product* every time.

This module owns the distinction:

    product_id    what the object is        e.g. ``cell_phone#1``  (session-scoped, stable)
    track_id      which detection run        e.g. ``7``            (temporary)

A new track is matched against recently-vocabulary products using three signals,
in descending order of reliability:

  1. **interaction history** - a product that reached ``IN_BASKET`` and then went
     dark is overwhelmingly likely to be the thing now sitting in the basket;
  2. **spatial continuity** - where did it disappear, and where did this appear;
  3. **appearance** - colour histogram + shape, from :mod:`app.appearance`.

Only if all three fail is a genuinely new ``product_id`` allocated.
"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from typing import Any

from .appearance import Descriptor, appearance_score
from .geometry import BBox, center_distance
from .interaction import ProductState


@dataclass
class ProductRecord:
    """One physical product, independent of which track is currently seeing it."""

    product_id: str
    product_name: str
    class_name: str
    first_seen: float
    last_seen: float
    last_box: BBox | None = None
    descriptor: Descriptor | None = None
    current_track_id: int | None = None
    state: ProductState = ProductState.ON_SHELF
    hand_id: int | None = None
    lost_at: float | None = None
    lost_box: BBox | None = None
    lost_state: ProductState | None = None
    lost_track_id: int | None = None
    track_ids: list[int] = field(default_factory=list)
    reassociations: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "product_name": self.product_name,
            "state": self.state.value,
            "current_track_id": self.current_track_id,
            "track_ids": list(self.track_ids),
            "reassociations": self.reassociations,
            "hand_id": self.hand_id,
            "first_seen": round(self.first_seen, 3),
            "last_seen": round(self.last_seen, 3),
            "box": self.last_box.as_list() if self.last_box else None,
        }


@dataclass
class MatchResult:
    product_id: str
    matched_previous_track: int | None = None
    score: float = 0.0
    evidence: str = "new"
    detail: dict[str, Any] = field(default_factory=dict)


class ProductRegistry:
    """Assigns and recovers stable product identities within one session."""

    def __init__(
        self,
        session_id: str,
        identity_hold_seconds: float = 45.0,
        max_reassociate_distance_px: float = 260.0,
        min_score: float = 0.42,
    ) -> None:
        self.session_id = session_id
        self.identity_hold_seconds = identity_hold_seconds
        self.max_reassociate_distance_px = max_reassociate_distance_px
        self.min_score = min_score
        self.records: dict[str, ProductRecord] = {}
        self._counter = itertools.count(1)
        self._class_counter: dict[str, int] = {}

    # ------------------------------------------------------------- internals
    def _new_product_id(self, class_name: str) -> str:
        slug = "".join(c if c.isalnum() else "_" for c in class_name).strip("_").lower() or "item"
        n = self._class_counter.get(slug, 0) + 1
        self._class_counter[slug] = n
        return f"{slug}#{n}"

    def _candidates(self, ts: float) -> list[ProductRecord]:
        """Records available for re-association (dark, but still within the window)."""
        out = []
        for rec in self.records.values():
            if rec.lost_at is None:
                continue
            if (ts - rec.lost_at) > self.identity_hold_seconds:
                continue
            out.append(rec)
        return out

    # ---------------------------------------------------------------- public
    def resolve(
        self,
        track_id: int,
        class_name: str,
        box: BBox,
        descriptor: Descriptor | None,
        ts: float,
        frame_size: tuple[int, int] | None = None,
    ) -> MatchResult:
        """Map a live ByteTrack id onto a stable product_id."""
        # already known and still being seen
        for rec in self.records.values():
            if rec.current_track_id == track_id:
                rec.last_seen = ts
                rec.last_box = box
                rec.state = rec.state
                if descriptor is not None and descriptor.is_valid():
                    rec.descriptor = descriptor
                return MatchResult(rec.product_id, track_id, 1.0, "continuing")

        best: tuple[float, ProductRecord] | None = None
        evidence = "new"
        detail: dict[str, Any] = {}

        for rec in self._candidates(ts):
            if rec.class_name != class_name:
                continue

            # --- signal 1: interaction history -----------------------------
            # A product that reached the basket and went dark is almost
            # certainly the one now sitting in there.
            history = 0.0
            if rec.lost_state is ProductState.IN_BASKET:
                history = 1.0
            elif rec.lost_state is ProductState.IN_HAND:
                history = 0.55
            elif rec.lost_state is ProductState.LIFTING:
                history = 0.35

            # --- signal 2: spatial continuity ------------------------------
            spatial = 0.0
            distance = float("inf")
            if rec.lost_box is not None:
                distance = center_distance(rec.lost_box, box)
                if frame_size:
                    diagonal = (frame_size[0] ** 2 + frame_size[1] ** 2) ** 0.5
                    spatial = max(0.0, 1.0 - distance / diagonal)
                # Distance is a soft penalty, not an absolute veto. Carrying a
                # product from the shelf to the basket routinely moves it further
                # than any sane gate, and interaction history is the stronger
                # signal - so a product that was last seen IN_BASKET is allowed
                # to reappear anywhere.
                if distance > self.max_reassociate_distance_px and history < 0.9:
                    continue

            # --- signal 3: appearance --------------------------------------
            appearance = 0.0
            if rec.descriptor is not None and descriptor is not None:
                appearance = appearance_score(rec.descriptor, descriptor)

            score = (
                0.40 * history
                + 0.35 * spatial
                + 0.25 * appearance
            )
            if score < self.min_score:
                continue
            if best is None or score > best[0]:
                best = (score, rec)
                evidence = "reassociated"
                detail = {
                    "history": round(history, 3),
                    "spatial": round(spatial, 3),
                    "appearance": round(appearance, 3),
                    "distance_px": round(distance, 1) if distance != float("inf") else None,
                    "lost_state": rec.lost_state.value if rec.lost_state else None,
                }

        if best is not None:
            rec = best[1]
            previous = rec.current_track_id or rec.lost_track_id
            rec.current_track_id = track_id
            rec.last_seen = ts
            rec.last_box = box
            rec.lost_at = None
            rec.lost_box = None
            rec.lost_state = None
            rec.lost_track_id = None
            rec.reassociations += 1
            if track_id not in rec.track_ids:
                rec.track_ids.append(track_id)
            if descriptor is not None and descriptor.is_valid():
                rec.descriptor = descriptor
            return MatchResult(rec.product_id, previous, best[0], evidence, detail)

        # genuinely new product
        pid = self._new_product_id(class_name)
        self.records[pid] = ProductRecord(
            product_id=pid,
            product_name=class_name,
            class_name=class_name,
            first_seen=ts,
            last_seen=ts,
            last_box=box,
            descriptor=descriptor,
            current_track_id=track_id,
            track_ids=[track_id],
        )
        return MatchResult(pid, None, 0.0, "new")

    def note_state(self, product_id: str, state: ProductState, box: BBox | None, hand_id: int | None) -> None:
        rec = self.records.get(product_id)
        if rec is None:
            return
        rec.state = state
        if box is not None:
            rec.last_box = box
        if hand_id is not None:
            rec.hand_id = hand_id

    def mark_lost(self, product_id: str, box: BBox | None, state: ProductState, ts: float) -> None:
        rec = self.records.get(product_id)
        if rec is None:
            return
        rec.lost_at = ts
        rec.lost_box = box
        rec.lost_state = state
        rec.lost_track_id = rec.current_track_id
        rec.current_track_id = None

    def product_id_for_track(self, track_id: int) -> str | None:
        for rec in self.records.values():
            if rec.current_track_id == track_id:
                return rec.product_id
        return None

    def snapshot(self) -> list[dict[str, Any]]:
        return [rec.as_dict() for rec in sorted(self.records.values(), key=lambda r: r.first_seen)]