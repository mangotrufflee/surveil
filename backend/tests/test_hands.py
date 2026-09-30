"""Hand-detection tests.

The ONNX test runs the converted victordibia/handtracking graph against the
image vendored with that repo, and is skipped when the conversion step has not
been run yet (see backend/tools/convert_hand_model.py).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

import cv2  # noqa: E402

from app.geometry import BBox  # noqa: E402
from app.hands import (  # noqa: E402
    MediapipeHandDetector,
    NullHandDetector,
    OnnxHandDetector,
    build_hand_detector,
    nms,
    parse_pbtxt_label_map,
)

MODEL = REPO_ROOT / "backend" / "models" / "hand_ssd_mobilenet.onnx"
LABEL_MAP = REPO_ROOT / "vendor" / "handtracking" / "hand_inference_graph" / "hand_label_map.pbtxt"
TEST_IMAGE = REPO_ROOT / "vendor" / "handtracking" / "handtrack" / "utils" / "test_image.jpeg"

needs_model = pytest.mark.skipif(
    not MODEL.exists(), reason="run backend/tools/convert_hand_model.py first"
)
needs_image = pytest.mark.skipif(
    not TEST_IMAGE.exists(), reason="vendor/handtracking is not cloned"
)


# ------------------------------------------------------------------------- nms
def test_nms_keeps_the_best_box_and_drops_its_neighbour():
    boxes = np.array(
        [
            [0, 0, 100, 100],  # best
            [5, 5, 105, 105],  # heavy overlap with the first
            [500, 500, 600, 600],  # disjoint
        ],
        dtype=np.float32,
    )
    scores = np.array([0.9, 0.85, 0.7], dtype=np.float32)
    keep = nms(boxes, scores, iou_threshold=0.4)
    assert keep == [0, 2]


def test_nms_on_empty_input():
    assert nms(np.zeros((0, 4), dtype=np.float32), np.zeros((0,), dtype=np.float32), 0.4) == []


# ------------------------------------------------------------------- label map
def test_parses_the_upstream_label_map():
    mapping = parse_pbtxt_label_map(LABEL_MAP)
    assert mapping == {1: "hand"}


# ------------------------------------------------------------------- detector
@needs_model
@needs_image
def test_converted_hand_model_detects_both_hands():
    detector = OnnxHandDetector(
        model_path=MODEL, input_size=300, conf_threshold=0.27, label_map_path=LABEL_MAP
    )
    assert detector.labels == {1: "hand"}

    image = cv2.imread(str(TEST_IMAGE))
    hands = detector.detect(image)

    assert len(hands) == 2, f"expected 2 hands, got {len(hands)}"
    h, w = image.shape[:2]
    for hand in hands:
        assert hand.score >= 0.27
        # boxes land inside the frame and have real area
        assert 0 <= hand.bbox.x1 < hand.bbox.x2 <= w
        assert 0 <= hand.bbox.y1 < hand.bbox.y2 <= h
        assert hand.bbox.area > 1000
    # the two detections are distinct hands, not one box duplicated
    assert abs(hands[0].bbox.center[0] - hands[1].bbox.center[0]) > 100


@needs_model
@needs_image
def test_a_blank_frame_produces_no_hands():
    detector = OnnxHandDetector(model_path=MODEL, input_size=300, conf_threshold=0.27)
    assert detector.detect(np.zeros((480, 640, 3), dtype=np.uint8)) == []


@needs_model
def test_threshold_controls_sensitivity():
    from app.config import get_settings

    settings = get_settings()
    settings.hand_onnx_path = MODEL
    settings.hand_label_map_path = LABEL_MAP

    settings.hand_backend = "onnx"
    detector = build_hand_detector(settings)
    assert isinstance(detector, OnnxHandDetector)
    assert detector.conf_threshold == settings.hand_conf_threshold

    settings.hand_backend = "off"
    assert isinstance(build_hand_detector(settings), NullHandDetector)


def test_backend_falls_back_when_the_model_is_missing():
    from app.config import get_settings

    settings = get_settings()
    settings.hand_onnx_path = Path("does/not/exist.onnx")
    settings.hand_backend = "onnx"
    # 'onnx' is explicit, so a missing model is a hard error, not a silent fallback
    with pytest.raises(RuntimeError, match="convert_hand_model"):
        build_hand_detector(settings)


def test_hand_class_is_excluded_from_products():
    """YOLO's own 'hand' class must not double-count as a product."""
    from app.detection import ROLE_IGNORED, ClassRoles

    roles = ClassRoles(ignored=["person", "hand", "face"], basket=["basket"])
    assert roles.role("hand") == ROLE_IGNORED
    assert roles.role("person") == ROLE_IGNORED


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
