"""Overlay renderer for the live monitor.

Hard requirement from the document: the ``person`` class is never boxed or
highlighted. Ignored detections are accepted here only so the HUD can *count*
them ("people in frame: n, not tracked") - they are never drawn.
"""

from __future__ import annotations

import time
from typing import Any

import cv2
import numpy as np

from .geometry import BBox
from .interaction import ProductState

STATE_COLORS: dict[ProductState, tuple[int, int, int]] = {
    ProductState.ON_SHELF: (60, 200, 60),
    ProductState.LIFTING: (0, 200, 255),
    ProductState.IN_HAND: (0, 140, 255),
    ProductState.RETURNING: (255, 180, 0),
    ProductState.IN_BASKET: (255, 80, 200),
    ProductState.LOST: (60, 60, 235),
}

HAND_COLOR = (240, 240, 240)
BASKET_COLOR = (255, 255, 0)
ANCHOR_COLOR = (180, 180, 180)

FONT = cv2.FONT_HERSHEY_SIMPLEX


def _text(img: np.ndarray, value: str, org: tuple[int, int], scale: float,
          color: tuple[int, int, int], thickness: int = 1) -> None:
    cv2.putText(img, value, org, FONT, scale, (0, 0, 0), thickness + 2, cv2.LINE_AA)
    cv2.putText(img, value, org, FONT, scale, color, thickness, cv2.LINE_AA)


def _dashed_rect(img: np.ndarray, box: BBox, color: tuple[int, int, int],
                 dash: int = 8, thickness: int = 1) -> None:
    x1, y1, x2, y2 = box.as_int().to_xyxy()
    x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
    for x in range(x1, x2, dash * 2):
        cv2.line(img, (x, y1), (min(x + dash, x2), y1), color, thickness)
        cv2.line(img, (x, y2), (min(x + dash, x2), y2), color, thickness)
    for y in range(y1, y2, dash * 2):
        cv2.line(img, (x1, y), (x1, min(y + dash, y2)), color, thickness)
        cv2.line(img, (x2, y), (x2, min(y + dash, y2)), color, thickness)


def render(
    frame: np.ndarray,
    tracks: list[dict[str, Any]],
    hands: list[dict[str, Any]],
    basket_zone: BBox | None,
    hud: dict[str, Any],
    ignored_count: int = 0,
    events_recent: list[dict[str, Any]] | None = None,
) -> np.ndarray:
    img = frame.copy()
    height, width = img.shape[:2]

    # The event ticker is drawn along the bottom edge; product labels must stay
    # above it or they get drawn on top of the ticker text.
    ticker_rows = min(6, len(events_recent or []))
    ticker_top = height - 14 - 20 * ticker_rows
    label_floor = ticker_top - 4

    # ---- basket zone --------------------------------------------------
    if basket_zone is not None:
        box = basket_zone.as_int().to_xyxy()
        cv2.rectangle(img, (box[0], box[1]), (box[2], box[3]), BASKET_COLOR, 2)
        _text(img, "BASKET ZONE", (box[0] + 6, max(14, box[1] - 8)), 0.45, BASKET_COLOR, 1)

    # ---- hands (drawn, but never as products) --------------------------
    for hand in hands:
        x1, y1, x2, y2 = hand["box"]
        cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), HAND_COLOR, 1)
        label = f"hand {hand['hand_id']} / {hand['customer_id']}"
        _text(img, label, (int(x1), max(12, int(y1) - 6)), 0.42, HAND_COLOR, 1)

    # ---- products ------------------------------------------------------
    for track in tracks:
        box = track["box"]
        if box is None:
            continue
        x1, y1, x2, y2 = (int(v) for v in box)
        state = track["state"]
        color = STATE_COLORS.get(ProductState(state), (200, 200, 200))
        thickness = 3 if state != ProductState.ON_SHELF.value else 2
        cv2.rectangle(img, (x1, y1), (x2, y2), color, thickness)

        anchor = track.get("anchor")
        if anchor and track.get("displaced"):
            ax, ay, bx, by = anchor
            cv2.line(img, (int(ax), int(ay)), (int(bx), int(by)), ANCHOR_COLOR, 1, cv2.LINE_AA)
            cv2.circle(img, (int(ax), int(ay)), 3, ANCHOR_COLOR, -1)

        name = track["product_name"][:18]
        head = f"{name} #{track['track_id']} {state}"
        _text(img, head, (x1, max(14, y1 - 22)), 0.48, color, 1)
        detail: list[str] = []
        if not track.get("anchor_confirmed"):
            detail.append(f"settling {track.get('settle_frames', 0)}")
        if track.get("touching"):
            detail.append("touch")
        if track.get("displaced"):
            detail.append(f"{track.get('displacement_px', 0):.0f}px")
        if detail:
            detail_y = y2 + 16
            if detail_y > label_floor:
                detail_y = max(14, y1 - 40)  # no room below: put it above the box
            _text(img, " | ".join(detail), (x1, detail_y), 0.42, color, 1)

    # ---- event ticker --------------------------------------------------
    y = ticker_top + 14
    for ev in (events_recent or [])[-6:]:
        _text(
            img,
            f"{time.strftime('%H:%M:%S', time.localtime(ev['ts']))}  {ev['type']:<17} "
            f"{ev['product_name']} #{ev.get('track_id')}",
            (10, max(16, y)),
            0.5,
            (255, 255, 255),
            1,
        )
        y += 20

    # ---- HUD -----------------------------------------------------------
    panel = 210
    overlay = img.copy()
    cv2.rectangle(overlay, (0, 0), (panel, 104), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.55, img, 0.45, 0, img)
    rows = [
        f"fps {hud.get('fps', 0):.1f}   frame {hud.get('frame', 0)}",
        f"yolo {hud.get('infer_ms', 0):.0f}ms  hands {hud.get('hand_ms', 0):.0f}ms",
        f"products {hud.get('product_count', 0)}  hands {hud.get('hand_count', 0)}",
        f"people in frame {ignored_count} (not tracked)",
        f"session {hud.get('session_id', '-')}",
        f"displace>{hud.get('shelf_displacement_px', 0):.0f}px  confirm {hud.get('lift_confirm_frames', 0)}f"
        f"  basket {hud.get('basket_overlap_ratio', 0):.2f}x{hud.get('basket_confirm_frames', 0)}f",
    ]
    for i, row in enumerate(rows):
        _text(img, row, (8, 16 + i * 16), 0.42, (235, 235, 235), 1)

    return img