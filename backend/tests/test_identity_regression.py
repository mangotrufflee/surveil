"""Regression tests: product identity through occlusion and track-id churn.

Guards the behaviour that was lost when the pipeline discarded coasting tracks
and the registry scored ON_SHELF products at zero:

  * a changed ``track_id`` is not evidence of a new product;
  * coasting (Kalman-predicted) boxes keep continuity but confirm nothing;
  * interaction state survives a temporary occlusion;
  * two visually identical products are never silently merged - ambiguity is
    reported instead;
  * expiry beyond the hold window is explicit, not silent.

Nothing here loads a model or a camera: the ByteTracker is driven directly and
the pipeline is fed a scripted detector.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.appearance import appearance_score, describe  # noqa: E402
from app.config import Settings, ThresholdSettings  # noqa: E402
from app.detection import (  # noqa: E402
    ROLE_IGNORED,
    ClassRoles,
    FrameDetections,
    RawDetection,
)
from app.geometry import BBox  # noqa: E402
from app.hands import HandBox  # noqa: E402
from app.interaction import EventType, InteractionEngine, ProductState  # noqa: E402
from app.ledger import Ledger  # noqa: E402
from app.pipeline import Pipeline  # noqa: E402
from app.registry import HISTORY_CREDIT, ProductRegistry  # noqa: E402
from app.tracking import ByteTracker, Detection, TrackResult  # noqa: E402
from app.tracking.bytetrack import STATUS_COASTING, STATUS_OBSERVED  # noqa: E402

W, H = 960, 720
FRAME = (W, H)
T = ThresholdSettings()
MAX_MISSED = T.max_missed_frames


# --------------------------------------------------------------------- helpers
def paint(box: tuple[float, float, float, float], color: tuple[int, int, int]) -> np.ndarray:
    frame = np.zeros((H, W, 3), dtype=np.uint8)
    x1, y1, x2, y2 = (int(v) for v in box)
    frame[y1:y2, x1:x2] = color
    return frame


def registry(**kw: Any) -> ProductRegistry:
    kw.setdefault("identity_hold_seconds", 300.0)
    return ProductRegistry("S-test", **kw)


def drive(
    reg: ProductRegistry,
    steps: list[tuple[int, str, BBox, float, set[int] | None]],
    frame: np.ndarray,
) -> list[Any]:
    """resolve() each step, then tell the registry which tracks still exist."""
    out = []
    for track_id, class_name, box, ts, present in steps:
        out.append(
            reg.resolve(
                track_id, class_name, box, describe(frame, box.to_xyxy()), ts, FRAME, True
            )
        )
        reg.observe_tracks(present if present is not None else {track_id}, ts)
    return out


# =============================================================== registry level
def test_on_shelf_products_earn_interaction_history_credit():
    """ON_SHELF used to score 0.0, the dominant cause of identity churn.

    A product that merely sat on the shelf while occluded is by far the most
    common way a track ends, so it must be a credible re-identification claim.
    """
    assert HISTORY_CREDIT[ProductState.ON_SHELF] > 0.0


def test_a_changed_track_id_does_not_imply_a_new_product():
    reg = registry()
    box = BBox(300, 200, 380, 320)
    frame = paint(box.to_xyxy(), (40, 60, 200))

    first = reg.resolve(7, "cell phone", box, describe(frame, box.to_xyxy()), 100.0, FRAME)
    reg.observe_tracks(set(), 110.0)  # the tracker dropped track 7

    moved = BBox(420, 250, 500, 370)
    second = reg.resolve(
        8, "cell phone", moved, describe(frame, moved.to_xyxy()), 120.0, FRAME
    )

    assert second.evidence == "reassociated"
    assert second.product_id == first.product_id
    assert second.matched_previous_track == 7
    assert reg.records[first.product_id].track_ids == [7, 8]


def test_the_same_track_id_returning_is_recovered_without_scoring():
    """The tracker gave the id back, so no evidence is needed - only certainty."""
    reg = registry()
    box = BBox(300, 200, 380, 320)
    frame = paint(box.to_xyxy(), (40, 60, 200))

    first = reg.resolve(7, "cup", box, describe(frame, box.to_xyxy()), 100.0, FRAME)
    reg.observe_tracks(set(), 110.0)  # the tracker dropped track 7

    # a different class must not hijack the cup's binding
    other = reg.resolve(8, "bottle", box, describe(frame, box.to_xyxy()), 112.0, FRAME)
    assert other.evidence == "new"
    assert other.product_id != first.product_id

    back = reg.resolve(7, "cup", box, describe(frame, box.to_xyxy()), 115.0, FRAME)
    assert back.evidence == "track_id_recovered"
    assert back.product_id == first.product_id
    assert back.score == 1.0


def test_a_product_in_the_basket_is_recovered_across_the_frame():
    """Interaction history is decisive, so the distance gate must not block it."""
    reg = registry()
    shelf = BBox(300, 200, 380, 320)
    basket = BBox(760, 500, 840, 620)
    frame = paint(shelf.to_xyxy(), (40, 60, 200))

    first = reg.resolve(1, "bottle", shelf, describe(frame, shelf.to_xyxy()), 100.0, FRAME)
    reg.mark_lost(first.product_id, shelf, ProductState.IN_BASKET, 110.0)

    later = reg.resolve(
        2, "bottle", basket, describe(frame, basket.to_xyxy()), 140.0, FRAME
    )
    assert later.evidence == "reassociated"
    assert later.product_id == first.product_id
    assert later.detail["lost_state"] == "IN_BASKET"


def test_a_product_in_hand_is_recovered_across_the_frame():
    reg = registry()
    shelf = BBox(300, 200, 380, 320)
    carried = BBox(500, 300, 580, 420)
    frame = paint(shelf.to_xyxy(), (40, 60, 200))

    first = reg.resolve(1, "bottle", shelf, describe(frame, shelf.to_xyxy()), 100.0, FRAME)
    reg.mark_lost(first.product_id, shelf, ProductState.IN_HAND, 110.0)

    later = reg.resolve(
        2, "bottle", carried, describe(frame, carried.to_xyxy()), 125.0, FRAME
    )
    assert later.product_id == first.product_id


def test_a_far_shelf_product_is_not_merged_into_a_different_item():
    """Conservative side: ON_SHELF history alone must not bypass the gate.

    Two same-class products on one shelf, no interaction history. The gate is
    the only thing stopping a false merge, so it has to hold.
    """
    reg = registry(max_reassociate_distance_px=120)
    left = BBox(100, 100, 180, 220)
    right = BBox(700, 480, 780, 600)
    frame = paint(left.to_xyxy(), (40, 60, 200))

    first = reg.resolve(1, "cup", left, describe(frame, left.to_xyxy()), 100.0, FRAME)
    reg.mark_lost(first.product_id, left, ProductState.ON_SHELF, 105.0)

    other = reg.resolve(
        2, "cup", right, describe(frame, right.to_xyxy()), 110.0, FRAME
    )
    assert other.evidence == "new"
    assert other.product_id != first.product_id


def test_on_shelf_product_is_recovered_even_when_its_appearance_changed():
    """The regression that mattered: an ON_SHELF product with a changed look.

    Interaction history is the only signal left when the product comes back
    nearer the shelf anchor but looking different (grabbed, rotated, relit).
    With ON_SHELF history at 0.0 this was unrecoverable and each occurrence
    minted another product.
    """
    reg = registry()
    first_box = BBox(300, 200, 380, 320)
    red = paint(first_box.to_xyxy(), (30, 30, 220))
    first = reg.resolve(
        1, "phone", first_box, describe(red, first_box.to_xyxy()), 100.0, FRAME
    )
    reg.observe_tracks(set(), 110.0)

    # same place on the shelf, but a different colour and a different pose
    again = BBox(330, 240, 360, 300)
    blue = paint(again.to_xyxy(), (200, 60, 30))
    red_desc = describe(red, first_box.to_xyxy())
    blue_desc = describe(blue, again.to_xyxy())
    assert appearance_score(red_desc, blue_desc) < 0.6, "the look must really differ"

    out = reg.resolve(2, "phone", again, blue_desc, 120.0, FRAME)

    assert out.detail["history"] == pytest.approx(HISTORY_CREDIT[ProductState.ON_SHELF])
    assert out.evidence == "reassociated"
    assert out.product_id == first.product_id


def test_a_product_still_visible_is_never_stolen_by_a_new_track():
    """Two simultaneous products must not collapse into one identity."""
    reg = registry()
    a_box = BBox(100, 100, 180, 220)
    b_box = BBox(700, 100, 780, 220)
    frame = paint(a_box.to_xyxy(), (40, 60, 200))

    first = reg.resolve(1, "cup", a_box, describe(frame, a_box.to_xyxy()), 100.0, FRAME)
    second = reg.resolve(2, "cup", b_box, describe(frame, b_box.to_xyxy()), 100.0, FRAME)

    assert first.product_id != second.product_id
    assert reg.records[first.product_id].current_track_id == 1
    assert reg.records[second.product_id].current_track_id == 2


def test_two_identical_products_are_not_merged_when_the_match_is_ambiguous():
    """Uncertainty must be surfaced, not resolved by guessing."""
    reg = registry(ambiguity_margin=0.5)  # wide, so the tie is detected
    frame = paint((300, 200, 380, 320), (40, 60, 200))

    left = reg.resolve(
        1, "cup", BBox(300, 200, 380, 320), describe(frame, (300, 200, 380, 320)), 100.0, FRAME
    )
    right = reg.resolve(
        2, "cup", BBox(300, 460, 380, 580), describe(frame, (300, 460, 380, 580)), 100.0, FRAME
    )
    assert left.product_id != right.product_id

    # both go dark; a new detection lands between them, equally well explained
    reg.observe_tracks(set(), 110.0)
    mid = BBox(300, 330, 380, 450)
    result = reg.resolve(3, "cup", mid, describe(frame, mid.to_xyxy()), 120.0, FRAME)

    assert result.ambiguous is True
    assert result.evidence == "ambiguous"
    assert result.product_id not in (left.product_id, right.product_id)
    assert result.detail["runner_up"] in (left.product_id, right.product_id)
    assert result.detail["reason"] == "ambiguous"
    # both originals record that they were candidates for an unsure match
    assert reg.records[left.product_id].ambiguous_matches >= 1
    assert reg.records[right.product_id].ambiguous_matches >= 1


def test_an_unambiguous_match_is_still_merged():
    """Ambiguity handling must not make recovery impossible."""
    reg = registry()
    frame = paint((300, 200, 380, 320), (40, 60, 200))
    first = reg.resolve(
        1, "cup", BBox(300, 200, 380, 320), describe(frame, (300, 200, 380, 320)), 100.0, FRAME
    )
    reg.observe_tracks(set(), 110.0)

    again = BBox(305, 205, 385, 325)
    out = reg.resolve(2, "cup", again, describe(frame, again.to_xyxy()), 115.0, FRAME)
    assert out.ambiguous is False
    assert out.evidence == "reassociated"
    assert out.product_id == first.product_id


def test_identity_is_explicitly_released_after_the_hold_window():
    """Beyond the window we stop guessing and mint a new identity on purpose."""
    reg = registry(identity_hold_seconds=30.0)
    box = BBox(300, 200, 380, 320)
    frame = paint(box.to_xyxy(), (40, 60, 200))

    first = reg.resolve(1, "cup", box, describe(frame, box.to_xyxy()), 100.0, FRAME)
    reg.observe_tracks(set(), 105.0)

    assert reg.expire(120.0) == []  # 15s in, still recoverable
    assert reg.expire(140.0) == [first.product_id]  # 35s in, released

    again = reg.resolve(
        2, "cup", BBox(305, 205, 385, 325), describe(frame, box.to_xyxy()), 150.0, FRAME
    )
    assert again.evidence == "new"
    assert again.product_id != first.product_id


def test_identity_is_retained_across_repeated_short_gaps():
    """Many short absences in a row must not accumulate into a new identity."""
    reg = registry(identity_hold_seconds=300.0)
    frame = paint((300, 200, 380, 320), (40, 60, 200))
    box = BBox(300, 200, 380, 320)

    pids = set()
    track_id = 1
    ts = 100.0
    for cycle in range(20):
        out = reg.resolve(track_id, "phone", box, describe(frame, box.to_xyxy()), ts, FRAME)
        pids.add(out.product_id)
        # 10s gap each cycle, tracker re-mints an id every time
        ts += 10.0
        reg.observe_tracks(set(), ts)
        track_id += 1
        ts += 0.1
        out = reg.resolve(
            track_id, "phone", box, describe(frame, box.to_xyxy()), ts, FRAME
        )
        pids.add(out.product_id)

    assert len(pids) == 1, f"identity churned across cycles: {pids}"


# ================================================================ engine level
def engine() -> InteractionEngine:
    return InteractionEngine(T, session_id="S-test")


def step(
    eng: InteractionEngine,
    box: BBox,
    ts: float,
    hand: list[tuple[int, HandBox]] | None = None,
    basket: BBox | None = None,
    observed: bool = True,
    pid: str = "bottle#1",
) -> list[Any]:
    return eng.update(
        frame=int(ts * 30),
        ts=ts,
        products=[(1, pid, "bottle", box, 0.9, observed)],
        hands=hand or [],
        basket_zone=basket,
        basket_track_id=42 if basket else None,
    )


def test_coasting_tracks_alone_cannot_confirm_a_pickup():
    """A predicted box is not evidence a human moved the product."""
    eng = engine()
    shelf = BBox(300, 200, 380, 320)
    hand = [(1, HandBox(BBox(490, 250, 590, 390), 0.9))]

    for i in range(16):  # settle on the shelf
        step(eng, shelf, 100.0 + i * 0.03)
    assert eng.tracks[1].anchor_confirmed is True

    # the product is now hidden behind a hand; the tracker coasts the box
    events = []
    for i in range(20):  # shorter than the ageing budget, so it is still tracked
        events.extend(
            step(eng, BBox(500, 250, 580, 370), 101.0 + i * 0.03, hand=hand, observed=False)
        )

    kinds = [e.type for e in events]
    assert EventType.PICKED_UP not in kinds
    assert EventType.PLACED_IN_BASKET not in kinds
    # and the state machine did not advance on the prediction either
    assert eng.tracks[1].state is ProductState.ON_SHELF
    assert eng.tracks[1].coasting is True


def test_coasting_tracks_alone_cannot_confirm_a_basket_entry():
    eng = engine()
    shelf = BBox(300, 200, 380, 320)
    basket = BBox(700, 450, 900, 650)
    hand = [(1, HandBox(BBox(490, 250, 590, 390), 0.9))]

    for i in range(16):
        step(eng, shelf, 100.0 + i * 0.03)
    for i in range(8):  # lift into the hand, observed
        step(eng, BBox(500, 250, 580, 370), 101.0 + i * 0.03, hand=hand)
    assert eng.tracks[1].state is ProductState.IN_HAND

    # drifting into the basket, but only ever predicted
    events = []
    for i in range(20):
        events.extend(
            step(
                eng,
                BBox(740, 470, 820, 590),
                102.0 + i * 0.03,
                basket=basket,
                observed=False,
            )
        )
    assert EventType.PLACED_IN_BASKET not in [e.type for e in events]
    assert eng.tracks[1].state is ProductState.IN_HAND


def test_coasting_tracks_alone_cannot_confirm_a_put_back():
    eng = engine()
    shelf = BBox(300, 200, 380, 320)
    hand = [(1, HandBox(BBox(490, 250, 590, 390), 0.9))]

    for i in range(16):
        step(eng, shelf, 100.0 + i * 0.03)
    for i in range(8):
        step(eng, BBox(500, 250, 580, 370), 101.0 + i * 0.03, hand=hand)
    assert eng.tracks[1].state is ProductState.IN_HAND

    events = []
    for i in range(20):
        events.extend(
            step(eng, shelf, 102.0 + i * 0.03, observed=False)
        )
    assert EventType.PUT_BACK not in [e.type for e in events]
    assert eng.tracks[1].state is ProductState.IN_HAND


def test_state_and_anchor_survive_a_temporary_occlusion():
    """Continuity: the product comes back the same object with the same anchor."""
    eng = engine()
    shelf = BBox(300, 200, 380, 320)

    for i in range(16):
        step(eng, shelf, 100.0 + i * 0.03)
    settled = eng.tracks[1]
    anchor = settled.anchor
    first_seen = settled.first_seen

    for i in range(20):  # occluded, tracker still owns it
        step(eng, BBox(302, 202, 382, 322), 101.0 + i * 0.03, observed=False)

    assert 1 in eng.tracks, "a coasting track must not be dropped"
    assert eng.tracks[1] is settled
    assert eng.tracks[1].anchor == anchor
    assert eng.tracks[1].first_seen == first_seen

    for i in range(5):  # observed again
        step(eng, shelf, 102.0 + i * 0.03)

    assert eng.tracks[1].state is ProductState.ON_SHELF
    assert eng.tracks[1].coasting is False
    assert eng.tracks[1].first_seen == first_seen
    assert len(eng.finished) == 0, "no identity was abandoned"


def test_a_track_expires_only_after_max_missed_unobserved_frames():
    """Coasting still ages: an occlusion cannot keep a product alive forever."""
    eng = engine()
    shelf = BBox(300, 200, 380, 320)
    for i in range(16):
        step(eng, shelf, 100.0 + i * 0.03)

    for i in range(MAX_MISSED - 1):
        step(eng, shelf, 101.0 + i * 0.03, observed=False)
    assert 1 in eng.tracks, "must survive an occlusion shorter than the budget"

    step(eng, shelf, 102.0, observed=False)
    assert 1 not in eng.tracks, "must expire once the budget is spent"


def test_revived_product_keeps_its_identity_and_leaves_lost():
    """A revived track must resume, not sit stuck in LOST forever."""
    eng = engine()
    shelf = BBox(300, 200, 380, 320)
    for i in range(16):
        step(eng, shelf, 100.0 + i * 0.03)
    anchor = eng.tracks[1].anchor

    for i in range(MAX_MISSED):
        step(eng, shelf, 101.0 + i * 0.03, observed=False)
    assert 1 not in eng.tracks
    assert eng.finished and eng.finished[-1].state is ProductState.LOST

    # new track id, same registry-resolved product_id
    for i in range(4):
        eng.update(
            frame=400 + i,
            ts=120.0 + i * 0.03,
            products=[(99, "bottle#1", "bottle", BBox(303, 203, 383, 323), 0.9, True)],
            hands=[],
            basket_zone=None,
        )

    revived = eng.tracks[99]
    assert revived.product_id == "bottle#1"
    assert revived.state is ProductState.ON_SHELF, "must not resume into LOST"
    assert revived.anchor == anchor, "the same object keeps its shelf anchor"


def test_revival_does_not_emit_a_duplicate_event():
    eng = engine()
    shelf = BBox(300, 200, 380, 320)
    basket = BBox(700, 450, 900, 650)
    hand = [(1, HandBox(BBox(490, 250, 590, 390), 0.9))]

    for i in range(16):
        step(eng, shelf, 100.0 + i * 0.03)
    for i in range(8):
        step(eng, BBox(500, 250, 580, 370), 101.0 + i * 0.03, hand=hand)
    for i in range(8):
        step(eng, BBox(740, 470, 820, 590), 102.0 + i * 0.03, basket=basket)

    placed_before = len(eng.finished)
    for i in range(MAX_MISSED):  # fully occluded, tracker only coasts
        step(eng, BBox(740, 470, 820, 590), 103.0 + i * 0.03, basket=basket, observed=False)
    assert placed_before == 0
    assert eng.finished and eng.finished[-1].state is ProductState.IN_BASKET

    events = []
    for i in range(4):  # re-acquired in the basket, observed
        events.extend(
            eng.update(
                frame=500 + i,
                ts=120.0 + i * 0.03,
                products=[(99, "bottle#1", "bottle", BBox(745, 475, 825, 595), 0.9, True)],
                hands=[],
                basket_zone=basket,
                basket_track_id=42,
            )
        )
    assert EventType.PLACED_IN_BASKET not in [e.type for e in events], (
        "a resumed track must not re-confirm an event it already reported"
    )
    assert eng.tracks[99].state is ProductState.IN_BASKET


# ============================================================== tracker level
def test_tracker_reports_explicit_observation_status():
    tracker = ByteTracker()
    box = BBox(300, 200, 380, 320)

    seen = tracker.update([Detection(1, "bottle", box, 0.9)])[0]
    assert seen.status == STATUS_OBSERVED
    assert seen.observed is True
    assert seen.predicted is False

    coasting = tracker.update([])[0]
    assert coasting.track_id == seen.track_id, "same id while coasting"
    assert coasting.status == STATUS_COASTING
    assert coasting.observed is False
    assert coasting.coasting is True


def test_track_result_defaults_keep_existing_callers_working():
    """Compatibility: a hand-built TrackResult still means 'observed'."""
    t = TrackResult(
        track_id=1, class_id=0, class_name="bottle", bbox=BBox(0, 0, 10, 10),
        score=0.9, predicted=False, time_since_update=0, hits=1,
    )
    assert t.observed is True
    assert t.status == STATUS_OBSERVED


# ============================================================= pipeline level
class ScriptedDetector:
    """Drives the real ByteTracker from a scripted per-frame detection list."""

    name = "scripted"

    def __init__(self, script: list[list[tuple[str, tuple[int, int, int, int]]]]) -> None:
        self.script = script
        self.frame = 0
        self.names = {0: "person", 1: "phone", 2: "basket"}
        self.roles = ClassRoles(["person"], ["basket"])

    def product_class_ids(self) -> list[int]:
        return [1]

    def class_names(self) -> list[str]:
        return list(self.names.values())

    def detect(self, image: np.ndarray, tracker: ByteTracker) -> FrameDetections:
        step_in = self.script[min(self.frame, len(self.script) - 1)]
        self.frame += 1
        products = [Detection(1, "phone", BBox(*b), 0.9) for _, b in step_in]
        return FrameDetections(
            tracks=tracker.update(products),
            raw_products=products,
            baskets=[],
            ignored=[RawDetection("person", BBox(600, 100, 900, 700), 0.9, ROLE_IGNORED)],
            basket_zone=None,
            infer_ms=1.0,
        )


def run_pipeline(tmp_path: Path, script: list[Any], *, dt: float = 1 / 30) -> tuple[Pipeline, Ledger]:
    settings = Settings(
        auto_start_pipeline=False,
        db_path=tmp_path / "p.db",
        frame_width=W,
        frame_height=H,
        identity_hold_seconds=300.0,
    )
    settings.thresholds = ThresholdSettings()
    ledger = Ledger(settings.db_path)
    pipeline = Pipeline(
        settings,
        ledger,
        detector=ScriptedDetector(script),  # type: ignore[arg-type]
        hand_detector=None,
    )
    pipeline.begin_session("S-reg")
    pipeline.detector = pipeline._injected_detector
    pipeline.ledger.open_session("S-reg", "test")
    pipeline.status.running = True
    frame = np.zeros((H, W, 3), dtype=np.uint8)
    ts = time.time()
    for i in range(len(script)):
        pipeline._process(i, ts, frame)
        ts += dt
    return pipeline, ledger


def test_pipeline_keeps_one_identity_across_repeated_occlusions(tmp_path: Path):
    """The reported symptom: one product shown over and over must stay one product."""
    box = (300, 200, 380, 320)
    seen: list[Any] = [("phone", box)]
    gone: list[Any] = []

    script: list[Any] = []
    for _ in range(6):
        script.extend([seen] * 12)  # on the shelf, settled
        script.extend([gone] * (MAX_MISSED + 5))  # hidden until the tracker drops it

    pipeline, ledger = run_pipeline(tmp_path, script)
    snap = pipeline.snapshot()

    identities = snap["products_registry"]
    assert len(identities) == 1, f"identity churned: {[i['product_id'] for i in identities]}"
    ident = identities[0]
    assert len(ident["track_ids"]) >= 2, "the tracker should have re-minted ids"
    assert ident["reassociations"] >= 1

    pids = {e["product_id"] for e in ledger.query_events()}
    assert len(pids) <= 1, f"the ledger split one product: {pids}"
    ledger.close()


def test_pipeline_keeps_a_coasting_product_visible_and_bound(tmp_path: Path):
    """Pipeline-level guard for the coasting fix.

    While the detector cannot see the product the tracker still owns it. The
    pipeline must therefore keep reporting it (marked `coasting`) and keep its
    identity binding, instead of dropping the frame entirely and forcing the
    identity to be re-earned by scoring on the way back.

    This is the test that fails if coasting tracks are filtered out upstream.
    """
    box = (300, 200, 380, 320)
    settings = Settings(
        auto_start_pipeline=False,
        db_path=tmp_path / "p.db",
        frame_width=W,
        frame_height=H,
    )
    settings.thresholds = ThresholdSettings()
    ledger = Ledger(settings.db_path)

    script: list[Any] = [[("phone", box)]] * 6 + [[]] * 8 + [[("phone", box)]] * 6
    pipeline = Pipeline(
        settings, ledger, detector=ScriptedDetector(script), hand_detector=None
    )
    pipeline.begin_session("S-reg")
    pipeline.detector = pipeline._injected_detector
    pipeline.ledger.open_session("S-reg", "test")
    pipeline.status.running = True

    frame = np.zeros((H, W, 3), dtype=np.uint8)
    ts = time.time()
    seen_during_occlusion = []
    for i in range(len(script)):
        pipeline._process(i, ts, frame)
        ts += 1 / 30
        if 6 <= i < 14:  # inside the occlusion
            snap = pipeline.snapshot()
            seen_during_occlusion.append(snap["states"].get("1"))

    # the product is still reported throughout the occlusion...
    assert all(s is not None for s in seen_during_occlusion), (
        "a coasting product must stay in the snapshot"
    )
    assert all(s["coasting"] is True for s in seen_during_occlusion)
    assert all(s["state"] == "ON_SHELF" for s in seen_during_occlusion)

    # ...and its identity binding was never torn down
    ident = pipeline.snapshot()["products_registry"][0]
    assert ident["identity_held"] is False, "binding was released during the occlusion"
    assert len(ident["track_ids"]) == 1, "the tracker never lost the id"
    ledger.close()


def test_pipeline_reports_coasting_tracks_in_the_snapshot(tmp_path: Path):
    box = (300, 200, 380, 320)
    script: list[Any] = [[("phone", box)]] * 5 + [[]] * 4 + [[("phone", box)]] * 5

    pipeline, ledger = run_pipeline(tmp_path, script)
    ledger.close()
    # the final state is observed again, so assert the flag exists and is False
    state = pipeline.snapshot()["states"]["1"]
    assert state["coasting"] is False
    assert "coasting_frames" in state


def test_pipeline_surfaces_identity_ambiguity(tmp_path: Path):
    """Uncertainty must reach the operator, not be silently resolved."""
    settings = Settings(
        auto_start_pipeline=False,
        db_path=tmp_path / "p.db",
        frame_width=W,
        frame_height=H,
        identity_ambiguity_margin=1.0,  # force every scored match to look ambiguous
    )
    settings.thresholds = ThresholdSettings()
    ledger = Ledger(settings.db_path)

    # two identical phones, both hidden, then one detection lands between them.
    # It must sit inside the distance gate of BOTH, otherwise the conservative
    # answer is "new product", not "ambiguous".
    script: list[Any] = (
        [[("phone", (300, 100, 380, 220))], [("phone", (300, 400, 380, 520))]] * 8
        + [[]] * (MAX_MISSED + 2)
        + [[("phone", (300, 250, 380, 370))]] * 6
    )
    pipeline = Pipeline(
        settings, ledger, detector=ScriptedDetector(script), hand_detector=None
    )
    pipeline.begin_session("S-reg")
    pipeline.detector = pipeline._injected_detector
    pipeline.ledger.open_session("S-reg", "test")
    pipeline.status.running = True

    frame = np.zeros((H, W, 3), dtype=np.uint8)
    ts = time.time()
    for i in range(len(script)):
        pipeline._process(i, ts, frame)
        ts += 1 / 30

    snap = pipeline.snapshot()
    assert snap["identity_ambiguities"], "an ambiguous match must be reported"
    entry = snap["identity_ambiguities"][-1]
    assert entry["reason"] == "ambiguous"
    assert entry["runner_up"]
    ledger.close()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))