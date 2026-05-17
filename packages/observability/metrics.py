from __future__ import annotations

import time

from opentelemetry import metrics

_meter = metrics.get_meter("elephant-agent")

# GenAI semconv metrics (semconv 1.41)
token_usage = _meter.create_histogram(
    name="gen_ai.client.token.usage",
    description="Number of tokens used in GenAI operations",
    unit="{token}",
)

operation_duration = _meter.create_histogram(
    name="gen_ai.client.operation.duration",
    description="Duration of GenAI operations",
    unit="s",
)

# Elephant-specific metrics
tool_duration = _meter.create_histogram(
    name="elephant.tool.duration",
    description="Duration of tool executions",
    unit="s",
)

kernel_turn_duration = _meter.create_histogram(
    name="elephant.kernel.turn.duration",
    description="Duration of a full kernel turn",
    unit="s",
)


def record_model_metrics(
    *,
    provider_id: str,
    model_id: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    duration_s: float = 0.0,
) -> None:
    attrs = {
        "gen_ai.operation.name": "chat",
        "gen_ai.request.model": model_id,
        "gen_ai.provider.name": provider_id,
    }
    if input_tokens:
        token_usage.record(input_tokens, attributes={**attrs, "gen_ai.token.type": "input"})
    if output_tokens:
        token_usage.record(output_tokens, attributes={**attrs, "gen_ai.token.type": "output"})
    if duration_s > 0:
        operation_duration.record(duration_s, attributes=attrs)


def record_tool_metrics(
    *,
    tool_name: str,
    duration_s: float,
    status: str = "success",
) -> None:
    tool_duration.record(duration_s, attributes={
        "gen_ai.tool.name": tool_name,
        "elephant.tool.status": status,
    })


def record_turn_metrics(
    *,
    episode_id: str,
    duration_s: float,
    trigger_type: str = "",
) -> None:
    attrs: dict[str, str] = {"elephant.episode_id": episode_id}
    if trigger_type:
        attrs["elephant.trigger_type"] = trigger_type
    kernel_turn_duration.record(duration_s, attributes=attrs)


class DurationTimer:
    __slots__ = ("_start",)

    def __init__(self) -> None:
        self._start = time.monotonic()

    def elapsed(self) -> float:
        return time.monotonic() - self._start
