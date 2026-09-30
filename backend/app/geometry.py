from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

Point = tuple[float, float]


@dataclass(frozen=True)
class BBox:
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def height(self) -> float:
        return max(0.0, self.y2 - self.y1)

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def center(self) -> Point:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)

    def as_int(self) -> "BBox":
        return BBox(int(self.x1), int(self.y1), int(self.x2), int(self.y2))

    def as_list(self) -> list[float]:
        return [round(self.x1, 2), round(self.y1, 2), round(self.x2, 2), round(self.y2, 2)]

    def to_xyxy(self) -> tuple[float, float, float, float]:
        return self.x1, self.y1, self.x2, self.y2


def union(a: BBox, b: BBox) -> BBox:
    return BBox(min(a.x1, b.x1), min(a.y1, b.y1), max(a.x2, b.x2), max(a.y2, b.y2))


def intersection(a: BBox, b: BBox) -> BBox:
    return BBox(max(a.x1, b.x1), max(a.y1, b.y1), min(a.x2, b.x2), min(a.y2, b.y2))


def intersection_over_union(a: BBox, b: BBox) -> float:
    inter = intersection(a, b).area
    if inter <= 0.0:
        return 0.0
    return inter / (a.area + b.area - inter)


def intersection_over_min(a: BBox, b: BBox) -> float:
    """Overlap normalised by the smaller box - used for 'hand covers product' tests."""
    inter = intersection(a, b).area
    smaller = min(a.area, b.area)
    if smaller <= 0.0:
        return 0.0
    return inter / smaller


def overlap_ratio(inner: BBox, container: BBox) -> float:
    """Fraction of `inner` that sits inside `container` (used for basket containment)."""
    if inner.area <= 0.0:
        return 0.0
    return intersection(inner, container).area / inner.area


def expand(box: BBox, pad: float) -> BBox:
    return BBox(box.x1 - pad, box.y1 - pad, box.x2 + pad, box.y2 + pad)


def center_distance(a: BBox, b: BBox) -> float:
    ax, ay = a.center
    bx, by = b.center
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def greedy_match(
    pairs: Sequence[tuple[int, int, float]],
    threshold: float,
) -> tuple[list[tuple[int, int]], set[int], set[int]]:
    """Greedy highest-score-first matching over (track_idx, det_idx, score) pairs."""
    ordered = sorted(pairs, key=lambda p: p[2], reverse=True)
    used_tracks: set[int] = set()
    used_dets: set[int] = set()
    matches: list[tuple[int, int]] = []
    for track_idx, det_idx, score in ordered:
        if score < threshold:
            break
        if track_idx in used_tracks or det_idx in used_dets:
            continue
        used_tracks.add(track_idx)
        used_dets.add(det_idx)
        matches.append((track_idx, det_idx))
    return matches, used_tracks, used_dets


def iou_candidates(
    track_boxes: Sequence[BBox],
    det_boxes: Sequence[BBox],
    class_ids: Sequence[int] | None = None,
    track_classes: Sequence[int] | None = None,
) -> list[tuple[int, int, float]]:
    out: list[tuple[int, int, float]] = []
    for ti, tbox in enumerate(track_boxes):
        for di, dbox in enumerate(det_boxes):
            if class_ids is not None and track_classes is not None:
                if class_ids[di] != track_classes[ti]:
                    continue
            out.append((ti, di, intersection_over_union(tbox, dbox)))
    return out