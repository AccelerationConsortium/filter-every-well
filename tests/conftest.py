"""Shared fixtures.

Tests run the FastAPI app without hardware. On a machine without the
adafruit libraries the app is naturally in dry-run; the ``hardware_client``
fixture injects a fake ``PressureProcessor`` and flips ``HAS_HARDWARE`` so
the real state-machine path (`ready`/`busy`/`requires_init`) is exercised.
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from filter_every_well import api


class FakePP96:
    """In-memory stand-in for the PP96 driver. Movements take ``move_s``
    seconds so tests can observe the busy/running span."""

    def __init__(self, move_s: float = 0.0) -> None:
        self.move_s = move_s
        self._system_state = "active"
        self._press_state = "up"
        self._plate_state = "out"

    def _move(self) -> bool:
        if self._system_state != "active":
            return False
        if self.move_s:
            time.sleep(self.move_s)
        return True

    def init(self) -> None:
        self._system_state = "active"
        self._press_state = "up"
        self._plate_state = "out"

    def stop(self) -> None:
        self._system_state = "stopped"
        self._press_state = "unknown"
        self._plate_state = "unknown"

    def press_up(self, hold_time: float = 0.5) -> bool:
        ok = self._move()
        if ok:
            self._press_state = "up"
        return ok

    def press_down(self, hold_time: float = 0.5) -> bool:
        ok = self._move()
        if ok:
            self._press_state = "down"
        return ok

    def plate_in(self, smooth: bool = True) -> bool:
        ok = self._move()
        if ok:
            self._plate_state = "in"
        return ok

    def plate_out(self, smooth: bool = True) -> bool:
        ok = self._move()
        if ok:
            self._plate_state = "out"
        return ok

    def shutdown(self) -> None:
        return None


def _reset_v12_state() -> None:
    api._activity = "unknown"
    api._activity_since = None
    api._cycles_total = 0


@pytest.fixture
def unclaimed_client() -> Iterator[TestClient]:
    _reset_v12_state()
    with TestClient(api.app) as c:
        yield c


@pytest.fixture
def client(unclaimed_client: TestClient) -> TestClient:
    """TestClient with a pre-acquired claim attached to every request."""
    r = unclaimed_client.post(
        "/control/claim",
        json={"owner": "pytest", "session_id": "pytest-default", "ttl_s": 60.0},
    )
    assert r.status_code == 200, r.text
    unclaimed_client.headers["X-Claim-Token"] = r.json()["claim_token"]
    return unclaimed_client


@pytest.fixture
def hardware_client(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, FakePP96]:
    """Claimed client with a fake driver injected (real state-machine path)."""
    fake = FakePP96()
    monkeypatch.setattr(api, "HAS_HARDWARE", True)
    monkeypatch.setattr(api, "_pp96", fake)
    return client, fake
