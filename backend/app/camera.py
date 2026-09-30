"""Video source with a grab-and-drop latest-frame buffer.

Reading from a webcam is heavy I/O, so capture runs on its own thread and the
inference loop always takes the newest available frame (frame dropping keeps the
latency bounded under load).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class FramePacket:
    index: int
    timestamp: float
    image: np.ndarray


class CameraSource:
    def __init__(
        self,
        source: int | str,
        width: int = 640,
        height: int = 480,
        target_fps: int = 30,
    ) -> None:
        self.source = source
        self.width = width
        self.height = height
        self.target_fps = target_fps
        self._cap: cv2.VideoCapture | None = None
        self._frame: FramePacket | None = None
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self.error: str | None = None
        self.fps = 0.0

    # ----------------------------------------------------------------- control
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="camera")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        cap, self._cap = self._cap, None
        if cap is not None:
            cap.release()

    @property
    def running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------ frame
    def read(self, last_index: int | None = None) -> FramePacket | None:
        with self._lock:
            frame = self._frame
        if frame is None:
            return None
        if last_index is not None and frame.index <= last_index:
            return None
        return frame

    @property
    def latest(self) -> FramePacket | None:
        with self._lock:
            return self._frame

    @property
    def size(self) -> tuple[int, int]:
        with self._lock:
            if self._frame is not None:
                return self._frame.image.shape[1], self._frame.image.shape[0]
        return self.width, self.height

    # ------------------------------------------------------------------- loop
    def _open(self) -> cv2.VideoCapture | None:
        cap = cv2.VideoCapture(self.source)
        if not cap.isOpened():
            cap.release()
            self.error = f"cannot open video source: {self.source!r}"
            return None
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        try:
            cap.set(cv2.CAP_PROP_FPS, self.target_fps)
        except cv2.error:  # pragma: no cover
            pass
        self.error = None
        return cap

    def _loop(self) -> None:
        index = 0
        last_ts = time.time()
        while self._running:
            if self._cap is None:
                self._cap = self._open()
                if self._cap is None:
                    time.sleep(1.0)
                    continue
            ok, image = self._cap.read()
            if not ok or image is None:
                self._cap.release()
                self._cap = None
                time.sleep(0.3)
                continue
            index += 1
            packet = FramePacket(index=index, timestamp=time.time(), image=image)
            with self._lock:
                self._frame = packet
            now = time.time()
            # Clamp the interval: a file source decodes faster than 1us apart,
            # which would otherwise produce an absurd capture-rate figure.
            dt = min(max(now - last_ts, 1.0 / 240.0), 1.0)
            self.fps = 0.9 * self.fps + 0.1 * (1.0 / dt)
            last_ts = now