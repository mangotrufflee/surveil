"""ByteTrack + ledger tests (no camera, no model weights)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.geometry import BBox  # noqa: E402
from app.detection import ROLE_BASKET, ROLE_IGNORED, ROLE_PRODUCT, ClassRoles  # noqa: E402
from app.interaction import EventType, InteractionEvent, ProductState  # noqa: E402
from app.ledger import Ledger  # noqa: E402
from app.tracking import ByteTracker, Detection  # noqa: E402


def det(class_id: int, name: str, x: float, score: float = 0.9, y: float = 100.0) -> Detection:
    return Detection(class_id, name, BBox(x, y, x + 60, y + 80), score)


# -------------------------------------------------------------------- bytetrack
def test_track_ids_are_persistent_across_frames():
    tracker = ByteTracker()
    first = tracker.update([det(0, "bottle", 100)])
    assert len(first) == 1
    track_id = first[0].track_id

    for i in range(1, 8):
        out = tracker.update([det(0, "bottle", 100 + i * 4)])
        assert [t.track_id for t in out] == [track_id]


def test_person_is_never_treated_as_a_product():
    """The 'person must not be boxed or highlighted' rule lives in ClassRoles."""
    roles = ClassRoles(
        ignored=["person", "people", "human", "hand", "face"],
        basket=["basket", "tote"],
    )
    assert roles.role("person") == ROLE_IGNORED
    assert roles.role("Person") == ROLE_IGNORED  # case-insensitive
    assert roles.role("basket") == ROLE_BASKET
    assert roles.role("bottle") == ROLE_PRODUCT
    assert roles.role("cup") == ROLE_PRODUCT
    assert not roles.is_product("person")

    # and person is excluded from the set of classes handed to the tracker
    coco = {0: "person", 39: "bottle", 41: "cup", 42: "bowl", 84: "book", 80: "toothbrush"}
    assert roles.product_class_ids(coco) == [39, 41, 42, 84, 80]


def test_ignored_class_never_reaches_the_tracker():
    """A filtered class produces no track: the tracker is only fed products."""
    tracker = ByteTracker()
    bottle_track = tracker.update([det(1, "bottle", 100)])[0].track_id
    for _ in range(5):
        out = tracker.update([det(1, "bottle", 100)])
    assert [t.track_id for t in out] == [bottle_track]
    assert {t.class_name for t in out} == {"bottle"}


def test_a_detection_never_hijacks_a_track_of_another_class():
    """Class-aware association: a cup at the bottle's exact box is a new track."""
    tracker = ByteTracker()
    bottle = tracker.update([det(0, "bottle", 100)])[0]
    out = tracker.update([det(0, "bottle", 100), det(2, "cup", 100)])
    ids = {t.class_name: t.track_id for t in out}
    assert ids["bottle"] == bottle.track_id
    assert ids["cup"] != bottle.track_id
    assert tracker.get(bottle.track_id).class_name == "bottle"


def test_class_aware_association_does_not_swap_ids():
    tracker = ByteTracker()
    ids = {t.class_name: t.track_id for t in tracker.update([det(0, "bottle", 100), det(2, "cup", 400)])}
    # two objects of different classes pass right through each other
    for step in range(1, 40):
        out = tracker.update([det(0, "bottle", 100 + step * 8), det(2, "cup", 400 - step * 8)])
        assert {t.class_name: t.track_id for t in out} == ids
    # each track followed its own object
    positions = {t.class_name: t.bbox.x1 for t in out}
    assert positions["bottle"] > positions["cup"]


def test_low_score_detection_recovers_an_occluded_track():
    """Second association pass: a partially occluded (low score) box keeps its id."""
    tracker = ByteTracker()
    ids = [t.track_id for t in tracker.update([det(0, "bottle", 100)])]
    for i in range(1, 4):
        tracker.update([det(0, "bottle", 100 + i * 3)])

    # score below high_threshold -> should match via the low-score pass, not spawn
    out = tracker.update([det(0, "bottle", 112, score=0.3)])
    assert [t.track_id for t in out] == ids
    assert tracker._next_id == 2  # nothing new was created


def test_track_is_removed_after_max_age():
    """max_age is counted in missed frames: dropped on the 5th, not the 6th."""
    tracker = ByteTracker(max_age=5)
    tracker.update([det(0, "bottle", 100)])
    for i in range(4):
        out = tracker.update([])
        assert len(out) == 1, f"survived {i + 1} missed frames"
    assert tracker.update([]) == []
    assert tracker.tracks == []


# ----------------------------------------------------------------------- ledger
def _event(event_type: EventType, product_id: str = "bottle:1", ts: float | None = None,
           track_id: int = 1, resolved: bool = False) -> InteractionEvent:
    return InteractionEvent(
        type=event_type,
        ts=ts if ts is not None else time.time(),
        product_id=product_id,
        product_name=product_id.split(":")[0],
        track_id=track_id,
        confidence=0.9,
        bbox=BBox(10, 10, 60, 90),
        state=ProductState.IN_HAND,
        session_id="S1",
        meta={"state_from": "LIFTING"},
    )


def test_events_round_trip_and_filter(tmp_path: Path):
    ledger = Ledger(tmp_path / "t.db")
    ledger.open_session("S1", "0")
    ledger.register_products([("bottle:1", "bottle", time.time())])
    uid = ledger.record_event(_event(EventType.PICKED_UP))

    rows = ledger.query_events(type_filter=EventType.PICKED_UP.value)
    assert len(rows) == 1
    assert rows[0]["event_uid"] == uid
    assert rows[0]["product_id"] == "bottle:1"
    assert rows[0]["meta"]["state_from"] == "LIFTING"
    assert "ts_iso" in rows[0]

    assert ledger.query_events(type_filter=EventType.PUT_BACK.value) == []
    ledger.close()


def test_csv_export_has_a_header_and_a_row(tmp_path: Path):
    ledger = Ledger(tmp_path / "t.db")
    ledger.record_event(_event(EventType.PICKED_UP))
    ledger.record_event(_event(EventType.PLACED_IN_BASKET))
    csv_text = ledger.export_csv()
    lines = csv_text.strip().splitlines()
    assert lines[0].startswith("event_uid,ts_iso,session_id,type")
    assert len(lines) == 3
    assert ",PICKED_UP," in csv_text
    ledger.close()


def test_checkout_resolves_the_open_events(tmp_path: Path):
    ledger = Ledger(tmp_path / "t.db")
    ledger.record_event(_event(EventType.PICKED_UP))
    ledger.record_event(_event(EventType.PLACED_IN_BASKET))
    assert len(ledger.basket_holds()) == 1

    ledger.checkout("bottle:1", "bottle", 1, "S1")
    assert ledger.basket_holds() == []
    stats = ledger.stats()
    assert stats.checked_out == 1
    assert all(e["resolved"] == 1 for e in ledger.query_events())
    ledger.close()


def test_unaccounted_alert_when_picked_up_and_never_accounted(tmp_path: Path):
    ledger = Ledger(tmp_path / "t.db")
    old = time.time() - 600
    ledger.record_event(_event(EventType.PICKED_UP, ts=old))
    assert len(ledger.unaccounted(grace_seconds=60, session_id="S1")) == 1

    # a put-back afterwards clears the alert
    ledger.record_event(_event(EventType.PUT_BACK, ts=old + 5))
    assert ledger.unaccounted(grace_seconds=60, session_id="S1") == []


def test_no_alert_inside_the_grace_window(tmp_path: Path):
    ledger = Ledger(tmp_path / "t.db")
    ledger.record_event(_event(EventType.PICKED_UP, ts=time.time()))
    assert ledger.unaccounted(grace_seconds=60, session_id="S1") == []


def test_stats_counts_every_event_type(tmp_path: Path):
    ledger = Ledger(tmp_path / "t.db")
    for et in (
        EventType.TOUCH,
        EventType.PICKED_UP,
        EventType.PUT_BACK,
        EventType.PLACED_IN_BASKET,
        EventType.CHECKED_OUT,
    ):
        ledger.record_event(_event(et))
    s = ledger.stats()
    assert (s.events, s.touch, s.picked_up, s.put_back) == (5, 1, 1, 1)
    assert (s.placed_in_basket, s.checked_out) == (1, 1)
    ledger.close()


def test_product_catalog_lists_seen_products(tmp_path: Path):
    ledger = Ledger(tmp_path / "t.db")
    ledger.register_products([("bottle:1", "bottle", time.time())])
    ledger.register_products([("bottle:1", "bottle", time.time())])
    ledger.record_event(_event(EventType.PICKED_UP))
    catalog = ledger.product_catalog()
    assert len(catalog) == 1
    assert catalog[0]["product_id"] == "bottle:1"
    assert catalog[0]["picked_up_count"] == 1
    assert catalog[0]["seen_count"] == 2
    ledger.close()


if __name__ == "__main__":
    raise SystemExit(__import__("pytest").main([__file__, "-q"]))
