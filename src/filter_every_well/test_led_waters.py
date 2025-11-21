#!/usr/bin/env python3
"""
Waters Automation – Raspberry Pi Zero 2 W + PCA9685 (Two Mirrored Servos + Linear Actuator + Relay/LED)

Commands over stdin (one per line):
  up | down | neutral | open | grip | close
  set <0..180>
  speed <1..100>
  help | ? | quit | exit
  push | pull
  relay on | relay off
  led on | led off

Hardware:
- Raspberry Pi Zero 2 W
- PCA9685 servo HAT/board at I2C address 0x40
- Two servos on channels 0 (primary) and 1 (mirrored)
- Linear actuator (servo-style) on channel 2
- Relay/LED on GPIO 17
"""

import sys
import time
import math
import RPi.GPIO as GPIO

try:
    from adafruit_servokit import ServoKit
except Exception as e:
    print("ERROR: adafruit_servokit not found. Install prerequisites, see README.", file=sys.stderr)
    raise

# ===== GPIO SETUP (Relay/LED) =====
RELAY_PIN = 17
GPIO.setmode(GPIO.BCM)
GPIO.setup(RELAY_PIN, GPIO.OUT)
GPIO.output(RELAY_PIN, GPIO.LOW)  # start off

# ===== Named positions =====
OPEN_ANGLE    = 0
GRASP_ANGLE   = 120
CLOSED_ANGLE  = 180
READY_ANGLE   = 90

UP_ANGLE   = 30
DOWN_ANGLE = 150

SPEED_PERCENT = 60

SERVO_CH_1 = 0
SERVO_CH_2 = 1

kit = ServoKit(channels=16, address=0x40)
for ch in (SERVO_CH_1, SERVO_CH_2):
    s = kit.servo[ch]
    s.set_pulse_width_range(500, 2500)
    s.actuation_range = 180

_current_angle = READY_ANGLE

def step_delay_from_speed(pct: int) -> float:
    pct = max(1, min(100, int(pct)))
    ms = ((100 - pct) * (30 - 1) / (100 - 1)) + 1
    return ms / 1000.0

def _write_mirrored(angle: float):
    angle = max(0, min(180, angle))
    kit.servo[SERVO_CH_1].angle = angle
    kit.servo[SERVO_CH_2].angle = 180 - angle

def move_to_angle_mirrored(target: int):
    global _current_angle, SPEED_PERCENT
    target = max(0, min(180, int(target)))
    if _current_angle is None:
        _current_angle = target
        _write_mirrored(target)
        return
    step = 1 if target >= _current_angle else -1
    dly = step_delay_from_speed(SPEED_PERCENT)
    a = _current_angle
    while a != target:
        a += step
        _write_mirrored(a)
        time.sleep(dly)
    _current_angle = target
    _write_mirrored(target)

# ===================== Linear Actuator =====================
SERVO_CH_ACT = 2
ACT_RETRACT_ANGLE = 0
ACT_EXTEND_ANGLE  = 180
ACT_READY_ANGLE   = 90
_actuator_angle = ACT_READY_ANGLE
try:
    s_act = kit.servo[SERVO_CH_ACT]
    s_act.set_pulse_width_range(500, 2500)
    s_act.actuation_range = 180
except Exception:
    pass

def _write_actuator(angle: float):
    angle = max(0, min(180, angle))
    kit.servo[SERVO_CH_ACT].angle = angle

def move_actuator_to(target: int):
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

try:
    _write_actuator(ACT_READY_ANGLE)
    _actuator_angle = ACT_READY_ANGLE
except Exception:
    pass

# ===================== Command Handler =====================
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

    # --- Actuator commands ---
    if line == "push":
        move_actuator_to(ACT_EXTEND_ANGLE)
        print("Actuator: PUSH (extended)")
        return
    if line == "pull":
        move_actuator_to(ACT_RETRACT_ANGLE)
        print("Actuator: PULL (retracted)")
        return

    # --- Relay / LED commands ---
    if line in ("relay on", "led on"):
        GPIO.output(RELAY_PIN, GPIO.HIGH)
        print("Relay ON (GPIO17 HIGH)")
        return
    if line in ("relay off", "led off"):
        GPIO.output(RELAY_PIN, GPIO.LOW)
        print("Relay OFF (GPIO17 LOW)")
        return

    if line in ("help", "?"):
        print("Commands: up | down | neutral | open | grip | close | set <0..180> | speed <1..100> | quit")
        print("Actuator: push | pull")
        print("Relay/LED: relay on | relay off | led on | led off")
        return

    if line in ("quit", "exit"):
        raise SystemExit

    print("Unrecognized command. Try 'help' for options.")

# ===================== Main =====================
def main():
    global _current_angle
    _write_mirrored(READY_ANGLE)
    _current_angle = READY_ANGLE
    time.sleep(0.2)

    print("Waters Automation ready (Pi + PCA9685 + Relay).")
    print("Commands: up | down | neutral | open | grip | close | set <0..180> | speed <1..100> | help")
    print("Actuator: push | pull")
    print("Relay/LED: relay on | relay off | led on | led off")

    try:
        for line in sys.stdin:
            handle_command(line)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        try:
            move_to_angle_mirrored(READY_ANGLE)
            time.sleep(0.2)
        except Exception:
            pass
        try:
            kit.servo[SERVO_CH_1].angle = None
            kit.servo[SERVO_CH_2].angle = None
            kit.servo[SERVO_CH_ACT].angle = None
        except Exception:
            pass
        GPIO.output(RELAY_PIN, GPIO.LOW)
        GPIO.cleanup()

if __name__ == "__main__":
    main()
