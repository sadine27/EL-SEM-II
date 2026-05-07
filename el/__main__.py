"""Command-line entry point for the EL Python port."""
from __future__ import annotations

import argparse

from el import pipeline
from el.error_handler import error_handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m el")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("run", help="run the EL workflow")
    args = parser.parse_args(argv)

    if args.command == "run":
        with error_handler():
            pipeline.run()
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
