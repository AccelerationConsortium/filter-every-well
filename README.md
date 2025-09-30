# filter-every-well

Control a Waters Positive Pressure-96 Processor (PP96) using a Raspberry Pi Zero 2W
and a 16‑channel motor HAT. This project exposes a small Python API and a simple CLI
for driving two servos (press up/down/neutral) and a linear actuator (plate in/out).

> **Note:** When hardware dependencies are not installed, the CLI runs in dry-run mode.
> Install with `pip install .[hardware]` on your Raspberry Pi to enable actual control.

## Hardware

- Raspberry Pi Zero 2W
- PCA9685 16‑channel PWM/servo HAT at I2C address 0x40
- Two servos on channels 0 & 1 (mirror-mounted, servo_2 = 180° - servo_1)
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

### Optional hardware dependencies

Install with extras to pull in common libraries for the PCA9685 on Raspberry Pi:

```bash
pip install .[hardware]
```

This extra includes:
- adafruit-circuitpython-servokit (which pulls in pca9685 and blinka)

## Usage

### CLI

```bash
# Move press
filter-every-well up
filter-every-well down
filter-every-well neutral

# Move plate
filter-every-well plate in
filter-every-well plate out
```

### Python API

```python
from filter_every_well import PressureProcessor

# Context manager ensures proper cleanup
# On initialization: servos to neutral (90°), actuator to OUT (0° - resting state)
with PressureProcessor() as pp96:
    # Control press (servo 1 / servo 2 mirrored)
    pp96.press_up()        # 30° / 150°
    pp96.press_down()      # 150° / 30°
    pp96.press_neutral()   # 90° / 90°
    
    # Control plate actuator (only IN and OUT)
    pp96.plate_in()        # Extend to 180° (push)
    pp96.plate_out()       # Retract to 0° (pull - resting state)

# Or manual initialization with custom configuration
pp96 = PressureProcessor(
    channels=16,
    address=0x40,
    servo_1_channel=0,           # Primary servo
    servo_2_channel=1,           # Mirrored servo (180 - servo_1)
    actuator_channel=2,          # Linear actuator
    servo_up_angle=30.0,         # Servo 1 angle for UP
    servo_down_angle=150.0,      # Servo 1 angle for DOWN
    servo_neutral_angle=90.0,    # Neutral position
    actuator_in_angle=180.0,     # Actuator extended (plate in/push)
    actuator_out_angle=0.0,      # Actuator retracted (plate out/pull - resting)
    pulse_min=500,               # Pulse width range
    pulse_max=2500,
)
pp96.press_up(hold_time=0.5)
pp96.shutdown()
```

## Development

- Project metadata is defined in `pyproject.toml` (PEP 621)
- Source lives under `src/filter_every_well/`
- Entry point script `filter-every-well` maps to `filter_every_well.cli:main`

## License

MIT. See `LICENSE`.
