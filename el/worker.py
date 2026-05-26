"""SP8 — background worker.

Drains the private.run_requests queue. One row per tick, then sleeps.
SIGTERM/SIGINT set an event that ends the loop after the current tick.
Single replica in compose makes the claim race-free by configuration;
the conditional UPDATE is defense in depth.
"""
from __future__ import annotations

import logging
import os
import signal
import socket
import threading
from typing import Callable

from el.web import run_service

log = logging.getLogger("el.worker")

_ERROR_MESSAGE_MAX_LEN = 2000
_POLL_SECONDS = float(os.environ.get("EL_WORKER_POLL_SECONDS", "30"))


def _default_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


def _default_pipeline(request_id: str, *, db_provider) -> None:
    from el.pipeline import run_for_request
    run_for_request(request_id, db_provider=db_provider)


def tick(*, db_provider, worker_id: str, run_pipeline: Callable) -> None:
    """One unit of work. Returns immediately if queue is empty."""
    claimed = run_service.claim_one_queued(worker_id=worker_id, db_provider=db_provider)
    if claimed is None:
        return
    request_id = claimed["id"]
    try:
        run_pipeline(request_id, db_provider=db_provider)
    except Exception as e:
        log.exception("pipeline failed for %s", request_id)
        run_service.mark_error(
            request_id=request_id,
            error_message=str(e)[:_ERROR_MESSAGE_MAX_LEN],
            db_provider=db_provider,
        )
        return
    run_service.mark_done(request_id=request_id, db_provider=db_provider)


def run_loop(
    *,
    db_provider,
    worker_id: str,
    run_pipeline: Callable,
    stop: threading.Event,
    poll_seconds: float = _POLL_SECONDS,
) -> None:
    log.info("worker %s starting (poll=%ss)", worker_id, poll_seconds)
    while not stop.is_set():
        try:
            tick(db_provider=db_provider, worker_id=worker_id, run_pipeline=run_pipeline)
        except Exception:
            log.exception("worker tick failed (continuing)")
        stop.wait(poll_seconds)
    log.info("worker %s stopped", worker_id)


def main() -> int:
    from el.supabase import SupabaseRestProvider
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    run_loop(
        db_provider=SupabaseRestProvider(),
        worker_id=_default_worker_id(),
        run_pipeline=_default_pipeline,
        stop=stop,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
