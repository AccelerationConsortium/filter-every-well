#!/usr/bin/env python3
import sys
import time
import math
import RPi.GPIO as GPIO
from adafruit_servokit import ServoKit

# ====================== SERVO CONFIG ==========================

SERVO_CH_PRIMARY = 0     # Servo 1
SERVO_CH_MIRROR = 15      # Servo 2 (mirrored)
SERVO_CH_ACT = 2          # Actuator channel

OPEN_ANGLE    = 0
GRASP_ANGLE   = 120
CLOSED_ANGLE  = 180
READY_ANGLE   = 90

UP_ANGLE   = 30
DOWN_ANGLE = 150

# Actuator safe limits (Option B)
ACT_PULL_SAFE  = 5      # DO NOT use 0° during normal use
ACT_PUSH_SAFE  = 170    # DO NOT use 180° during normal use

SPEED_PERCENT = 60

# ====================== PCA9685 SETUP ==========================

kit = ServoKit(channels=16, address=0x40)

for ch in (SERVO_CH_PRIMARY, SERVO_CH_MIRROR, SERVO_CH_ACT):
    try:
        s = kit.servo[ch]
        s.set_pulse_width_range(500, 2500)
        s.actuation_range = 180
    except Exception:
        pass

_current_angle = READY_ANGLE
_actuator_angle = ACT_PULL_SAFE  # will be corrected after calibration

def step_delay_from_speed(pct: int) -> float:
    pct = max(1, min(100, int(pct)))
    ms = ((100 - pct) * (30 - 1) / 99) + 1
    return ms / 1000.0


# ====================== MIRRORED SERVO MOVEMENT ==========================

def _write_mirrored(angle: float):
    angle = max(0, min(180, angle))
    kit.servo[SERVO_CH_PRIMARY].angle = angle
    kit.servo[SERVO_CH_MIRROR].angle = 180 - angle


def move_to_angle_mirrored(target: int):
    global _current_angle
    target = max(0, min(180, int(target)))

    step = 1 if target >= _current_angle else -1
    dly = step_delay_from_speed(SPEED_PERCENT)
    a = _current_angle

    while a != target:
        a += step
        _write_mirrored(a)
        time.sleep(dly)

    _current_angle = target
    _write_mirrored(target)

# ====================== ACTUATOR ==========================

def _write_actuator(angle: float):
    angle = max(0, min(180, angle))
    kit.servo[SERVO_CH_ACT].angle = angle


def move_actuator_to(target: int):
    global _actuator_angle
    target = max(0, min(180, int(target)))
    
    step = 1 if target >= _actuator_angle else -1
    dly = step_delay_from_speed(SPEED_PERCENT)
    a = _actuator_angle

    while a != target:
        a += step
        _write_actuator(a)
        time.sleep(dly)

    _actuator_angle = target
    _write_actuator(target)


# ====================== ACTUATOR CALIBRATION (CRITICAL FIX) ==========================

def calibrate_actuator():
    global _actuator_angle

    print("Calibrating actuator...")

    # 1. Hard pull to stop
    _write_actuator(0)
    time.sleep(0.40)

    # 2. Move forward to escape deadband
    _write_actuator(10)
    time.sleep(0.25)

    # 3. Move to defined safe pulled position
    _write_actuator(ACT_PULL_SAFE)
    time.sleep(0.25)

    _actuator_angle = ACT_PULL_SAFE

    print(f"Actuator calibrated. Start = {ACT_PULL_SAFE}°")


# ====================== RELAY (ACTIVE-HIGH, CLEANUP ON OFF) ==========================

RELAY_PIN = 17

# Global init: set mode but don't assume pin stays configured forever
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
GPIO.setup(RELAY_PIN, GPIO.OUT, initial=GPIO.LOW)  # start OFF

def relay_on():
    # If someone cleaned up the pin, we need to re-init it
    if GPIO.getmode() is None:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
    try:
        GPIO.setup(RELAY_PIN, GPIO.OUT)
    except RuntimeError:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(RELAY_PIN, GPIO.OUT)

    GPIO.output(RELAY_PIN, GPIO.HIGH)  # ACTIVE-HIGH: HIGH = ON
    print("Relay ON (GPIO17 HIGH)")

def relay_off():
    # Your requested behavior: turn relay off by cleaning up the pin
    try:
        GPIO.cleanup(RELAY_PIN)
        print("Relay OFF (GPIO17 cleaned up)")
    except Exception as e:
        print(f"Relay OFF error during cleanup: {e}")

# ====================== COMMAND HANDLER ==========================

def handle_command(line: str):
    global SPEED_PERCENT
    line = (line or "").strip().lower()

    if line in ("neutral", "ready", "center"):
        move_to_angle_mirrored(READY_ANGLE)
        print("State: NEUTRAL")
        return
    if line == "up":
        move_to_angle_mirrored(UP_ANGLE)
        print("State: UP")
        return
    if line == "down":
        move_to_angle_mirrored(DOWN_ANGLE)
        print("State: DOWN")
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
            angle = int(line.split()[1])
        except:
            print("Usage: set <0..180>")
            return
        move_to_angle_mirrored(angle)
        print(f"Angle set to {angle}°")
        return

    if line.startswith("speed "):
        try:
            SPEED_PERCENT = int(line.split()[1])
        except:
            print("Usage: speed <1..100>")
            return
        SPEED_PERCENT = max(1, min(100, SPEED_PERCENT))
        print(f"Speed set to {SPEED_PERCENT}%")
        return

    # Actuator
    if line == "push":
        move_actuator_to(ACT_PUSH_SAFE)
        print(f"Actuator PUSH → {ACT_PUSH_SAFE}°")
        return

    if line == "pull":
        move_actuator_to(ACT_PULL_SAFE)
        print(f"Actuator PULL → {ACT_PULL_SAFE}°")
        return

    # Relay
    if line == "relay on":
        relay_on()
        return

    if line == "relay off":
        relay_off()
        return

    if line in ("help", "?"):
        print("Commands: up | down | neutral | open | grip | close | set <0..180> | speed <1..100>")
        print("Actuator: push | pull")
        print("Relay: relay on | relay off")
        print("System: help | quit | exit")
        return

    if line in ("quit", "exit"):
        raise SystemExit

    print("Unknown command. Type 'help'.")

# ====================== MAIN ==========================

def main():
    global _current_angle

    # Move dual servos to ready
    _write_mirrored(READY_ANGLE)
    _current_angle = READY_ANGLE
    time.sleep(0.2)

    # Critical: fix actuator direction issue
    calibrate_actuator()

    print("System ready.")
    print("Commands: up | down | open | grip | close | push | pull | relay on/off | quit")

    try:
        for line in sys.stdin:
            handle_command(line)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        print("\nShutting down safely...")

        try:
            # Put mirrored servos in neutral
            move_to_angle_mirrored(READY_ANGLE)
            time.sleep(0.2)
        except:
            pass

        try:
            # Move actuator to safe retracted position
            move_actuator_to(ACT_PULL_SAFE)
            time.sleep(0.2)
        except:
            pass

        # Stop sending PWM to servos
        try:
            kit.servo[SERVO_CH_PRIMARY].angle = None
            kit.servo[SERVO_CH_MIRROR].angle = None
            kit.servo[SERVO_CH_ACT].angle = None
        except:
            pass

        # Full GPIO cleanup at the very end
        try:
            GPIO.cleanup()
        except:
            pass

        print("Safe shutdown complete.")


if __name__ == "__main__":
    main()
