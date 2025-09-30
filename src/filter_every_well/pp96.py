"""
Control class for Waters Positive Pressure-96 Processor.

Uses PCA9685 via ServoKit for:
- Two servos (mirror-mounted on opposite sides) to press rocker buttons synchronously
- One PWM channel for linear actuator (plate in/out)

The two servos rotate in opposite directions to press the same position on
mirror-image rocker buttons (up/down/neutral).
"""

import time

try:
    from adafruit_servokit import ServoKit
except ImportError:
    ServoKit = None


class PressureProcessor:
    """
    Control interface for Waters PP96 filtration system.
    
    Hardware:
    - PCA9685 16-channel PWM/servo driver at I2C address 0x40
    - Two servos on channels 0 & 1 (mirrored: servo_2 = 180 - servo_1)
    - Linear actuator on channel 2 (controlled as a servo)
    
    Default angles (matching test_Waters.py):
    - Press UP: 30° / 150° (servo_1 / servo_2)
    - Press DOWN: 150° / 30°
    - Press NEUTRAL: 90° / 90°
    - Actuator IN: 180° (extended/push)
    - Actuator OUT: 0° (retracted/pull - resting state)
    
    On initialization:
    - Servos move to neutral (90° / 90°)
    - Actuator moves to OUT position (0° - resting state)
    - Pulse width configured to 500-2500µs for all channels
    """

    def __init__(
        self,
        channels: int = 16,
        address: int = 0x40,
        servo_1_channel: int = 0,
        servo_2_channel: int = 1,
        actuator_channel: int = 2,
        servo_up_angle: float = 30.0,
        servo_down_angle: float = 150.0,
        servo_neutral_angle: float = 90.0,
        actuator_in_angle: float = 180.0,
        actuator_out_angle: float = 0.0,
        pulse_min: int = 500,
        pulse_max: int = 2500,
    ):
        """
        Initialize the Waters PP96 controller.

        Args:
            channels: Number of channels on the PCA9685 (typically 16)
            address: I2C address of PCA9685 (default 0x40)
            servo_1_channel: Channel for servo 1 (primary)
            servo_2_channel: Channel for servo 2 (mirrored as 180 - servo_1)
            actuator_channel: Servo channel for linear actuator
            servo_up_angle: Angle for servo 1 to press UP (default 30°)
            servo_down_angle: Angle for servo 1 to press DOWN (default 150°)
            servo_neutral_angle: Neutral angle for servo 1 (default 90°)
            actuator_in_angle: Actuator angle for plate IN/extended/push (default 180°)
            actuator_out_angle: Actuator angle for plate OUT/retracted/pull (default 0°, resting state)
            pulse_min: Minimum pulse width in microseconds (default 500)
            pulse_max: Maximum pulse width in microseconds (default 2500)
        """
        if ServoKit is None:
            raise RuntimeError(
                "adafruit-circuitpython-servokit not installed. "
                "Install with: pip install .[hardware]"
            )

        self.kit = ServoKit(channels=channels, address=address)
        
        # Servo channels (mirror-mounted on opposite sides)
        self.servo_1_channel = servo_1_channel
        self.servo_2_channel = servo_2_channel
        
        # Actuator channel (regular servo for linear actuator)
        self.actuator_channel = actuator_channel
        
        # Servo angles (servo 2 = 180 - servo 1)
        self.servo_up_angle = servo_up_angle
        self.servo_down_angle = servo_down_angle
        self.servo_neutral_angle = servo_neutral_angle
        
        # Actuator angles
        self.actuator_in_angle = actuator_in_angle
        self.actuator_out_angle = actuator_out_angle
        
        # Configure pulse width ranges for all servos
        for ch in (self.servo_1_channel, self.servo_2_channel, self.actuator_channel):
            self.kit.servo[ch].set_pulse_width_range(pulse_min, pulse_max)
            self.kit.servo[ch].actuation_range = 180
        
        # Initialize: servos to neutral, actuator to OUT (resting state)
        self._reset_servos()
        self.plate_out()

    def _reset_servos(self) -> None:
        """Reset both servos to neutral position synchronously."""
        self.kit.servo[self.servo_1_channel].angle = self.servo_neutral_angle
        # Servo 2 mirrors: 180 - servo_1_angle
        self.kit.servo[self.servo_2_channel].angle = 180 - self.servo_neutral_angle

    def _set_mirrored_position(self, servo_1_angle: float, hold_time: float = 0.5) -> None:
        """
        Set both servos to mirrored positions synchronously.
        
        Servo 1 moves to the specified angle, while Servo 2 mirrors it
        as 180 - servo_1_angle to press the same rocker position.

        Args:
            servo_1_angle: Target angle for servo 1
            hold_time: Duration to hold position (seconds)
        """
        # Servo 1 moves to target angle
        self.kit.servo[self.servo_1_channel].angle = servo_1_angle
        # Servo 2 mirrors: 180 - servo_1_angle
        servo_2_angle = 180 - servo_1_angle
        self.kit.servo[self.servo_2_channel].angle = servo_2_angle
        
        time.sleep(hold_time)

    def press_up(self, hold_time: float = 0.5) -> None:
        """
        Press the UP rocker button to raise pneumatic press.
        Both servos move synchronously in opposite directions.

        Args:
            hold_time: Duration to hold button (seconds)
        """
        self._set_mirrored_position(self.servo_up_angle, hold_time)
        self._reset_servos()

    def press_down(self, hold_time: float = 0.5) -> None:
        """
        Press the DOWN rocker button to lower pneumatic press.
        Both servos move synchronously in opposite directions.

        Args:
            hold_time: Duration to hold button (seconds)
        """
        self._set_mirrored_position(self.servo_down_angle, hold_time)
        self._reset_servos()

    def press_neutral(self) -> None:
        """
        Return both servos to neutral (no button pressed).
        """
        self._reset_servos()

    def plate_in(self) -> None:
        """
        Move plate under the press (extend actuator to IN position, 180°).
        Equivalent to 'push' in test_Waters.py.
        """
        self.kit.servo[self.actuator_channel].angle = self.actuator_in_angle

    def plate_out(self) -> None:
        """
        Retract plate from press (move actuator to OUT position, 0°).
        This is the resting state. Equivalent to 'pull' in test_Waters.py.
        """
        self.kit.servo[self.actuator_channel].angle = self.actuator_out_angle

    def shutdown(self) -> None:
        """
        Safely shut down: return servos to neutral, actuator to OUT (resting state).
        """
        self._reset_servos()
        self.plate_out()
        time.sleep(0.2)  # Brief pause for movement to complete
        # Release servo pulses (optional)
        try:
            self.kit.servo[self.servo_1_channel].angle = None
            self.kit.servo[self.servo_2_channel].angle = None
            self.kit.servo[self.actuator_channel].angle = None
        except Exception:
            pass

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit: clean shutdown."""
        self.shutdown()
        return False

