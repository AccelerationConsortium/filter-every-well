import argparse
from typing import List

from filter_every_well.pp96 import PressureProcessor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="filter-every-well",
        description=(
            "Control Waters Positive Pressure-96 Processor using Raspberry Pi Zero 2W "
            "and a 16-channel motor HAT."
        ),
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("up", help="Move pneumatic press up")
    subparsers.add_parser("down", help="Move pneumatic press down")
    subparsers.add_parser("neutral", help="Set pneumatic press to neutral")

    plate = subparsers.add_parser("plate", help="Control plate actuator")
    plate_sub = plate.add_subparsers(dest="plate_cmd", required=True)
    plate_sub.add_parser("in", help="Move plate under press")
    plate_sub.add_parser("out", help="Retract plate from press")

    return parser


def execute_command(args: argparse.Namespace) -> int:
    command = args.command

    # Try to execute with actual hardware
    try:
        with PressureProcessor() as pp96:
            if command == "up":
                print("Moving press UP...")
                pp96.press_up()
                print("Done.")
            elif command == "down":
                print("Moving press DOWN...")
                pp96.press_down()
                print("Done.")
            elif command == "neutral":
                print("Setting press to NEUTRAL...")
                pp96.press_neutral()
                print("Done.")
            elif command == "plate":
                if args.plate_cmd == "in":
                    print("Moving plate IN...")
                    pp96.plate_in()
                    print("Done.")
                elif args.plate_cmd == "out":
                    print("Moving plate OUT...")
                    pp96.plate_out()
                    print("Done.")
                else:
                    print(f"Unknown plate command: {args.plate_cmd}")
                    return 1
            else:
                print("Unknown command")
                return 1
        return 0
    except RuntimeError as e:
        # Hardware not available, run in dry-run mode
        if "adafruit-circuitpython-servokit not installed" in str(e):
            if command in {"up", "down", "neutral"}:
                print(f"[DRY-RUN] Press command: {command}")
                return 0
            if command == "plate":
                print(f"[DRY-RUN] Plate command: {args.plate_cmd}")
                return 0
        print(f"Error: {e}")
        return 1
    except Exception as e:
        print(f"Error: {e}")
        return 1


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return execute_command(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
