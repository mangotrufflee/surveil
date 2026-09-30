"""Hand detection.

The primary backend is the hand detector from
    https://github.com/victordibia/handtracking.git
(vendored into ``vendor/handtracking``).

Upstream ships a **TensorFlow 1.x frozen graph** (``hand_inference_graph/
frozen_inference_graph.pb``, SSD MobileNet, single class ``hand``). TF1 cannot
run on a modern Python, so ``tools/convert_hand_model.py`` converts that frozen
graph to ONNX once and this module runs it with onnxruntime - no TensorFlow in
the runtime at all.

``MediapipeHandDetector`` is a dependency-light fallback so the pipeline still
works before the conversion step has been run.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .geometry import BBox

_LOCK = threading.Lock()


@dataclass
class HandBox:
    bbox: BBox
    score: float


def parse_pbtxt_label_map(path: Path) -> dict[int, str]:
    """Read the upstream protobuf text-format label map into {id: name}."""
    text = path.read_text(encoding="utf-8")
    mapping: dict[int, str] = {}
    for block in re.findall(r"item\s*\{(.*?)\}", text, flags=re.DOTALL):
        id_match = re.search(r"id:\s*(\d+)", block)
        name_match = re.search(r"name:\s*'([^']*)'", block)
        if id_match and name_match:
            mapping[int(id_match.group(1))] = name_match.group(1)
    return mapping


def nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> list[int]:
    """Plain greedy NMS. Returns indices of the boxes to keep."""
    if len(boxes) == 0:
        return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        i = order[0]
        keep.append(int(i))
        if order.size == 1:
            break
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        union = areas[i] + areas[order[1:]] - inter
        iou = np.where(union > 0, inter / np.maximum(union, 1e-9), 0.0)
        order = order[1:][iou <= iou_threshold]
    return keep


class BaseHandDetector:
    name = "base"

    def detect(self, frame_bgr: np.ndarray) -> list[HandBox]:
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - trivial
        pass


class OnnxHandDetector(BaseHandDetector):
    """Runs the converted victordibia/handtracking SSD graph via onnxruntime."""

    name = "onnx"

    def __init__(
        self,
        model_path: Path,
        input_size: int = 300,
        conf_threshold: float = 0.27,
        nms_iou: float = 0.4,
        max_detections: int = 10,
        label_map_path: Path | None = None,
    ) -> None:
        import onnxruntime as ort

        if not model_path.exists():
            raise FileNotFoundError(f"hand ONNX model not found at {model_path}")

        so = ort.SessionOptions()
        so.intra_op_num_threads = 2
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(str(model_path), so, providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        # tf2onnx keeps the ':0' tensor suffixes from the frozen graph, so
        # normalise them: 'detection_boxes:0' -> 'detection_boxes'
        self.output_names = [o.name for o in self.session.get_outputs()]
        self._outputs_by_key = {
            self._normalise(o.name): o.name for o in self.session.get_outputs()
        }
        self.input_size = input_size
        self.conf_threshold = conf_threshold
        self.nms_iou = nms_iou
        self.max_detections = max_detections
        self.labels: dict[int, str] = {}
        if label_map_path and label_map_path.exists():
            self.labels = parse_pbtxt_label_map(label_map_path)

    def detect(self, frame_bgr: np.ndarray) -> list[HandBox]:
        h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(rgb, (self.input_size, self.input_size), interpolation=cv2.INTER_LINEAR)
        batch = np.expand_dims(resized.astype(np.uint8), axis=0)

        with _LOCK:
            outputs = self.session.run(self.output_names, {self.input_name: batch})
        by_name = dict(zip(self.output_names, outputs))

        boxes = self._pick(by_name, ["detection_boxes", "boxes"])
        scores = self._pick(by_name, ["detection_scores", "scores"])
        num = by_name.get("num_detections")

        if boxes is None or scores is None:
            return []
        boxes = np.asarray(boxes).reshape(-1, 4)
        scores = np.asarray(scores).reshape(-1)

        n = int(num[0]) if num is not None and len(np.asarray(num).reshape(-1)) else min(100, len(scores))
        n = max(1, min(n, len(scores)))

        keep_mask = scores[:n] >= self.conf_threshold
        boxes = boxes[:n][keep_mask]
        scores = scores[:n][keep_mask]
        if len(boxes) == 0:
            return []

        # SSD normalised output is (ymin, xmin, ymax, xmax) in [0, 1].
        xy = np.empty_like(boxes)
        xy[:, 0] = boxes[:, 1] * w
        xy[:, 1] = boxes[:, 0] * h
        xy[:, 2] = boxes[:, 3] * w
        xy[:, 3] = boxes[:, 2] * h

        kept = nms(xy, scores, self.nms_iou)[: self.max_detections]
        return [
            HandBox(
                bbox=BBox(*(float(v) for v in xy[i])),
                score=float(scores[i]),
            )
            for i in kept
        ]

    @staticmethod
    def _normalise(name: str) -> str:
        return name.split(":")[0].strip().lower()

    def _pick(self, by_name: dict[str, np.ndarray], candidates: list[str]) -> np.ndarray | None:
        for name in candidates:
            actual = self._outputs_by_key.get(self._normalise(name))
            if actual is not None and actual in by_name:
                return by_name[actual]
        return None


class MediapipeHandDetector(BaseHandDetector):
    """Fallback backend - no conversion step required."""

    name = "mediapipe"

    def __init__(self, conf_threshold: float = 0.5) -> None:
        import mediapipe as mp

        self.conf_threshold = conf_threshold
        self.hands = mp.solutions.hands.Hands(
            static_image_mode=False,
            max_num_hands=10,
            model_complexity=0,
            min_detection_confidence=conf_threshold,
            min_tracking_confidence=conf_threshold,
        )

    def detect(self, frame_bgr: np.ndarray) -> list[HandBox]:
        h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        result = self.hands.process(rgb)
        out: list[HandBox] = []
        if not result.multi_hand_landmarks:
            return out
        scores = [1.0] * len(result.multi_hand_landmarks)
        if result.multi_handedness:
            scores = [h.classification[0].score for h in result.multi_handedness]
        for landmarks, score in zip(result.multi_hand_landmarks, scores):
            xs = [lm.x * w for lm in landmarks.landmark]
            ys = [lm.y * h for lm in landmarks.landmark]
            out.append(
                HandBox(
                    bbox=BBox(min(xs), min(ys), max(xs), max(ys)),
                    score=float(score),
                )
            )
        return out

    def close(self) -> None:
        self.hands.close()


class NullHandDetector(BaseHandDetector):
    name = "off"

    def detect(self, frame_bgr: np.ndarray) -> list[HandBox]:
        return []


def build_hand_detector(settings) -> BaseHandDetector:
    """Resolve ``SURVEIL_HAND_BACKEND`` = auto | onnx | mediapipe | off."""
    if not settings.hand_enabled or settings.hand_backend == "off":
        return NullHandDetector()

    errors: list[str] = []
    want_onnx = settings.hand_backend in ("auto", "onnx")
    if want_onnx:
        try:
            return OnnxHandDetector(
                model_path=Path(settings.hand_onnx_path),
                input_size=settings.hand_input_size,
                conf_threshold=settings.hand_conf_threshold,
                nms_iou=settings.hand_nms_iou,
                max_detections=settings.hand_max_detections,
                label_map_path=Path(settings.hand_label_map_path),
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"onnx: {exc}")

    if settings.hand_backend in ("auto", "mediapipe"):
        try:
            return MediapipeHandDetector(conf_threshold=max(0.35, settings.hand_conf_threshold))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"mediapipe: {exc}")

    if settings.hand_backend == "onnx":
        raise RuntimeError(
            "hand_backend=onnx but the hand model could not be loaded: "
            + "; ".join(errors)
            + ". Run: python tools/convert_hand_model.py"
        )
    return NullHandDetector()