"""FastAPI application.

Tab 1 (Live CCTV Monitor)  -> /api/stream, /api/live, /api/pipeline/*
Tab 2 (Shop Owner Dashboard) -> /api/ledger/*, /api/products, /api/alerts, /api/purchases
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from .config import get_settings
from .hands import AVAILABLE_HAND_BACKENDS
from .interaction import EventType, ProductState
from .ledger import Ledger
from .pipeline import HAND_BACKEND_HELP, Pipeline

settings = get_settings()
ledger = Ledger(settings.db_path)
pipeline = Pipeline(settings, ledger)

BOUNDARY = "--surveilframe"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auto_start_pipeline:
        try:
            pipeline.start()
        except Exception as exc:  # noqa: BLE001
            pipeline.status.error = f"autostart failed: {exc}"
    yield
    pipeline.stop()
    ledger.close()


app = FastAPI(
    title="surveil",
    version="1.0.0",
    description=(
        "Turns a laptop camera into structured product-interaction events: "
        "YOLO product detection, ByteTrack identity, hand detection, and a "
        "product state machine feeding a Product Interaction Ledger."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------- schemas
class PipelineRequest(BaseModel):
    source: str | None = Field(
        None, description="Camera index (0, 1, ...) or a video file path. Default: configured source."
    )


class BasketRoiRequest(BaseModel):
    roi: list[float] | None = Field(
        None,
        description="Fallback basket region as normalised [x, y, w, h]. null disables the fallback.",
    )


class ThresholdUpdate(BaseModel):
    shelf_displacement_px: float | None = None
    settle_frames: int | None = None
    settle_motion_px: float | None = None
    hand_touch_px: float | None = None
    hand_touch_min_overlap: float | None = None
    lift_confirm_frames: int | None = None
    return_confirm_frames: int | None = None
    basket_overlap_ratio: float | None = None
    basket_confirm_frames: int | None = None
    touch_emit_frames: int | None = None
    max_missed_frames: int | None = None
    mark_lost_state: bool | None = None
    lost_emit_event: bool | None = None


class CheckoutRequest(BaseModel):
    product_id: str = Field(
        ..., description="Stable product identity, e.g. 'bottle#1' - not the ByteTrack id."
    )
    product_name: str
    track_id: int
    session_id: str | None = None
    hand_id: int | None = None
    note: str = "confirmed by owner"
    event_uid: str | None = Field(
        None,
        description="The exact pending event being settled. Lets the owner confirm one "
        "specific interaction instead of everything for the product.",
    )
    basket_track_id: int | None = None


class HandBackendRequest(BaseModel):
    backend: str = Field(..., description="auto | onnx | pose | mediapipe | off")


class ResolveRequest(BaseModel):
    resolution: str = "acknowledged by owner"
    resolved_by: str = "owner"


# ------------------------------------------------------------------ system info
@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "app": settings.app_name,
        "pipeline_running": pipeline.running,
        "db": str(settings.db_path),
        "yolo_model": settings.yolo_model,
        "hand_backend": pipeline.status.hand_backend,
        "hand_model": str(settings.hand_onnx_path),
        "hand_model_present": settings.hand_onnx_path.exists(),
    }


@app.get("/api/config")
def config() -> dict[str, Any]:
    return {
        "settings": settings.dump(),
        "thresholds": settings.thresholds.model_dump(mode="json"),
        "state_machine": {
            "states": ["ON_SHELF", "LIFTING", "IN_HAND", "RETURNING", "IN_BASKET", "LOST"],
            "events": ["TOUCH", "PICKED_UP", "PUT_BACK", "PLACED_IN_BASKET", "CHECKED_OUT",
                       "TRACK_LOST", "ALERT_RAISED"],
            "transitions": [
                {"from": "ON_SHELF", "to": "LIFTING",
                 "when": "hand touching AND displaced >= shelf_displacement_px from the anchor"},
                {"from": "LIFTING", "to": "IN_HAND",
                 "when": f"condition holds for {settings.thresholds.lift_confirm_frames} frames -> PICKED_UP"},
                {"from": "LIFTING", "to": "ON_SHELF", "when": "condition breaks (false alarm)"},
                {"from": "IN_HAND", "to": "RETURNING",
                 "when": "hand no longer touching AND no longer displaced"},
                {"from": "RETURNING", "to": "ON_SHELF",
                 "when": f"condition holds for {settings.thresholds.return_confirm_frames} frames -> PUT_BACK"},
                {"from": "RETURNING", "to": "IN_HAND", "when": "condition breaks"},
                {"from": "IN_HAND", "to": "IN_BASKET",
                 "when": (f">= {settings.thresholds.basket_overlap_ratio:.0%} of the box inside the basket "
                          f"for {settings.thresholds.basket_confirm_frames} frames -> PLACED_IN_BASKET")},
                {"from": "IN_BASKET", "to": "IN_HAND", "when": "box leaves the basket zone"},
                {"from": "*", "to": "LOST",
                 "when": f"track missing for {settings.thresholds.max_missed_frames} frames"},
            ],
            "always_events": [
                {"event": "TOUCH", "when": "hand contacts a product that does not leave its anchor"},
                {"event": "CHECKED_OUT", "when": "owner confirms the purchase in Tab 2"},
            ],
        },
    }


# --------------------------------------------------------------------- pipeline
def _await_first_frame(timeout: float = 8.0) -> None:
    """Give the pipeline a moment to prove it can read frames.

    Without this, asking for a bad video path returns 200 and the failure only
    shows up in the status poll seconds later.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pipeline.status.error:
            return
        if pipeline.status.processed_frames > 0:
            return
        time.sleep(0.1)


@app.post("/api/pipeline/start")
def pipeline_start(body: PipelineRequest | None = None) -> dict[str, Any]:
    source = body.source if body else None
    pipeline.start(source)
    _await_first_frame()
    if pipeline.status.error:
        raise HTTPException(status_code=500, detail=pipeline.status.error)
    return pipeline.status_dict()


@app.post("/api/pipeline/stop")
def pipeline_stop() -> dict[str, Any]:
    pipeline.stop()
    return pipeline.status_dict()


@app.post("/api/pipeline/restart")
def pipeline_restart(body: PipelineRequest | None = None) -> dict[str, Any]:
    source = body.source if body else None
    pipeline.stop()
    pipeline.start(source)
    _await_first_frame()
    if pipeline.status.error:
        raise HTTPException(status_code=500, detail=pipeline.status.error)
    return pipeline.status_dict()


@app.get("/api/pipeline/status")
def pipeline_status() -> dict[str, Any]:
    return pipeline.status_dict()


@app.get("/api/live")
def live() -> dict[str, Any]:
    return pipeline.snapshot()


@app.get("/api/stream")
def stream() -> StreamingResponse:
    """MJPEG stream of the annotated frame (products and hands only, never people)."""

    def generator():
        boundary = BOUNDARY
        while True:
            frame = pipeline.frame_jpeg()
            if frame is None:
                yield b"--" + boundary.encode() + b"\r\nContent-Type: image/jpeg\r\n\r\n"
                import time as _t

                _t.sleep(0.2)
                continue
            yield (
                b"--" + boundary.encode() + b"\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n"
            )

    return StreamingResponse(
        generator(),
        media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"},
    )


@app.get("/api/snapshot.jpg")
def snapshot_jpeg() -> Response:
    frame = pipeline.frame_jpeg()
    if frame is None:
        raise HTTPException(status_code=503, detail="no frame available yet")
    return Response(content=frame, media_type="image/jpeg",
                    headers={"Cache-Control": "no-store"})


@app.post("/api/settings/basket-roi")
def set_basket_roi(body: BasketRoiRequest) -> dict[str, Any]:
    settings.basket_roi = body.roi
    pipeline.status.basket_mode = "roi" if body.roi else "none"
    return {"basket_roi": settings.basket_roi}


@app.get("/api/hand-backends")
def hand_backends() -> dict[str, Any]:
    return {
        "configured": settings.hand_backend,
        "active": pipeline.status.hand_backend,
        "options": [
            {"key": key, "label": key, "description": HAND_BACKEND_HELP.get(key, "")}
            for key in AVAILABLE_HAND_BACKENDS
        ],
        "hand_model_present": settings.hand_onnx_path.exists(),
    }


@app.post("/api/hand-backend")
def set_hand_backend(body: HandBackendRequest) -> dict[str, Any]:
    try:
        return pipeline.set_hand_backend(body.backend)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.patch("/api/settings/thresholds")
def set_thresholds(body: ThresholdUpdate) -> dict[str, Any]:
    data = body.model_dump(exclude_none=True)
    for key, value in data.items():
        setattr(settings.thresholds, key, value)
    if "max_missed_frames" in data and pipeline.tracker:
        pipeline.tracker.max_age = int(data["max_missed_frames"])
    return {"thresholds": settings.thresholds.model_dump(mode="json")}


# ------------------------------------------------------------------------ ledger
@app.get("/api/events")
def events(
    limit: int = Query(100, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    type: str | None = None,
    product_id: str | None = None,
    session_id: str | None = None,
    resolved: bool | None = None,
) -> dict[str, Any]:
    rows = ledger.query_events(
        limit=limit,
        offset=offset,
        type_filter=type,
        product_id=product_id,
        session_id=session_id,
        resolved=resolved,
    )
    return {"events": rows, "count": len(rows), "total": ledger.count_events(type)}


@app.get("/api/stats")
def stats() -> dict[str, Any]:
    s = ledger.stats()
    pending_rows = ledger.open_pickups()
    return {
        "events": s.events,
        "picked_up": s.picked_up,
        "put_back": s.put_back,
        "placed_in_basket": s.placed_in_basket,
        "checked_out": s.checked_out,
        "touch": s.touch,
        "lost": s.lost,
        "unaccounted": s.unaccounted,
        "pending_basket": len(ledger.basket_holds()),
        "pending_in_hand": sum(1 for r in pending_rows if r["type"] != EventType.PLACED_IN_BASKET.value),
        "pending_total": len(pending_rows),
    }


@app.get("/api/products")
def products() -> dict[str, Any]:
    """Detected products, with their stable identity separated from track ids.

    `current_track_id` is the ByteTrack id right now (temporary); `product_id` is
    the session identity that survives the track dying. `track_ids` lists every
    track the object has been seen under.
    """
    return {
        "products": ledger.product_catalog(),
        "identities": pipeline.registry.snapshot() if pipeline.registry else [],
        "reassociations": pipeline._reassociations[-12:],
        "identity_ambiguities": pipeline._identity_ambiguities[-12:],
    }


@app.get("/api/baskets")
def baskets() -> dict[str, Any]:
    """Tracked baskets and which product identities are in each of them."""
    return {"baskets": pipeline.baskets.snapshot() if pipeline.baskets else []}


@app.get("/api/sessions")
def sessions(limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    return {"sessions": ledger.list_sessions(limit)}


@app.get("/api/alerts")
def alerts() -> dict[str, Any]:
    return {
        "alerts": ledger.alerts(settings.unaccounted_alert_seconds),
        "grace_seconds": settings.unaccounted_alert_seconds,
    }


@app.get("/api/pending")
def pending(session_id: str | None = None) -> dict[str, Any]:
    """Products awaiting the owner's decision - IN_HAND or IN_BASKET.

    An item only leaves this list once the owner confirms the sale or the CV
    system sees it put back. `live_state` is the state machine's current
    opinion, so the dashboard can badge IN HAND vs IN BASKET.
    """
    live = pipeline.snapshot().get("states", {})
    rows = ledger.open_pickups(session_id=session_id)
    for row in rows:
        state = live.get(str(row.get("track_id")))
        row["live_state"] = state["state"] if state else None
        row["reason"] = (
            "in_basket"
            if row.get("type") == EventType.PLACED_IN_BASKET.value
            or row.get("live_state") == ProductState.IN_BASKET.value
            else "in_hand"
        )
    return {
        "pending": rows,
        "in_hand": sum(1 for r in rows if r["reason"] == "in_hand"),
        "in_basket": sum(1 for r in rows if r["reason"] == "in_basket"),
    }


@app.get("/api/basket")
def basket() -> dict[str, Any]:
    """Backwards-compatible alias: only the IN_BASKET rows."""
    return {"pending": ledger.basket_holds()}


@app.get("/api/purchases")
def purchases(limit: int = Query(100, ge=1, le=1000)) -> dict[str, Any]:
    return {"purchases": ledger.purchased(limit)}


@app.get("/api/unaccounted")
def unaccounted() -> dict[str, Any]:
    return {
        "unaccounted": ledger.unaccounted(settings.unaccounted_alert_seconds),
        "grace_seconds": settings.unaccounted_alert_seconds,
    }


@app.post("/api/checkout")
def checkout(body: CheckoutRequest) -> dict[str, Any]:
    record = ledger.checkout(
        product_id=body.product_id,
        product_name=body.product_name,
        track_id=body.track_id,
        session_id=body.session_id,
        hand_id=body.hand_id,
        note=body.note,
        event_uid=body.event_uid,
        basket_track_id=body.basket_track_id,
    )
    return {"ok": True, "purchase": record}


@app.post("/api/events/{event_uid}/resolve")
def resolve_event(event_uid: str, body: ResolveRequest) -> dict[str, Any]:
    ok = ledger.resolve_event(event_uid, body.resolution, body.resolved_by)
    if not ok:
        raise HTTPException(status_code=404, detail="event not found or already resolved")
    return {"ok": True, "event_uid": event_uid, "resolution": body.resolution}


@app.get("/api/ledger/export.csv")
def export_csv(
    limit: int = Query(10000, ge=1, le=100000),
    type: str | None = None,
    product_id: str | None = None,
    session_id: str | None = None,
    resolved: bool | None = None,
) -> Response:
    csv_text = ledger.export_csv(
        limit=limit, type_filter=type, product_id=product_id, session_id=session_id, resolved=resolved
    )
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="product_interaction_ledger.csv"'},
    )


@app.get("/")
def root() -> JSONResponse:
    return JSONResponse(
        {
            "app": settings.app_name,
            "docs": "/docs",
            "tabs": {
                "tab_1_live_cctv_monitor": ["/api/stream", "/api/live", "/api/pipeline/start"],
                "tab_2_shop_owner_dashboard": [
                    "/api/products", "/api/basket", "/api/alerts", "/api/purchases", "/api/checkout"
                ],
            },
        }
    )