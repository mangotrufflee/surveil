"""Basket identity, tracked independently of the products it contains.

The document treats the basket as a *zone*, but a zone cannot answer "which
basket". Tracking it as an object gives every basket its own ``basket_track_id``
so the ledger can record a relationship between two identities rather than
saying the product turned into the basket:

    {"product_id": "bottle#1", "product_track_id": 7,
     "basket_track_id": 3, "event": "PLACED_IN_BASKET"}

Two sources, in priority order:

  1. a ``basket`` class in the YOLO model, tracked with its own ByteTrack, so
     the basket survives the products moving in front of it;
  2. the drawn ROI region, which gets a stable per-session id (``roi#1``) so the
     relationship column is populated either way.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

from .detection import RawDetection
from .geometry import BBox
from .tracking import ByteTracker, Detection

ROI_ID_BASE = 100_000  # drawn regions get ids that cannot clash with ByteTrack's


@dataclass
class BasketIdentity:
    basket_track_id: int
    source: str  # "yolo" | "roi"
    box: BBox
    first_seen: float
    last_seen: float
    contents: list[str] = field(default_factory=list)  # product_ids
    active: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "basket_track_id": self.basket_track_id,
            "source": self.source,
            "active": self.active,
            "box": self.box.as_list(),
            "first_seen": round(self.first_seen, 3),
            "last_seen": round(self.last_seen, 3),
            "contents": list(self.contents),
        }


# All basket classes share one id so any basket kind associates with any other
# rather than being tracked as separate species.
BASKET_CLASS_ID = -1


class BasketTracker:
    def __init__(
        self,
        high_threshold: float = 0.4,
        low_threshold: float = 0.1,
        match_threshold: float = 0.3,
        max_age: int = 30,
    ) -> None:
        self.tracker = ByteTracker(
            high_threshold=high_threshold,
            low_threshold=low_threshold,
            match_threshold=match_threshold,
            second_match_threshold=0.15,
            max_age=max_age,
        )
        self.ids = itertools.count(1)
        self.identities: dict[int, BasketIdentity] = {}
        self._roi_id: int | None = None

    def update(
        self,
        detections: list[RawDetection],
        roi_box: BBox | None,
        ts: float,
    ) -> tuple[BBox | None, int | None, str]:
        """Return (zone, basket_track_id, source).

        The zone is the union of every tracked basket, so several baskets in
        frame are all usable, while `basket_track_id` is the largest one - the
        one a carried product is most likely heading into.
        """
        dets = [
            Detection(BASKET_CLASS_ID, d.class_name, d.bbox, d.score) for d in detections
        ]
        tracks = self.tracker.update(dets) if dets else []
        alive = [t for t in tracks if not t.predicted]

        for t in alive:
            ident = self.identities.get(t.track_id)
            if ident is None:
                self.identities[t.track_id] = BasketIdentity(
                    basket_track_id=t.track_id,
                    source="yolo",
                    box=t.bbox,
                    first_seen=ts,
                    last_seen=ts,
                )
            else:
                ident.box = t.bbox
                ident.last_seen = ts

        if alive:
            # a detected basket supersedes the drawn fallback region
            self._retire_roi()
            largest = max(alive, key=lambda t: t.bbox.area)
            zone = largest.bbox
            for t in alive[1:]:
                if t.bbox.area > zone.area:
                    zone = BBox(
                        min(zone.x1, t.bbox.x1),
                        min(zone.y1, t.bbox.y1),
                        max(zone.x2, t.bbox.x2),
                        max(zone.y2, t.bbox.y2),
                    )
            return zone, largest.track_id, "yolo"

        if roi_box is not None:
            # one stable identity for the drawn region for the whole session -
            # minting a new id per frame would make the relationship column noise.
            # Drawn regions live in a separate id range so they can never collide
            # with a ByteTrack id from a detected basket class.
            if self._roi_id is None or self._roi_id not in self.identities:
                self._roi_id = ROI_ID_BASE + next(self.ids)
                self.identities[self._roi_id] = BasketIdentity(
                    basket_track_id=self._roi_id,
                    source="roi",
                    box=roi_box,
                    first_seen=ts,
                    last_seen=ts,
                )
            else:
                ident = self.identities[self._roi_id]
                ident.box = roi_box
                ident.last_seen = ts
            return roi_box, self._roi_id, "roi"

        return None, None, "none"

    def _retire_roi(self) -> None:
        """Drop the drawn-region identity once a real basket is being detected."""
        if self._roi_id is not None:
            ident = self.identities.pop(self._roi_id, None)
            if ident is not None:
                ident.active = False
            self._roi_id = None

    def add_contents(self, basket_track_id: int | None, product_id: str) -> None:
        if basket_track_id is None:
            return
        ident = self.identities.get(basket_track_id)
        if ident is not None and product_id not in ident.contents:
            ident.contents.append(product_id)

    def snapshot(self, include_inactive: bool = False) -> list[dict[str, Any]]:
        return [
            i.as_dict()
            for i in sorted(self.identities.values(), key=lambda i: i.first_seen)
            if include_inactive or i.active
        ]