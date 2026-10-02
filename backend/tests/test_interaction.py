"""State-machine tests - no camera or model weights required.

    .venv\\Scripts\\python -m pytest tests -q
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import ThresholdSettings  # noqa: E402
from app.geometry import BBox, center_distance, overlap_ratio  # noqa: E402
from app.hands import HandBox  # noqa: E402
from app.interaction import (  # noqa: E402
    EventType,
    InteractionEngine,
    ProductState,
)

T = ThresholdSettings()
BASKET = BBox(700, 300, 900, 500)


def box_at(x: float, y: float = 400.0, w: float = 60.0, h: float = 80.0) -> BBox:
    return BBox(x, y, x + w, y + h)


def product(track_id: int, box: BBox, name: str = "bottle", score: float = 0.9):
    return (track_id, f"{name}:{track_id}", name, box, score)


def hands(*specs: tuple[int, BBox]):
    return [(hid, HandBox(bx, 0.9)) for hid, bx in specs]


def make_engine() -> InteractionEngine:
    return InteractionEngine(T, session_id="S-test")


def run(
    engine: InteractionEngine,
    frames: int,
    box: BBox,
    hand: list[tuple[int, HandBox]] | None = None,
    basket_zone: BBox | None = None,
    dt: float = 0.05,
):
    """Advance `frames` frames starting at a moving timestamp, returning all events."""
    events = []
    base = time.time()
    for i in range(frames):
        events.extend(
            engine.update(
                frame=i,
                ts=base + i * dt,
                products=[product(1, box)],
                hands=hand or [],
                basket_zone=basket_zone,
            )
        )
    return events


# --------------------------------------------------------------------- settling
def test_anchor_needs_settling_frames_before_interactions_count():
    engine = make_engine()
    run(engine, T.settle_frames - 1, box_at(100))
    assert engine.tracks[1].anchor_confirmed is False

    events = run(engine, 1, box_at(100))
    assert engine.tracks[1].anchor_confirmed is True
    # anchored but untouched -> no events
    assert events == []


def test_no_pickup_while_anchor_is_still_settling():
    engine = make_engine()
    # hand on the product and it jumps away, but before the anchor is confirmed
    events = run(engine, 5, box_at(100))
    run(engine, 1, box_at(400), hand=hands((1, box_at(380))))
    assert all(e.type is not EventType.PICKED_UP for e in events)


# ---------------------------------------------------------------------- lifting
def test_full_pickup_transition():
    engine = make_engine()
    run(engine, T.settle_frames, box_at(100))

    # 1) hand arrives, product still on the shelf -> TOUCH only
    events = run(engine, T.touch_emit_frames, box_at(100), hand=hands((1, box_at(90))))
    assert [e.type for e in events] == [EventType.TOUCH]
    assert engine.tracks[1].state is ProductState.ON_SHELF

    # 2) product lifted clear of the anchor -> PICKED_UP after the confirm frames
    events = run(engine, T.lift_confirm_frames, box_at(400), hand=hands((1, box_at(380))))
    assert [e.type for e in events] == [EventType.PICKED_UP]
    assert engine.tracks[1].state is ProductState.IN_HAND

    picked = [e for e in events if e.type is EventType.PICKED_UP][0]
    assert picked.meta["displacement_px"] >= T.shelf_displacement_px
    assert picked.meta["displaced"] is True
    assert picked.track_id == 1
    assert picked.session_id == "S-test"


def test_lifting_below_displacement_threshold_stays_on_shelf():
    engine = make_engine()
    run(engine, T.settle_frames, box_at(100))
    # moved 20px - well under the 60px shelf displacement
    events = run(engine, 20, box_at(120), hand=hands((1, box_at(110))))
    assert engine.tracks[1].state is ProductState.ON_SHELF
    assert all(e.type is not EventType.PICKED_UP for e in events)


def test_lifting_without_a_hand_never_confirms():
    engine = make_engine()
    run(engine, T.settle_frames, box_at(100))
    events = run(engine, 30, box_at(400))
    assert all(e.type is not EventType.PICKED_UP for e in events)
    assert engine.tracks[1].state is ProductState.ON_SHELF


def test_false_alarm_falls_back_to_on_shelf():
    engine = make_engine()
    run(engine, T.settle_frames, box_at(100))
    run(engine, T.lift_confirm_frames - 1, box_at(400), hand=hands((1, box_at(380))))
    assert engine.tracks[1].state is ProductState.LIFTING

    events = run(engine, 1, box_at(400))  # hand leaves before confirmation
    assert engine.tracks[1].state is ProductState.ON_SHELF
    assert all(e.type is not EventType.PICKED_UP for e in events)


# ---------------------------------------------------------------------- basket
def test_basket_placement():
    engine = make_engine()
    run(engine, T.settle_frames, box_at(100))
    run(engine, T.lift_confirm_frames, box_at(400), hand=hands((1, box_at(380))))

    in_basket = box_at(760)
    assert overlap_ratio(in_basket, BASKET) >= T.basket_overlap_ratio

    events = run(engine, T.basket_confirm_frames, in_basket, basket_zone=BASKET)
    assert [e.type for e in events] == [EventType.PLACED_IN_BASKET]
    assert engine.tracks[1].state is ProductState.IN_BASKET


def test_basket_needs_enough_overlap():
    engine = make_engine()
    run(engine, T.settle_frames, box_at(100))
    run(engine, T.lift_confirm_frames, box_at(400), hand=hands((1, box_at(380))))

    # only ~17% of the box is inside the basket
    partial = BBox(890, 320, 950, 400)
    assert overlap_ratio(partial, BASKET) < T.basket_overlap_ratio
    events = run(engine, 10, partial, basket_zone=BASKET)
    assert all(e.type is not EventType.PLACED_IN_BASKET for e in events)


def test_product_leaving_basket_returns_to_in_hand():
    engine = make_engine()
    run(engine, T.settle_frames, box_at(100))
    run(engine, T.lift_confirm_frames, box_at(400), hand=hands((1, box_at(380))))
    run(engine, T.basket_confirm_frames, box_at(760), basket_zone=BASKET)
    assert engine.tracks[1].state is ProductState.IN_BASKET

    run(engine, 1, box_at(300), basket_zone=BASKET)
    assert engine.tracks[1].state is ProductState.IN_HAND


# --------------------------------------------------------------------- returning
def test_put_back_transition_relearns_the_anchor():
    engine = make_engine()
    run(engine, T.settle_frames, box_at(100))
    run(engine, T.lift_confirm_frames, box_at(400), hand=hands((1, box_at(380))))
    assert engine.tracks[1].state is ProductState.IN_HAND

    events = run(engine, 1, box_at(100))  # back at the anchor, hand gone
    assert engine.tracks[1].state is ProductState.RETURNING

    events = run(engine, T.return_confirm_frames, box_at(100))
    assert [e.type for e in events] == [EventType.PUT_BACK]
    assert engine.tracks[1].state is ProductState.ON_SHELF
    # the anchor has been re-learned at the put-back position
    assert engine.tracks[1].anchor == box_at(100)


def test_returning_reverts_when_the_hand_comes_back():
    engine = make_engine()
    run(engine, T.settle_frames, box_at(100))
    run(engine, T.lift_confirm_frames, box_at(400), hand=hands((1, box_at(380))))
    run(engine, 1, box_at(100))
    assert engine.tracks[1].state is ProductState.RETURNING

    run(engine, 1, box_at(105), hand=hands((1, box_at(95))))
    assert engine.tracks[1].state is ProductState.IN_HAND


# ------------------------------------------------------------------------- lost
def test_track_expires_into_lost_after_max_missed_frames():
    engine = make_engine()
    run(engine, T.settle_frames, box_at(100))

    base = time.time()
    events = []
    for i in range(T.max_missed_frames):
        events.extend(
            engine.update(
                frame=100 + i,
                ts=base + 0.05 * i,
                products=[],  # detector stopped reporting the product
                hands=[],
                basket_zone=None,
            )
        )
    assert [e.type for e in events] == [EventType.TRACK_LOST]
    assert 1 not in engine.tracks
    assert engine.finished[-1].state is ProductState.LOST


# ------------------------------------------------------------------------ touch
def test_touch_is_emitted_once_per_contact():
    engine = make_engine()
    run(engine, T.settle_frames, box_at(100))

    events = run(engine, 10, box_at(100), hand=hands((1, box_at(90))))
    assert [e.type for e in events].count(EventType.TOUCH) == 1

    # hand leaves and comes back -> a second TOUCH
    run(engine, 1, box_at(100))
    events = run(engine, 5, box_at(100), hand=hands((1, box_at(90))))
    assert [e.type for e in events].count(EventType.TOUCH) == 1


def test_no_duplicate_touch_while_still_touching():
    engine = make_engine()
    run(engine, T.settle_frames, box_at(100))
    run(engine, T.touch_emit_frames, box_at(100), hand=hands((1, box_at(90))))
    for _ in range(3):
        events = run(engine, 5, box_at(100), hand=hands((1, box_at(90))))
        assert events == []


# ------------------------------------------------------------------- multi-item
def test_two_products_are_tracked_independently():
    engine = make_engine()
    base = time.time()
    for i in range(T.settle_frames + 1):
        engine.update(
            frame=i,
            ts=base + i * 0.05,
                products=[product(1, box_at(100)), product(2, box_at(300), name="box")],
            hands=[],
            basket_zone=None,
        )
    assert engine.tracks[1].anchor_confirmed and engine.tracks[2].anchor_confirmed

    events = []
    for i in range(T.lift_confirm_frames):
        events.extend(
            engine.update(
                frame=100 + i,
                ts=base + (100 + i) * 0.05,
                products=[product(1, box_at(400)), product(2, box_at(300))],
                hands=hands((1, box_at(380))),
                basket_zone=None,
            )
        )
    assert [e.type for e in events] == [EventType.PICKED_UP]
    assert events[0].product_name == "bottle"
    assert events[0].track_id == 1


# --------------------------------------------------------------- jitter
# A slow steady drift of 2px/frame plus +/-2px jitter. Every single frame-to-frame
# step stays well inside settle_motion_px, while the cumulative distance from the
# first sighting grows past it within a few frames.
JITTER = [(0, 0), (2, -2), (-2, 1), (1, 2), (-1, -1), (2, 1)]


def jittered_box(i: int, x: float, y: float = 200.0) -> BBox:
    dx, dy = JITTER[i % len(JITTER)]
    return box_at(x + dx + 2 * i, y + dy)


def test_anchor_settles_despite_drift_and_jitter():
    """REGRESSION: settling must measure frame-to-frame movement.

    Measuring drift from the anchor makes the error accumulate until it always
    exceeds the threshold, so the anchor never confirms and - because the whole
    state machine used to be gated behind confirmation - every product sat at
    ON_SHELF forever.
    """
    engine = make_engine()
    frames = T.settle_frames + 2

    for i in range(frames):
        engine.update(
            frame=i,
            ts=100.0 + i * 0.05,
            products=[product(1, jittered_box(i, 300))],
            hands=[],
            basket_zone=None,
        )

    track = engine.tracks[1]
    first = jittered_box(0, 300)
    cumulative = center_distance(track.box, first)

    # guard: the scenario must actually break a cumulative-drift implementation
    assert cumulative > T.settle_motion_px, "test is not exercising the regression"
    assert track.anchor_confirmed is True, "jitter must not prevent settling"
    assert track.state is ProductState.ON_SHELF


def test_full_pickup_still_works_with_jitter():
    """The end-to-end journey must survive a noisy detector."""
    engine = make_engine()
    for i in range(T.settle_frames + 2):
        engine.update(
            frame=i,
            ts=100.0 + i * 0.05,
            products=[product(1, jittered_box(i, 300))],
            hands=[],
            basket_zone=None,
        )
    assert engine.tracks[1].anchor_confirmed is True
    settled = engine.tracks[1].anchor

    events = []
    for i in range(T.touch_emit_frames + T.lift_confirm_frames + 2):
        events.extend(
            engine.update(
                frame=100 + i,
                ts=200.0 + i * 0.05,
                products=[product(1, jittered_box(i, 300))],
                hands=hands((1, box_at(290, 190))),
                basket_zone=None,
            )
        )
    # touched but never displaced -> TOUCH only, still on the shelf
    assert [e.type for e in events].count(EventType.PICKED_UP) == 0
    assert engine.tracks[1].state is ProductState.ON_SHELF

    # now carry it well away from the settled anchor
    events = []
    for i in range(T.lift_confirm_frames + 1):
        box = box_at(settled.center[0] + 120 * (i + 1), 400)
        events.extend(
            engine.update(
                frame=200 + i,
                ts=300.0 + i * 0.05,
                products=[product(1, box)],
                hands=hands((1, BBox(box.x1 - 10, box.y1 - 10, box.x2 + 10, box.y2 + 10))),
                basket_zone=None,
            )
        )
    assert EventType.PICKED_UP in [e.type for e in events]
    assert engine.tracks[1].state is ProductState.IN_HAND


def test_a_brand_new_track_can_never_be_displaced():
    """No settling gate is needed: a new track's anchor IS its box."""
    engine = make_engine()
    for i in range(4):
        engine.update(
            frame=i,
            ts=100.0 + i * 0.05,
            products=[product(7, box_at(300 + i * 2, 200))],
            hands=hands((1, box_at(295, 195))),
            basket_zone=None,
        )
    track = engine.tracks[7]
    assert track.anchor_confirmed is False
    assert track.displaced is False
    assert track.state is ProductState.ON_SHELF


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
