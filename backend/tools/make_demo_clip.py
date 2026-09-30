"""Generate a short test clip so the pipeline can be exercised without a webcam.

    .venv\\Scripts\\python tools\\make_demo_clip.py --out data/demo_clip.mp4

Point the pipeline at the result with:
    SURVEIL_CAMERA_SOURCE=data/demo_clip.mp4
or from the UI's "Video source" field.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = REPO_ROOT / "vendor" / "handtracking" / "handtrack" / "utils" / "test_image.jpeg"
DEFAULT_OUT = REPO_ROOT / "data" / "demo_clip.mp4"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--frames", type=int, default=120)
    parser.add_argument("--fps", type=float, default=12.0)
    args = parser.parse_args()

    if not args.image.exists():
        print(f"error: {args.image} not found. Pass --image <path>.")
        return 1

    image = cv2.imread(str(args.image))
    if image is None:
        print(f"error: could not read {args.image}")
        return 1
    h, w = image.shape[:2]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(args.out), cv2.VideoWriter_fourcc(*"mp4v"), args.fps, (w, h)
    )
    if not writer.isOpened():
        print(f"error: could not open {args.out} for writing")
        return 1

    # A slow zoom + pan so the tracked objects genuinely move between frames.
    for i in range(args.frames):
        t = i / max(1, args.frames - 1)
        scale = 1.0 - 0.18 * t
        nw, nh = int(w * scale), int(h * scale)
        zoomed = cv2.resize(image, (nw, nh))
        ox, oy = int((w - nw) * t), int((h - nh) * 0.5 * t)
        frame = np.zeros_like(image)
        frame[oy : oy + nh, ox : ox + nw] = zoomed
        writer.write(frame)

    writer.release()
    print(f"wrote {args.out} ({args.frames} frames, {args.out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
