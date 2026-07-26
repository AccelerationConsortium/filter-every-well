"""STATUS_SPEC v1.2 conformance tests (§2.3, §2.3.1, §9 checklist) plus the
pre-existing spec surface, which previously had no test suite at all."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from filter_every_well import api

from .conftest import FakePP96

# ---------------------------------------------------------------------------
# Spec surface
# ---------------------------------------------------------------------------


def test_probe(unclaimed_client):
    r = unclaimed_client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["equipment_id"] == "filter_every_well"
    assert body["protocol_version"] == "1.2"


def test_health(unclaimed_client):
    assert unclaimed_client.get("/health").json() == {"status": "healthy"}


def test_control_requires_claim(unclaimed_client):
    r = unclaimed_client.post("/control/press/up", json={})
    assert r.status_code == 423
    assert "claimed_by" in r.json()


def test_status_dry_run_envelope(unclaimed_client):
    s = unclaimed_client.get("/status").json()
    assert s["protocol_version"] == "1.2"
    assert s["equipment_kind"] == "press"
    assert s["equipment_status"] == "dry_run"
    # v1.2: activity observed (lock free → idle), counter exposed,
    # equipment_version populated from package metadata.
    assert s["activity"] == "idle"
    assert s["activity_since"] is not None
    assert s["metrics"]["cycles_total"]["value"] == 0
    assert s["metrics"]["cycles_total"]["unit"] == "count"
    assert s["equipment_version"] is not None


# ---------------------------------------------------------------------------
# §2.3 invariants on the real state-machine path
# ---------------------------------------------------------------------------


def test_ready_implies_idle_and_requires_init_implies_idle(hardware_client):
    client, fake = hardware_client
    s = client.get("/status").json()
    assert s["equipment_status"] == "ready"
    assert s["activity"] == "idle"

    fake.stop()
    s = client.get("/status").json()
    assert s["equipment_status"] == "requires_init"
    assert s["activity"] == "idle"
    assert s["allowed_actions"] == ["init"]


def test_busy_implies_running_mid_movement():
    """Hold the move lock (exactly what a movement does) and confirm the
    envelope reports busy + running with allowed_actions reduced to stop."""

    async def scenario():
        api._move_lock = asyncio.Lock()
        api._claims = api.ClaimStore()
        api._start_time = datetime.now(timezone.utc)
        fake = FakePP96()
        api._pp96 = fake
        async with api._move_lock:
            return await api._build_status()

    orig = api.HAS_HARDWARE
    api.HAS_HARDWARE = True
    try:
        status = asyncio.run(scenario())
    finally:
        api.HAS_HARDWARE = orig
        api._pp96 = None
    assert status.equipment_status == "busy"
    assert status.activity == "running"
    assert status.allowed_actions == ["stop"]


def test_activity_since_stamps_transitions(hardware_client):
    client, _fake = hardware_client
    idle_since = client.get("/status").json()["activity_since"]
    # A movement flips the span running → idle; the new idle span must be
    # newer than the pre-movement one, and a second idle poll must not
    # restart it.
    assert client.post("/control/press/down", json={}).status_code == 200
    after = client.get("/status").json()["activity_since"]
    assert after > idle_since
    assert client.get("/status").json()["activity_since"] == after


# ---------------------------------------------------------------------------
# §2.3.1 — cycles_total counts platen strokes, not staging moves
# ---------------------------------------------------------------------------


def test_cycles_total_counts_platen_strokes_only(hardware_client):
    client, _fake = hardware_client
    assert client.get("/status").json()["metrics"]["cycles_total"]["value"] == 0

    assert client.post("/control/press/down", json={}).status_code == 200
    assert client.post("/control/press/up", json={}).status_code == 200
    # staging moves report activity but are not cycles
    assert client.post("/control/plate/in", json={}).status_code == 200
    assert client.post("/control/plate/out", json={}).status_code == 200

    assert client.get("/status").json()["metrics"]["cycles_total"]["value"] == 2


def test_failed_stroke_does_not_count(hardware_client):
    client, fake = hardware_client
    fake._system_state = "stopped"
    # endpoint-level guard fires first (409); either way, no count
    r = client.post("/control/press/down", json={})
    assert r.status_code == 409
    fake.init()
    assert client.get("/status").json()["metrics"]["cycles_total"]["value"] == 0


# ---------------------------------------------------------------------------
# §9 — snapshot fixtures validate against the shared contract
# ---------------------------------------------------------------------------


def test_fixture_snapshots_validate_against_the_contract():
    from sdl_lab_contract import EquipmentStatus

    required_activity = {
        "busy": {"running"},
        "ready": {"idle"},
        "requires_init": {"idle"},
        "e_stop": {"idle"},
    }
    fixtures = sorted((Path(__file__).parent / "fixtures").glob("status_*.json"))
    assert len(fixtures) >= 3
    for path in fixtures:
        status = EquipmentStatus.model_validate(json.loads(path.read_text()))
        assert status.protocol_version == "1.2", path.name
        allowed = required_activity.get(status.equipment_status)
        if allowed is not None:
            assert status.activity in allowed, path.name
