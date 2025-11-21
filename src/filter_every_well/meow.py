#!/usr/bin/env python3
"""
Waters Automation – Pi Zero 2 W + PCA9685 via smbus
(Two Mirrored Servos on CH0/1 + Linear Actuator on CH2 + Relay/LED on GPIO17)

Relay is ACTIVE-LOW (LOW = ON, HIGH = OFF).

Commands:
  up | down | neutral | open | grip | close
  set <0..180>
  speed <1..100>
  push | pull
  relay on | relay off | relay toggle | relay status
  help | ? | quit | exit
"""

import sys, time

# ---------- I2C / smbus (PCA9685) ----------
try:
    from smbus2 import SMBus
except Exception as e:
    print("ERROR: smbus2 not found. Install: sudo apt-get install -y python3-smbus && pip3 install smbus2", file=sys.stderr)
    raise

I2C_BUS_NUM   = 1
PCA_ADDR      = 0x40
MODE1         = 0x00
PRESCALE      = 0xFE

def pca_write8(bus, reg, val): bus.write_byte_data(PCA_ADDR, reg, val & 0xFF)
def pca_read8(bus, reg): return bus.read_byte_data(PCA_ADDR, reg)

def pca_set_pwm_freq(bus, freq_hz: float):
    prescaleval = 25000000.0 / (4096.0 * float(freq_hz)) - 1.0
    prescale = int(prescaleval + 0.5)
    oldmode = pca_read8(bus, MODE1)
    pca_write8(bus, MODE1, (oldmode & 0x7F) | 0x10)  # sleep
    pca_write8(bus, PRESCALE, prescale)
    pca_write8(bus, MODE1, oldmode)                 # wake
    time.sleep(0.005)
    pca_write8(bus, MODE1, oldmode | 0xA1)          # restart, autoinc

def pca_set_pwm(bus, channel: int, on: int, off: int):
    base = 0x06 + 4 * channel
    bus.write_i2c_block_data(PCA_ADDR, base, [on & 0xFF, (on >> 8) & 0x0F, off & 0xFF, (off >> 8) & 0x0F])

def pca_set_pwm_us(bus, channel: int, pulse_us: float, period_us: float = 20000.0):
    pulse_us = max(0.0, min(period_us, pulse_us))
    off_count = int((pulse_us / period_us) * 4096.0)
    pca_set_pwm(bus, channel, 0, off_count)

def angle_to_us(angle: float, min_us=500.0, max_us=2500.0):
    a = max(0.0, min(180.0, float(angle)))
    return min_us + (max_us - min_us) * (a / 180.0)

# ---------- Servo channels / motion ----------
SERVO_CH_1 = 0   # primary
SERVO_CH_2 = 1   # mirrored (180 - primary)
SERVO_CH_ACT = 2 # actuator

OPEN_ANGLE, GRASP_ANGLE, CLOSED_ANGLE, READY_ANGLE = 0, 120, 180, 90
UP_ANGLE, DOWN_ANGLE = 30, 150
SPEED_PERCENT = 60

_current_angle = READY_ANGLE
_actuator_angle = 90

def step_delay_from_speed(pct: int) -> float:
    pct = max(1, min(100, int(pct)))
    ms = ((100 - pct) * (30 - 1) / (100 - 1)) + 1
    return ms / 1000.0

def write_angle(bus, ch: int, angle_deg: float): pca_set_pwm_us(bus, ch, angle_to_us(angle_deg))

def _write_mirrored(bus, a: float):
    a = max(0, min(180, int(a)))
    write_angle(bus, SERVO_CH_1, a)
    write_angle(bus, SERVO_CH_2, 180 - a)

def move_to_angle_mirrored(bus, target: int):
    global _current_angle
    t = max(0, min(180, int(target)))
    if _current_angle is None:
        _current_angle = t; _write_mirrored(bus, t); return
    step = 1 if t >= _current_angle else -1
    dly = step_delay_from_speed(SPEED_PERCENT)
    a = _current_angle
    while a != t:
        a += step; _write_mirrored(bus, a); time.sleep(dly)
    _current_angle = t; _write_mirrored(bus, t)

def _write_actuator(bus, angle: float): write_angle(bus, SERVO_CH_ACT, angle)

def move_actuator_to(bus, target: int):
    global _actuator_angle
    t = max(0, min(180, int(target)))
    if _actuator_angle is None:
        _actuator_angle = t; _write_actuator(bus, t); return
    step = 1 if t >= _actuator_angle else -1
    dly = step_delay_from_speed(SPEED_PERCENT)
    a = _actuator_angle
    while a != t:
        a += step; _write_actuator(bus, a); time.sleep(dly)
    _actuator_angle = t; _write_actuator(bus, t)

# ---------- Relay on GPIO17 (ACTIVE-LOW) ----------
import RPi.GPIO as GPIO
import time
RELAY_PIN = 17  # BCM
RELAY_TIMEOUT = 5.0  # Default timeout in seconds

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
# Set up GPIO with stronger drive and pull-up
GPIO.setup(RELAY_PIN, GPIO.OUT, initial=GPIO.HIGH)
GPIO.output(RELAY_PIN, GPIO.HIGH)  # Ensure it starts OFF
time.sleep(0.1)  # Let it stabilize

# PWM for more reliable control
relay_pwm = GPIO.PWM(RELAY_PIN, 100)  # 100Hz frequency
relay_pwm.start(0)  # Start with 0% duty cycle (OFF for active-low)

# Keep track of when to turn off the relay
_relay_off_time = 0
_relay_last_check = 0
CHECK_INTERVAL = 0.1  # Check every 100ms

def _check_relay_timeout():
    global _relay_off_time, _relay_last_check
    current_time = time.time()
    
    # Only check periodically to reduce CPU usage
    if current_time - _relay_last_check < CHECK_INTERVAL:
        return
        
    _relay_last_check = current_time
    
    if _relay_off_time > 0 and current_time >= _relay_off_time:
        _relay_off_time = 0
        _set_relay_state(False)  # Turn off
        print("Relay timed out - turning OFF", flush=True)

def _set_relay_state(on: bool):
    """Set relay state with proper timing and full signal strength"""
    if on:
        relay_pwm.ChangeDutyCycle(100)  # Full ON for active-low
    else:
        relay_pwm.ChangeDutyCycle(0)    # Full OFF for active-low
    time.sleep(0.05)  # Give relay time to physically switch

def relay_on(timeout=RELAY_TIMEOUT):
    global _relay_off_time
    _relay_off_time = time.time() + timeout
    _set_relay_state(True)
    print(f"Relay ON (GPIO17 LOW) - Will turn off in {timeout} seconds", flush=True)

def relay_off():
    global _relay_off_time
    _relay_off_time = 0
    _set_relay_state(False)
    print("Relay OFF (GPIO17 HIGH)", flush=True)

def relay_toggle(timeout=RELAY_TIMEOUT):
    lvl = GPIO.input(RELAY_PIN)
    # lvl==LOW means currently ON in active-low logic
    if lvl == GPIO.LOW:
        relay_off()
    else:
        relay_on(timeout)
    relay_status()

def relay_status():
    lvl = GPIO.input(RELAY_PIN)
    logical = "ON" if lvl == GPIO.LOW else "OFF"
    if logical == "ON" and _relay_off_time > 0:
        remaining = _relay_off_time - time.time()
        print(f"Relay STATE: {logical} | GPIO17: {'LOW' if lvl == GPIO.LOW else 'HIGH'} | Time remaining: {remaining:.1f}s", flush=True)
    else:
        print(f"Relay STATE: {logical} | GPIO17: {'LOW' if lvl == GPIO.LOW else 'HIGH'}", flush=True)

# ---------- Command handling ----------
def handle_command(bus, line: str):
    global SPEED_PERCENT
    line = (line or "").strip().lower()

    if line in ("neutral", "ready", "center"): move_to_angle_mirrored(bus, READY_ANGLE); print("State: NEUTRAL", flush=True); return
    if line == "up":    move_to_angle_mirrored(bus, UP_ANGLE);   print("State: UP (30 / 150)", flush=True); return
    if line == "down":  move_to_angle_mirrored(bus, DOWN_ANGLE); print("State: DOWN (150 / 30)", flush=True); return
    if line == "open":  move_to_angle_mirrored(bus, OPEN_ANGLE); print("State: OPEN", flush=True); return
    if line == "grip":  move_to_angle_mirrored(bus, GRASP_ANGLE); print("State: GRIP", flush=True); return
    if line in ("close","closed"): move_to_angle_mirrored(bus, CLOSED_ANGLE); print("State: CLOSED", flush=True); return

    if line.startswith("set "):
        try: angle = int(line.split(None, 1)[1])
        except Exception: print("Usage: set <0..180>", flush=True); return
        angle = max(0, min(180, angle)); move_to_angle_mirrored(bus, angle)
        print(f"Angle set to {angle} / {180 - angle}", flush=True); return

    if line.startswith("speed "):
        try: pct = int(line.split(None, 1)[1])
        except Exception: print("Usage: speed <1..100>", flush=True); return
        SPEED_PERCENT = max(1, min(100, pct)); print(f"Speed set to {SPEED_PERCENT}%", flush=True); return

    if line == "push": move_actuator_to(bus, 180); print("Actuator: PUSH (extended)", flush=True); return
    if line == "pull": move_actuator_to(bus, 0);   print("Actuator: PULL (retracted)", flush=True); return

    if line.startswith("relay on"):
        parts = line.split()
        timeout = float(parts[2]) if len(parts) > 2 else RELAY_TIMEOUT
        relay_on(timeout)
        return
    if line == "relay off":    relay_off(); return
    if line == "relay toggle": relay_toggle(); return
    if line == "relay status": relay_status(); return

    if line in ("help","?"):
        print("Commands: up | down | neutral | open | grip | close", flush=True)
        print("          set <0..180> | speed <1..100>", flush=True)
        print("          push | pull", flush=True)
        print("          relay on [seconds] | relay off | relay toggle | relay status", flush=True)
        print("          quit | exit", flush=True); return

    if line in ("quit","exit"): raise SystemExit
    print("Unrecognized. Type 'help' for commands.", flush=True)

# ---------- Main ----------
def main():
    global _current_angle, _actuator_angle
    with SMBus(I2C_BUS_NUM) as bus:
        # PCA9685 init
        pca_write8(bus, MODE1, 0x00); time.sleep(0.01)
        pca_set_pwm_freq(bus, 50.0)

        # Park at ready; ensure relay OFF
        relay_off()
        move_to_angle_mirrored(bus, READY_ANGLE); _current_angle = READY_ANGLE
        _write_actuator(bus, 90); _actuator_angle = 90
        time.sleep(0.2)

        print("Ready (smbus + PCA9685 + ACTIVE-LOW relay on GPIO17). Type 'help' for commands.", flush=True)
        try:
            import threading
            
            def check_timeouts():
                while True:
                    _check_relay_timeout()
                    time.sleep(0.1)  # Check every 100ms
            
            # Start timeout checker in a separate thread
            checker = threading.Thread(target=check_timeouts, daemon=True)
            checker.start()
            
            # Main input loop
            while True:
                try:
                    line = input("> ")
                    if line.strip():  # Only process non-empty lines
                        handle_command(bus, line)
                except EOFError:
                    time.sleep(0.1)
                    continue
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            # Ensure relay is OFF before releasing the pin
            try:
                relay_off()
                relay_pwm.stop()  # Stop PWM
                time.sleep(0.1)   # Give it time to settle
            except Exception: pass
            GPIO.cleanup()

if __name__ == "__main__":
    main()
