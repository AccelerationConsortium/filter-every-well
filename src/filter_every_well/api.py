#!/usr/bin/env python3
"""
RESTful API server for Waters PP96 control.
Maintains persistent connection to hardware and tracks state.
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import uvicorn

try:
    from filter_every_well.pp96 import PressureProcessor
    HAS_HARDWARE = True
except RuntimeError:
    HAS_HARDWARE = False


# Response models
class StatusResponse(BaseModel):
    status: str
    message: str
    system_state: Optional[str] = None  # "stopped", "active"
    press_state: Optional[str] = None  # "up", "down", "unknown"
    plate_state: Optional[str] = None  # "in", "out", "unknown"


class ErrorResponse(BaseModel):
    error: str
    detail: str


# Create FastAPI app
app = FastAPI(
    title="Waters PP96 Control API",
    description="Control Waters Positive Pressure-96 Processor via REST API",
    version="0.1.0",
)

# Global hardware instance (persistent across requests)
pp96: Optional[PressureProcessor] = None


@app.on_event("startup")
async def startup_event():
    """Initialize hardware on server startup."""
    global pp96
    if HAS_HARDWARE:
        try:
            pp96 = PressureProcessor()
            print("✓ Hardware initialized successfully")
        except Exception as e:
            print(f"✗ Failed to initialize hardware: {e}")
            pp96 = None
    else:
        print("⚠ Running in dry-run mode (hardware libraries not available)")


@app.on_event("shutdown")
async def shutdown_event():
    """Clean shutdown of hardware."""
    global pp96
    if pp96:
        try:
            pp96.shutdown()
            print("✓ Hardware shut down successfully")
        except Exception as e:
            print(f"⚠ Error during shutdown: {e}")


@app.get("/", response_model=StatusResponse)
async def root():
    """API root - health check."""
    return StatusResponse(
        status="ok",
        message="Waters PP96 Control API is running",
        system_state=pp96._system_state if pp96 else None,
        press_state=pp96._press_state if pp96 else None,
        plate_state=pp96._plate_state if pp96 else None
    )


@app.get("/status", response_model=StatusResponse)
async def get_status():
    """Get current system status."""
    if not pp96:
        return StatusResponse(
            status="dry-run",
            message="Hardware not available - running in dry-run mode"
        )
    
    return StatusResponse(
        status="ready",
        message=f"Hardware ready - System is {pp96._system_state.upper()}",
        system_state=pp96._system_state,
        press_state=pp96._press_state,
        plate_state=pp96._plate_state
    )


@app.post("/init", response_model=StatusResponse)
async def initialize():
    """
    Initialize system to known state:
    - Move press UP
    - Move plate OUT
    - Activate system
    
    Must be called before any movement commands.
    """
    if not pp96:
        return StatusResponse(status="dry-run", message="Init (dry-run)")
    
    try:
        pp96.init()
        return StatusResponse(
            status="success",
            message="System initialized and ACTIVE",
            system_state=pp96._system_state,
            press_state=pp96._press_state,
            plate_state=pp96._plate_state
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/stop", response_model=StatusResponse)
async def stop_system():
    """
    Emergency stop: Disable all movement.
    Call /init to reactivate.
    """
    if not pp96:
        return StatusResponse(status="dry-run", message="Stop (dry-run)")
    
    try:
        pp96.stop()
        return StatusResponse(
            status="success",
            message="System STOPPED - call /init to reactivate",
            system_state=pp96._system_state,
            press_state=pp96._press_state,
            plate_state=pp96._plate_state
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/press/up", response_model=StatusResponse)
async def press_up(hold_time: float = 0.5):
    """Move pneumatic press UP. Requires system to be active (call /init first)."""
    if not pp96:
        return StatusResponse(status="dry-run", message="Press UP (dry-run)")
    
    try:
        if pp96.press_up(hold_time=hold_time):
            return StatusResponse(
                status="success",
                message="Press moved UP",
                system_state=pp96._system_state,
                press_state=pp96._press_state,
                plate_state=pp96._plate_state
            )
        else:
            return StatusResponse(
                status="stopped",
                message="System is STOPPED. Call /init to activate before movement.",
                system_state=pp96._system_state,
                press_state=pp96._press_state,
                plate_state=pp96._plate_state
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/press/down", response_model=StatusResponse)
async def press_down(hold_time: float = 0.5):
    """Move pneumatic press DOWN. Requires system to be active (call /init first)."""
    if not pp96:
        return StatusResponse(status="dry-run", message="Press DOWN (dry-run)")
    
    try:
        if pp96.press_down(hold_time=hold_time):
            return StatusResponse(
                status="success",
                message="Press moved DOWN",
                system_state=pp96._system_state,
                press_state=pp96._press_state,
                plate_state=pp96._plate_state
            )
        else:
            return StatusResponse(
                status="stopped",
                message="System is STOPPED. Call /init to activate before movement.",
                system_state=pp96._system_state,
                press_state=pp96._press_state,
                plate_state=pp96._plate_state
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/plate/in", response_model=StatusResponse)
async def plate_in(smooth: bool = True):
    """Move plate under the press (retract actuator to IN position). Requires system to be active (call /init first)."""
    if not pp96:
        return StatusResponse(status="dry-run", message="Plate IN (dry-run)")
    
    try:
        if pp96.plate_in(smooth=smooth):
            return StatusResponse(
                status="success",
                message="Plate moved IN",
                system_state=pp96._system_state,
                press_state=pp96._press_state,
                plate_state=pp96._plate_state
            )
        else:
            return StatusResponse(
                status="stopped",
                message="System is STOPPED. Call /init to activate before movement.",
                system_state=pp96._system_state,
                press_state=pp96._press_state,
                plate_state=pp96._plate_state
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/plate/out", response_model=StatusResponse)
async def plate_out(smooth: bool = True):
    """Move plate away from press (extend actuator to OUT position). Requires system to be active (call /init first)."""
    if not pp96:
        return StatusResponse(status="dry-run", message="Plate OUT (dry-run)")
    
    try:
        if pp96.plate_out(smooth=smooth):
            return StatusResponse(
                status="success",
                message="Plate moved OUT",
                system_state=pp96._system_state,
                press_state=pp96._press_state,
                plate_state=pp96._plate_state
            )
        else:
            return StatusResponse(
                status="stopped",
                message="System is STOPPED. Call /init to activate before movement.",
                system_state=pp96._system_state,
                press_state=pp96._press_state,
                plate_state=pp96._plate_state
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def main(host: str = "0.0.0.0", port: int = 8000):
    """Run the API server."""
    print("=" * 60)
    print("Waters PP96 Control API")
    print("=" * 60)
    print(f"Starting server at http://{host}:{port}")
    print(f"API docs available at http://{host}:{port}/docs")
    print("=" * 60)
    
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Waters PP96 REST API Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    args = parser.parse_args()
    
    main(host=args.host, port=args.port)
