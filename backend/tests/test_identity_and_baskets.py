"""Stable product identity, basket tracking, and occlusion-tolerant basket entry.

Covers the identity churn visible in the ledger: a product whose ByteTrack id
kept changing (#3 -> #4 -> #5 ...) must stay a single product_id.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.appearance import Descriptor, appearance_score, describe  # noqa: E402
from app.baskets import ROI_ID_BASE, BasketTracker  # noqa: E402
from app.config import ThresholdSettings  # noqa: E402
from app.detection import RawDetection  # noqa: E402
from app.geometry import BBox  # noqa: E402
from app.interaction import (  # noqa: E402
    EventType,
    InteractionEngine,
    ProductState,
)
from app.registry import ProductRegistry  # noqa: E402
from app.tracking import ByteTracker  # noqa: E402

T = ThresholdSettings()
FRAME = (960, 720)


def paint(box: tuple[float, float, float, float], color: tuple[int, int, int],
         size: tuple[int, int] = FRAME) -> np.ndarray:
    """A frame with a solid product-coloured rectangle at `box`."""
    frame = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    x1, y1, x2, y2 = (int(v) for v in box)
    frame[y1:y2, x1:x2] = color
    return frame


# ------------------------------------------------------------------ appearance
def test_descriptor_is_stable_for_the_same_object():
    frame = paint((300, 200, 380, 320), (40, 60, 200))
    a = describe(frame, (300, 200, 380, 320))
    b = describe(frame.copy(), (302, 202, 382, 322))
    assert a.is_valid()
    assert appearance_score(a, b) > 0.9


def test_descriptor_separates_different_objects():
    red = describe(paint((300, 200, 380, 320), (30, 30, 220)), (300, 200, 380, 320))
    green = describe(paint((300, 200, 380, 320), (40, 200, 40)), (300, 200, 380, 320))
    assert appearance_score(red, green) < 0.5


def test_descriptor_tolerates_a_hand_covering_the_product():
    frame = paint((300, 200, 380, 320), (40, 60, 200))
    clean = describe(frame, (300, 200, 380, 320))
    occluded = frame.copy()
    occluded[240:280, 300:380] = (170, 190, 210)  # a hand across the middle
    dirty = describe(occluded, (300, 200, 380, 320))
    # the centre crop means some contamination, but identity survives
    assert appearance_score(clean, dirty) > 0.4


def test_descriptor_handles_a_zero_area_box():
    """A degenerate box must not crash or produce nonsense."""
    frame = np.zeros((720, 960, 3), dtype=np.uint8)
    d = describe(frame, (10, 10, 10, 10))
    assert d.rel_size < 1e-4  # clamped to a 1px box
    assert d.aspect == pytest.approx(1.0)
    assert 0.0 <= appearance_score(d, d) <= 1.0


# -------------------------------------------------------------------- registry
def _registry(**kw) -> ProductRegistry:
    return ProductRegistry("S-test", **kw)


def test_first_sighting_allocates_a_session_identity():
    reg = _registry()
    box = BBox(300, 200, 380, 320)
    frame = paint(box.to_xyxy(), (40, 60, 200))
    m = reg.resolve(3, "cell phone", box, describe(frame, box.to_xyxy()), 100.0, FRAME)
    assert m.evidence == "new"
    assert m.product_id == "cell_phone#1"
    assert not m.product_id.endswith(":3"), "identity must not be track-scoped"


def test_same_track_keeps_the_same_identity():
    reg = _registry()
    box = BBox(300, 200, 380, 320)
    frame = paint(box.to_xyxy(), (40, 60, 200))
    d = describe(frame, box.to_xyxy())
    first = reg.resolve(3, "cell phone", box, d, 100.0, FRAME)
    second = reg.resolve(3, "cell phone", box, d, 100.1, FRAME)
    assert second.product_id == first.product_id
    assert second.evidence == "continuing"


def test_identity_survives_a_track_id_change():
    """The churn from the ledger: #7 dies, #8 appears, same product_id."""
    reg = _registry()
    box = BBox(300, 200, 380, 320)
    frame = paint(box.to_xyxy(), (40, 60, 200))
    d = describe(frame, box.to_xyxy())

    first = reg.resolve(7, "cell phone", box, d, 100.0, FRAME)
    reg.mark_lost(first.product_id, box, ProductState.IN_HAND, 110.0)

    moved = BBox(320, 210, 400, 330)
    second = reg.resolve(8, "cell phone", moved, describe(frame, moved.to_xyxy()), 120.0, FRAME)

    assert second.evidence == "reassociated"
    assert second.product_id == first.product_id
    assert second.matched_previous_track == 7
    rec = reg.records[first.product_id]
    assert rec.track_ids == [7, 8]
    assert rec.reassociations == 1


def test_a_different_object_gets_a_new_identity():
    reg = _registry()
    red = BBox(300, 200, 380, 320)
    green = BBox(600, 200, 680, 320)
    frame_red = paint(red.to_xyxy(), (30, 30, 220))
    frame_green = paint(green.to_xyxy(), (40, 200, 40))

    a = reg.resolve(1, "cup", red, describe(frame_red, red.to_xyxy()), 100.0, FRAME)
    reg.mark_lost(a.product_id, red, ProductState.ON_SHELF, 105.0)
    b = reg.resolve(
        2, "cup", green, describe(frame_green, green.to_xyxy()), 110.0, FRAME
    )
    assert b.evidence == "new"
    assert b.product_id != a.product_id


def test_a_far_away_reappearance_is_not_reassociated():
    reg = _registry(max_reassociate_distance_px=120)
    box = BBox(100, 100, 180, 220)
    frame = paint(box.to_xyxy(), (40, 60, 200))
    a = reg.resolve(1, "cup", box, describe(frame, box.to_xyxy()), 100.0, FRAME)
    reg.mark_lost(a.product_id, box, ProductState.ON_SHELF, 105.0)

    far = BBox(800, 550, 880, 670)
    frame2 = paint(far.to_xyxy(), (40, 60, 200))
    b = reg.resolve(2, "cup", far, describe(frame2, far.to_xyxy()), 110.0, FRAME)
    assert b.evidence == "new"


def test_identity_is_forgotten_after_the_hold_window():
    reg = _registry(identity_hold_seconds=10.0)
    box = BBox(300, 200, 380, 320)
    frame = paint(box.to_xyxy(), (40, 60, 200))
    a = reg.resolve(1, "cup", box, describe(frame, box.to_xyxy()), 100.0, FRAME)
    reg.mark_lost(a.product_id, box, ProductState.ON_SHELF, 105.0)

    later = BBox(315, 205, 395, 325)
    b = reg.resolve(
        2, "cup", later, describe(frame, later.to_xyxy()), 130.0, FRAME
    )  # 25s later > 10s hold
    assert b.evidence == "new"


def test_in_basket_history_strongly_favours_reassociation():
    reg = _registry()
    shelf = BBox(300, 200, 380, 320)
    basket = BBox(700, 450, 780, 570)
    frame = paint(shelf.to_xyxy(), (40, 60, 200))
    a = reg.resolve(
        1, "bottle", shelf, describe(frame, shelf.to_xyxy()), 100.0, FRAME
    )
    reg.mark_lost(a.product_id, shelf, ProductState.IN_BASKET, 110.0)

    frame_b = paint(basket.to_xyxy(), (40, 60, 200))
    b = reg.resolve(
        2, "bottle", basket, describe(frame_b, basket.to_xyxy()), 120.0, FRAME
    )
    assert b.evidence == "reassociated"
    assert b.product_id == a.product_id
    assert b.detail["lost_state"] == "IN_BASKET"


# -------------------------------------------------------------------- baskets
def test_basket_region_gets_one_stable_id_for_the_session():
    tracker = BasketTracker()
    roi = BBox(700, 450, 900, 650)
    ids = {tracker.update([], roi, 100.0 + i * 0.05)[1] for i in range(20)}
    assert len(ids) == 1
    assert ids.pop() >= ROI_ID_BASE


def test_detected_basket_class_beats_the_drawn_region():
    tracker = BasketTracker()
    dets = [RawDetection("basket", BBox(700, 450, 880, 640), 0.9, "basket")]
    zone, bid, source = tracker.update(dets, BBox(0, 0, 100, 100), 100.0)
    assert source == "yolo"
    assert bid is not None and bid < ROI_ID_BASE
    assert zone == BBox(700, 450, 880, 640)


def test_basket_keeps_its_track_id_across_frames():
    tracker = BasketTracker()
    ids = set()
    for i in range(12):
        dets = [RawDetection("basket", BBox(700 + i * 2, 450, 880 + i * 2, 640), 0.9, "basket")]
        ids.add(tracker.update(dets, None, 100.0 + i * 0.05)[1])
    assert len(ids) == 1


def test_basket_tracks_contents():
    tracker = BasketTracker()
    roi = BBox(700, 450, 900, 650)
    _, bid, _ = tracker.update([], roi, 100.0)
    tracker.add_contents(bid, "bottle#1")
    tracker.add_contents(bid, "bottle#1")  # idempotent
    tracker.add_contents(bid, "cup#2")
    ident = tracker.identities[bid]
    assert ident.contents == ["bottle#1", "cup#2"]


def test_no_basket_anywhere_yields_nothing():
    tracker = BasketTracker()
    assert tracker.update([], None, 100.0) == (None, None, "none")


# ----------------------------------------------- occlusion into the basket
def _engine():
    return InteractionEngine(T, session_id="S-test")


def _advance(engine, frames: int, box: BBox, hand=None, basket=None, base=0.0, start=0):
    events = []
    for i in range(frames):
        events.extend(
            engine.update(
                frame=start + i,
                ts=base + i * 0.05,
                products=[(1, "bottle#1", "bottle", box, 0.9)],
                hands=hand or [],
                basket_zone=basket,
                basket_track_id=42 if basket else None,
            )
        )
    return events


def test_occlusion_inside_the_basket_is_recorded_as_inferred():
    engine = _engine()
    basket = BBox(700, 450, 900, 650)
    _advance(engine, 16, BBox(300, 200, 380, 320))  # settle on the shelf
    _advance(engine, 6, BBox(500, 250, 580, 370), hand=[(1, __import__("app.hands", fromlist=["HandBox"]).HandBox(BBox(490, 240, 590, 380), 0.9))], base=10.0, start=100)
    assert engine.tracks[1].state is ProductState.IN_HAND

    # it was overlapping the basket, then disappears (occluded inside it)
    _advance(engine, 3, BBox(740, 470, 820, 590), basket=basket, base=20.0, start=200)
    assert engine.tracks[1].ever_overlapped_basket is True

    events: list[Any] = []
    for i in range(T.max_missed_frames):
        events.extend(
            engine.update(
                frame=300 + i,
                ts=30.0 + i * 0.05,
                products=[],
                hands=[],
                basket_zone=basket,
                basket_track_id=42,
            )
        )

    kinds = [e.type for e in events]
    assert EventType.PLACED_IN_BASKET in kinds
    assert EventType.TRACK_LOST not in kinds, "a product in the basket is not lost"

    placed = [e for e in events if e.type is EventType.PLACED_IN_BASKET][0]
    assert placed.inferred is True
    assert placed.basket_track_id == 42
    assert placed.meta["occluded"] is True


def test_inferred_entry_can_be_disabled():
    t = ThresholdSettings(infer_basket_on_occlusion=False)
    engine = InteractionEngine(t, session_id="S-test")
    basket = BBox(700, 450, 900, 650)
    _advance(engine, 16, BBox(300, 200, 380, 320))
    _advance(engine, 6, BBox(500, 250, 580, 370),
             hand=[(1, __import__("app.hands", fromlist=["HandBox"]).HandBox(BBox(490, 240, 590, 380), 0.9))],
             base=10.0, start=100)
    _advance(engine, 3, BBox(740, 470, 820, 590), basket=basket, base=20.0, start=200)

    events = []
    for i in range(T.max_missed_frames):
        events.extend(
            engine.update(frame=300 + i, ts=30.0 + i * 0.05, products=[], hands=[],
                          basket_zone=basket, basket_track_id=42)
        )
    kinds = [e.type for e in events]
    assert EventType.PLACED_IN_BASKET not in kinds
    assert EventType.TRACK_LOST in kinds


def test_a_product_that_vanishes_on_the_shelf_is_still_lost():
    engine = _engine()
    _advance(engine, 16, BBox(300, 200, 380, 320))
    events = []
    for i in range(T.max_missed_frames):
        events.extend(
            engine.update(frame=300 + i, ts=30.0 + i * 0.05, products=[], hands=[],
                          basket_zone=None)
        )
    kinds = [e.type for e in events]
    assert EventType.TRACK_LOST in kinds
    assert EventType.PLACED_IN_BASKET not in kinds


# ------------------------------------------------- engine revives an identity
def test_engine_revives_state_for_a_returning_product_id():
    engine = _engine()
    _advance(engine, 16, BBox(300, 200, 380, 320))
    settled = engine.tracks[1]
    assert settled.anchor_confirmed is True
    anchor = settled.anchor

    # let it expire
    for i in range(T.max_missed_frames):
        engine.update(frame=100 + i, ts=50.0 + i * 0.05, products=[], hands=[],
                      basket_zone=None)
    assert 1 not in engine.tracks

    # a new track id for the SAME product_id comes back
    events = []
    for i in range(3):
        events.extend(
            engine.update(
                frame=300 + i,
                ts=80.0 + i * 0.05,
                products=[(99, "bottle#1", "bottle", BBox(305, 202, 385, 322), 0.9)],
                hands=[],
                basket_zone=None,
            )
        )
    revived = engine.tracks[99]
    assert revived.product_id == "bottle#1"
    assert revived.anchor == anchor, "state must carry over, not restart"
    assert revived.first_seen == settled.first_seen


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))