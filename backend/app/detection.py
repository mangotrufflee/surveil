"""YOLO product detection with hard class filtering.

Two things matter here:

1. The ``person`` class must never be boxed or highlighted (explicit requirement
   in the document). Ignored classes are dropped *before* tracking, drawing and
   ledger writes - they never exist as far as the rest of the system is
   concerned.
2. The basket is a first-class detection, so it can be an extra YOLO class
   (``basket``, ``tote``, ...) instead of a hand-drawn region. A configured
   ``basket_roi`` is used only as a fallback when no basket class is detected.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

import numpy as np

from .config import Settings
from .geometry import BBox, clamp, union
from .tracking import ByteTracker, Detection, TrackResult


@dataclass
class RawDetection:
    class_name: str
    bbox: BBox
    score: float
    role: str  # "product" | "basket" | "ignored"


def roi_to_bbox(roi: list[float], width: int, height: int) -> BBox:
    """Convert a normalised [x, y, w, h] region into pixel coordinates."""
    x, y, w, h = roi
    return BBox(
        clamp(x * width, 0, width),
        clamp(y * height, 0, height),
        clamp((x + w) * width, 0, width),
        clamp((y + h) * height, 0, height),
    )


def resolve_basket_zone(
    detections: list[RawDetection],
    roi: list[float] | None,
    width: int,
    height: int,
) -> BBox | None:
    """Prefer a detected basket class; fall back to the drawn region.

    Applied by the pipeline rather than by ProductDetector so the rule holds for
    any detection source and the live snapshot always agrees with what the
    state machine is actually using.
    """
    if detections:
        largest = max(detections, key=lambda d: d.bbox.area)
        zone = largest.bbox
        for other in detections:
            if other is largest:
                continue
            if other.bbox.area > zone.area:
                zone = union(zone, other.bbox)
        return zone
    if roi:
        return roi_to_bbox(roi, width, height)
    return None


@dataclass
class FrameDetections:
    tracks: list[TrackResult]
    raw_products: list[Detection]
    baskets: list[RawDetection]
    ignored: list[RawDetection]
    basket_zone: BBox | None
    infer_ms: float


ROLE_PRODUCT = "product"
ROLE_BASKET = "basket"
ROLE_IGNORED = "ignored"


class ClassRoles:
    """Maps a YOLO class name onto its role in the pipeline.

    Extracted from :class:`ProductDetector` so the 'person is never a product'
    rule can be unit tested without loading a YOLO checkpoint.
    """

    def __init__(self, ignored: list[str], basket: list[str]) -> None:
        self.ignored = {n.strip().lower() for n in ignored if n.strip()}
        self.basket = {n.strip().lower() for n in basket if n.strip()}

    def role(self, class_name: str) -> str:
        key = (class_name or "").strip().lower()
        if key in self.ignored:
            return ROLE_IGNORED
        if key in self.basket:
            return ROLE_BASKET
        return ROLE_PRODUCT

    def is_product(self, class_name: str) -> bool:
        return self.role(class_name) == ROLE_PRODUCT

    def product_class_ids(self, names: dict[int, str]) -> list[int]:
        return [cid for cid, name in names.items() if self.is_product(name)]


class ProductDetector:
    def __init__(self, settings: Settings) -> None:
        from ultralytics import YOLO

        self.settings = settings
        self._lock = threading.Lock()
        self.model = YOLO(settings.yolo_model)
        self.names: dict[int, str] = dict(self.model.names)
        self.roles = ClassRoles(settings.ignored_classes, settings.basket_class_names)
        self._product_class_ids = self.roles.product_class_ids(self.names)

    # ------------------------------------------------------------------ utils
    def product_class_ids(self) -> list[int]:
        return list(self._product_class_ids)

    def class_names(self) -> list[str]:
        return list(self.names.values())

    @staticmethod
    def _roi_to_bbox(roi: list[float], width: int, height: int) -> BBox:
        return roi_to_bbox(roi, width, height)

    # ----------------------------------------------------------------- detect
    def detect(self, frame: np.ndarray, tracker: ByteTracker) -> FrameDetections:
        import time

        t0 = time.perf_counter()
        h, w = frame.shape[:2]

        kwargs: dict[str, Any] = {
            "conf": self.settings.yolo_conf,
            "iou": self.settings.yolo_iou,
            "verbose": False,
            "imgsz": self.settings.yolo_imgsz,
        }
        if self.settings.yolo_device:
            kwargs["device"] = self.settings.yolo_device
        if self.settings.yolo_half:
            kwargs["half"] = True

        with self._lock:
            results = self.model.predict(frame, **kwargs)

        products: list[Detection] = []
        baskets: list[RawDetection] = []
        ignored: list[RawDetection] = []

        result = results[0]
        boxes = getattr(result, "boxes", None)
        if boxes is not None:
            xyxy = boxes.xyxy.cpu().numpy()
            confs = boxes.conf.cpu().numpy()
            clss = boxes.cls.cpu().numpy().astype(int)
            for (x1, y1, x2, y2), conf, cls_id in zip(xyxy, confs, clss):
                name = self.names.get(int(cls_id), str(cls_id))
                bbox = BBox(float(x1), float(y1), float(x2), float(y2))
                # 'person' lands in `ignored` and stops here: it is never tracked,
                # never drawn and never written to the ledger.
                role = self.roles.role(name)
                if role == ROLE_IGNORED:
                    ignored.append(RawDetection(name, bbox, float(conf), role))
                elif role == ROLE_BASKET:
                    baskets.append(RawDetection(name, bbox, float(conf), role))
                else:
                    products.append(Detection(int(cls_id), name, bbox, float(conf)))

        tracks = tracker.update(products)

        # keep only tracks whose class is a product class
        valid_ids = set(self._product_class_ids)
        tracks = [t for t in tracks if t.class_id in valid_ids]

        # A detected basket class wins; the drawn region is applied by the
        # pipeline so it applies uniformly to every detection source.
        return FrameDetections(
            tracks=tracks,
            raw_products=products,
            baskets=baskets,
            ignored=ignored,
            basket_zone=None,
            infer_ms=(time.perf_counter() - t0) * 1000.0,
        )