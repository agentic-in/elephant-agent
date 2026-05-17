from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
import logging
from uuid import uuid4


@dataclass(slots=True)
class TraceContext:
    trace_id: str = field(default_factory=lambda: uuid4().hex)
    episode_id: str = ""
    loop_id: str = ""
    step_id: str = ""
    request_id: str = ""


_current_context: ContextVar[TraceContext | None] = ContextVar(
    "elephant_trace_context", default=None,
)


def set_context(ctx: TraceContext) -> None:
    _current_context.set(ctx)


def get_context() -> TraceContext:
    ctx = _current_context.get()
    if ctx is None:
        ctx = TraceContext()
        _current_context.set(ctx)
    return ctx


def update_context(**kwargs: str) -> TraceContext:
    ctx = get_context()
    for key, value in kwargs.items():
        if hasattr(ctx, key):
            setattr(ctx, key, value)
    return ctx


class TraceContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        ctx = _current_context.get()
        record.trace_id = ctx.trace_id if ctx else ""
        record.episode_id = ctx.episode_id if ctx else ""
        record.loop_id = ctx.loop_id if ctx else ""
        record.step_id = ctx.step_id if ctx else ""
        record.request_id = ctx.request_id if ctx else ""
        return True
