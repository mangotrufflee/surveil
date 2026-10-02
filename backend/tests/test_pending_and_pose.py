"""Tests for the outstanding-pickup ledger, the pose hand backend and the
basket-zone resolution."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.detection import RawDetection, resolve_basket_zone, roi_to_bbox  # noqa: E402
from app.geometry import BBox  # noqa: E402
from app.hands import (  # noqa: E402
    AVAILABLE_HAND_BACKENDS,
    HandBox,
    NullHandDetector,
    PoseHandDetector,
    build_hand_detector,
)
from app.interaction import EventType, InteractionEvent, ProductState  # noqa: E402
from app.ledger import Ledger  # noqa: E402


def _event(event_type: EventType, ts: float | None = None, track_id: int = 1,
           product_id: str = "bottle:1") -> InteractionEvent:
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
        meta={},
    )


# ------------------------------------------------- IN_HAND is purchasable
def test_in_hand_pickup_appears_as_pending(tmp_path: Path):
    ledger = Ledger(tmp_path / "t.db")
    ledger.record_event(_event(EventType.PICKED_UP))

    pending = ledger.open_pickups()
    assert len(pending) == 1
    assert pending[0]["product_name"] == "bottle"

    # ...and the owner can close it out even though it never reached a basket
    ledger.checkout("bottle:1", "bottle", 1, "S1")
    assert ledger.open_pickups() == []
    assert ledger.stats().checked_out == 1
    ledger.close()


def test_basket_placement_also_appears_as_pending(tmp_path: Path):
    ledger = Ledger(tmp_path / "t.db")
    ledger.record_event(_event(EventType.PICKED_UP))
    ledger.record_event(_event(EventType.PLACED_IN_BASKET))
    assert len(ledger.open_pickups()) == 1
    ledger.close()


def test_put_back_clears_the_pending_pickup(tmp_path: Path):
    ledger = Ledger(tmp_path / "t.db")
    now = time.time()
    ledger.record_event(_event(EventType.PICKED_UP, ts=now))
    ledger.record_event(_event(EventType.PUT_BACK, ts=now + 5))
    assert ledger.open_pickups() == []
    ledger.close()


def test_two_products_stay_independent(tmp_path: Path):
    ledger = Ledger(tmp_path / "t.db")
    ledger.record_event(_event(EventType.PICKED_UP, track_id=1, product_id="bottle:1"))
    ledger.record_event(_event(EventType.PICKED_UP, track_id=2, product_id="cup:2"))
    assert len(ledger.open_pickups()) == 2

    ledger.checkout("bottle:1", "bottle", 1, "S1")
    remaining = ledger.open_pickups()
    assert len(remaining) == 1
    assert remaining[0]["product_id"] == "cup:2"
    ledger.close()


def test_pending_is_scoped_to_the_session(tmp_path: Path):
    ledger = Ledger(tmp_path / "t.db")
    ev = _event(EventType.PICKED_UP)
    ev.session_id = "S1"
    ledger.record_event(ev)
    assert len(ledger.open_pickups(session_id="S1")) == 1
    assert len(ledger.open_pickups(session_id="S2")) == 0
    ledger.close()


# ------------------------------------------------------------- basket zone
def test_roi_converts_to_pixels():
    box = roi_to_bbox([0.5, 0.25, 0.25, 0.5], 800, 400)
    assert box == BBox(400, 100, 600, 300)


def test_roi_is_clamped_to_the_frame():
    box = roi_to_bbox([0.8, 0.8, 0.5, 0.5], 100, 100)
    assert box.x2 <= 100 and box.y2 <= 100


def test_detected_basket_class_beats_the_drawn_region():
    detected = [RawDetection("basket", BBox(10, 10, 60, 60), 0.9, "basket")]
    zone = resolve_basket_zone(detected, [0.0, 0.0, 1.0, 1.0], 800, 400)
    assert zone == BBox(10, 10, 60, 60)


def test_drawn_region_is_used_when_no_basket_class():
    zone = resolve_basket_zone([], [0.5, 0.5, 0.25, 0.25], 800, 400)
    assert zone == BBox(400, 200, 600, 300)


def test_no_basket_at_all_yields_no_zone():
    assert resolve_basket_zone([], None, 800, 400) is None


def test_basket_roi_has_a_working_default():
    from app.config import Settings

    roi = Settings().basket_roi
    assert roi is not None and len(roi) == 4
    assert all(0.0 <= v <= 1.0 for v in roi)


# ------------------------------------------------------------ pose backend
class _FakeKeypoints:
    def __init__(self, data: np.ndarray) -> None:
        self.data = data


class _FakeBoxes:
    def __init__(self) -> None:
        self.xyxy = None


class _FakeResult:
    def __init__(self, kpts: np.ndarray | None) -> None:
        self.keypoints = _FakeKeypoints(kpts) if kpts is not None else None
        self.boxes = _FakeBoxes()


class _StubModel:
    """Stands in for ultralytics YOLO so the pose backend needs no weights."""

    def __init__(self, kpts: np.ndarray | None) -> None:
        self._kpts = kpts

    def __call__(self, frame: np.ndarray, **_: Any):
        return [_FakeResult(self._kpts)]


def _pose_detector(kpts: np.ndarray | None) -> PoseHandDetector:
    """Build a PoseHandDetector with a stubbed model, so no weights are needed."""
    import threading

    det = PoseHandDetector.__new__(PoseHandDetector)  # bypass __init__ / model load
    det.model = _StubModel(kpts)
    det.conf_threshold = 0.4
    det.wrist_conf = 0.4
    det.box_size = 90.0
    det.device = ""
    det._lock = threading.Lock()
    return det


def _person(wrist_x: float, wrist_y: float, conf: float, n_keypoints: int = 17) -> list:
    row = [[0.0, 0.0, 0.0] for _ in range(n_keypoints)]
    if 0 <= PoseHandDetector.LEFT_WRIST < n_keypoints:
        row[PoseHandDetector.LEFT_WRIST] = [wrist_x, wrist_y, conf]
    if 0 <= PoseHandDetector.RIGHT_WRIST < n_keypoints:
        row[PoseHandDetector.RIGHT_WRIST] = [wrist_x + 20, wrist_y, conf]
    return row


def test_pose_backend_builds_a_box_per_wrist():
    torch = pytest.importorskip("torch")
    kpts = torch.tensor([_person(200.0, 150.0, 0.9)], dtype=torch.float32)
    hands = _pose_detector(kpts).detect(np.zeros((480, 640, 3), dtype=np.uint8))
    assert len(hands) == 2
    for h in hands:
        assert isinstance(h, HandBox)
        assert h.bbox.width == 90.0 and h.bbox.height == 90.0
    # the two wrists are distinct boxes, 20px apart in x
    assert abs(hands[0].bbox.center[0] - hands[1].bbox.center[0]) == 20.0


def test_pose_backend_ignores_low_confidence_wrists():
    torch = pytest.importorskip("torch")
    kpts = torch.tensor([_person(200.0, 150.0, 0.1)], dtype=torch.float32)
    assert _pose_detector(kpts).detect(np.zeros((480, 640, 3), dtype=np.uint8)) == []


def test_pose_backend_handles_no_people():
    assert _pose_detector(None).detect(np.zeros((480, 640, 3), dtype=np.uint8)) == []


def test_pose_is_a_selectable_backend():
    assert "pose" in AVAILABLE_HAND_BACKENDS
    from app.config import get_settings

    s = get_settings()
    s.hand_enabled = True
    s.hand_backend = "pose"
    s.pose_model = "definitely-missing-pose-model.pt"
    s.pose_wrist_conf = 0.4
    s.pose_hand_box_size = 90.0
    with pytest.raises(RuntimeError):
        build_hand_detector(s)
    s.hand_backend = "off"
    assert isinstance(build_hand_detector(s), NullHandDetector)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
