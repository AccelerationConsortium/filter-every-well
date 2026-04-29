# filter-every-well

Remote control for Waters Positive Pressure-96 Processor (PP96) using a Raspberry Pi Zero 2W and a 16‑channel PWM/servo HAT.

**Features:**
- 🌐 **REST API** - Persistent service with state tracking, accessible via WiFi and Tailscale
- 🔒 **Safety Controls** - Init/stop mechanism prevents accidental movement
- 📊 **State Tracking** - Always know press position (up/down) and plate position (in/out)
- 🛠️ **Multiple Interfaces** - REST API, CLI, or Python library
- 🎯 **Hardware Control** - Two mirrored servos for press control, linear actuator for plate positioning

> **Note:** Install with `pip install .[hardware]` on your Raspberry Pi to enable hardware control. On other systems, commands run in dry-run mode.

## Hardware

- Raspberry Pi Zero 2W
- PCA9685 16‑channel PWM/servo HAT at I2C address 0x40
- Two servos on channels 0 & 15 (mirror-mounted, servo_2 = 180° - servo_1)
- Linear actuator on channel 2 (controlled as a servo)

The two servos rotate in opposite directions (mirrored) to press the same position on mirror-image rocker buttons. All servos configured with 500-2500µs pulse width range.

## Installation

Python 3.9+ is required.

```bash
# From source (editable):
pip install -e .

# Or build a wheel/sdist and install
python -m pip install build
python -m build
pip install dist/*.whl
```

### Optional dependencies

**Hardware support (for Raspberry Pi):**

```bash
pip install .[hardware]
```

Includes: `adafruit-circuitpython-servokit`, `RPi.GPIO`

**REST API server:**

```bash
pip install .[api]
```

Includes: `fastapi`, `uvicorn`, `pydantic`

**Everything (hardware + API):**

```bash
pip install .[all]
```

## Usage

### REST API (Recommended for persistent service)

The REST API maintains a persistent connection to hardware and tracks system state between requests.

**Start the API server:**

```bash
# Start API server (default: http://0.0.0.0:8000)
filter-every-well-api

# Or specify host/port
filter-every-well-api --host 127.0.0.1 --port 5000
```

**Interactive API Documentation:**
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

**API Endpoints:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/status` | Get system status |
| POST | `/init` | Initialize system (required before first use) |
| POST | `/stop` | Emergency stop (disables all movement) |
| POST | `/press/up` | Move press UP |
| POST | `/press/down` | Move press DOWN |
| POST | `/plate/in` | Move plate IN (under press) |
| POST | `/plate/out` | Move plate OUT (away from press) |

**Example Workflow:**

```bash
# 1. Check initial status (system is stopped)
curl http://localhost:8000/status | jq
# {
#   "equipment_name": "waters_filtration_pressor",
#   "equipment_ip": "192.168.1.100",
#   "equipment_tailscale": "100.64.254.104",
#   "equipment_status": "ready",
#   "message": "Hardware ready - System is STOPPED",
#   "system_state": "stopped",
#   "press_state": "unknown",
#   "plate_state": "unknown"
# }

# 2. Initialize system (moves press UP and plate OUT)
curl -X POST http://localhost:8000/init | jq
# {
#   "equipment_name": "waters_filtration_pressor",
#   "equipment_ip": "192.168.1.100",
#   "equipment_tailscale": "100.64.254.104",
#   "equipment_status": "success",
#   "message": "System initialized and ACTIVE",
#   "system_state": "active",
#   "press_state": "up",
#   "plate_state": "out"
# }

# 3. Move plate under press
curl -X POST http://localhost:8000/plate/in | jq

# 4. Lower press
curl -X POST http://localhost:8000/press/down | jq

# 5. Raise press
curl -X POST http://localhost:8000/press/up | jq

# 6. Move plate out
curl -X POST http://localhost:8000/plate/out | jq

# 7. Emergency stop (if needed)
curl -X POST http://localhost:8000/stop | jq
# System is now stopped. Call /init to reactivate.
```

**Remote Access:**

The API is accessible via both WiFi and Tailscale:

```bash
# Local network (find Pi's IP: hostname -I)
curl http://192.168.1.100:8000/status

# Tailscale VPN (find Pi's Tailscale IP: tailscale ip -4)
curl http://100.64.254.104:8000/status
```

### CLI (Quick one-shot commands)

```bash
# Move press
filter-every-well up
filter-every-well down

# Move plate
filter-every-well plate in
filter-every-well plate out
```

### Python API

```python
from filter_every_well import PressureProcessor

# Initialize hardware (system starts in stopped state)
pp96 = PressureProcessor()

# Initialize to known state (press UP, plate OUT)
pp96.init()  # Sets system to active

# Control press (servo 1 / servo 2 mirrored)
pp96.press_up()        # Raises pneumatic press
pp96.press_down()      # Lowers pneumatic press

# Control plate actuator
pp96.plate_in()        # Move plate under press
pp96.plate_out()       # Move plate away from press

# Optional: instant movement without smooth speed control
pp96.plate_in(smooth=False)
pp96.plate_out(smooth=False)

# Emergency stop (disables all movement)
pp96.stop()

# Must call init() again to resume
pp96.init()

# Clean shutdown (returns to neutral, releases servos)
pp96.shutdown()

# Or manual initialization with custom configuration
pp96 = PressureProcessor(
    channels=16,
    address=0x40,
    servo_1_channel=0,           # Primary servo
    servo_2_channel=15,          # Mirrored servo (180 - servo_1)
    actuator_channel=2,          # Linear actuator
    servo_up_angle=30.0,         # Servo 1 angle for UP
    servo_down_angle=150.0,      # Servo 1 angle for DOWN
    servo_neutral_angle=90.0,    # Neutral position
    actuator_in_angle=40.0,      # Actuator retracted (plate in/pull)
    actuator_out_angle=140.0,    # Actuator extended (plate out/push - resting)
    actuator_speed_percent=60,   # Actuator movement speed 1-100%
    pulse_min=500,               # Pulse width range
    pulse_max=2500,
)
pp96.press_up(hold_time=0.5)
pp96.shutdown()
```

## System States

The API tracks three types of state:

**System State:**
- `stopped` - System inactive, no movement allowed (default at startup)
- `active` - System active, movement commands allowed

**Press State:**
- `unknown` - Position unknown (at startup or after stop)
- `up` - Pneumatic press raised
- `down` - Pneumatic press lowered

**Plate State:**
- `unknown` - Position unknown (at startup or after stop)
- `in` - Plate under press (actuator retracted)
- `out` - Plate away from press (actuator extended)

**State Transitions:**

```
Startup → stopped/unknown/unknown
  ↓ /init
Active → active/up/out
  ↓ /press/down
Active → active/down/out
  ↓ /plate/in
Active → active/down/in
  ↓ /stop
Stopped → stopped/unknown/unknown
  ↓ /init (to resume)
Active → active/up/out
```

## Running API as a System Service

To run the API automatically on boot (recommended for production):

```bash
# Copy service file
sudo cp filter-every-well-api.service /etc/systemd/system/

# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable filter-every-well-api
sudo systemctl start filter-every-well-api

# Check status
sudo systemctl status filter-every-well-api

# View logs
sudo journalctl -u filter-every-well-api -f
```

The API will be available at `http://<pi-ip>:8000`

## Development

- Project metadata is defined in `pyproject.toml` (PEP 621)
- Source lives under `src/filter_every_well/`
- Entry points:
  - `filter-every-well` → CLI (`filter_every_well.cli:main`)
  - `filter-every-well-api` → API server (`filter_every_well.api:main`)

## License

MIT. See `LICENSE`.
