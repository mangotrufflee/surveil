from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent


class ThresholdSettings(BaseSettings):
    """Product state-machine thresholds. All values mirror refernces/surveil.docx."""

    model_config = SettingsConfigDict(env_prefix="SURVEIL_T_", env_file=".env", extra="ignore")

    # ON_SHELF -> LIFTING
    shelf_displacement_px: float = 60.0
    settle_frames: int = 15
    # Frame-to-frame movement still counts as "not moving". Must tolerate YOLO
    # box jitter on a live feed; too tight and the shelf anchor never settles.
    settle_motion_px: float = 8.0
    hand_touch_px: float = 20.0
    hand_touch_min_overlap: float = 0.05

    # LIFTING -> IN_HAND
    lift_confirm_frames: int = 5

    # IN_HAND -> RETURNING -> ON_SHELF
    return_confirm_frames: int = 5

    # IN_HAND -> IN_BASKET
    basket_overlap_ratio: float = 0.5
    basket_confirm_frames: int = 4
    # A product that was IN_HAND and overlapping the basket is recorded as
    # PLACED_IN_BASKET (flagged inferred) when it becomes occluded, instead of
    # being reported as a lost track.
    infer_basket_on_occlusion: bool = True

    # TOUCH (RetailAction TOUCH parity, does not move the product)
    touch_emit_frames: int = 2

    # tracking lifetime
    max_missed_frames: int = 30
    mark_lost_state: bool = True
    lost_emit_event: bool = True


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SURVEIL_",
        env_file=(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "surveil"
    api_prefix: str = "/api"

    # ---- camera / source -------------------------------------------------
    camera_source: str = "0"
    frame_width: int = 640
    frame_height: int = 480
    capture_fps_target: int = 30
    stream_jpeg_quality: int = 70

    # ---- product detection ---------------------------------------------
    yolo_model: str = "yolo11n.pt"
    yolo_conf: float = 0.35
    yolo_iou: float = 0.5
    yolo_imgsz: int = 640
    yolo_device: str = ""
    yolo_half: bool = False

    # HARD REQUIREMENT (docx): the PERSON class must never be boxed or highlighted.
    ignored_classes: list[str] = Field(
        default_factory=lambda: ["person", "people", "human", "hand", "face"]
    )
    hand_class_names: list[str] = Field(default_factory=lambda: ["hand"])
    basket_class_names: list[str] = Field(
        default_factory=lambda: ["basket", "shopping_basket", "shopping basket", "tote", "tote bag"]
    )

    # ---- tracking --------------------------------------------------------
    tracker_high_threshold: float = 0.5
    tracker_low_threshold: float = 0.1
    # IoU gates for the two ByteTrack association passes. The first pass is 0.3
    # rather than the paper's 0.5: a product carried off a shelf moves ~20px per
    # frame, which on a typical box puts IoU just under 0.5, and a missed match
    # costs a new track id (and a reset shelf anchor). The second pass is
    # stricter, so recovering a partially occluded product needs a clear overlap.
    tracker_match_threshold: float = 0.3
    tracker_second_match_threshold: float = 0.15

    # How long a product identity is held after the tracker lets it go, so a
    # later detection can be re-associated onto the same product_id. This is the
    # ceiling on "we can still tell which product that was" - beyond it the
    # identity is explicitly released and a new product_id is minted.
    identity_hold_seconds: float = 300.0
    # A new track id is only re-associated onto an existing product when the
    # combined evidence clears this bar.
    identity_min_score: float = 0.42
    # Hard spatial ceiling for re-association, unless interaction history is
    # decisive (see registry.HISTORY_GATE_BYPASS). Carrying an item to a basket
    # routinely exceeds any sane pixel gate, so this is deliberately soft.
    identity_max_reassociate_distance_px: float = 260.0
    # If the best and second-best candidates score within this margin the match
    # is ambiguous: two identical products are on the shelf and we cannot tell
    # which one came back. We refuse to merge and report the uncertainty rather
    # than silently guessing.
    identity_ambiguity_margin: float = 0.08

    # ---- hand detection (victordibia/handtracking) ----------------------
    # auto | onnx | pose | mediapipe | off
    hand_backend: str = "auto"
    hand_onnx_path: Path = REPO_ROOT / "backend" / "models" / "hand_ssd_mobilenet.onnx"
    hand_label_map_path: Path = (
        REPO_ROOT / "vendor" / "handtracking" / "hand_inference_graph" / "hand_label_map.pbtxt"
    )
    hand_input_size: int = 300
    hand_conf_threshold: float = 0.27
    hand_nms_iou: float = 0.4
    hand_max_detections: int = 10
    hand_enabled: bool = True

    # pose fallback: wrist keypoints (COCO idx 9/10) as a hand-box proxy
    pose_model: str = "yolo11n-pose.pt"
    pose_wrist_conf: float = 0.4
    pose_hand_box_size: float = 90.0

    # ---- basket zone -----------------------------------------------------
    # Preferred source is a `basket` class in the YOLO model. Stock COCO has no
    # such class, so this normalised [x, y, w, h] region is the working
    # fallback; redraw it on the live feed for the actual shelf.
    basket_roi: list[float] | None = Field(default_factory=lambda: [0.66, 0.58, 0.32, 0.40])

    # ---- ledger ----------------------------------------------------------
    db_path: Path = REPO_ROOT / "data" / "surveil.db"
    auto_start_pipeline: bool = True
    unaccounted_alert_seconds: float = 90.0
    # How long an unresolved alert stays on the owner's dashboard before it drops
    # off. Nothing is deleted from the ledger - this is only how long an
    # unattended alert keeps competing for space with newer ones.
    alert_max_age_seconds: float = 300.0

    thresholds: ThresholdSettings = Field(default_factory=ThresholdSettings)

    # ---- derived helpers -------------------------------------------------
    @field_validator("ignored_classes", "hand_class_names", "basket_class_names", "basket_roi", mode="before")
    @classmethod
    def _split_csv(cls, value: Any) -> Any:
        if isinstance(value, str):
            parts = [p.strip() for p in value.split(",") if p.strip()]
            if not parts:
                return None
            return parts
        return value

    @field_validator("camera_source")
    @classmethod
    def _strip_source(cls, value: str) -> str:
        return value.strip()

    @property
    def camera_source_value(self) -> int | str:
        raw = self.camera_source
        if raw.isdigit():
            return int(raw)
        return raw

    def resolved_source(self) -> int | Path:
        """Camera index for a numeric source, otherwise a usable file path.

        A relative path is tried as given and then relative to the repo root, so
        `data/demo_clip.mp4` works no matter which directory the server was
        started from. Falls back to the original string if nothing matches, so
        the camera layer can report a proper "cannot open source" error.
        """
        raw = self.camera_source
        if raw.isdigit():
            return int(raw)
        candidate = Path(raw)
        if candidate.exists():
            return candidate.resolve()
        from_root = REPO_ROOT / raw
        if from_root.exists():
            return from_root.resolve()
        return raw

    def dump(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        return data


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.thresholds = ThresholdSettings()
    return settings


def reset_settings_cache() -> None:
    get_settings.cache_clear()