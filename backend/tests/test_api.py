"""API-level tests with a scripted pipeline (TestClient, no camera or weights)."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "backend" / "tests"))

from fastapi.testclient import TestClient  # noqa: E402

from test_pipeline_integration import (  # noqa: E402
    H,
    W,
    FakeDetector,
    FakeHandDetector,
    build,
    play,
    pickup_story,
    shelf_story,
)


@pytest.fixture()
def make_client(tmp_path: Path):
    """Returns a factory building a TestClient over a scripted pipeline."""
    from app import api as api_module

    created: list[tuple[Any, Any]] = []

    def _make(story: list[dict[str, Any]]):
        pipeline, ledger = build(tmp_path, story)

        # The API module and the pipeline must share one Settings object, or a
        # PATCH writes to the module's copy and the pipeline never sees it.
        api_module.settings = pipeline.settings
        api_module.pipeline = pipeline
        api_module.ledger = ledger
        pipeline.settings.hand_backend = "off"  # no model loading in tests

        client = TestClient(api_module.app)
        client.pipeline = pipeline  # type: ignore[attr-defined]
        created.append((pipeline, ledger))
        return client

    yield _make

    for pipeline, ledger in created:
        pipeline.stop()
        ledger.close()


@pytest.fixture()
def client(make_client):
    with make_client(pickup_story()) as c:
        yield c


def test_health_and_config(client: TestClient):
    assert client.get("/api/health").json()["ok"] is True
    cfg = client.get("/api/config").json()
    assert "IN_HAND" in cfg["state_machine"]["states"]
    assert cfg["thresholds"]["lift_confirm_frames"] == 5


def test_pending_endpoint_lists_in_hand_items(client: TestClient):
    play(client.pipeline, len(pickup_story()))  # type: ignore[attr-defined]

    body = client.get("/api/pending").json()
    # the story ends with the product in the basket, so it must appear there
    assert body["pending"], "expected at least one pending row"
    assert body["in_basket"] >= 1
    row = body["pending"][0]
    assert row["reason"] in ("in_hand", "in_basket")
    assert row["live_state"] in ("IN_HAND", "IN_BASKET", None)


def test_checkout_clears_a_pending_item(client: TestClient):
    play(client.pipeline, len(pickup_story()))  # type: ignore[attr-defined]
    row = client.get("/api/pending").json()["pending"][0]

    res = client.post(
        "/api/checkout",
        json={
            "product_id": row["product_id"],
            "product_name": row["product_name"],
            "track_id": row["track_id"],
            "session_id": row["session_id"],
        },
    )
    assert res.status_code == 200
    assert client.get("/api/pending").json()["pending"] == []
    assert client.get("/api/stats").json()["checked_out"] == 1


def test_stats_reports_pending_totals(client: TestClient):
    play(client.pipeline, len(pickup_story()))  # type: ignore[attr-defined]
    stats = client.get("/api/stats").json()
    assert stats["picked_up"] >= 1
    assert stats["pending_total"] >= 1
    assert "pending_in_hand" in stats


def test_hand_backend_endpoint_lists_options(client: TestClient):
    body = client.get("/api/hand-backends").json()
    keys = [o["key"] for o in body["options"]]
    assert "onnx" in keys and "pose" in keys and "off" in keys
    assert all(o["description"] for o in body["options"])


def test_hand_backend_rejects_unknown_backend(client: TestClient):
    res = client.post("/api/hand-backend", json={"backend": "telepathy"})
    assert res.status_code == 400


def test_hand_backend_off_is_accepted(client: TestClient):
    res = client.post("/api/hand-backend", json={"backend": "off"})
    assert res.status_code == 200
    assert res.json()["hand_backend"] == "off"


def test_basket_roi_endpoint_round_trips(make_client):
    # a story with no basket-class detections, so the drawn region is what is used
    with make_client(shelf_story()) as c:
        roi = [0.1, 0.2, 0.3, 0.4]
        assert c.post("/api/settings/basket-roi", json={"roi": roi}).json()["basket_roi"] == roi

        play(c.pipeline, 20)  # type: ignore[attr-defined]
        live = c.get("/api/live").json()
        assert live["basket_source"] == "roi"
        assert live["basket_zone"] == pytest.approx([0.1 * W, 0.2 * H, 0.4 * W, 0.6 * H], abs=1)

        assert c.post("/api/settings/basket-roi", json={"roi": None}).json()["basket_roi"] is None
        play(c.pipeline, 2)  # type: ignore[attr-defined]
        assert c.get("/api/live").json()["basket_source"] == "none"


def test_detected_basket_class_overrides_the_drawn_region(client: TestClient):
    play(client.pipeline, len(pickup_story()))  # type: ignore[attr-defined]
    live = client.get("/api/live").json()
    # the story carries a detected basket during the carry phase
    assert live["basket_source"] == "yolo"
    assert live["basket_zone"] is not None


def test_thresholds_endpoint_applies_to_the_running_pipeline(client: TestClient):
    res = client.patch("/api/settings/thresholds", json={"lift_confirm_frames": 9})
    assert res.status_code == 200
    assert res.json()["thresholds"]["lift_confirm_frames"] == 9
    play(client.pipeline, 5)  # type: ignore[attr-defined]
    assert client.get("/api/live").json()["thresholds"]["lift_confirm_frames"] == 9


def test_events_endpoint_filters_by_type(client: TestClient):
    play(client.pipeline, len(pickup_story()))  # type: ignore[attr-defined]
    picked = client.get("/api/events", params={"type": "PICKED_UP"}).json()
    assert picked["count"] >= 1
    assert all(e["type"] == "PICKED_UP" for e in picked["events"])
    assert client.get("/api/events", params={"type": "NOPE"}).json()["count"] == 0


def test_csv_export_has_a_header(client: TestClient):
    play(client.pipeline, len(pickup_story()))  # type: ignore[attr-defined]
    res = client.get("/api/ledger/export.csv")
    assert res.status_code == 200
    assert "text/csv" in res.headers["content-type"]
    first = res.text.splitlines()[0]
    assert first.startswith("event_uid,ts_iso,session_id,type")
    assert "PICKED_UP" in res.text


def test_resolve_endpoint_rejects_unknown_event(client: TestClient):
    res = client.post("/api/events/does-not-exist/resolve", json={"resolution": "x"})
    assert res.status_code == 404


def test_live_snapshot_exposes_the_people_handling(client: TestClient):
    play(client.pipeline, 20)  # type: ignore[attr-defined]
    live = client.get("/api/live").json()
    assert live["ignored_count"] == 1
    assert "person" in live["ignored_classes"]
    assert all(p["class_name"] != "person" for p in live["products"])
    assert "hands_blind" in live
    assert isinstance(live["hud"]["hand_backend"], str)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
