"""Cheap appearance descriptors for re-identifying a product after its track dies.

ByteTrack gives continuity while a detection keeps moving. It cannot tell you that
the detection appearing 20 seconds later inside the basket is the same bottle -
a new track id is simply minted. Recovering that link needs more than geometry,
so each track also carries a small descriptor:

  * a 3x3x3 RGB histogram over the centre crop (ignores background and the
    hand that may be covering it),
  * the box aspect ratio,
  * the box size relative to the frame.

Deliberately not a deep embedding: this runs on CPU at a few frames per second
alongside two detectors, and a colour histogram over the product's middle is
enough to separate the handful of objects on a shelf. It is a *tiebreaker* -
spatial continuity and interaction history are the stronger signals, and all
three are combined in :mod:`app.registry`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

BINS = 3
HIST_SIZE = BINS * BINS * BINS  # 27
CROP = 0.6  # use the middle 60% of the box to avoid hand/background contamination


@dataclass
class Descriptor:
    hist: np.ndarray = field(default_factory=lambda: np.zeros(HIST_SIZE, dtype=np.float32))
    aspect: float = 1.0
    rel_size: float = 0.0

    def is_valid(self) -> bool:
        return bool(self.hist.sum() > 0)

    def as_dict(self) -> dict[str, float | list[float]]:
        return {
            "hist": [round(float(v), 5) for v in self.hist],
            "aspect": round(float(self.aspect), 4),
            "rel_size": round(float(self.rel_size), 6),
        }


def describe(frame_bgr: np.ndarray, box: tuple[float, float, float, float]) -> Descriptor:
    """Build a descriptor for `box` (x1, y1, x2, y2) in `frame_bgr`."""
    x1, y1, x2, y2 = box
    fw = max(frame_bgr.shape[1], 1)
    fh = max(frame_bgr.shape[0], 1)

    w = max(x2 - x1, 1.0)
    h = max(y2 - y1, 1.0)
    aspect = w / h
    rel_size = (w * h) / float(fw * fh)

    # centre crop
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    cw, ch = w * CROP, h * CROP
    ix1 = int(np.clip(cx - cw / 2.0, 0, fw - 1))
    iy1 = int(np.clip(cy - ch / 2.0, 0, fh - 1))
    ix2 = int(np.clip(cx + cw / 2.0, ix1 + 1, fw))
    iy2 = int(np.clip(cy + ch / 2.0, iy1 + 1, fh))

    crop = frame_bgr[iy1:iy2, ix1:ix2]
    if crop.size == 0:
        return Descriptor(aspect=aspect, rel_size=rel_size)

    # to RGB, then quantise into BINS levels per channel
    rgb = crop[:, :, ::-1].astype(np.int32)
    q = np.minimum(rgb * BINS // 256, BINS - 1)
    flat = (q[:, :, 0] * BINS + q[:, :, 1]) * BINS + q[:, :, 2]

    hist = np.bincount(flat.ravel(), minlength=HIST_SIZE).astype(np.float32)
    total = hist.sum()
    if total > 0:
        hist /= total
    return Descriptor(hist=hist, aspect=aspect, rel_size=rel_size)


def hist_similarity(a: Descriptor, b: Descriptor) -> float:
    """Histogram intersection in [0, 1]."""
    if not a.is_valid() or not b.is_valid():
        return 0.0
    return float(np.minimum(a.hist, b.hist).sum())


def aspect_similarity(a: Descriptor, b: Descriptor) -> float:
    """1.0 for identical aspect ratio, decaying as the ratio diverges."""
    if a.aspect <= 0 or b.aspect <= 0:
        return 0.0
    ratio = min(a.aspect, b.aspect) / max(a.aspect, b.aspect)
    return float(ratio)


def size_similarity(a: Descriptor, b: Descriptor) -> float:
    """Relative box-area agreement; tolerant of perspective change."""
    if a.rel_size <= 0 or b.rel_size <= 0:
        return 0.0
    ratio = min(a.rel_size, b.rel_size) / max(a.rel_size, b.rel_size)
    return float(ratio)


def appearance_score(a: Descriptor, b: Descriptor) -> float:
    """Weighted combination in [0, 1]."""
    return float(
        0.60 * hist_similarity(a, b)
        + 0.25 * aspect_similarity(a, b)
        + 0.15 * size_similarity(a, b)
    )