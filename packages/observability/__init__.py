from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .context import TraceContext, get_context, set_context, update_context
from .instrumentor import instrument, uninstrument
from .logger import configure_logging, get_logger
from .metrics import (
    DurationTimer,
    record_model_metrics,
    record_tool_metrics,
    record_turn_metrics,
)
from .setup import setup_observability
from .spans import (
    record_token_usage,
    trace_kernel_turn,
    trace_model_call,
    trace_tool_execution,
)


def setup_from_config(
    global_config: Mapping[str, Any],
    *,
    state_dir: str = "",
) -> None:
    obs = global_config.get("observability")
    if not isinstance(obs, Mapping):
        obs = {}
    if not obs.get("enabled", True):
        return
    setup_observability(
        service_name=obs.get("service_name", "elephant-agent"),
        log_level=obs.get("log_level", "INFO"),
        log_file=obs.get("log_file", ""),
        state_dir=state_dir,
        otel_endpoint=obs.get("otel_endpoint", ""),
    )
    instrument()


__all__ = [
    "DurationTimer",
    "TraceContext",
    "configure_logging",
    "get_context",
    "get_logger",
    "instrument",
    "record_model_metrics",
    "record_token_usage",
    "record_tool_metrics",
    "record_turn_metrics",
    "set_context",
    "setup_from_config",
    "setup_observability",
    "trace_kernel_turn",
    "trace_model_call",
    "trace_tool_execution",
    "uninstrument",
    "update_context",
]
