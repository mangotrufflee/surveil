# surveil

Turns a laptop camera into **structured product-interaction events** and then
reconciles those events with sales.

YOLO detects products, ByteTrack gives each one a persistent identity, a hand
detector supplies the touch signal, and a product state machine turns all of that
into `PICKED_UP` / `PUT_BACK` / `PLACED_IN_BASKET` / `TOUCH` events in a
**Product Interaction Ledger**. Two interfaces sit on top:

| Tab | What it is | Rule |
| --- | --- | --- |
| **1 - Live CCTV Monitor** | the CV interface: annotated feed, live product states, hand identities, engine output | *observes* |
| **2 - Shop Owner Dashboard** | the business interface: detected products, purchases to confirm, unresolved alerts, the full ledger | *manages and reconciles* |

The CV system never decides on its own that something was stolen. It surfaces an
unresolved / lost-product situation and brings it to the owner for review.

---

## Architecture

```
                    laptop camera / video file
                              |
                              v
            +---------------------------------+
            |  YOLO product detection         |  person & friends are dropped
            |  (ultralytics)                  |  here, before anything else
            +---------------------------------+
                              |
              products        |        basket
                              v         |
            +---------------------------------+
            |  ByteTrack                      |  persistent track_id per product,
            |  (class-aware, 2-stage IoU)    |  Kalman motion model
            +---------------------------------+
                              |            ^
        +---------------------+            |
        v                                  |
 +--------------+                 +------------------+
 | Hand detector|  ---- touch ---> |                  |
 | (ONNX)      |                   | Interaction     |
 +--------------+                   | Engine          |
        |                           | (state machine) |
        v                           +------------------+
 +--------------+                            |
 | Hand identity|                           v
 | + customer/s |                  +----------------------+
 | session ids  |                  | Product Interaction |
 +--------------+                  | Ledger (SQLite)     |
                                   +----------------------+
                                            |
                                            v
                                   Shop Owner Dashboard
```

### Layout

```
surveil/
  backend/
    app/
      api.py           FastAPI routes (both tabs)
      camera.py        threaded video source with a drop-latest frame buffer
      config.py        settings + state machine thresholds (env overridable)
      detection.py     YOLO wrapper, class -> role mapping, basket zone
      geometry.py      BBox maths (IoU, overlap, centre distance)
      hand_tracking.py persistent hand ids -> customer/session ids
      hands.py         ONNX / mediapipe hand detectors
      interaction.py   the product state machine
      ledger.py        Product Interaction Ledger
      overlay.py       annotated frame renderer
      pipeline.py      orchestration
      tracking/        ByteTrack + Kalman filter
    tools/
      convert_hand_model.py   TF1 frozen graph -> ONNX (one-off)
      make_demo_clip.py       generate a test clip without a webcam
    tests/             43 tests, no camera or weights required
  frontend/             Next.js (App Router) + Tailwind
  vendor/handtracking/  the imported hand model (gitignored)
  data/                 SQLite ledger + demo clips (gitignored)
```

---

## Setup

Requirements: Python 3.11+, Node 20+, git. A GPU is optional but changes
throughput a lot - CPU-only runs about **5 fps** at 800x671 with both models.

### 1. Hand model (the imported handtracking model)

The hand detector comes from
[**victordibia/handtracking**](https://github.com/victordibia/handtracking).
Upstream ships a **TensorFlow 1.x frozen graph** (SSD MobileNet, single class
`hand`). TF1 cannot be installed on a current Python, so the frozen graph is
converted **once** to ONNX and served by onnxruntime - the runtime never imports
TensorFlow.

```bat
backend\setup-hand-model.bat
```

That clones the repo into `vendor/handtracking` and runs
`backend/tools/convert_hand_model.py`, producing
`backend/models/hand_ssd_mobilenet.onnx` (~19 MB) plus the label map.

It runs in a **separate virtualenv** on purpose: TensorFlow pins `protobuf<5`
while ultralytics wants a newer one, so the two cannot share an environment.

If the conversion has not been run, the backend falls back to MediaPipe hands so
the pipeline still works (`SURVEIL_HAND_BACKEND=auto`).

### 2. Backend

```bat
start-backend.bat
```

Serves `http://127.0.0.1:8000` (interactive docs at `/docs`). On startup it
opens the default camera and begins processing.

### 3. Frontend

```bat
start-frontend.bat
```

Serves `http://localhost:3000` and talks to the backend on port 8000.

### No webcam?

```bat
cd backend
.venv\Scripts\python tools\make_demo_clip.py
```
then set **Video source** to `data/demo_clip.mp4` in Tab 1.

### Configuration

Copy `.env.example` to `.env`. Every value is documented there, including all
the state machine thresholds.

---

## The product state machine

Exactly the transitions in `refernces/surveil.docx`, with the thresholds the
document specifies (all tunable at runtime from the UI):

| From | To | Condition | Event |
| --- | --- | --- | --- |
| - | `ON_SHELF` | first detection; the box becomes the **shelf anchor**, learned over 15 settling frames | - |
| `ON_SHELF` | `LIFTING` | hand touching **AND** displaced >= 60 px from the anchor | - |
| `LIFTING` | `IN_HAND` | that condition holds **5 consecutive frames** | `PICKED_UP` |
| `LIFTING` | `ON_SHELF` | condition breaks (false alarm) | - |
| `ON_SHELF` | `ON_SHELF` | hand contacts the product but it does not leave its anchor | `TOUCH` |
| `IN_HAND` | `IN_BASKET` | >= **50%** of the box inside the basket zone for **4 frames** | `PLACED_IN_BASKET` |
| `IN_HAND` | `RETURNING` | hand no longer touching **AND** no longer displaced | - |
| `RETURNING` | `ON_SHELF` | that condition holds **5 consecutive frames** | `PUT_BACK` |
| `RETURNING` | `IN_HAND` | condition breaks | - |
| `IN_BASKET` | `IN_HAND` | the box leaves the basket zone | - |
| any | `LOST` | the track goes **30 frames** without a detection | `TRACK_LOST` |

So the two journeys the document asks for are:

```
ON_SHELF -> LIFTING -> IN_HAND -> RETURNING -> ON_SHELF     (picked up, put back)
ON_SHELF -> LIFTING -> IN_HAND -> IN_BASKET                 (picked up, in basket)
```

and `CHECKED_OUT` is emitted **only** when the owner confirms it in Tab 2.

Two implementation notes worth knowing:

* **The shelf anchor is frozen once confirmed.** It is re-learned only after a
  confirmed `PUT_BACK`. Re-learning it while a product is being lifted would
  make the displacement always read 0 and no pickup would ever be confirmed.
* **The document defines `LOST` but never enters it**, letting tracks age out
  instead. Here `LOST` is a real transition emitting `TRACK_LOST`. Set
  `SURVEIL_T_MARK_LOST_STATE=false` to reproduce the original behaviour.

### `TOUCH`

The document's "next steps" call out that the engine uses hand contact as an
internal signal but never emits a `TOUCH` event, and that the RetailAction
dataset has `TAKE` / `PUT` / `TOUCH`. Implemented: a hand contact that does not
displace the product emits `TOUCH`, once per contact.

---

## The `person` requirement

> MAKE SURE PEOPLE I.E. "PERSON" CLASS IS NOT BOXED AND HIGHLIGHTED, OUR FOCUS IS PRODUCTS

Enforced in three layers, not just at draw time:

1. `ClassRoles.role()` classifies every YOLO class as `product` / `basket` /
   `ignored`. Ignored classes are dropped **before** the tracker sees them, so
   they have no track id, no state machine entry and no ledger row.
2. The overlay renderer only receives product tracks, hands and the basket zone.
   It has no code path that could draw a person.
3. The HUD shows `people in frame N (not tracked)` so the operator still knows
   the room is occupied.

`hand` and `face` are in the default ignore list too, so a YOLO model's own hand
detections cannot double-count as products.

---

## Tracking

ByteTrack (Zhang et al., ECCV 2022), implemented directly in
`backend/app/tracking/bytetrack.py` rather than pulled from a tracker package,
because we need three things a generic tracker does not give us:

* **per-class association**, so a bottle never inherits a cup's id;
* the **ignore list applied before tracking**, not after;
* the track lifetime **shared** with the state machine that consumes the ids.

Two-stage association: high-confidence detections first, then a stricter second
pass over low-confidence ones so a product partly covered by a hand keeps its
identity. A constant-velocity Kalman filter supplies the prediction.

The first-pass IoU gate is **0.3** rather than the paper's 0.5. A product carried
off a shelf moves roughly 20 px per frame, which on a typical box puts the IoU
just under 0.5 - and a missed match costs a new track id, which resets the shelf
anchor and loses the pickup.

### Hand identity, customer and session ids

Hands are matched across frames by IoU to get a stable `hand_id`, which maps to
a `customer_id` (`C01`, `C02`, ...) and a `session_id` for the camera session.
A hand that has been gone for 8 seconds ends its session. Every interaction
event carries the hand that caused it. This is a shopping-episode notion of a
customer, not face recognition - a laptop camera cannot do that reliably.

---

## Basket detection

A basket class in YOLO is always preferred, so the zone is detected rather than
drawn by hand. `SURVEIL_BASKET_CLASS_NAMES` lists the accepted names
(`basket`, `shopping_basket`, `tote`, ...). When the model has no basket class, a
normalised `SURVEIL_BASKET_ROI` region is used as a fallback, editable from Tab 1.

---

## API

Full interactive documentation at `http://127.0.0.1:8000/docs`.

### Pipeline

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/stream` | MJPEG stream of the annotated frame |
| `GET` | `/api/snapshot.jpg` | single annotated frame |
| `GET` | `/api/live` | live state: products, hands, states, recent events |
| `GET` | `/api/pipeline/status` | session id, fps, model, backend, throughput |
| `POST` | `/api/pipeline/start` \| `/stop` \| `/restart` | body `{ "source": "0" \| "path.mp4" }` |
| `PATCH` | `/api/settings/thresholds` | retune the state machine live |
| `POST` | `/api/settings/basket-roi` | set/clear the fallback basket region |
| `GET` | `/api/config` | settings + the live state machine description |

### Ledger

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/events` | filter by `type`, `product_id`, `session_id`, `resolved` |
| `GET` | `/api/stats` | event counts per type |
| `GET` | `/api/products` | detected product catalogue |
| `GET` | `/api/basket` | in-basket products awaiting owner confirmation |
| `GET` | `/api/alerts` | unaccounted + lost-track alerts |
| `GET` | `/api/purchases` | confirmed sales |
| `GET` | `/api/sessions` | camera sessions |
| `POST` | `/api/checkout` | owner confirms a purchase -> `CHECKED_OUT` |
| `POST` | `/api/events/{uid}/resolve` | acknowledge an event |
| `GET` | `/api/ledger/export.csv` | the ledger as CSV |

---

## Swapping the store

SQLite is the default so the demo needs no infrastructure. All access goes
through `Ledger` in `backend/app/ledger.py`; swap that class for a
psycopg/asyncpg implementation of the same methods to move to
Supabase/PostgreSQL. Nothing above the ledger knows it is SQLite.

---

## Tests

```bat
cd backend
.venv\Scripts\python -m pytest tests -q
```

43 tests, none of which need a camera, model weights or the converted hand model
(the two hand tests skip themselves if the ONNX model is absent):

* `test_interaction.py` - every state transition and threshold, including the
  false-alarm rollback, the put-back re-anchoring, and the `LOST` timeout.
* `test_tracking_and_ledger.py` - track-id persistence, the low-score recovery
  pass, class-aware association, `max_age` counting, and the ledger's derived
  views (checkout, unaccounted alerts, CSV export).
* `test_pipeline_integration.py` - the whole pipeline driven by scripted fake
  detectors: a full pickup-to-basket produces `TOUCH` -> `PICKED_UP` ->
  `PLACED_IN_BASKET` in the ledger, and the person class is counted but never
  tracked.
* `test_hands.py` - NMS, the upstream label map, and the converted ONNX hand
  model against the image vendored with the handtracking repo.

---

## Known limitations

* The imported hand model was trained on **EgoHands** (egocentric views), so it
  sees some false positives on faces and sleeves from a third-person laptop
  camera. Raise `SURVEIL_HAND_CONF_THRESHOLD` or fine-tune on shop footage.
* Throughput is ~5 fps on CPU. Enable the YOLO device and lower
  `SURVEIL_YOLO_IMGSZ` / `SURVEIL_FRAME_*` for more.
* A product that teleports across the frame in a single frame is a new track, not
  a moved one - see the IoU note above.
* The default YOLO checkpoint is COCO. A real shop wants a fine-tuned model; set
  `SURVEIL_YOLO_MODEL` to it.
* `IN_BASKET` is not cleared by the CV system. Only an owner confirmation in
  Tab 2 resolves it, by design.

## Attribution

Hand detection model: [victordibia/handtracking](https://github.com/victordibia/handtracking)
(SSD MobileNet trained on the [EgoHands dataset](https://github.com/greenbua/egohands),
Bambach et al., ICCV 2015). Please cite it if you use the model.

Product detection: [ultralytics](https://docs.ultralytics.com/) YOLO.
Tracking: ByteTrack, Zhang et al., ECCV 2022.
