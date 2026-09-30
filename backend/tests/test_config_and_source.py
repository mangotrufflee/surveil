"""Config and video-source tests."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import REPO_ROOT, Settings  # noqa: E402
from app.camera import CameraSource  # noqa: E402


def test_numeric_source_is_a_camera_index():
    s = Settings(camera_source="0")
    assert s.resolved_source() == 0
    s.camera_source = "2"
    assert s.resolved_source() == 2


def test_existing_relative_path_resolves():
    s = Settings(camera_source="data/demo_clip.mp4")
    resolved = s.resolved_source()
    assert isinstance(resolved, Path)
    # resolves to the repo-root copy so the server works from any cwd
    assert resolved.exists(), "run backend/tools/make_demo_clip.py first"
    assert resolved == (REPO_ROOT / "data" / "demo_clip.mp4").resolve()


def test_missing_file_is_passed_through_for_a_proper_error(tmp_path: Path):
    s = Settings(camera_source="nope/does-not-exist.mp4")
    assert s.resolved_source() == "nope/does-not-exist.mp4"


def test_camera_reports_an_unopenable_source():
    cam = CameraSource("definitely/not/here.mp4", width=64, height=48)
    cam.start()
    import time

    time.sleep(1.5)
    assert cam.error is not None
    assert "cannot open video source" in cam.error
    assert cam.read() is None
    cam.stop()


def test_ignored_classes_default_includes_person():
    s = Settings()
    assert "person" in [c.lower() for c in s.ignored_classes]
    # the YOLO hand class must not double-count as a product
    assert "hand" in [c.lower() for c in s.ignored_classes]


def test_csv_parsing_of_list_settings(monkeypatch=None):
    s = Settings(ignored_classes="person, human ,")
    assert s.ignored_classes == ["person", "human"]


def test_thresholds_match_the_specification():
    s = Settings()
    t = s.thresholds
    assert t.shelf_displacement_px == 60
    assert t.settle_frames == 15
    assert t.lift_confirm_frames == 5
    assert t.return_confirm_frames == 5
    assert t.basket_confirm_frames == 4
    assert t.basket_overlap_ratio == 0.5
    assert t.max_missed_frames == 30


if __name__ == "__main__":
    raise SystemExit(__import__("pytest").main([__file__, "-q"]))
