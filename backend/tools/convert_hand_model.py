"""Convert the TF1 frozen hand detector from vendor/handtracking into ONNX.

The upstream model (victordibia/handtracking) is an SSD MobileNet graph frozen
with TensorFlow 1.x. TensorFlow 1 cannot be installed on a current Python, but
the *frozen graph* itself converts cleanly to ONNX, which the runtime then
executes with onnxruntime - so the production backend never imports TensorFlow.

Run it in a throwaway environment, because tensorflow pins protobuf<5 while
ultralytics wants a newer one:

    python -m venv .venv-tools
    .venv-tools\\Scripts\\pip install -r backend\\requirements-tools.txt
    .venv-tools\\Scripts\\python backend\\tools\\convert_hand_model.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HANDTRACKING_DIR = REPO_ROOT / "vendor" / "handtracking"
DEFAULT_PB = HANDTRACKING_DIR / "hand_inference_graph" / "frozen_inference_graph.pb"
DEFAULT_LABEL_MAP = HANDTRACKING_DIR / "hand_inference_graph" / "hand_label_map.pbtxt"
DEFAULT_OUT = REPO_ROOT / "backend" / "models" / "hand_ssd_mobilenet.onnx"

INPUT_NAMES = ["image_tensor:0"]
OUTPUT_NAMES = [
    "detection_boxes:0",
    "detection_scores:0",
    "detection_classes:0",
    "num_detections:0",
]
OPSET = 11


def load_graph_def(pb_path: Path):
    from tensorflow.compat.v1 import GraphDef

    graph_def = GraphDef()
    graph_def.ParseFromString(pb_path.read_bytes())
    return graph_def


def convert(pb_path: Path, out_path: Path, opset: int = OPSET) -> Path:
    import onnx
    from tf2onnx import convert

    graph_def = load_graph_def(pb_path)
    print(f"loaded {pb_path} ({len(graph_def.node)} nodes)")

    model_proto = convert.from_graph_def(
        graph_def,
        name="hand_ssd",
        input_names=INPUT_NAMES,
        output_names=OUTPUT_NAMES,
        opset=opset,
        # the frozen graph declares a fully dynamic input ([1, ?, ?, 3]); the
        # in-graph 300x300 resizer then upscales whatever arrives, so pin it to
        # the model's native size to keep the ONNX graph static and simple.
        shape_override={"image_tensor:0": [1, 300, 300, 3]},
    )
    if isinstance(model_proto, tuple):
        model_proto = model_proto[0]

    onnx.checker.check_model(model_proto)
    print("onnx.checker: model is valid")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    onnx.save_model(model_proto, str(out_path))
    print(f"wrote {out_path} ({out_path.stat().st_size / 1e6:.1f} MB)")

    label_map_out = out_path.parent / "hand_label_map.pbtxt"
    if DEFAULT_LABEL_MAP.exists():
        label_map_out.write_text(DEFAULT_LABEL_MAP.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"copied label map -> {label_map_out}")
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pb", type=Path, default=DEFAULT_PB)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--opset", type=int, default=OPSET)
    args = parser.parse_args()

    if not args.pb.exists():
        print(
            f"error: {args.pb} not found.\n"
            "Clone the model first:  git clone https://github.com/victordibia/handtracking.git vendor/handtracking",
            file=sys.stderr,
        )
        return 1

    convert(args.pb, args.out, args.opset)

    import onnxruntime as ort

    session = ort.InferenceSession(str(args.out), providers=["CPUExecutionProvider"])
    print("inputs :", [(i.name, i.shape, i.type) for i in session.get_inputs()])
    print("outputs:", [(o.name, o.shape) for o in session.get_outputs()])
    print("conversion OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
