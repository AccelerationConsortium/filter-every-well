# filter-every-well

Control a Waters Positive Pressure-96 Processor (PP96) using a Raspberry Pi Zero 2W
and a 16‑channel motor HAT. This project exposes a small Python API and a simple CLI
for driving two servos (press up/down/neutral) and a linear actuator (plate in/out).

> **Note:** When hardware dependencies are not installed, the CLI runs in dry-run mode.
> Install with `pip install .[hardware]` on your Raspberry Pi to enable actual control.

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

Start the API server:

```bash
# Start API server (default: http://0.0.0.0:8000)
filter-every-well-api

# Or specify host/port
filter-every-well-api --host 127.0.0.1 --port 5000
```

Access the interactive API docs at `http://localhost:8000/docs`

**API Endpoints:**

```bash
# Check status
curl http://localhost:8000/status

# Control press
curl -X POST http://localhost:8000/press/up
curl -X POST http://localhost:8000/press/down

# Control plate
curl -X POST http://localhost:8000/plate/in
curl -X POST http://localhost:8000/plate/out
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

# Context manager ensures proper cleanup
# On initialization: servos to neutral (90°), actuator position unknown
with PressureProcessor() as pp96:
    # Control press (servo 1 / servo 2 mirrored)
    pp96.press_up()        # 30° / 150° - raises pneumatic press
    pp96.press_down()      # 150° / 30° - lowers pneumatic press
    
    # Control plate actuator (only IN and OUT, with smooth movement)
    pp96.plate_in()        # Retract to 40° (pull - plate under press)
    pp96.plate_out()       # Extend to 140° (push - plate away, resting state)
    
    # Optional: instant movement without speed control
    pp96.plate_in(smooth=False)
    pp96.plate_out(smooth=False)

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
