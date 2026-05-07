"""Entrypoint: runs the EL daily batch under the Telegram error alerter."""
from __future__ import annotations

from el.error_handler import error_handler
from el.pipeline import run as run_pipeline


if __name__ == "__main__":
    with error_handler():
        run_pipeline()
