"""Product interaction state machine.

Implements exactly the transitions described in ``refernces/surveil.docx``:

    ON_SHELF -> LIFTING -> IN_HAND -> RETURNING -> ON_SHELF     (pickup + put back)
    ON_SHELF -> LIFTING -> IN_HAND -> IN_BASKET                 (pickup + basket)
    any      -> LOST                                            (track expires)

    ON_SHELF  first detection saves the box as the shelf anchor; the anchor is
              re-learned while the product is still for ~15 settling frames.
    LIFTING   hand touching AND displaced >= 60px from the anchor.
    IN_HAND   the LIFTING condition holds for 5 consecutive frames -> PICKED_UP.
    RETURNING hand no longer touching AND no longer displaced.
    ON_SHELF  the RETURNING condition holds for 5 consecutive frames -> PUT_BACK.
    IN_BASKET >=50% of the box inside the basket zone for 4 frames -> PLACED_IN_BASKET.
    LOST      the track has been missing for 30 frames.

A TOUCH event is emitted for a hand contact that never displaces the product,
so the ledger speaks the same language as the RetailAction dataset
(TAKE / PUT / TOUCH).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .config import ThresholdSettings
from .geometry import BBox, center_distance, expand, intersection_over_min, overlap_ratio
from .hands import HandBox


class ProductState(str, Enum):
    ON_SHELF = "ON_SHELF"
    LIFTING = "LIFTING"
    IN_HAND = "IN_HAND"
    RETURNING = "RETURNING"
    IN_BASKET = "IN_BASKET"
    LOST = "LOST"


class EventType(str, Enum):
    TOUCH = "TOUCH"
    PICKED_UP = "PICKED_UP"
    PUT_BACK = "PUT_BACK"
    PLACED_IN_BASKET = "PLACED_IN_BASKET"
    CHECKED_OUT = "CHECKED_OUT"
    TRACK_LOST = "TRACK_LOST"
    ALERT_RAISED = "ALERT_RAISED"


@dataclass
class InteractionEvent:
    type: EventType
    ts: float
    product_id: str
    product_name: str
    track_id: int
    confidence: float
    bbox: BBox
    state: ProductState
    hand_id: int | None = None
    session_id: str | None = None
    dwell_ms: int = 0
    basket_track_id: int | None = None
    inferred: bool = False
    reassociated_from: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProductTrack:
    track_id: int
    product_id: str
    product_name: str
    state: ProductState = ProductState.ON_SHELF
    box: BBox | None = None
    prev_box: BBox | None = None
    anchor: BBox | None = None
    anchor_confirmed: bool = False
    settle_frames: int = 0
    score: float = 0.0
    first_seen: float = 0.0
    last_seen: float = 0.0
    state_since: float = 0.0

    # counters
    lift_frames: int = 0
    return_frames: int = 0
    basket_frames: int = 0
    touch_frames: int = 0
    missed_frames: int = 0
    touch_emitted: bool = False

    # context
    displaced: bool = False
    touched: bool = False
    hand_id: int | None = None
    session_id: str | None = None
    displacement_px: float = 0.0
    basket_overlap: float = 0.0
    on_shelf_since: float = 0.0
    picked_up_at: float | None = None

    # basket relationship + occlusion handling
    basket_track_id: int | None = None
    ever_overlapped_basket: bool = False
    last_basket_overlap_ts: float | None = None
    last_basket_track_id: int | None = None
    reassociated_from: int | None = None
    inferred_basket_entry: bool = False

    # Detection status. A coasting track is still owned by the tracker but was
    # not seen by the detector this frame; its box is the Kalman prediction, so
    # it must not drive geometry or confirm an interaction.
    coasting: bool = False
    coasting_frames: int = 0
    last_observed_ts: float = 0.0

    def set_state(self, state: ProductState, ts: float) -> None:
        if state is self.state:
            return
        self.state = state
        self.state_since = ts


class InteractionEngine:
    def __init__(self, thresholds: ThresholdSettings, session_id: str) -> None:
        self.t = thresholds
        self.session_id = session_id
        self.tracks: dict[int, ProductTrack] = {}
        self.finished: list[ProductTrack] = []

    # ------------------------------------------------------------------ utils
    def reset(self) -> None:
        self.tracks.clear()
        self.finished.clear()

    def _touching(self, box: BBox, hands: list[tuple[int, HandBox]]) -> tuple[bool, int | None]:
        """True when a hand overlaps (or sits within hand_touch_px of) the box."""
        padded = expand(box, self.t.hand_touch_px)
        best_hand: int | None = None
        best_score = 0.0
        for hand_id, hand in hands:
            overlap = intersection_over_min(padded, hand.bbox)
            gap_ok = center_distance(hand.bbox, box) <= self.t.hand_touch_px * 1.5
            if overlap >= self.t.hand_touch_min_overlap or (gap_ok and overlap > 0.0):
                if overlap + hand.score * 1e-3 > best_score:
                    best_score = overlap + hand.score * 1e-3
                    best_hand = hand_id
        return best_hand is not None, best_hand

    def _in_basket(self, box: BBox, basket_zone: BBox | None) -> float:
        if basket_zone is None:
            return 0.0
        return overlap_ratio(box, basket_zone)

    # ----------------------------------------------------------------- update
    def update(
        self,
        frame: int,
        ts: float,
        products: list[tuple],
        hands: list[tuple[int, HandBox]],
        basket_zone: BBox | None,
        basket_track_id: int | None = None,
    ) -> list[InteractionEvent]:
        """Advance the state machine one frame.

        `products` entries are `(track_id, product_id, product_name, box, score)`
        or the 6-tuple form `(..., score, observed)`. The 5-tuple form means
        observed, so existing callers keep their behaviour.

        A track reported as *not* observed is coasting: the tracker still owns
        it but the detector did not see it this frame. Such a track is kept alive
        and keeps its state, but its predicted box is never used to drive
        geometry and it can never confirm an event. Only observed detections
        count towards `missed_frames` reset, so a product that is coasting
        through an occlusion ages out on the same schedule as before.
        """
        events: list[InteractionEvent] = []

        seen: set[int] = set()
        for entry in products:
            if len(entry) == 5:
                track_id, product_id, product_name, box, score = entry
                observed = True
            else:
                track_id, product_id, product_name, box, score, observed = entry

            seen.add(track_id)
            track = self.tracks.get(track_id)

            if track is None:
                revived = self._revive(product_id)
                if revived is not None:
                    # same physical product, new ByteTrack id after a long
                    # occlusion - carry the state over instead of starting fresh
                    revived.track_id = track_id
                    revived.box = box
                    revived.prev_box = box
                    revived.missed_frames = 0
                    revived.coasting_frames = 0
                    revived.coasting = not observed
                    revived.score = score
                    revived.last_seen = ts
                    if observed:
                        revived.last_observed_ts = ts
                    self.tracks[track_id] = revived
                    self.finished = [t for t in self.finished if t.product_id != product_id]
                    events.extend(self._resumed(revived, ts))
                    track = revived
                else:
                    track = ProductTrack(
                        track_id=track_id,
                        product_id=product_id,
                        product_name=product_name,
                        first_seen=ts,
                        state_since=ts,
                        on_shelf_since=ts,
                    )
                    track.anchor = box
                    self.tracks[track_id] = track

            track.score = score
            track.last_seen = ts

            # --- coasting: hold state, trust nothing ------------------------
            if not observed:
                track.coasting = True
                track.coasting_frames += 1
                continue

            track.coasting = False
            track.coasting_frames = 0
            track.last_observed_ts = ts
            track.prev_box = track.box
            track.box = box
            track.missed_frames = 0

            # --- signals ---------------------------------------------------
            track.touched, hand_id = self._touching(box, hands)
            if hand_id is not None:
                track.hand_id = hand_id
                track.session_id = self.session_id
            track.basket_overlap = self._in_basket(box, basket_zone)
            track.basket_track_id = basket_track_id
            if track.basket_overlap > 0.0:
                track.ever_overlapped_basket = True
                track.last_basket_overlap_ts = ts
                track.last_basket_track_id = basket_track_id
            track.displacement_px = (
                center_distance(box, track.anchor) if track.anchor is not None else 0.0
            )
            track.displaced = track.displacement_px >= self.t.shelf_displacement_px

            events.extend(self._transition(track, ts))

        # --- expire tracks the detector is not currently reporting ----------
        for track_id, track in list(self.tracks.items()):
            if track_id in seen and not track.coasting:
                continue  # observed this frame, missed_frames already reset
            track.missed_frames += 1
            if track.missed_frames >= self.t.max_missed_frames:
                events.extend(self._expire(track, ts))

        return events

    # ------------------------------------------------------------- re-identity
    def _revive(self, product_id: str) -> ProductTrack | None:
        """Recover the state of a recently-lost product with the same identity.

        Keyed on `product_id` - the registry-resolved identity - so revival works
        whenever the identity layer recovered the product, whether the track id
        changed or not. A revived product is a genuinely new observation, so it
        does not depend on a freshly minted identity ever appearing.

        A track that expired into LOST is reset to ON_SHELF but keeps its shelf
        anchor: it is the same object, we know where it lives. Counts that were
        mid-transition are cleared so confirmation cannot be inherited from an
        absence.
        """
        candidates = [t for t in self.finished if t.product_id == product_id]
        if not candidates:
            return None
        track = max(candidates, key=lambda t: t.last_seen)

        if track.state is ProductState.LOST:
            track.state = ProductState.ON_SHELF
            track.state_since = track.last_seen
            track.lift_frames = 0
            track.return_frames = 0
            track.basket_frames = 0
            track.touch_frames = 0
            track.touch_emitted = False
            track.displaced = False
            track.displacement_px = 0.0
            track.missed_frames = 0
            track.coasting_frames = 0
            track.coasting = False
            track.anchor_confirmed = False
            track.settle_frames = 0
            track.picked_up_at = None

        # Bound the revival pool: identities the registry can still recover are
        # finite per session, so keeping every expired track forever is waste.
        if len(self.finished) > 32:
            self.finished = self.finished[-32:]
        return track

    def _resumed(self, track: ProductTrack, ts: float) -> list[InteractionEvent]:
        """Emit nothing, but leave a breadcrumb that the identity was resumed."""
        track.state_since = ts
        return []

    # ------------------------------------------------------------- transitions
    def _transition(self, track: ProductTrack, ts: float) -> list[InteractionEvent]:
        out: list[InteractionEvent] = []
        t = self.t

        if track.state is ProductState.ON_SHELF:
            # Learn the shelf anchor from *frame-to-frame* movement while the
            # product sits still and untouched. Using distance-from-anchor here
            # would accumulate detection jitter until it always exceeded the
            # settle threshold, so the anchor would never confirm.
            moved_little = (
                track.prev_box is None
                or center_distance(track.box, track.prev_box) <= t.settle_motion_px
            )
            if not track.touched and moved_little:
                track.settle_frames += 1
                if track.settle_frames >= t.settle_frames:
                    track.anchor = track.box
                    track.anchor_confirmed = True
            else:
                track.settle_frames = 0

            track.basket_frames = 0
            track.return_frames = 0
            track.lift_frames = 0

            if track.touched:
                track.touch_frames += 1
                if track.touch_frames >= t.touch_emit_frames and not track.touch_emitted:
                    track.touch_emitted = True
                    out.append(self._event(track, ts, EventType.TOUCH))
            else:
                track.touch_frames = 0
                track.touch_emitted = False

            if track.touched and track.displaced:
                track.lift_frames = 1
                track.set_state(ProductState.LIFTING, ts)
            return out

        if track.state is ProductState.LIFTING:
            if track.touched and track.displaced:
                track.lift_frames += 1
                if track.lift_frames >= t.lift_confirm_frames:
                    track.set_state(ProductState.IN_HAND, ts)
                    track.picked_up_at = ts
                    track.touch_emitted = False
                    out.append(self._event(track, ts, EventType.PICKED_UP, state_from="LIFTING"))
            else:
                # false alarm - fall back to ON_SHELF
                track.lift_frames = 0
                track.set_state(ProductState.ON_SHELF, ts)
                track.on_shelf_since = ts
            return out

        if track.state is ProductState.IN_HAND:
            track.lift_frames = 0
            if track.basket_overlap >= t.basket_overlap_ratio:
                track.basket_frames += 1
                if track.basket_frames >= t.basket_confirm_frames:
                    track.set_state(ProductState.IN_BASKET, ts)
                    out.append(
                        self._event(track, ts, EventType.PLACED_IN_BASKET, state_from="IN_HAND")
                    )
            else:
                track.basket_frames = 0
                if not track.touched and not track.displaced:
                    track.return_frames = 0
                    track.set_state(ProductState.RETURNING, ts)
            return out

        if track.state is ProductState.RETURNING:
            if not track.touched and not track.displaced:
                track.return_frames += 1
                if track.return_frames >= t.return_confirm_frames:
                    track.set_state(ProductState.ON_SHELF, ts)
                    track.on_shelf_since = ts
                    # the product is back where it was put down; let the anchor
                    # re-confirm naturally now that we are back on the shelf
                    track.anchor = track.box
                    track.anchor_confirmed = False
                    track.settle_frames = 0
                    track.touch_emitted = False
                    track.basket_frames = 0
                    track.picked_up_at = None
                    out.append(self._event(track, ts, EventType.PUT_BACK, state_from="RETURNING"))
            else:
                track.return_frames = 0
                track.set_state(ProductState.IN_HAND, ts)
            return out

        if track.state is ProductState.IN_BASKET:
            # Only the owner (dashboard) moves a product out of IN_BASKET via
            # CHECKED_OUT. If it physically leaves the basket, we follow it back
            # into the hand rather than silently dropping the track.
            if track.basket_overlap < t.basket_overlap_ratio:
                track.set_state(ProductState.IN_HAND, ts)
                track.basket_frames = 0
            return out

        return out

    def _expire(self, track: ProductTrack, ts: float) -> list[InteractionEvent]:
        out: list[InteractionEvent] = []
        prior_state = track.state

        # A product that was IN_HAND and had just been overlapping the basket is
        # very likely inside it now, hidden by its own contents or the basket rim.
        # The disappearance is NOT the proof - the history is. Record the event
        # as inferred so the owner can tell the two apart.
        if (
            not track.inferred_basket_entry
            and prior_state is ProductState.IN_HAND
            and track.ever_overlapped_basket
            and self.t.infer_basket_on_occlusion
        ):
            track.set_state(ProductState.IN_BASKET, ts)
            track.inferred_basket_entry = True
            out.append(
                self._event(
                    track,
                    ts,
                    EventType.PLACED_IN_BASKET,
                    state_from="IN_HAND",
                    inferred=True,
                    occluded=True,
                    evidence="was IN_HAND and overlapping the basket before being occluded",
                )
            )

        track.set_state(ProductState.LOST, ts)
        # The product record survives in `finished` so the registry can
        # re-associate a later detection onto the same product_id.
        #
        # If the product's final resting place was the basket it is NOT lost -
        # it is exactly where the owner expects it - so no TRACK_LOST is
        # emitted. Otherwise the track genuinely vanished.
        resting_in_basket = track.inferred_basket_entry or prior_state is ProductState.IN_BASKET
        if resting_in_basket:
            track.set_state(ProductState.IN_BASKET, ts)
        elif self.t.lost_emit_event and self.t.mark_lost_state:
            out.append(self._event(track, ts, EventType.TRACK_LOST, missed=track.missed_frames))
        track.coasting = False
        track.coasting_frames = 0
        self.tracks.pop(track.track_id, None)
        self.finished.append(track)
        return out

    # ------------------------------------------------------------------ events
    def _event(
        self,
        track: ProductTrack,
        ts: float,
        event_type: EventType,
        state_from: str | None = None,
        **meta: Any,
    ) -> InteractionEvent:
        dwell = int(max(0.0, ts - track.first_seen) * 1000)
        payload = {
            "anchor": track.anchor.as_list() if track.anchor else None,
            "displacement_px": round(track.displacement_px, 1),
            "displaced": track.displaced,
            "basket_overlap": round(track.basket_overlap, 3),
            "settle_frames": track.settle_frames,
            "frames_in_state": track.lift_frames or track.return_frames or track.basket_frames,
        }
        if state_from:
            payload["state_from"] = state_from
        payload.update(meta)
        return InteractionEvent(
            type=event_type,
            ts=ts,
            product_id=track.product_id,
            product_name=track.product_name,
            track_id=track.track_id,
            confidence=round(track.score, 4),
            bbox=track.box or BBox(0, 0, 0, 0),
            state=track.state,
            hand_id=track.hand_id,
            session_id=track.session_id or self.session_id,
            dwell_ms=dwell,
            basket_track_id=track.last_basket_track_id or track.basket_track_id,
            inferred=bool(meta.get("inferred", False)),
            meta=payload,
        )

    # ---------------------------------------------------------------- snapshot
    def snapshot(self, ts: float) -> list[dict[str, Any]]:
        out = []
        for track in sorted(self.tracks.values(), key=lambda t: t.track_id):
            out.append(
                {
                    "track_id": track.track_id,
                    "product_id": track.product_id,
                    "product_name": track.product_name,
                    "state": track.state.value,
                    "coasting": track.coasting,
                    "coasting_frames": track.coasting_frames,
                    "last_observed_ts": round(track.last_observed_ts, 3),
                    "anchor": track.anchor.as_list() if track.anchor else None,
                    "anchor_confirmed": track.anchor_confirmed,
                    "settle_frames": track.settle_frames,
                    "box": track.box.as_list() if track.box else None,
                    "score": round(track.score, 3),
                    "touching": track.touched,
                    "displaced": track.displaced,
                    "displacement_px": round(track.displacement_px, 1),
                    "basket_overlap": round(track.basket_overlap, 3),
                    "hand_id": track.hand_id,
                    "session_id": track.session_id or self.session_id,
                    "lift_frames": track.lift_frames,
                    "return_frames": track.return_frames,
                    "basket_frames": track.basket_frames,
                    "missed_frames": track.missed_frames,
                    "age_s": round(ts - track.first_seen, 2),
                    "in_state_s": round(ts - track.state_since, 2),
                    "picked_up_at": track.picked_up_at,
                }
            )
        return out