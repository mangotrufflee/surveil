"""Stable product identity, separated from tracking identity.

ByteTrack's ``track_id`` is a *temporary, camera-local* label. It is minted anew
whenever an object is occluded long enough for the old track to expire, so
``cell phone #7`` becomes ``cell phone #8`` for what is physically the same
object. Writing that straight into the ledger is what produced the churn in the
event table - and the old ``product_id = f"{class}:{track_id}"`` made it worse by
minting a brand-new *product* every time.

This module owns the distinction:

    product_id    what the object is        e.g. ``cell_phone#1``  (session-scoped, stable)
    track_id      which detection run        e.g. ``7``            (temporary)

A changed ``track_id`` is **not** evidence of a new product. Recovery is layered,
most reliable first:

  0. **live binding** - this track id is already bound to a product; keep it.
  1. **same id returned** - the tracker gave this exact id back after a gap.
     ByteTrack had not actually lost the object, so the binding is restored
     with certainty rather than by scoring.
  2. **scored evidence** - interaction history, spatial continuity and
     appearance, in that order of reliability. Only if all fail is a genuinely
     new ``product_id`` allocated.

Two conservative rules keep this from merging distinct physical products:

  * a product that is *currently visible* (still bound to a live track) is never
    a re-association candidate - it cannot be the object that just appeared;
  * when the best and second-best candidates score within
    ``ambiguity_margin`` the match is ambiguous, and we refuse to merge. The new
    detection gets its own product_id and the uncertainty is reported.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

from .appearance import Descriptor, appearance_score
from .geometry import BBox, center_distance
from .interaction import ProductState

# How much credit a product's state at the moment it went dark gives the claim
# that a later detection is the same object.
#
# IN_BASKET is decisive: a product that reached the basket and then went dark is
# overwhelmingly likely to be the thing now sitting in the basket.
#
# ON_SHELF used to score 0.0, which combined with the distance gate meant a
# product that merely sat on the shelf while occluded was *never* re-identified.
# That was the dominant source of "the same phone shows up as a new product 20
# times": it is by far the most common way a track ends.
HISTORY_CREDIT: dict[ProductState, float] = {
    ProductState.IN_BASKET: 1.00,
    ProductState.IN_HAND: 0.55,
    ProductState.ON_SHELF: 0.45,
    ProductState.LIFTING: 0.35,
    ProductState.RETURNING: 0.30,
    ProductState.LOST: 0.20,
}

# At or above this interaction-history credit the spatial gate is bypassed: the
# product was demonstrably carried somewhere, so reappearing far away is expected.
HISTORY_GATE_BYPASS = 0.90

W_HISTORY = 0.40
W_SPATIAL = 0.35
W_APPEARANCE = 0.25


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
    # The most recent track id this product has been bound to, independent of
    # whether that binding is currently live. Binding lifetime is managed by
    # observe_tracks() and mark_lost() independently, so the "previous" track id
    # cannot be reconstructed from `current_track_id` alone.
    last_track_id: int | None = None
    track_ids: list[int] = field(default_factory=list)
    reassociations: int = 0
    # Times this product was the *runner-up* in an ambiguous match. Surfaced so
    # the owner can be told the system is unsure rather than being shown a
    # confident-looking wrong answer.
    ambiguous_matches: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "product_name": self.product_name,
            "state": self.state.value,
            "current_track_id": self.current_track_id,
            "track_ids": list(self.track_ids),
            "reassociations": self.reassociations,
            "hand_id": self.hand_id,
            "ambiguous_matches": self.ambiguous_matches,
            "identity_held": self.lost_at is not None,
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
    # True when a plausible alternative candidate scored almost as well and we
    # declined to merge. `product_id` is then a *new* identity, not a recovery.
    ambiguous: bool = False


class ProductRegistry:
    """Assigns and recovers stable product identities within one session."""

    def __init__(
        self,
        session_id: str,
        identity_hold_seconds: float = 300.0,
        max_reassociate_distance_px: float = 260.0,
        min_score: float = 0.42,
        ambiguity_margin: float = 0.08,
    ) -> None:
        self.session_id = session_id
        self.identity_hold_seconds = identity_hold_seconds
        self.max_reassociate_distance_px = max_reassociate_distance_px
        self.min_score = min_score
        self.ambiguity_margin = ambiguity_margin
        self.records: dict[str, ProductRecord] = {}
        self._class_counter: dict[str, int] = {}

    # ------------------------------------------------------------- internals
    def _new_product_id(self, class_name: str) -> str:
        slug = "".join(c if c.isalnum() else "_" for c in class_name).strip("_").lower() or "item"
        n = self._class_counter.get(slug, 0) + 1
        self._class_counter[slug] = n
        return f"{slug}#{n}"

    def _held(self, rec: ProductRecord, ts: float) -> bool:
        """True while this product's identity is still recoverable."""
        if rec.lost_at is None:
            return False
        return (ts - rec.lost_at) <= self.identity_hold_seconds

    def _candidates(self, ts: float) -> list[ProductRecord]:
        """Products available for re-association: not currently visible, still held.

        A record whose `current_track_id` is still set is being seen right now.
        It cannot also be the object that just appeared, so it is never offered
        as a candidate - this is what stops two simultaneous identical products
        from collapsing into one identity.
        """
        return [
            rec
            for rec in self.records.values()
            if self._held(rec, ts)
        ]

    def _bind(
        self,
        rec: ProductRecord,
        track_id: int,
        box: BBox,
        descriptor: Descriptor | None,
        ts: float,
        observed: bool,
    ) -> int | None:
        """Point this product at `track_id`; returns the id it was on before."""
        previous = rec.last_track_id
        rec.current_track_id = track_id
        rec.last_track_id = track_id
        rec.last_seen = ts
        rec.last_box = box
        rec.lost_at = None
        rec.lost_box = None
        rec.lost_state = None
        rec.lost_track_id = None
        if track_id not in rec.track_ids:
            rec.track_ids.append(track_id)
        # Only refresh appearance from a frame the detector actually saw: a
        # coasted box can be over an occluder, and writing that in would poison
        # the descriptor we later match against.
        if observed and descriptor is not None and descriptor.is_valid():
            rec.descriptor = descriptor
        if previous is not None and previous != track_id:
            rec.reassociations += 1
        return previous

    # ---------------------------------------------------------------- public
    def observe_tracks(self, present_track_ids: set[int], ts: float) -> list[str]:
        """Tell the registry which track ids the tracker currently owns.

        Includes coasting tracks: the tracker still holds the object, so the
        binding is still valid even though the detector cannot see it. A binding
        whose track id has disappeared is released so a later detection can be
        scored against it.

        Returns the product_ids whose binding was released.
        """
        released: list[str] = []
        for rec in self.records.values():
            if rec.current_track_id is None:
                continue
            if rec.current_track_id in present_track_ids:
                continue
            rec.lost_at = ts
            rec.lost_box = rec.last_box
            rec.lost_state = rec.state
            rec.lost_track_id = rec.current_track_id
            rec.current_track_id = None
            released.append(rec.product_id)
        return released

    def resolve(
        self,
        track_id: int,
        class_name: str,
        box: BBox,
        descriptor: Descriptor | None,
        ts: float,
        frame_size: tuple[int, int] | None = None,
        observed: bool = True,
    ) -> MatchResult:
        """Map a live ByteTrack id onto a stable product_id."""

        # --- signal 0: the binding is still live ---------------------------
        for rec in self.records.values():
            if rec.current_track_id == track_id:
                rec.last_seen = ts
                rec.last_box = box
                rec.last_track_id = track_id
                if observed and descriptor is not None and descriptor.is_valid():
                    rec.descriptor = descriptor
                return MatchResult(rec.product_id, track_id, 1.0, "continuing")

        # --- signal 1: this exact track id came back after a gap -------------
        # ByteTrack never really lost the object, so no scoring is needed.
        same_id = [
            rec
            for rec in self._candidates(ts)
            if rec.lost_track_id == track_id and rec.class_name == class_name
        ]
        if len(same_id) == 1:
            rec = same_id[0]
            previous = self._bind(rec, track_id, box, descriptor, ts, observed)
            return MatchResult(rec.product_id, previous, 1.0, "track_id_recovered")
        if len(same_id) > 1:
            for rec in same_id:
                rec.ambiguous_matches += 1

        # --- signal 2: scored evidence --------------------------------------
        scored: list[tuple[float, ProductRecord, dict[str, Any]]] = []
        for rec in self._candidates(ts):
            if rec.class_name != class_name:
                continue

            # --- interaction history ---------------------------------------
            history = HISTORY_CREDIT.get(rec.lost_state or ProductState.ON_SHELF, 0.20)

            # --- spatial continuity ----------------------------------------
            spatial = 0.0
            distance = float("inf")
            if rec.lost_box is not None:
                distance = center_distance(rec.lost_box, box)
                if frame_size:
                    diagonal = (frame_size[0] ** 2 + frame_size[1] ** 2) ** 0.5
                    spatial = max(0.0, 1.0 - distance / diagonal)
                # Distance is a soft penalty, not an absolute veto, but a shelf
                # product reappearing a long way away with no interaction history
                # is far more likely to be a different physical item.
                if distance > self.max_reassociate_distance_px and history < HISTORY_GATE_BYPASS:
                    continue

            # --- appearance --------------------------------------------------
            appearance = 0.0
            if rec.descriptor is not None and descriptor is not None:
                appearance = appearance_score(rec.descriptor, descriptor)

            score = W_HISTORY * history + W_SPATIAL * spatial + W_APPEARANCE * appearance
            if score < self.min_score:
                continue

            scored.append(
                (
                    score,
                    rec,
                    {
                        "history": round(history, 3),
                        "spatial": round(spatial, 3),
                        "appearance": round(appearance, 3),
                        "distance_px": round(distance, 1) if distance != float("inf") else None,
                        "lost_state": rec.lost_state.value if rec.lost_state else None,
                    },
                )
            )

        if scored:
            scored.sort(key=lambda row: row[0], reverse=True)
            best_score, best_rec, detail = scored[0]

            # Refuse to merge when a runner-up is almost as good. Two identical
            # products on one shelf are genuinely indistinguishable here, and
            # confidently picking one is worse than admitting we cannot tell.
            if len(scored) > 1:
                runner_score, runner_rec, _ = scored[1]
                if best_score - runner_score < self.ambiguity_margin:
                    runner_rec.ambiguous_matches += 1
                    best_rec.ambiguous_matches += 1
                    pid = self._create(class_name, track_id, box, descriptor, ts)
                    rec = self.records[pid]
                    rec.ambiguous_matches += 1
                    detail = {
                        **detail,
                        "reason": "ambiguous",
                        "best_score": round(best_score, 3),
                        "runner_up": runner_rec.product_id,
                        "runner_up_score": round(runner_score, 3),
                        "margin": round(self.ambiguity_margin, 3),
                    }
                    return MatchResult(pid, None, 0.0, "ambiguous", detail, ambiguous=True)

            previous = self._bind(best_rec, track_id, box, descriptor, ts, observed)
            return MatchResult(
                best_rec.product_id, previous, best_score, "reassociated", detail
            )

        # --- genuinely new product -----------------------------------------
        pid = self._create(class_name, track_id, box, descriptor, ts, observed)
        return MatchResult(pid, None, 0.0, "new")

    def _create(
        self,
        class_name: str,
        track_id: int,
        box: BBox,
        descriptor: Descriptor | None,
        ts: float,
        observed: bool = True,
    ) -> str:
        pid = self._new_product_id(class_name)
        self.records[pid] = ProductRecord(
            product_id=pid,
            product_name=class_name,
            class_name=class_name,
            first_seen=ts,
            last_seen=ts,
            last_box=box,
            descriptor=descriptor if observed else None,
            current_track_id=track_id,
            last_track_id=track_id,
            track_ids=[track_id],
        )
        return pid

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

    def expire(self, ts: float) -> list[str]:
        """Release identities past the hold window; report what was released."""
        gone = [rec.product_id for rec in self.records.values() if not self._held(rec, ts)]
        return gone

    def snapshot(self) -> list[dict[str, Any]]:
        return [rec.as_dict() for rec in sorted(self.records.values(), key=lambda r: r.first_seen)]