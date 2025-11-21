#!/usr/bin/env python3
"""
Waters Automation – Pi Zero 2 W + PCA9685 via smbus2
(Two Mirrored Servos on CH0/1 + Linear Actuator on CH2 + Relay on GPIO17 ACTIVE-HIGH)

Commands:
  up | down | neutral | open | grip | close
  set <0..180>
  speed <1..100>
  push | pull
  relay on | relay off | relay toggle | relay status
  help | ? | quit | exit

Notes:
- Relay is ACTIVE-HIGH (HIGH = ON). 'relay off' releases the pin via GPIO.cleanup(RELAY_PIN).
"""

import sys, time

# ---------- I2C / smbus2 (PCA9685) ----------
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
    pca_write8(bus, MODE1, oldmode | 0xA1)          # restart, autoincrement

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
SERVO_CH_2 = 15   # mirrored (180 - primary)
SERVO_CH_ACT = 2 # actuator

OPEN_ANGLE, GRASP_ANGLE, CLOSED_ANGLE, READY_ANGLE = 0, 120, 180, 90
UP_ANGLE, DOWN_ANGLE = 30, 150
SPEED_PERCENT = 60

_current_angle = READY_ANGLE
_actuator_angle = 180

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

# ---------- Relay on GPIO17 (ACTIVE-HIGH) ----------
import RPi.GPIO as GPIO
RELAY_PIN = 17  # BCM

def _ensure_mode():
    if GPIO.getmode() is None:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

def relay_on():
    """Turn relay ON: configure pin as OUTPUT and drive HIGH (active-high)."""
    _ensure_mode()
    try:
        GPIO.setup(RELAY_PIN, GPIO.OUT)
    except RuntimeError:
        GPIO.setmode(GPIO.BCM); GPIO.setup(RELAY_PIN, GPIO.OUT)
    GPIO.output(RELAY_PIN, GPIO.HIGH)  # HIGH = ON
    print("Relay ON (GPIO17 HIGH)", flush=True)

def relay_off():
    """Turn relay OFF by releasing the pin (cleanup), per your request."""
    _ensure_mode()
    try:
        GPIO.cleanup(RELAY_PIN)  # release channel -> stop driving
        print("Relay OFF (GPIO17 released via cleanup)", flush=True)
    except Exception as e:
        print(f"Relay OFF cleanup error: {e}", flush=True)

def relay_status():
    """Report current status if pin is configured; otherwise report released."""
    _ensure_mode()
    try:
        lvl = GPIO.input(RELAY_PIN)
        print(f"Relay STATE: {'ON' if lvl == GPIO.HIGH else 'OFF (driven LOW)'} | GPIO17: {'HIGH' if lvl else 'LOW'}",
              flush=True)
    except Exception:
        print("Relay pin released (GPIO cleaned up)", flush=True)

def relay_toggle():
    _ensure_mode()
    try:
        # If pin is released, treat as OFF -> turn ON
        try:
            lvl = GPIO.input(RELAY_PIN)
            configured = True
        except Exception:
            configured = False
        if not configured:
            relay_on(); return
        # Toggle between HIGH (ON) and cleanup (OFF)
        if GPIO.input(RELAY_PIN) == GPIO.HIGH:
            relay_off()
        else:
            relay_on()
    except Exception as e:
        print(f"Relay toggle error: {e}", flush=True)

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

    if line == "relay on":     relay_on(); return
    if line == "relay off":    relay_off(); return
    if line == "relay toggle": relay_toggle(); return
    if line == "relay status": relay_status(); return

    if line in ("help","?"):
        print("Commands: up | down | neutral | open | grip | close", flush=True)
        print("          set <0..180> | speed <1..100>", flush=True)
        print("          push | pull", flush=True)
        print("          relay on | relay off | relay toggle | relay status", flush=True)
        print("          quit | exit", flush=True); return

    if line in ("quit","exit"): raise SystemExit
    print("Unrecognized. Type 'help' for commands.", flush=True)

# ---------- Main ----------
def main():
    with SMBus(I2C_BUS_NUM) as bus:
        # PCA9685 init
        pca_write8(bus, MODE1, 0x00); time.sleep(0.01)
        pca_set_pwm_freq(bus, 50.0)

        # Ensure relay starts OFF by releasing the pin
        try:
            GPIO.setmode(GPIO.BCM); GPIO.setwarnings(False)
            GPIO.cleanup(RELAY_PIN)
        except Exception:
            pass

        # Park servos
        move_to_angle_mirrored(bus, READY_ANGLE)
        _write_actuator(bus, 180)
        time.sleep(0.2)

        print("Ready (smbus + PCA9685 + active-HIGH relay on GPIO17). Type 'help' for commands.", flush=True)
        try:
            while True:
                try: line = input("> ")
                except EOFError: time.sleep(0.1); continue
                handle_command(bus, line)
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            # Release relay and cleanup
            try: relay_off()
            except Exception: pass
            try: GPIO.cleanup()
            except Exception: pass

if __name__ == "__main__":
    main()
