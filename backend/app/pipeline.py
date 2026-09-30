"""The CV pipeline: camera -> YOLO -> ByteTrack -> hands -> interaction engine -> ledger."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from . import overlay
from .camera import CameraSource
from .config import Settings
from .detection import FrameDetections, ProductDetector
from .hand_tracking import HandIdentityTracker
from .hands import HandBox, build_hand_detector
from .interaction import EventType, InteractionEngine, ProductState
from .ledger import Ledger
from .tracking import ByteTracker


@dataclass
class PipelineStatus:
    running: bool = False
    session_id: str | None = None
    frame: int = 0
    fps: float = 0.0
    started_at: float | None = None
    error: str | None = None
    model: str = ""
    hand_backend: str = "off"
    product_classes: list[str] = field(default_factory=list)
    ignored_classes: list[str] = field(default_factory=list)
    basket_mode: str = "yolo"
    processed_frames: int = 0


class Pipeline:
    """Owns all CV state for one camera session.

    `detector`, `hand_detector` and `camera` can be injected. That keeps the
    orchestration (tracking -> interaction engine -> ledger -> overlay) testable
    offline, without a camera or model weights.
    """

    def __init__(
        self,
        settings: Settings,
        ledger: Ledger,
        detector: ProductDetector | None = None,
        hand_detector: Any | None = None,
        camera: CameraSource | None = None,
    ) -> None:
        self.settings = settings
        self.ledger = ledger
        self.status = PipelineStatus(
            model=settings.yolo_model,
            ignored_classes=list(settings.ignored_classes),
        )

        self._injected_detector = detector
        self._injected_hand_detector = hand_detector
        self._injected_camera = camera

        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._running = False
        self._session_id: str | None = None

        self.camera: CameraSource | None = None
        self.detector: ProductDetector | None = None
        self.hand_detector = None
        self.tracker: ByteTracker | None = None
        self.engine: InteractionEngine | None = None
        self.hand_tracker: HandIdentityTracker | None = None

        self._frame_jpeg: bytes | None = None
        self._snapshot: dict[str, Any] = self._empty_snapshot()
        self._events: list[dict[str, Any]] = []
        self._frame_lock = threading.Lock()

    # ------------------------------------------------------------------ status
    @property
    def running(self) -> bool:
        return self._running

    def _empty_snapshot(self) -> dict[str, Any]:
        return {
            "running": False,
            "session_id": None,
            "frame": 0,
            "fps": 0.0,
            "timestamp": time.time(),
            "frame_size": [self.settings.frame_width, self.settings.frame_height],
            "products": [],
            "hands": [],
            "basket_zone": None,
            "basket_source": "none",
            "ignored_count": 0,
            "ignored_classes": list(self.settings.ignored_classes),
            "states": {},
            "hud": {},
            "recent_events": [],
            "thresholds": self.settings.thresholds.model_dump(mode="json"),
        }

    def status_dict(self) -> dict[str, Any]:
        s = self.status
        return {
            "running": s.running,
            "session_id": s.session_id,
            "frame": s.frame,
            "fps": round(s.fps, 2),
            "started_at": s.started_at,
            "uptime_s": round(time.time() - s.started_at, 1) if s.started_at else 0.0,
            "error": s.error,
            "model": s.model,
            "hand_backend": s.hand_backend,
            "product_classes": s.product_classes,
            "ignored_classes": s.ignored_classes,
            "basket_mode": s.basket_mode,
            "processed_frames": s.processed_frames,
            "camera_source": self.settings.camera_source,
        }

    # ------------------------------------------------------------------ control
    def begin_session(self, session_id: str) -> None:
        """Initialise every piece of per-session CV state (no I/O).

        Split out of :meth:`start` so an offline driver can set up a session and
        push frames through :meth:`_process` without a camera thread.
        """
        settings = self.settings
        self.session_id = session_id
        self._session_id = session_id
        self.status.session_id = session_id
        self.status.error = None
        self.tracker = ByteTracker(
            high_threshold=settings.tracker_high_threshold,
            low_threshold=settings.tracker_low_threshold,
            match_threshold=settings.tracker_match_threshold,
            second_match_threshold=settings.tracker_second_match_threshold,
            max_age=settings.thresholds.max_missed_frames,
        )
        self.engine = InteractionEngine(settings.thresholds, session_id)
        self.hand_tracker = HandIdentityTracker(session_id)
        # must reset, otherwise the new session's throughput is computed against
        # the previous session's frame count and readiness checks pass instantly
        self.status.processed_frames = 0
        self.status.fps = 0.0
        self.status.frame = 0
        self._events.clear()

    def start(self, source: str | None = None) -> None:
        with self._lock:
            if self._running:
                return

            settings = self.settings
            if source is not None:
                settings.camera_source = source.strip()

            self.begin_session(f"S{int(time.time())}-{uuid.uuid4().hex[:4]}")

            try:
                self.detector = self._injected_detector or ProductDetector(settings)
                self.status.product_classes = [
                    n for n in self.detector.class_names()
                    if n.lower() not in {c.lower() for c in settings.ignored_classes}
                    and n.lower() not in {c.lower() for c in settings.basket_class_names}
                ]
            except Exception as exc:  # noqa: BLE001
                self.status.error = f"YOLO load failed: {exc}"
                return

            if self._injected_hand_detector is not None:
                self.hand_detector = self._injected_hand_detector
                self.status.hand_backend = getattr(self.hand_detector, "name", "injected")
            else:
                try:
                    self.hand_detector = build_hand_detector(settings)
                    self.status.hand_backend = self.hand_detector.name
                except Exception as exc:  # noqa: BLE001
                    self.hand_detector = None
                    self.status.hand_backend = "off"
                    self.status.error = (self.status.error + f" | hands off: {exc}").strip(" |")

            self.camera = self._injected_camera or CameraSource(
                settings.resolved_source(),
                width=settings.frame_width,
                height=settings.frame_height,
                target_fps=settings.capture_fps_target,
            )
            self.camera.start()

            self._running = True
            self.status.running = True
            self.status.started_at = time.time()
            self.status.basket_mode = "yolo" if self.detector.product_class_ids() else "roi"
            self.ledger.open_session(
                self.session_id,
                str(settings.camera_source),
                {"yolo_model": settings.yolo_model, "hand_backend": self.status.hand_backend},
            )

            self._thread = threading.Thread(target=self._loop, daemon=True, name="pipeline")
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        if self.camera:
            self.camera.stop()
        self.camera = None
        if self.hand_detector:
            self.hand_detector.close()
        self.status.running = False
        if self._session_id:
            self.ledger.close_session(self._session_id)

    # -------------------------------------------------------------------- loop
    def _loop(self) -> None:
        last_index = 0
        while self._running:
            if self.camera is not None and self.camera.error:
                # surface capture failures instead of spinning silently
                self.status.error = self.camera.error
            packet = self.camera.read(last_index) if self.camera else None
            if packet is None:
                time.sleep(0.005)
                continue
            last_index = packet.index
            try:
                self._process(packet.index, packet.timestamp, packet.image)
                if self.camera is not None and not self.camera.error:
                    self.status.error = None
            except Exception as exc:  # noqa: BLE001
                self.status.error = f"frame {packet.index}: {exc}"
                time.sleep(0.05)

    def _process(self, frame_index: int, ts: float, image: np.ndarray) -> None:
        assert self.detector is not None and self.tracker is not None
        assert self.engine is not None and self.hand_tracker is not None

        det: FrameDetections = self.detector.detect(image, self.tracker)

        # ---- hands ------------------------------------------------------
        hand_ms = 0.0
        if self.hand_detector is not None:
            t0 = time.perf_counter()
            raw_hands: list[HandBox] = self.hand_detector.detect(image)
            hand_ms = (time.perf_counter() - t0) * 1000.0
        else:
            raw_hands = []
        tracked_hands = self.hand_tracker.update(raw_hands, ts)

        # ---- interaction engine ----------------------------------------
        engine_input = [
            (t.track_id, f"{t.class_name}:{t.track_id}", t.class_name, t.bbox, t.score)
            for t in det.tracks
            if not t.predicted
        ]
        hand_input = [(h.hand_id, HandBox(h.box, h.score)) for h in tracked_hands]
        new_events = self.engine.update(
            frame=frame_index,
            ts=ts,
            products=engine_input,
            hands=hand_input,
            basket_zone=det.basket_zone,
        )

        # ---- ledger ------------------------------------------------------
        if new_events:
            self.ledger.register_products(
                [(e.product_id, e.product_name, e.ts) for e in new_events]
            )
            for ev in new_events:
                uid = self.ledger.record_event(ev)
                self._events.append(
                    {
                        "event_uid": uid,
                        "type": ev.type.value,
                        "ts": ev.ts,
                        "product_id": ev.product_id,
                        "product_name": ev.product_name,
                        "track_id": ev.track_id,
                        "hand_id": ev.hand_id,
                        "session_id": ev.session_id,
                        "confidence": ev.confidence,
                        "box": ev.bbox.as_list(),
                        "state": ev.state.value,
                        "meta": ev.meta,
                    }
                )
            if len(self._events) > 200:
                self._events = self._events[-200:]

        # ---- snapshot ----------------------------------------------------
        states = self.engine.snapshot(ts)
        self.status.frame = frame_index
        self.status.processed_frames += 1
        # Throughput of the whole pipeline (capture + YOLO + hands + state
        # machine), which is the number that matters - not the camera's rate.
        if self.status.started_at:
            elapsed = max(ts - self.status.started_at, 1e-6)
            self.status.fps = self.status.processed_frames / elapsed

        snapshot = {
            "running": True,
            "session_id": self._session_id,
            "frame": frame_index,
            "fps": round(self.status.fps, 2),
            "timestamp": ts,
            "frame_size": [image.shape[1], image.shape[0]],
            "products": [
                {
                    "track_id": t.track_id,
                    "class_name": t.class_name,
                    "score": round(t.score, 3),
                    "box": t.bbox.as_list(),
                    "predicted": t.predicted,
                    "time_since_update": t.time_since_update,
                }
                for t in det.tracks
            ],
            "hands": self.hand_tracker.snapshot(),
            "basket_zone": det.basket_zone.as_list() if det.basket_zone else None,
            "basket_source": "yolo" if det.baskets else (
                "roi" if self.settings.basket_roi else "none"
            ),
            "ignored_count": len(det.ignored),
            "ignored_classes": list(self.settings.ignored_classes),
            "states": {str(s["track_id"]): s for s in states},
            "hud": {
                "fps": round(self.status.fps, 2),
                "frame": frame_index,
                "infer_ms": round(det.infer_ms, 1),
                "hand_ms": round(hand_ms, 1),
                "product_count": len(det.tracks),
                "hand_count": len(tracked_hands),
                "session_id": self._session_id,
                "shelf_displacement_px": self.settings.thresholds.shelf_displacement_px,
                "lift_confirm_frames": self.settings.thresholds.lift_confirm_frames,
                "basket_overlap_ratio": self.settings.thresholds.basket_overlap_ratio,
                "basket_confirm_frames": self.settings.thresholds.basket_confirm_frames,
            },
            "recent_events": self._events[-12:],
            "thresholds": self.settings.thresholds.model_dump(mode="json"),
        }
        with self._frame_lock:
            self._snapshot = snapshot

        # ---- annotated frame for MJPEG -----------------------------------
        rendered = overlay.render(
            image,
            states,
            snapshot["hands"],
            det.basket_zone,
            snapshot["hud"],
            ignored_count=len(det.ignored),
            events_recent=self._events[-4:],
        )
        ok, buf = cv2.imencode(
            ".jpg", rendered, [int(cv2.IMWRITE_JPEG_QUALITY), self.settings.stream_jpeg_quality]
        )
        if ok:
            with self._frame_lock:
                self._frame_jpeg = buf.tobytes()

    # ------------------------------------------------------------------ output
    def snapshot(self) -> dict[str, Any]:
        with self._frame_lock:
            return self._snapshot

    def frame_jpeg(self) -> bytes | None:
        with self._frame_lock:
            return self._frame_jpeg