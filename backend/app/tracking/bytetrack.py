"""Class-aware ByteTrack (Zhang et al., ECCV 2022) implemented on numpy only.

ByteTrack associates high-confidence detections first, then performs a *second*
association pass with low-confidence detections so that objects which are
partially occluded (for example a product covered by a hand) keep their identity.

Implemented directly rather than pulled from a tracker package because we need
    * per-class association, so a bottle never inherits a cup's track id,
    * hard exclusion of ignored classes (person) from the tracker state,
    * the tracker lifetime (`max_missed_frames`) to be shared with the product
      state machine that consumes the track ids.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..geometry import BBox, greedy_match, iou_candidates


class KalmanBox:
    """Constant-velocity Kalman filter over an axis-aligned box.

    The velocity process noise is deliberately generous. A product carried away
    from a shelf moves far faster than the filter's initial zero-velocity prior
    expects; with a tight prior the prediction lags, IoU against the next
    detection drops below the match gate and the object gets a second track id.
    """

    _F = np.eye(8, dtype=np.float64)
    _F[0, 4] = _F[1, 5] = _F[2, 6] = _F[3, 7] = 1.0
    _H = np.zeros((4, 8), dtype=np.float64)
    _H[0, 0] = _H[1, 1] = _H[2, 2] = _H[3, 3] = 1.0
    _Q = np.diag(np.array([2.0, 2.0, 1.0, 1.0, 0.05, 0.05, 0.05, 0.05]) ** 2)
    _R = np.eye(4, dtype=np.float64) * 1.0
    _I = np.eye(8, dtype=np.float64)

    def __init__(self, bbox: BBox | None = None) -> None:
        self.x = np.zeros(8, dtype=np.float64)
        self.p = np.eye(8, dtype=np.float64) * 10.0
        if bbox is not None:
            self.x[:4] = np.array(
                [bbox.center[0], bbox.center[1], bbox.width, bbox.height], dtype=np.float64
            )

    def predict(self) -> BBox:
        self.x = self._F @ self.x
        self.p = self._F @ self.p @ self._F.T + self._Q
        return self.to_bbox()

    def update(self, bbox: BBox) -> None:
        z = np.array(
            [bbox.center[0], bbox.center[1], bbox.width, bbox.height], dtype=np.float64
        )
        y = z - self._H @ self.x
        s = self._H @ self.p @ self._H.T + self._R
        k = self.p @ self._H.T @ np.linalg.inv(s)
        self.x = self.x + k @ y
        self.p = (self._I - k @ self._H) @ self.p

    def to_bbox(self) -> BBox:
        cx, cy, w, h = self.x[:4]
        w = max(float(w), 1.0)
        h = max(float(h), 1.0)
        return BBox(float(cx - w / 2), float(cy - h / 2), float(cx + w / 2), float(cy + h / 2))


@dataclass
class Detection:
    class_id: int
    class_name: str
    bbox: BBox
    score: float


# Detection status of a track in a given frame. Explicit so callers never have to
# infer it from `time_since_update`, and so "the tracker still owns this object"
# is distinguishable from "the detector currently sees this object".
STATUS_OBSERVED = "observed"
STATUS_COASTING = "coasting"


@dataclass
class TrackResult:
    track_id: int
    class_id: int
    class_name: str
    bbox: BBox
    score: float
    predicted: bool
    time_since_update: int
    hits: int
    status: str = STATUS_OBSERVED
    observed: bool = True

    @property
    def coasting(self) -> bool:
        return not self.observed


@dataclass
class Track:
    track_id: int
    class_id: int
    class_name: str
    kf: KalmanBox
    score: float = 0.0
    hits: int = 1
    time_since_update: int = 0

    @property
    def bbox(self) -> BBox:
        return self.kf.to_bbox()


class ByteTracker:
    """Two-stage ByteTrack with per-class IoU association."""

    def __init__(
        self,
        high_threshold: float = 0.5,
        low_threshold: float = 0.1,
        match_threshold: float = 0.3,
        second_match_threshold: float = 0.15,
        max_age: int = 30,
    ) -> None:
        self.high_threshold = high_threshold
        self.low_threshold = low_threshold
        self.match_threshold = match_threshold
        self.second_match_threshold = second_match_threshold
        self.max_age = max_age
        self.tracks: list[Track] = []
        self._next_id = 1
        self.frame_index = 0
        self._matched: set[int] = set()

    def reset(self) -> None:
        self.tracks.clear()
        self._next_id = 1
        self.frame_index = 0
        self._matched.clear()

    def _spawn(self, det: Detection) -> Track:
        track = Track(
            track_id=self._next_id,
            class_id=det.class_id,
            class_name=det.class_name,
            kf=KalmanBox(det.bbox),
            score=det.score,
        )
        self._next_id += 1
        self.tracks.append(track)
        return track

    def update(self, detections: list[Detection]) -> list[TrackResult]:
        self.frame_index += 1
        self._matched = set()

        for track in self.tracks:
            track.kf.predict()

        high = [d for d in detections if d.score >= self.high_threshold]
        low = [d for d in detections if self.low_threshold <= d.score < self.high_threshold]

        # ---- first association: high-score detections ---------------------
        unmatched_tracks = list(self.tracks)
        consumed_high: set[int] = set()
        if high and unmatched_tracks:
            pairs = iou_candidates(
                [t.bbox for t in unmatched_tracks],
                [d.bbox for d in high],
                class_ids=[d.class_id for d in high],
                track_classes=[t.class_id for t in unmatched_tracks],
            )
            matches, used_tracks, used_dets = greedy_match(pairs, self.match_threshold)
            for ti, di in matches:
                track = unmatched_tracks[ti]
                track.kf.update(high[di].bbox)
                track.score = high[di].score
                track.hits += 1
                track.time_since_update = 0
                self._matched.add(track.track_id)
                consumed_high.add(di)
            unmatched_tracks = [t for i, t in enumerate(unmatched_tracks) if i not in used_tracks]

        # ---- second association: low-score detections ---------------------
        if low and unmatched_tracks:
            pairs = iou_candidates(
                [t.bbox for t in unmatched_tracks],
                [d.bbox for d in low],
                class_ids=[d.class_id for d in low],
                track_classes=[t.class_id for t in unmatched_tracks],
            )
            matches, used_tracks, _ = greedy_match(pairs, self.second_match_threshold)
            for ti, di in matches:
                track = unmatched_tracks[ti]
                track.kf.update(low[di].bbox)
                track.score = low[di].score
                track.hits += 1
                track.time_since_update = 0
                self._matched.add(track.track_id)

        # ---- spawn tracks for unmatched high-score detections -------------
        for di, det in enumerate(high):
            if di not in consumed_high:
                self._spawn(det)
                # a track born this frame is observed, not predicted
                self._matched.add(self.tracks[-1].track_id)

        # ---- age out stale tracks ----------------------------------------
        # A track is dropped on its max_age'th missed frame, so
        # `max_missed_frames = 30` means "30 frames without a detection".
        for track in self.tracks:
            if track.track_id not in self._matched:
                track.time_since_update += 1
        self.tracks = [t for t in self.tracks if t.time_since_update < self.max_age]

        return [
            TrackResult(
                track_id=t.track_id,
                class_id=t.class_id,
                class_name=t.class_name,
                bbox=t.bbox,
                score=t.score,
                predicted=t.time_since_update > 0,
                time_since_update=t.time_since_update,
                hits=t.hits,
                status=STATUS_OBSERVED if t.time_since_update == 0 else STATUS_COASTING,
                observed=t.time_since_update == 0,
            )
            for t in self.tracks
        ]

    def get(self, track_id: int) -> Track | None:
        for t in self.tracks:
            if t.track_id == track_id:
                return t
        return None