#!/usr/bin/env python3
"""
Waters Automation – Raspberry Pi Zero 2 W + PCA9685 (Two Mirrored Servos + Linear Actuator on CH2)

Commands over stdin (one per line):
  up | down | neutral | open | grip | close
  set <0..180>
  speed <1..100>
  help | ? | quit | exit

# NEW actuator commands:
  push | pull

Hardware:
- Raspberry Pi Zero 2 W
- PCA9685 servo HAT/board at I2C address 0x40
- Two servos on channels 0 (primary) and 1 (mirrored)
- Linear actuator (servo-style) on channel 2
"""

import sys
import time
import math

try:
    from adafruit_servokit import ServoKit  # pulls in Blinka + PCA9685 + adafruit_motor
except Exception as e:
    print("ERROR: adafruit_servokit not found. Install prerequisites, see README.", file=sys.stderr)
    raise

# ===== Named positions (you can change these if you like) =====
OPEN_ANGLE    = 0
GRASP_ANGLE   = 120
CLOSED_ANGLE  = 180
READY_ANGLE   = 90   # Neutral / Ready

# Convenience for "up" and "down" behaviors
UP_ANGLE   = 30    # primary -> 30°, mirrored -> 150°
DOWN_ANGLE = 150   # primary -> 150°, mirrored -> 30°

SPEED_PERCENT = 60  # 1..100 (higher = faster)

# PCA9685 channels for the two servos
SERVO_CH_1 = 0     # primary
SERVO_CH_2 = 1     # mirrored (180 - primary)

# ===== Servo + PCA9685 setup =====
# 16 channels on a single PCA9685
kit = ServoKit(channels=16, address=0x40)  # change address if you moved A0..A5 jumpers
# Typical analog hobby servos: 50 Hz, ~500..2500 µs pulse
for ch in (SERVO_CH_1, SERVO_CH_2):
    s = kit.servo[ch]
    s.set_pulse_width_range(500, 2500)     # microseconds
    s.actuation_range = 180                # degrees [0, 180]

# Keep track of current angle ourselves (ServoKit doesn't read it back)
_current_angle = READY_ANGLE

def step_delay_from_speed(pct: int) -> float:
    """
    Map 1..100% -> 30..1 ms / degree (same feel as Arduino map).
    Returns seconds per degree for time.sleep().
    """
    pct = max(1, min(100, int(pct)))
    # 1..100% -> 30..1 (ms/deg)
    ms = ((100 - pct) * (30 - 1) / (100 - 1)) + 1  # linear map
    return ms / 1000.0

def _write_mirrored(angle: float):
    """Write primary angle and mirrored (180 - angle) to the two channels."""
    angle = max(0, min(180, angle))
    kit.servo[SERVO_CH_1].angle = angle
    kit.servo[SERVO_CH_2].angle = 180 - angle

def move_to_angle_mirrored(target: int):
    """Smoothly sweep to target with speed shaping; s2 = 180 - s1."""
    global _current_angle, SPEED_PERCENT
    target = max(0, min(180, int(target)))
    if _current_angle is None:
        _current_angle = target
        _write_mirrored(target)
        return

    step = 1 if target >= _current_angle else -1
    dly = step_delay_from_speed(SPEED_PERCENT)
    # Walk one degree at a time
    a = _current_angle
    while a != target:
        a += step
        _write_mirrored(a)
        time.sleep(dly)
    _current_angle = target
    _write_mirrored(target)

# ========================== ADDED: Linear Actuator on CH2 ==========================
SERVO_CH_ACT = 2  # third channel on PCA9685

# Tune these for your actuator/linkage
ACT_RETRACT_ANGLE = 0
ACT_EXTEND_ANGLE  = 180
ACT_READY_ANGLE   = 90

_actuator_angle = ACT_READY_ANGLE
try:
    s_act = kit.servo[SERVO_CH_ACT]
    s_act.set_pulse_width_range(500, 2500)  # adjust if your actuator needs a narrower range
    s_act.actuation_range = 180
except Exception:
    pass

def _write_actuator(angle: float):
    angle = max(0, min(180, angle))
    kit.servo[SERVO_CH_ACT].angle = angle

def move_actuator_to(target: int):
    """Smoothly sweep actuator to target using same SPEED_PERCENT shaping."""
    global _actuator_angle, SPEED_PERCENT
    target = max(0, min(180, int(target)))
    if _actuator_angle is None:
        _actuator_angle = target
        _write_actuator(target)
        return
    step = 1 if target >= _actuator_angle else -1
    dly = step_delay_from_speed(SPEED_PERCENT)
    a = _actuator_angle
    while a != target:
        a += step
        _write_actuator(a)
        time.sleep(dly)
    _actuator_angle = target
    _write_actuator(target)

# Home actuator to READY during startup init phase
try:
    _write_actuator(ACT_READY_ANGLE)
    _actuator_angle = ACT_READY_ANGLE
except Exception:
    pass
# ======================== END ADDED ACTUATOR SECTION ========================

def handle_command(line: str):
    global SPEED_PERCENT
    line = (line or "").strip().lower()

    if line in ("neutral", "ready", "center"):
        move_to_angle_mirrored(READY_ANGLE)
        print("State: NEUTRAL")
        return
    if line == "up":
        move_to_angle_mirrored(UP_ANGLE)
        print("State: UP (30 / 150)")
        return
    if line == "down":
        move_to_angle_mirrored(DOWN_ANGLE)
        print("State: DOWN (150 / 30)")
        return
    if line == "open":
        move_to_angle_mirrored(OPEN_ANGLE)
        print("State: OPEN")
        return
    if line == "grip":
        move_to_angle_mirrored(GRASP_ANGLE)
        print("State: GRIP")
        return
    if line in ("close", "closed"):
        move_to_angle_mirrored(CLOSED_ANGLE)
        print("State: CLOSED")
        return
    if line.startswith("set "):
        try:
            angle = int(line.split(None, 1)[1])
        except Exception:
            print("Usage: set <0..180>")
            return
        angle = max(0, min(180, angle))
        move_to_angle_mirrored(angle)
        print(f"Angle set to {angle} / {180 - angle}")
        return
    if line.startswith("speed "):
        try:
            pct = int(line.split(None, 1)[1])
        except Exception:
            print("Usage: speed <1..100>")
            return
        SPEED_PERCENT = max(1, min(100, pct))
        print(f"Speed set to {SPEED_PERCENT}%")
        return
    if line in ("help", "?"):
        print("Commands: up | down | neutral | open | grip | close | set <0..180> | speed <1..100> | quit")
        # Added line for actuator commands (non-breaking)
        print("Actuator: push | pull")
        return
    if line in ("quit", "exit"):
        raise SystemExit

    # ---- Added actuator commands (doesn't change existing two-servo logic) ----
    if line == "push":
        move_actuator_to(ACT_EXTEND_ANGLE)
        print("Actuator: PUSH (extended)")
        return
    if line == "pull":
        move_actuator_to(ACT_RETRACT_ANGLE)
        print("Actuator: PULL (retracted)")
        return
    # ---------------------------------------------------------------------------

    print("Unrecognized. Try: up | down | neutral | open | grip | close | set <angle> | speed <1..100> | help")

def main():
    global _current_angle
    # Move to ready on startup
    _write_mirrored(READY_ANGLE)
    _current_angle = READY_ANGLE
    time.sleep(0.2)

    print("Waters Automation ready (Pi + PCA9685).")
    print("Commands: up | down | neutral | open | grip | close | set <0..180> | speed <1..100> | help")
    # Added informational line for actuator
    print("Actuator: push | pull")

    # Read commands line-by-line from stdin, like Arduino serial monitor
    try:
        for line in sys.stdin:
            handle_command(line)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        # Park safely at neutral on exit
        try:
            move_to_angle_mirrored(READY_ANGLE)
            time.sleep(0.2)
        except Exception:
            pass
        # Release pulses (optional): set to None to stop driving
        try:
            kit.servo[SERVO_CH_1].angle = None
            kit.servo[SERVO_CH_2].angle = None
        except Exception:
            pass
        # Also release actuator channel
        try:
            kit.servo[SERVO_CH_ACT].angle = None
        except Exception:
            pass

if __name__ == "__main__":
    main()

