#!/usr/bin/env python3
"""Waters PP96 Control API — STATUS_SPEC v1.1 conformant.

Endpoints
---------
Spec-mandated (always 200, side-effect-free):

* ``GET /``                    ProbeResponse
* ``GET /health``              HealthResponse
* ``GET /status``              EquipmentStatus (v1.1)

Claim protocol (v1.1 — required before any /control/* when enforced):

* ``POST /control/claim``      body: ClaimRequest → ClaimResponse
* ``POST /control/heartbeat``  header: X-Claim-Token → ClaimResponse
* ``POST /control/release``    header: X-Claim-Token → 204

Control (X-Claim-Token required when ENFORCE_CLAIMS=True):

* ``POST /control/startup``    Initialize: press UP, plate OUT, system ACTIVE
* ``POST /control/stop``       Emergency stop (disables movement; re-init required)
* ``POST /control/press/up``   Move pneumatic press to UP position
* ``POST /control/press/down`` Move pneumatic press to DOWN position
* ``POST /control/plate/in``   Retract plate carriage under the press
* ``POST /control/plate/out``  Extend plate carriage away from the press

State machine
-------------
system_state='stopped' (boot default)
    └─ POST /control/startup ─→ system_state='active'   equipment_status='ready'
                                    └─ moving           equipment_status='busy'
                                    └─ POST /control/stop ─→ system_state='stopped'  equipment_status='requires_init'
No hardware: equipment_status='dry_run'  (all actions simulated)
"""

from __future__ import annotations

import asyncio
import logging
import socket
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .claims import ClaimConflict, ClaimStore, UnknownClaim
from .models import (
    PROTOCOL_VERSION,
    ClaimRejection,
    ClaimRequest,
    ClaimResponse,
    ComponentStatus,
    EquipmentStatus,
    HealthResponse,
    ProbeResponse,
)

try:
    from filter_every_well.pp96 import PressureProcessor
    HAS_HARDWARE = True
except (ImportError, RuntimeError):
    HAS_HARDWARE = False

logger = logging.getLogger(__name__)

EQUIPMENT_ID = "filter_every_well"
EQUIPMENT_NAME = "Waters Filtration"
EQUIPMENT_KIND = "press"

# Set False for advisory-only claims (device publishes claimed_by but does
# not reject /control/* calls from unclaimed clients).
ENFORCE_CLAIMS = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hostname() -> str | None:
    try:
        return socket.gethostname()
    except Exception:
        return None


def _allowed_actions(is_dry_run: bool, active: bool, busy: bool) -> list[str]:
    """Compute the v1.1 ``allowed_actions`` list from the current state."""
    if is_dry_run:
        return ["init", "stop", "press.up", "press.down", "plate.in", "plate.out"]
    if busy:
        return ["stop"]
    if active:
        return ["stop", "press.up", "press.down", "plate.in", "plate.out"]
    # requires_init
    return ["init"]


# ---------------------------------------------------------------------------
# App-level singletons — initialised inside lifespan so the asyncio.Lock
# binds to the running event loop (required for Python 3.9 compat).
# ---------------------------------------------------------------------------

_pp96: "PressureProcessor | None" = None
_move_lock: asyncio.Lock | None = None
_claims: ClaimStore | None = None
_start_time: datetime | None = None


# ---------------------------------------------------------------------------
# Status builder
# ---------------------------------------------------------------------------


async def _build_status() -> EquipmentStatus:
    assert _move_lock is not None and _claims is not None and _start_time is not None

    is_dry_run = not HAS_HARDWARE or _pp96 is None
    busy = _move_lock.locked()
    claimed_by = await _claims.current()
    uptime = (_utcnow() - _start_time).total_seconds()

    if is_dry_run:
        equipment_status: str = "dry_run"
        active = True
        message = "Hardware not available – running in dry-run mode"
        press_state: str | None = None
        plate_state: str | None = None
    else:
        pp96 = _pp96
        active = pp96._system_state == "active"
        press_state = pp96._press_state
        plate_state = pp96._plate_state

        if busy:
            equipment_status = "busy"
            message = "Movement in progress"
        elif active:
            equipment_status = "ready"
            message = (
                f"System ACTIVE – press {press_state.upper()}, "
                f"plate {plate_state.upper()}"
            )
        else:
            equipment_status = "requires_init"
            message = "System STOPPED – call /control/startup to initialize"

    components: dict[str, ComponentStatus] = {}
    if press_state is not None:
        components["press_valve"] = ComponentStatus(
            connected=press_state != "unknown",
            state=press_state,
        )
    if plate_state is not None:
        components["plate"] = ComponentStatus(
            connected=plate_state in ("in", "out"),
            state=plate_state,
        )

    details: dict[str, Any] = {}
    if claimed_by is not None:
        details["claimed_by"] = claimed_by.model_dump(mode="json")
    if not is_dry_run and _pp96 is not None:
        details["system_state"] = _pp96._system_state
        if press_state is not None:
            details["press_state"] = press_state
        if plate_state is not None:
            details["plate_state"] = plate_state

    return EquipmentStatus(
        protocol_version=PROTOCOL_VERSION,
        equipment_id=EQUIPMENT_ID,
        equipment_name=EQUIPMENT_NAME,
        equipment_kind=EQUIPMENT_KIND,  # type: ignore[arg-type]
        equipment_status=equipment_status,  # type: ignore[arg-type]
        message=message,
        allowed_actions=_allowed_actions(is_dry_run, active, busy),
        device_time=_utcnow(),
        uptime_seconds=uptime,
        host=_hostname(),
        components=components,
        details=details,
    )


# ---------------------------------------------------------------------------
# Internal exception for top-level claim rejection body.
# FastAPI's HTTPException wraps the detail; v1.1 requires the rejection
# body at the top level so ``response.json()["claimed_by"]`` works.
# ---------------------------------------------------------------------------


class _ClaimResponseException(Exception):
    def __init__(
        self,
        status_code: int,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code
        self.payload = payload
        self.headers = headers or {}


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    global _pp96, _move_lock, _claims, _start_time
    _move_lock = asyncio.Lock()
    _claims = ClaimStore()
    _start_time = _utcnow()

    if HAS_HARDWARE:
        try:
            _pp96 = PressureProcessor()
            logger.info("PP96 hardware initialized")
        except Exception as exc:
            logger.warning("Failed to initialize PP96 hardware: %s", exc)
            _pp96 = None
    else:
        logger.warning("Running in dry-run mode (hardware libraries not available)")

    try:
        yield
    finally:
        try:
            await _claims.force_clear()
        except Exception:
            logger.exception("Error clearing claim on shutdown")
        if _pp96 is not None:
            try:
                _pp96.shutdown()
            except Exception as exc:
                logger.warning("Error during hardware shutdown: %s", exc)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Waters PP96 Control API",
    version="1.1.0",
    description=(
        "REST API for the Waters Positive Pressure-96 filtration press. "
        "Conforms to the AC lab equipment status spec v1.1. "
        "See docs/STATUS_SPEC_v1_1.md in the ac-organic-lab monorepo."
    ),
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(_ClaimResponseException)
async def _claim_response_handler(
    request: Request, exc: _ClaimResponseException  # noqa: ARG001
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.payload,
        headers=exc.headers,
    )


# ---------------------------------------------------------------------------
# Spec endpoints
# ---------------------------------------------------------------------------


@app.get("/", response_model=ProbeResponse, tags=["spec"])
async def probe() -> ProbeResponse:
    return ProbeResponse(
        equipment_id=EQUIPMENT_ID,
        equipment_name=EQUIPMENT_NAME,
        protocol_version=PROTOCOL_VERSION,
    )


@app.get("/health", response_model=HealthResponse, tags=["spec"])
async def health() -> HealthResponse:
    return HealthResponse()


@app.get("/status", response_model=EquipmentStatus, tags=["spec"])
async def status() -> EquipmentStatus:
    return await _build_status()


# ---------------------------------------------------------------------------
# Claim protocol (v1.1)
# ---------------------------------------------------------------------------


async def _require_claim(
    x_claim_token: Annotated[str | None, Header(alias="X-Claim-Token")] = None,
) -> None:
    """Dependency: gate /control/* on the live claim token."""
    if not ENFORCE_CLAIMS:
        return
    assert _claims is not None
    if x_claim_token is None or not await _claims.validate(x_claim_token):
        current = await _claims.current()
        payload: dict[str, Any] = {
            "detail": "missing or invalid X-Claim-Token; POST /control/claim first",
            "claimed_by": (
                current.model_dump(mode="json") if current is not None else None
            ),
            "retry_after_s": None,
        }
        raise _ClaimResponseException(status_code=423, payload=payload)


@app.post(
    "/control/claim",
    response_model=ClaimResponse,
    responses={409: {"model": ClaimRejection}},
    tags=["claim"],
)
async def control_claim(req: ClaimRequest) -> ClaimResponse:
    assert _claims is not None
    try:
        return await _claims.acquire(req)
    except ClaimConflict as exc:
        rejection = ClaimRejection(
            detail=str(exc),
            claimed_by=exc.claimed_by,
            retry_after_s=exc.retry_after_s,
        )
        raise _ClaimResponseException(
            status_code=409,
            payload=rejection.model_dump(mode="json"),
            headers={"Retry-After": str(int(exc.retry_after_s + 1))},
        )


@app.post("/control/heartbeat", response_model=ClaimResponse, tags=["claim"])
async def control_heartbeat(
    x_claim_token: Annotated[str | None, Header(alias="X-Claim-Token")] = None,
) -> ClaimResponse:
    assert _claims is not None
    try:
        return await _claims.heartbeat(x_claim_token)
    except UnknownClaim:
        raise HTTPException(
            status_code=401,
            detail="claim token is unknown or expired; POST /control/claim",
        )


@app.post("/control/release", status_code=204, tags=["claim"])
async def control_release(
    x_claim_token: Annotated[str | None, Header(alias="X-Claim-Token")] = None,
) -> Response:
    assert _claims is not None
    await _claims.release(x_claim_token)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Request / response models for control endpoints
# ---------------------------------------------------------------------------


class CommandResponse(BaseModel):
    ok: bool = True
    message: str | None = None


class PressMoveRequest(BaseModel):
    """Parameters for press movement commands."""

    hold_time: float = Field(
        default=0.5,
        ge=0.0,
        le=10.0,
        description="How long (seconds) to hold the pressed position before returning to neutral.",
    )


class PlateMoveRequest(BaseModel):
    """Parameters for plate carriage movement commands."""

    smooth: bool = Field(
        default=True,
        description="Ramp the actuator smoothly (True) vs. step move (False).",
    )


# ---------------------------------------------------------------------------
# Control endpoints
# ---------------------------------------------------------------------------


@app.post("/control/startup", response_model=CommandResponse, tags=["control"])
async def control_startup(
    _claim: None = Depends(_require_claim),
) -> CommandResponse:
    """Initialize the press to a known state: press UP, plate OUT, system ACTIVE.

    Must be called before any movement command on a freshly booted device,
    or after ``/control/stop``.
    """
    if not HAS_HARDWARE or _pp96 is None:
        return CommandResponse(message="Init (dry-run)")
    assert _move_lock is not None
    async with _move_lock:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, _pp96.init)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))
    return CommandResponse(message="System initialized and ACTIVE")


@app.post("/control/stop", response_model=CommandResponse, tags=["control"])
async def control_stop(
    _claim: None = Depends(_require_claim),
) -> CommandResponse:
    """Emergency-stop the press.  Disables all movement until the next /control/startup."""
    if not HAS_HARDWARE or _pp96 is None:
        return CommandResponse(message="Stop (dry-run)")
    try:
        _pp96.stop()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return CommandResponse(message="System STOPPED – call /control/startup to reactivate")


@app.post("/control/press/up", response_model=CommandResponse, tags=["control"])
async def control_press_up(
    req: PressMoveRequest,
    _claim: None = Depends(_require_claim),
) -> CommandResponse:
    """Move the pneumatic press to the UP position."""
    if not HAS_HARDWARE or _pp96 is None:
        return CommandResponse(message="Press UP (dry-run)")
    if _pp96._system_state != "active":
        raise HTTPException(
            status_code=409,
            detail="system is STOPPED; call /control/startup first",
        )
    assert _move_lock is not None
    async with _move_lock:
        loop = asyncio.get_running_loop()
        ok = await loop.run_in_executor(
            None, lambda: _pp96.press_up(hold_time=req.hold_time)
        )
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="system is STOPPED; call /control/startup first",
        )
    return CommandResponse(message="Press moved UP")


@app.post("/control/press/down", response_model=CommandResponse, tags=["control"])
async def control_press_down(
    req: PressMoveRequest,
    _claim: None = Depends(_require_claim),
) -> CommandResponse:
    """Move the pneumatic press to the DOWN position."""
    if not HAS_HARDWARE or _pp96 is None:
        return CommandResponse(message="Press DOWN (dry-run)")
    if _pp96._system_state != "active":
        raise HTTPException(
            status_code=409,
            detail="system is STOPPED; call /control/startup first",
        )
    assert _move_lock is not None
    async with _move_lock:
        loop = asyncio.get_running_loop()
        ok = await loop.run_in_executor(
            None, lambda: _pp96.press_down(hold_time=req.hold_time)
        )
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="system is STOPPED; call /control/startup first",
        )
    return CommandResponse(message="Press moved DOWN")


@app.post("/control/plate/in", response_model=CommandResponse, tags=["control"])
async def control_plate_in(
    req: PlateMoveRequest,
    _claim: None = Depends(_require_claim),
) -> CommandResponse:
    """Retract the plate carriage under the press (IN position)."""
    if not HAS_HARDWARE or _pp96 is None:
        return CommandResponse(message="Plate IN (dry-run)")
    if _pp96._system_state != "active":
        raise HTTPException(
            status_code=409,
            detail="system is STOPPED; call /control/startup first",
        )
    assert _move_lock is not None
    async with _move_lock:
        loop = asyncio.get_running_loop()
        ok = await loop.run_in_executor(
            None, lambda: _pp96.plate_in(smooth=req.smooth)
        )
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="system is STOPPED; call /control/startup first",
        )
    return CommandResponse(message="Plate moved IN")


@app.post("/control/plate/out", response_model=CommandResponse, tags=["control"])
async def control_plate_out(
    req: PlateMoveRequest,
    _claim: None = Depends(_require_claim),
) -> CommandResponse:
    """Extend the plate carriage away from the press (OUT position)."""
    if not HAS_HARDWARE or _pp96 is None:
        return CommandResponse(message="Plate OUT (dry-run)")
    if _pp96._system_state != "active":
        raise HTTPException(
            status_code=409,
            detail="system is STOPPED; call /control/startup first",
        )
    assert _move_lock is not None
    async with _move_lock:
        loop = asyncio.get_running_loop()
        ok = await loop.run_in_executor(
            None, lambda: _pp96.plate_out(smooth=req.smooth)
        )
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="system is STOPPED; call /control/startup first",
        )
    return CommandResponse(message="Plate moved OUT")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(host: str = "0.0.0.0", port: int = 8000) -> None:
    import uvicorn

    uvicorn.run("filter_every_well.api:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Waters PP96 REST API Server (v1.1)")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    main(host=args.host, port=args.port)
