"""End-to-end pipeline test with fake detectors.

Exercises the full orchestration - ByteTrack -> interaction engine -> ledger ->
overlay -> live snapshot - with no camera, no YOLO weights and no hand model.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings, ThresholdSettings  # noqa: E402
from app.detection import (  # noqa: E402
    ROLE_IGNORED,
    ROLE_PRODUCT,
    ClassRoles,
    FrameDetections,
    RawDetection,
)
from app.geometry import BBox  # noqa: E402
from app.hands import HandBox  # noqa: E402
from app.ledger import Ledger  # noqa: E402
from app.pipeline import Pipeline  # noqa: E402
from app.tracking import ByteTracker, Detection  # noqa: E402

W, H = 960, 720
BASKET = BBox(700, 450, 940, 700)


class FakeDetector:
    """Scripted detector: hands out a fixed per-frame story."""

    name = "fake"

    def __init__(self, story: list[dict[str, Any]]) -> None:
        self.story = story
        self.frame = 0
        self.names = {0: "person", 1: "bottle", 2: "basket"}
        self.roles = ClassRoles(["person", "hand", "face"], ["basket"])

    def product_class_ids(self) -> list[int]:
        return [1]

    def class_names(self) -> list[str]:
        return list(self.names.values())

    def detect(self, image: np.ndarray, tracker: ByteTracker) -> FrameDetections:
        step = self.story[min(self.frame, len(self.story) - 1)]
        self.frame += 1

        products: list[Detection] = [
            Detection(1, "bottle", BBox(*b), 0.9) for b in step.get("bottles", [])
        ]
        tracks = tracker.update(products)

        baskets = [
            RawDetection("basket", BBox(*step["basket"]), 0.9, "basket")
            if step.get("basket")
            else None
        ]
        baskets = [b for b in baskets if b is not None]

        ignored = [
            RawDetection("person", BBox(*step["person"]), 0.95, ROLE_IGNORED)
        ] if step.get("person") else []

        return FrameDetections(
            tracks=tracks,
            raw_products=products,
            baskets=baskets,
            ignored=ignored,
            basket_zone=BBox(*step["basket"]) if step.get("basket") else None,
            infer_ms=5.0,
        )


class FakeHandDetector:
    name = "fake-hands"

    def __init__(self, story: list[dict[str, Any]]) -> None:
        self.story = story
        self.frame = 0

    def detect(self, image: np.ndarray) -> list[HandBox]:
        step = self.story[min(self.frame, len(self.story) - 1)]
        self.frame += 1
        return [HandBox(BBox(*b), 0.9) for b in step.get("hands", [])]

    def close(self) -> None:
        pass


def build(tmp_path: Path, story: list[dict[str, Any]]) -> tuple[Pipeline, Ledger]:
    settings = Settings(
        auto_start_pipeline=False,
        db_path=tmp_path / "p.db",
        frame_width=W,
        frame_height=H,
    )
    settings.thresholds = ThresholdSettings()
    ledger = Ledger(settings.db_path)
    pipeline = Pipeline(
        settings,
        ledger,
        detector=FakeDetector(story),  # type: ignore[arg-type]
        hand_detector=FakeHandDetector(story),  # type: ignore[arg-type]
    )
    # set up a session exactly like start() does, minus the camera thread
    pipeline.begin_session("S-integration")
    pipeline.detector = pipeline._injected_detector
    pipeline.hand_detector = pipeline._injected_hand_detector
    pipeline.ledger.open_session("S-integration", "test")
    pipeline.status.running = True
    return pipeline, ledger


def play(pipeline: Pipeline, frames: int) -> None:
    frame = np.zeros((H, W, 3), dtype=np.uint8)
    for i in range(frames):
        pipeline._process(i, time.time() + i * 0.05, frame)


def shelf_step() -> dict[str, Any]:
    """One frame: product sits on the shelf; a person is always in frame."""
    return {"bottles": [[300, 200, 380, 320]], "person": [600, 100, 900, 700]}


def shelf_story(frames: int = 20) -> list[dict[str, Any]]:
    return [shelf_step() for _ in range(frames)]


def shelf_step_with(box: list[int]) -> dict[str, Any]:
    return {"bottles": [box], "person": [600, 100, 900, 700]}


def pickup_story() -> list[dict[str, Any]]:
    """Shelf -> hand reaches in -> gradual carry to the basket -> hand releases.

    The carry is interpolated over many frames on purpose: ByteTrack associates
    on IoU, so a product teleporting 200px in one frame is a new object, not a
    moved one. A real hand moves the product smoothly.
    """
    person = [600, 100, 900, 700]
    shelf = [300, 200, 380, 320]
    basket = [760, 480, 840, 600]
    zone = [700, 450, 940, 700]

    steps: list[dict[str, Any]] = []
    steps += [{"bottles": [shelf], "person": person} for _ in range(16)]
    steps += [{"bottles": [shelf], "hands": [[290, 190, 390, 330]], "person": person} for _ in range(2)]

    carry_frames = 24
    for i in range(1, carry_frames + 1):
        t = i / carry_frames
        b = [round(shelf[j] + (basket[j] - shelf[j]) * t, 1) for j in range(4)]
        hand = [b[0] - 10, b[1] - 10, b[2] + 10, b[3] + 10]
        steps.append({"bottles": [b], "hands": [hand], "basket": zone, "person": person})

    steps += [{"bottles": [basket], "basket": zone, "person": person} for _ in range(6)]
    return steps


# ------------------------------------------------------------------ invariants
def test_person_is_counted_but_never_tracked_or_drawn(tmp_path: Path):
    pipeline, ledger = build(tmp_path, shelf_story())
    play(pipeline, 20)
    snap = pipeline.snapshot()

    # counted so the operator knows the room is occupied...
    assert snap["ignored_count"] == 1
    assert "person" in snap["ignored_classes"]
    # ...but there is no track, no state and no event for it
    assert all(p["class_name"] == "bottle" for p in snap["products"])
    assert all(s["product_name"] == "bottle" for s in snap["states"].values())
    assert ledger.query_events() == []
    ledger.close()


def test_snapshot_and_overlay_are_produced(tmp_path: Path):
    pipeline, ledger = build(tmp_path, shelf_story())
    play(pipeline, 20)

    snap = pipeline.snapshot()
    assert snap["running"] is True
    assert snap["session_id"] == "S-integration"
    assert snap["frame"] == 19
    assert snap["frame_size"] == [W, H]
    assert len(snap["products"]) == 1
    assert snap["products"][0]["track_id"] == 1
    assert snap["states"]["1"]["state"] == "ON_SHELF"
    assert snap["states"]["1"]["anchor_confirmed"] is True
    # stock COCO has no basket class, so the drawn fallback region is used
    assert snap["basket_source"] == "roi"
    assert snap["basket_zone"] is not None

    jpeg = pipeline.frame_jpeg()
    assert jpeg is not None and jpeg[:2] == b"\xff\xd8"  # JPEG SOI marker
    ledger.close()


def test_full_pickup_to_basket_writes_the_ledger(tmp_path: Path):
    pipeline, ledger = build(tmp_path, pickup_story())
    play(pipeline, len(pickup_story()))

    # query_events is newest-first, so compare on a chronological ordering
    types = [e["type"] for e in reversed(ledger.query_events())]
    assert "TOUCH" in types
    assert "PICKED_UP" in types
    assert "PLACED_IN_BASKET" in types
    assert types.index("TOUCH") < types.index("PICKED_UP") < types.index("PLACED_IN_BASKET")

    picked = [e for e in ledger.query_events() if e["type"] == "PICKED_UP"][0]
    assert picked["product_name"] == "bottle"
    assert picked["session_id"] == "S-integration"
    assert picked["hand_id"] == 1  # the hand that caused the pickup
    assert picked["meta"]["displaced"] is True
    assert picked["meta"]["state_from"] == "LIFTING"

    basket = [e for e in ledger.query_events() if e["type"] == "PLACED_IN_BASKET"][0]
    assert basket["meta"]["basket_overlap"] >= 0.5

    assert pipeline.snapshot()["states"]["1"]["state"] == "IN_BASKET"
    assert len(ledger.basket_holds()) == 1
    ledger.close()


def test_checkout_clears_the_pending_basket(tmp_path: Path):
    pipeline, ledger = build(tmp_path, pickup_story())
    play(pipeline, len(pickup_story()))
    pending = ledger.basket_holds()
    assert len(pending) == 1

    # product_id is now a stable session identity (e.g. "bottle#1"), not derived
    # from the ByteTrack id
    pid = pending[0]["product_id"]
    assert not pid.endswith(":1"), f"product_id must not be track-scoped, got {pid}"

    ledger.checkout(pid, pending[0]["product_name"], pending[0]["track_id"], "S-integration")
    assert ledger.basket_holds() == []
    assert len(ledger.purchased()) == 1
    assert ledger.stats().checked_out == 1
    ledger.close()


def test_track_expiry_emits_lost_after_max_missed_frames(tmp_path: Path):
    gone = {"person": [600, 100, 900, 700]}  # the product is no longer detected
    max_missed = ThresholdSettings().max_missed_frames
    pipeline, ledger = build(tmp_path, shelf_story(20) + [gone] * max_missed)
    play(pipeline, 20 + max_missed)

    lost = ledger.query_events(type_filter="TRACK_LOST")
    assert len(lost) == 1
    assert lost[0]["product_name"] == "bottle"
    assert "1" not in pipeline.snapshot()["states"]
    ledger.close()


def test_multiple_products_keep_separate_ledgers(tmp_path: Path):
    story = [
        {
            "bottles": [[300, 200, 380, 320], [450, 200, 530, 320]],
            "person": [600, 100, 900, 700],
        }
    ]
    pipeline, ledger = build(tmp_path, story)
    play(pipeline, 20)
    snap = pipeline.snapshot()
    assert {p["track_id"] for p in snap["products"]} == {1, 2}
    assert {s["product_name"] for s in snap["states"].values()} == {"bottle"}
    ledger.close()


def test_track_churn_does_not_create_new_products(tmp_path: Path):
    """The bug from the ledger: one phone became #3, #4, #5, #6, #7, #8, #9.

    ByteTrack must keep re-minting ids when a detection drops out for longer
    than max_missed_frames, but the *product* must stay one product_id - and the
    ledger must not fill with TRACK_LOST noise for the same object.
    """
    max_missed = ThresholdSettings().max_missed_frames
    box = [300, 200, 380, 320]
    gone = {"person": [600, 100, 900, 700]}

    # visible -> hidden long enough to lose the track -> visible again, slightly moved
    story = (
        [shelf_step_with(box)]
        + [gone] * (max_missed + 5)
        + [shelf_step_with([315, 205, 395, 325])] * 10
    )
    pipeline, ledger = build(tmp_path, story)
    play(pipeline, len(story))

    snap = pipeline.snapshot()
    identities = snap["products_registry"]
    assert len(identities) == 1, f"expected 1 product, got {[i['product_id'] for i in identities]}"
    ident = identities[0]
    assert len(ident["track_ids"]) >= 2, "the track should have been re-minted"
    assert ident["reassociations"] >= 1
    assert snap["reassociations"], "the re-association should be reported"

    # the ledger must not have minted a second product
    products = {e["product_id"] for e in ledger.query_events()}
    assert len(products) <= 1, f"ledger churned: {products}"


def test_basket_identity_is_stable_and_records_contents(tmp_path: Path):
    pipeline, ledger = build(tmp_path, pickup_story())
    play(pipeline, len(pickup_story()))

    baskets = pipeline.snapshot()["baskets"]
    assert len(baskets) == 1, "exactly one basket identity, not a per-frame one"
    ident = baskets[0]
    assert ident["active"] is True
    # the story detects a basket class during the carry, which supersedes the
    # drawn fallback region rather than adding a second identity
    assert ident["source"] == "yolo"

    placed = [e for e in ledger.query_events() if e["type"] == "PLACED_IN_BASKET"]
    assert placed, "expected a PLACED_IN_BASKET event"
    assert placed[0]["basket_track_id"] == ident["basket_track_id"]
    # the product_id is stable, and recorded as basket contents
    assert ident["contents"] == [placed[0]["product_id"]]
    assert not placed[0]["product_id"].endswith(":1")


def test_drawn_basket_region_is_used_when_no_basket_class(tmp_path: Path):
    pipeline, ledger = build(tmp_path, shelf_story(20))
    play(pipeline, 20)
    baskets = pipeline.snapshot()["baskets"]
    assert len(baskets) == 1
    assert baskets[0]["source"] == "roi"
    assert baskets[0]["basket_track_id"] >= 100000  # separate id range
    assert pipeline.snapshot()["basket_track_id"] == baskets[0]["basket_track_id"]


def test_events_record_the_product_basket_relationship(tmp_path: Path):
    pipeline, ledger = build(tmp_path, pickup_story())
    play(pipeline, len(pickup_story()))
    for ev in ledger.query_events():
        # identity is never track-scoped
        assert not (ev["product_id"] or "").endswith(f":{ev['track_id']}")
        if ev["type"] == "PLACED_IN_BASKET":
            assert ev["basket_track_id"] is not None
            assert ev["product_track_id"] == ev["track_id"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
