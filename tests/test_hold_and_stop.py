"""Long press holds (up to MAX_HOLD_TIME_S) and the stop that must end them.

A hold blocks its request for the whole duration with the servos pressing
the rocker, so /control/stop has to get through while that request holds
the claim, and has to release the rocker without waiting out the hold.
"""

from __future__ import annotations

import threading
import time

import pytest

from filter_every_well import api, pp96


class FakeServo:
    def __init__(self) -> None:
        self.angle: float | None = None

    def set_pulse_width_range(self, _lo: int, _hi: int) -> None:
        return None


class FakeServoKit:
    def __init__(self, channels: int, address: int) -> None:
        self.servo = [FakeServo() for _ in range(channels)]


@pytest.fixture
def driver(monkeypatch: pytest.MonkeyPatch) -> pp96.PressureProcessor:
    """The real driver over a fake PCA9685, initialised and ACTIVE."""
    monkeypatch.setattr(pp96, "ServoKit", FakeServoKit)
    d = pp96.PressureProcessor()
    d.init()
    return d


def _rocker_angle(d: pp96.PressureProcessor) -> float | None:
    return d.kit.servo[d.servo_1_channel].angle


def test_hold_time_accepts_five_minutes_and_rejects_more(hardware_client):
    client, _fake = hardware_client
    assert api.MAX_HOLD_TIME_S == 300.0
    assert client.post("/control/press/down", json={"hold_time": 300.0}).status_code == 200
    assert client.post("/control/press/down", json={"hold_time": 300.5}).status_code == 422


def test_stop_needs_no_claim(unclaimed_client):
    assert unclaimed_client.post("/control/stop").status_code == 200


def test_stop_ends_a_hold_early(driver):
    result: list[bool] = []
    t = threading.Thread(target=lambda: result.append(driver.press_down(hold_time=60.0)))
    t.start()
    time.sleep(0.1)
    assert _rocker_angle(driver) == driver.servo_down_angle  # pressing
    started = time.monotonic()
    driver.stop()
    t.join(timeout=2.0)
    assert not t.is_alive()
    assert time.monotonic() - started < 1.0
    assert result == [False]
    assert _rocker_angle(driver) == driver.servo_neutral_angle
    assert driver._press_state == "unknown"  # not overwritten to "down"


def test_init_after_stop_rearms_holds(driver):
    driver.stop()
    driver.init()
    started = time.monotonic()
    assert driver.press_down(hold_time=0.2) is True
    assert time.monotonic() - started >= 0.2
    assert driver._press_state == "down"


def test_unclaimed_stop_interrupts_a_claimed_hold_over_http(hardware_client, driver, monkeypatch):
    client, _fake = hardware_client
    monkeypatch.setattr(api, "_pp96", driver)
    token = client.headers["X-Claim-Token"]
    responses: list[int] = []

    def hold() -> None:
        r = client.post(
            "/control/press/down",
            json={"hold_time": 60.0},
            headers={"X-Claim-Token": token},
        )
        responses.append(r.status_code)

    t = threading.Thread(target=hold)
    t.start()
    deadline = time.monotonic() + 2.0
    while client.get("/status").json()["equipment_status"] != "busy":
        assert time.monotonic() < deadline, "hold never started"
        time.sleep(0.02)

    r = client.post("/control/stop", headers={"X-Claim-Token": ""})
    assert r.status_code == 200
    t.join(timeout=2.0)
    assert not t.is_alive()
    assert responses == [409]
    status = client.get("/status").json()
    assert status["equipment_status"] == "requires_init"
    assert status["metrics"]["cycles_total"]["value"] == 0
