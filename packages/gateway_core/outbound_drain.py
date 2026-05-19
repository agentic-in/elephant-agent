"""Shared drain loop for the cross-process gateway outbound queue.

Each gateway adapter (weixin, feishu, discord, ...) runs a long-lived worker
that pulls rows for its adapter_id off the queue and hands each row to the
adapter's own send primitive. Without this shared helper every adapter would
grow its own near-identical ``while running: claim; send; complete`` loop. That
is exactly the kind of bug surface the unified outbound queue was built to
prevent.

Two worker shapes are offered so adapters can pick whichever fits their
existing lifecycle:

- ``run_outbound_drain_loop`` (async): a coroutine that can be awaited as a
  sibling asyncio task inside an adapter's existing event loop. Best when the
  adapter already has an async primary loop (weixin's iLink poll, discord's
  discord.py gateway, dingding/wecom's WebSocket).

- ``run_outbound_drain_thread`` (sync): spawns a daemon ``threading.Thread``
  and returns it. Best when the adapter's main loop is synchronous or is owned
  by an external SDK we cannot re-enter (feishu's ``lark.ws.Client.start``,
  feishu's wsgiref HTTP callback server). The sender callback is sync and can
  issue blocking HTTP calls directly.

The sender callable is adapter-specific (weixin's ``_send_ilink_message``,
feishu's ``_send_outbound``, discord's REST helper). Everything else — claim /
release / complete / backoff — is owned by this helper so all adapters share
one reliability story.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging
import threading
import time

from .outbound_queue import GatewayOutboundQueue, GatewayOutboundRow


async def run_outbound_drain_loop(
    *,
    queue: GatewayOutboundQueue,
    adapter_id: str,
    sender: Callable[[GatewayOutboundRow], Awaitable[None]],
    is_running: Callable[[], bool],
    poll_interval_seconds: float = 2.0,
    claim_limit: int = 10,
    logger: logging.Logger | None = None,
    log_label: str | None = None,
) -> None:
    """Poll the outbound queue (async) and deliver every row claimed for this adapter.

    Semantics:

    - Every ``poll_interval_seconds``, call ``queue.claim(adapter_id=..., limit=claim_limit)``.
    - For each claimed row, call ``await sender(row)``. On success, ``queue.complete(row_id)``.
    - On exception, ``queue.release(row_id, error=...)`` so the queue's built-in
      backoff + max-attempt logic takes over.
    - Exit cleanly when ``is_running()`` becomes ``False`` — the caller is expected
      to wire this to the adapter's own running flag so ``stop_gateway`` can
      unwind the drain task the same way it unwinds the primary loop.

    The helper never swallows ``asyncio.CancelledError`` — cancellation propagates
    up so cooperative shutdown works. All other exceptions either come from the
    sender (in which case the row is released and the loop continues) or from
    the queue itself (in which case we sleep and retry, logging once per poll
    cycle so a permanently broken disk doesn't spam the log).
    """
    label = log_label or adapter_id
    log = logger or logging.getLogger(__name__)
    while is_running():
        try:
            claimed = queue.claim(adapter_id=adapter_id, limit=claim_limit)
        except Exception as exc:  # pragma: no cover - disk I/O failures.
            log.error("[%s] outbound queue claim failed: %s", label, exc)
            await asyncio.sleep(poll_interval_seconds)
            continue
        for row in claimed:
            await _send_one_row_async(
                queue=queue,
                row=row,
                sender=sender,
                logger=log,
                log_label=label,
            )
        await asyncio.sleep(poll_interval_seconds)


def run_outbound_drain_thread(
    *,
    queue: GatewayOutboundQueue,
    adapter_id: str,
    sender: Callable[[GatewayOutboundRow], None],
    is_running: Callable[[], bool],
    poll_interval_seconds: float = 2.0,
    claim_limit: int = 10,
    logger: logging.Logger | None = None,
    log_label: str | None = None,
    thread_name: str | None = None,
) -> threading.Thread:
    """Spawn a daemon thread running the drain loop with a synchronous sender.

    Returns the live ``threading.Thread`` so the caller can ``.join()`` during
    shutdown if it wants to. The thread is ``daemon=True`` so the process does
    not hang on it, which matches the semantics operators expect when they
    ``stop`` the gateway.

    Design note: we keep a separate sync entry point instead of bridging to
    ``run_outbound_drain_loop`` via ``asyncio.run``. An adapter whose main
    dispatch is sync (lark SDK, wsgiref) should not have to spin up its own
    event loop just to drain a queue — that adds surprise cancellation and
    reentrancy hazards that a plain thread dodges entirely.
    """
    label = log_label or adapter_id
    log = logger or logging.getLogger(__name__)

    def _worker() -> None:
        while is_running():
            try:
                claimed = queue.claim(adapter_id=adapter_id, limit=claim_limit)
            except Exception as exc:  # pragma: no cover - disk I/O failures.
                log.error("[%s] outbound queue claim failed: %s", label, exc)
                time.sleep(poll_interval_seconds)
                continue
            for row in claimed:
                _send_one_row_sync(
                    queue=queue,
                    row=row,
                    sender=sender,
                    logger=log,
                    log_label=label,
                )
            # Sleep last so the thread exits promptly when is_running becomes
            # False between work batches.
            time.sleep(poll_interval_seconds)

    thread = threading.Thread(
        target=_worker,
        name=thread_name or f"gateway-outbound-drain-{adapter_id}",
        daemon=True,
    )
    thread.start()
    return thread


async def _send_one_row_async(
    *,
    queue: GatewayOutboundQueue,
    row: GatewayOutboundRow,
    sender: Callable[[GatewayOutboundRow], Awaitable[None]],
    logger: logging.Logger,
    log_label: str,
) -> None:
    try:
        await sender(row)
    except asyncio.CancelledError:
        # Leave the row in-flight; a stopped adapter will not re-claim, but the
        # next process start will resume from 'pending' since rows that sit in
        # in_flight past a restart are treated as stuck. In practice the next
        # claim cycle reclaims nothing unless we release here, but releasing
        # inside CancelledError risks a write during cancellation — so we just
        # propagate and let the operator restart.
        raise
    except Exception as exc:
        logger.warning(
            "[%s] outbound send failed row=%s attempts=%d: %s",
            log_label,
            row.row_id,
            row.attempts,
            exc,
        )
        try:
            queue.release(row.row_id, error=f"{type(exc).__name__}: {exc}")
        except Exception:  # pragma: no cover - release is best-effort
            logger.exception("[%s] outbound queue release failed", log_label)
        return
    try:
        queue.complete(row.row_id)
    except Exception:  # pragma: no cover - complete is best-effort
        logger.exception("[%s] outbound queue complete failed", log_label)


def _send_one_row_sync(
    *,
    queue: GatewayOutboundQueue,
    row: GatewayOutboundRow,
    sender: Callable[[GatewayOutboundRow], None],
    logger: logging.Logger,
    log_label: str,
) -> None:
    try:
        sender(row)
    except Exception as exc:
        logger.warning(
            "[%s] outbound send failed row=%s attempts=%d: %s",
            log_label,
            row.row_id,
            row.attempts,
            exc,
        )
        try:
            queue.release(row.row_id, error=f"{type(exc).__name__}: {exc}")
        except Exception:  # pragma: no cover - release is best-effort
            logger.exception("[%s] outbound queue release failed", log_label)
        return
    try:
        queue.complete(row.row_id)
    except Exception:  # pragma: no cover - complete is best-effort
        logger.exception("[%s] outbound queue complete failed", log_label)


__all__ = ["run_outbound_drain_loop", "run_outbound_drain_thread"]
